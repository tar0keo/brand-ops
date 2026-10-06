"""Ask each category's consumer questions of an AI engine and write the answers as a research file the app imports."""
import argparse
import json
import os
import re
import shutil
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path

from runner import engines, extract

REPO = Path(__file__).resolve().parent.parent
SYSTEM = ("You are a helpful assistant answering a consumer's question. When you recommend companies or sites, "
          "list them as a numbered list, best first, using each company's usual name, followed by a short reason.")


def desktop_home():
    if sys.platform == "win32":
        base = Path(os.environ.get("APPDATA") or Path.home() / "AppData" / "Roaming")
    elif sys.platform == "darwin":
        base = Path.home() / "Library" / "Application Support"
    else:
        base = Path(os.environ.get("XDG_DATA_HOME") or Path.home() / ".local" / "share")
    return base / "BrandOps"


def resolve_home(arg=None):
    """The data folder to read questions from and write results to: the desktop app's, unless told otherwise."""
    if arg:
        return Path(arg)
    if os.environ.get("BRANDOPS_HOME"):
        return Path(os.environ["BRANDOPS_HOME"])
    return desktop_home() if desktop_home().is_dir() else REPO


def ensure_config(home):
    """Give a data folder any default settings it is missing, as the app does on first launch. Yours are never overwritten."""
    if home.resolve() == REPO.resolve():
        return
    (home / "config").mkdir(parents=True, exist_ok=True)
    for f in (REPO / "config").glob("*.yaml"):
        target = home / "config" / f.name
        if not target.exists():
            shutil.copy(f, target)


def build_plan(cfg, categories, engine_id, only=None, per_category=None, existing=frozenset(), force=False, norm=lambda q: q):
    """Which (category, question) pairs to ask. Returns (plan, skipped_because_recent)."""
    plan, skipped = [], 0
    for c in categories:
        if only and c["id"] != only:
            continue
        for q in (cfg.get("questions", {}).get(c["id"]) or [])[:per_category]:
            if not force and (c["id"], norm(q), engine_id) in existing:
                skipped += 1
            else:
                plan.append({"category": c["id"], "label": c["label"], "question": q})
    return plan, skipped


def ask_all(tasks, engine, engine_id, today, delay=1.0, sleep=time.sleep, say=print):
    runs, review, failed = [], [], []
    totals, streak, aborted = {"searches": 0, "input_tokens": 0, "output_tokens": 0}, 0, None
    for i, t in enumerate(tasks, 1):
        tag = f"[{i}/{len(tasks)}] {t['label']}"
        try:
            ans = engine.ask(t["question"])
        except engines.AuthError as e:
            aborted = str(e)
            say(f"Stopping: {e}")
            break
        except engines.EngineError as e:
            failed.append({**t, "error": str(e)})
            streak += 1
            say(f"{tag}: failed ({e})")
            if streak >= 3:
                aborted = "Stopped after 3 failures in a row."
                say(aborted)
                break
            sleep(delay)
            continue
        streak = 0
        for k in totals:
            totals[k] += getattr(ans, k)
        ex = extract.extract_companies(ans.text, ans.citations)
        record = {"date": today.isoformat(), "category": t["category"], "question": t["question"], "engine": engine_id,
                  "model": ans.model, "location": engine.location, "answer": ans.text, "citations": ans.citations}
        if ex["ok"]:
            runs.append({**record, "results": ex["results"]})
            say(f"{tag}: {len(ex['results'])} companies, {len(ans.citations)} sources")
        else:
            review.append({**record, "reason": ex["reason"], "found": ex["results"]})
            say(f"{tag}: needs a person to check ({ex['reason']})")
        if i < len(tasks):
            sleep(delay)
    return runs, review, failed, totals, aborted


def write_outputs(runs, review, out_dir, engine_id, stamp):
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    path = None
    if runs:
        path = out_dir / f"runner-{engine_id}-{stamp}.jsonl"
        path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in runs) + "\n", encoding="utf-8")
    held = []
    for i, r in enumerate(review, 1):
        folder = out_dir / "needs_review"
        folder.mkdir(exist_ok=True)
        slug = re.sub(r"[^a-z0-9]+", "-", r["question"].lower()).strip("-")[:40]
        p = folder / f"{engine_id}-{r['category']}-{slug}-{stamp}-{i}.json"
        p.write_text(json.dumps(r, ensure_ascii=False, indent=2), encoding="utf-8")
        held.append(p)
    return path, held


def build_parser():
    p = argparse.ArgumentParser(prog="python -m runner", description=__doc__)
    p.add_argument("--engine", default="claude", help="engine id from config/research.yaml (default: claude)")
    p.add_argument("--category", help="only this category id")
    p.add_argument("--questions", type=int, help="at most this many questions per category")
    p.add_argument("--within-days", type=int, default=6, help="skip questions already answered by this engine in the last N days (default 6)")
    p.add_argument("--force", action="store_true", help="ask even if a recent answer exists")
    p.add_argument("--max-runs", type=int, default=40, help="safety cap on questions asked in one go (default 40)")
    p.add_argument("--delay", type=float, default=1.0, help="seconds to wait between questions (default 1)")
    p.add_argument("--model", help="override the model named in config/research.yaml")
    p.add_argument("--no-system", action="store_true", help="ask the bare question, with no instruction about how to list companies")
    p.add_argument("--dry-run", action="store_true", help="show what would be asked, and the cost limits, without calling the API")
    p.add_argument("--import", dest="do_import", action="store_true", help="also load the results straight into the app's database")
    p.add_argument("--home", help="the app's data folder (default: the desktop app's folder)")
    p.add_argument("--out", help="where to write results (default: <data folder>/data_inbox/research)")
    return p


def main(argv=None, engine_factory=None, say=print, sleep=time.sleep, today=None):
    args = build_parser().parse_args(argv)
    home = resolve_home(args.home)
    ensure_config(home)
    os.environ["BRANDOPS_HOME"] = str(home)  # must be set before the app's modules are imported
    if home != REPO and not os.environ.get("DATABASE_URL"):
        os.environ["DATABASE_URL"] = "sqlite:///" + str(home / "brandops.db")
    from app import registry, research
    from connectors import store

    today = today or date.today()
    cfg = research.config()
    if args.engine not in cfg["engines"]:
        say(f"Unknown engine '{args.engine}'. Engines in config/research.yaml: {', '.join(cfg['engines'])}")
        return 2
    api = cfg["engines"][args.engine].get("api") or {}
    existing = set()
    if not args.force:
        try:
            since = (today - timedelta(days=args.within_days)).isoformat()
            existing = {(r["category"], research.norm_q(r["question"]), r["engine"]) for r in store.research_runs(since)}
        except Exception as e:
            say(f"(Could not read earlier results, so every question will be asked: {e})")
    plan, skipped = build_plan(cfg, registry.categories(), args.engine, args.category, args.questions, existing, args.force, research.norm_q)
    capped = max(0, len(plan) - args.max_runs)
    plan = plan[:args.max_runs]
    say(f"Data folder: {home}")
    say(f"{len(plan)} questions to ask {args.engine}" + (f", {skipped} skipped (answered in the last {args.within_days} days)" if skipped else "")
        + (f", {capped} more held back by --max-runs {args.max_runs}" if capped else ""))
    searches = int(api.get("max_searches", engines.ANTHROPIC_DEFAULTS["max_searches"])) if api.get("web_search", True) else 0
    if args.dry_run:
        for t in plan:
            say(f"  {t['label']}: {t['question']}")
        say(f"Search fees would be at most {len(plan) * searches} searches (check the provider's current price per search), plus token costs."
            if searches else "Web search is off for this engine: token costs only.")
        return 0
    if not plan:
        say("Nothing to do.")
        return 0
    try:
        engine = (engine_factory or engines.make_engine)(args.engine, api, None if args.no_system else SYSTEM, args.model)
        getattr(engine, "check", lambda: None)()  # a missing key is reported before anything is asked
    except engines.EngineError as e:
        say(str(e))
        return 2
    runs, review, failed, totals, aborted = ask_all(plan, engine, args.engine, today, args.delay, sleep, say)
    stamp = datetime.now().strftime("%Y%m%d-%H%M%S")
    out = Path(args.out) if args.out else home / "data_inbox" / "research"
    path, held = write_outputs(runs, review, out, args.engine, stamp)
    say(f"\nAnswered {len(runs)} | needs a check {len(review)} | failed {len(failed)}. "
        f"Used {totals['searches']} searches and {totals['input_tokens']:,} + {totals['output_tokens']:,} tokens.")
    if held:
        say(f"Answers that need a person to check are in {held[0].parent}")
    if path:
        text = path.read_text(encoding="utf-8")
        _, errors = research.parse_text(path.name, text, cfg)
        if errors:
            say(f"Wrote {path}, but the app would reject it: {errors[:3]}")
        elif args.do_import:
            r = research.import_text(path.name, text, False, cfg)
            say(f"Wrote {path} and imported it: {r['added']} added, {r['replaced']} replaced.")
        else:
            say(f"Wrote {path}\nNext: open the app, go to Market research, and click Import inbox folder.")
    return 1 if (aborted or failed) else 0


if __name__ == "__main__":
    sys.exit(main())
