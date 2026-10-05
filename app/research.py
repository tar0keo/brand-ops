"""Market research: consumer-style questions asked of AI engines and of Google, compared per loan category."""
import csv
import io
import json
import os
import random
import threading
import re
from collections import Counter, defaultdict
from datetime import date, timedelta
from urllib.parse import urlparse

import yaml

from app import demo, media, registry
from connectors import base, store
from connectors.files import inbox, load_yaml, parse_date

MAX_TEXT, MAX_ERRORS = 10_000_000, 10
ALIASES = {"date": "date", "run_date": "date", "category": "category", "loan_type": "category",
           "question": "question", "prompt": "question", "query": "question", "engine": "engine", "source": "engine",
           "rank": "rank", "position": "rank", "name": "name", "company": "name", "brand": "name", "site": "name",
           "url": "url", "link": "url", "note": "note", "notes": "note", "answer": "answer",
           "model": "model", "location": "location"}
REQUIRED = ("date", "category", "question", "engine", "rank", "name")


_CFG_LOCK = threading.Lock()
CFG_HEADER = "# Market research settings. The questions can be edited from the Market research tab.\n"


def config():
    with open(base.RESEARCH_PATH) as f:
        return yaml.safe_load(f)


def set_questions(category, questions):
    """Replace the consumer questions for one category."""
    if category not in {c["id"] for c in registry.categories()}:
        raise ValueError("Unknown category")
    if not isinstance(questions, list):
        raise ValueError("questions must be a list")
    cleaned, seen = [], set()
    for q in questions:
        q = re.sub(r"\s+", " ", str(q)).strip()
        if q and norm_q(q) not in seen:
            if len(q) > 200:
                raise ValueError("Keep each question to 200 characters or fewer")
            seen.add(norm_q(q))
            cleaned.append(q)
    if len(cleaned) > 20:
        raise ValueError("Up to 20 questions per category")
    with _CFG_LOCK:
        cfg = config()
        cfg.setdefault("questions", {})[category] = cleaned
        tmp = f"{base.RESEARCH_PATH}.tmp"
        with open(tmp, "w") as f:
            f.write(CFG_HEADER + yaml.safe_dump(cfg, sort_keys=False, allow_unicode=True, width=1000))
        os.replace(tmp, base.RESEARCH_PATH)
    return {"questions": cleaned}


def norm_q(q):
    return re.sub(r"\W+", " ", (q or "").lower()).strip()


def domain_of(url):
    if not url:
        return None
    try:
        p = urlparse(url if "//" in url else "//" + url.strip())
        host = (p.hostname or "").removeprefix("www.")
    except ValueError:
        return None
    return host if registry.DOMAIN.match(host) else None


def resolve_brand(name, url, brands):
    """Which of our brands (if any) a listed company is. A matching site wins over a matching name."""
    d = domain_of(url)
    if d:
        for b in brands:
            if any(d == s or d.endswith("." + s) for s in b.get("sites") or []):
                return b["id"]
    for b in brands:
        if media._name_re(b["name"]).search(name or ""):
            return b["id"]
    return None


# ---------- reading files ----------
def _lookup(value, options, what):
    v = str(value or "").strip().lower()
    for k, label in options.items():
        if v in (k.lower(), label.lower()):
            return k
    raise ValueError(f"{what} '{value}' is not one of: {', '.join(options)}")


def _options(cfg):
    return ({c["id"]: c["label"] for c in registry.category_list()}, {k: v["label"] for k, v in cfg["engines"].items()})


def _question(q):
    q = re.sub(r"\s+", " ", str(q or "")).strip()
    if not q:
        raise ValueError("Question is empty")
    return q


def _rank(v):
    m = re.match(r"^\D*(\d+)", str(v))
    if not m or not 1 <= int(m.group(1)) <= 50:
        raise ValueError(f"Rank '{v}' must be a whole number from 1 to 50")
    return int(m.group(1))


def _csv_runs(text, cfg):
    cats, engs = _options(cfg)
    first = text.splitlines()[0] if text.strip() else ""
    delim = max((",", ";", "\t"), key=first.count)
    rows = [r for r in csv.reader(io.StringIO(text), delimiter=delim) if any(c.strip() for c in r)]
    if not rows:
        raise ValueError("The file is empty")
    header = [ALIASES.get(re.sub(r"[^a-z]+", "_", h.strip().lower()).strip("_")) for h in rows[0]]
    missing = [c for c in REQUIRED if c not in header]
    if missing:
        raise ValueError("Missing columns: " + ", ".join(missing))
    runs, errors = {}, []
    for n, row in enumerate(rows[1:], start=2):
        rec = {name: (row[i].strip() if i < len(row) else "") for i, name in enumerate(header) if name}
        try:
            d = parse_date(rec["date"]).isoformat()
            category, engine = _lookup(rec["category"], cats, "Category"), _lookup(rec["engine"], engs, "Engine")
            question, rank = _question(rec["question"]), _rank(rec["rank"])
            if not rec["name"]:
                raise ValueError("Name is empty")
        except ValueError as e:
            errors.append(f"Row {n}: {e}")
            continue
        key = (d, category, question, engine, rec.get("model", ""), rec.get("location", ""))
        run = runs.setdefault(key, {"date": d, "category": category, "question": question, "engine": engine,
                                    "model": key[4], "location": key[5], "answer": "", "citations": [], "results": []})
        run["results"].append({"rank": rank, "name": rec["name"], "url": rec.get("url") or None})
        if rec.get("answer") and not run["answer"]:
            run["answer"] = rec["answer"]
    return list(runs.values()), errors


def _run_from_obj(o, cfg):
    cats, engs = _options(cfg)
    if not isinstance(o, dict):
        raise ValueError("expected an object")
    res = o.get("results")
    if not isinstance(res, list) or not res:
        raise ValueError("results must be a non-empty list")
    results = []
    for i, it in enumerate(res, 1):
        it = {"name": it} if isinstance(it, str) else it
        if not isinstance(it, dict) or not str(it.get("name") or "").strip():
            raise ValueError(f"result {i} has no name")
        results.append({"rank": _rank(it.get("rank") or i), "name": str(it["name"]).strip(), "url": it.get("url") or None})
    cites = []
    for c in o.get("citations") or []:
        c = {"url": c} if isinstance(c, str) else c
        if isinstance(c, dict) and c.get("url"):
            cites.append({"url": str(c["url"]), "title": str(c.get("title") or "")})
    return {"date": parse_date(str(o.get("date") or "")).isoformat(), "category": _lookup(o.get("category"), cats, "Category"),
            "question": _question(o.get("question")), "engine": _lookup(o.get("engine"), engs, "Engine"),
            "model": str(o.get("model") or ""), "location": str(o.get("location") or ""),
            "answer": str(o.get("answer") or ""), "citations": cites, "results": results}


def _json_runs(text, cfg):
    runs, errors, pairs, label = [], [], [], "Run"
    try:
        data = json.loads(text)
        items = data if isinstance(data, list) else (data.get("runs", [data]) if isinstance(data, dict) else [])
        pairs = list(enumerate(items, 1))
    except ValueError:
        label = "Line"
        for n, line in enumerate(text.splitlines(), 1):
            if line.strip():
                try:
                    pairs.append((n, json.loads(line)))
                except ValueError:
                    errors.append(f"Line {n}: not valid JSON")
    for n, o in pairs:
        try:
            runs.append(_run_from_obj(o, cfg))
        except (ValueError, TypeError) as e:
            errors.append(f"{label} {n}: {e}")
    return runs, errors


def parse_text(name, text, cfg=None):
    """Read a CSV, JSON, or JSON Lines file into runs. Returns (runs, errors)."""
    cfg = cfg or config()
    if len(text) > MAX_TEXT:
        raise ValueError("That file is larger than 10 MB")
    text = text.lstrip("\ufeff").strip()
    is_json = name.lower().endswith((".json", ".jsonl", ".ndjson")) or text[:1] in ("[", "{")
    try:
        return _json_runs(text, cfg) if is_json else _csv_runs(text, cfg)
    except ValueError as e:
        return [], [str(e)]


# ---------- storage (demo mode keeps imports in memory) ----------
def _key(d, r):
    return (d, r["category"], r["question"], r["engine"], r.get("model") or "", r.get("location") or "")


class MemResearch:
    def __init__(self):
        self.clear()

    def clear(self):
        self.imported = {}

    def research_save_run(self, run):
        k = _key(run["date"], run)
        status = "replaced" if k in self.imported else "added"
        self.imported[k] = {"run_date": date.fromisoformat(run["date"]), "category": run["category"], "question": run["question"],
                            "engine": run["engine"], "model": run.get("model", ""), "location": run.get("location", ""),
                            "citations": run.get("citations", []), "results": run["results"]}
        return status

    def research_runs(self, since):
        merged = {_key(r["run_date"].isoformat(), r): r for r in demo_runs(date.today())}
        merged.update(self.imported)
        return [r for r in merged.values() if r["run_date"].isoformat() >= since]


_MEM = MemResearch()


def _be(demo_mode):
    return _MEM if demo_mode else store


def import_text(name, text, demo_mode, cfg=None):
    runs, errors = parse_text(name, text, cfg)
    out = {"file": name, "runs": 0, "added": 0, "replaced": 0, "errors": errors[:MAX_ERRORS], "error_count": len(errors)}
    if errors or not runs:  # all or nothing, so a half-imported file never skews the numbers
        if not errors:
            out["errors"], out["error_count"] = ["No results found in this file"], 1
        return out
    be = _be(demo_mode)
    out["runs"] = len(runs)
    for r in runs:
        out[be.research_save_run(r)] += 1
    return out


def import_request(body, demo_mode):
    if body.get("inbox"):
        folder = inbox("research")
        folder.mkdir(parents=True, exist_ok=True)
        files = sorted(p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in (".csv", ".json", ".jsonl", ".ndjson", ".txt"))
        if not files:
            raise ValueError("No files found in data_inbox/research/. Put exported .csv or .jsonl files there first.")
        return {"results": [import_text(p.name, p.read_text(encoding="utf-8-sig", errors="replace"), demo_mode) for p in files]}
    files = body.get("files")
    if not isinstance(files, list) or not files or not all(isinstance(f, dict) and isinstance(f.get("text"), str) for f in files):
        raise ValueError("Choose one or more files to import")
    return {"results": [import_text(str(f.get("name") or "file"), f["text"], demo_mode) for f in files]}


# ---------- analysis ----------
def _our_domain(d, brands):
    return any(d == s or d.endswith("." + s) for b in brands for s in b.get("sites") or [])


def analyze(runs, brands, category, since, cfg=None):
    """Compare the latest answer to each question, per engine, within the period."""
    cfg = cfg or config()
    kind = {k: v.get("kind", "generative") for k, v in cfg["engines"].items()}
    names = {b["id"]: b["name"] for b in brands}
    latest = {}
    for r in runs:
        if r["category"] == category and r["run_date"] >= since and r["engine"] in kind:
            k = (norm_q(r["question"]), r["engine"])
            if k not in latest or r["run_date"] >= latest[k]["run_date"]:
                latest[k] = r

    def listed(run):
        seen = {}
        for it in sorted(run["results"], key=lambda x: x["rank"]):
            bid, d = resolve_brand(it["name"], it.get("url"), brands), domain_of(it.get("url"))
            key = "brand:" + bid if bid else ("d:" + d if d else "n:" + re.sub(r"[^a-z0-9]", "", it["name"].lower()))
            seen.setdefault(key, {"key": key, "name": names[bid] if bid else it["name"], "brand_id": bid, "domain": d, "rank": it["rank"]})
        return seen

    parsed = {k: listed(r) for k, r in latest.items()}
    gen = [k for k in latest if kind[k[1]] == "generative"]
    seo = [k for k in latest if kind[k[1]] == "seo"]
    ent = {}

    def entity(e):
        return ent.setdefault(e["key"], {"name": e["name"], "brand_id": e["brand_id"], "domain": e["domain"],
                                         "gen": [], "seo": [], "by_engine": defaultdict(list)})

    for k in gen:
        for e in parsed[k].values():
            x = entity(e)
            x["gen"].append(e["rank"])
            x["by_engine"][k[1]].append(e["rank"])
    for k in seo:
        for e in parsed[k].values():
            entity(e)["seo"].append(e["rank"])
    for b in brands:
        if b["category"] == category:
            entity({"key": "brand:" + b["id"], "name": b["name"], "brand_id": b["id"], "domain": None})

    def stat(ranks, n):
        return {"count": len(ranks), "rate": round(len(ranks) / n, 3) if n else None,
                "avg_rank": round(sum(ranks) / len(ranks), 1) if ranks else None, "best": min(ranks) if ranks else None}

    rows = []
    for x in ent.values():
        g, s = stat(x["gen"], len(gen)), stat(x["seo"], len(seo))
        rows.append({"name": x["name"], "brand_id": x["brand_id"], "ours": bool(x["brand_id"]), "domain": x["domain"], "gen": g, "seo": s,
                     "by_engine": {e: round(sum(v) / len(v), 1) for e, v in x["by_engine"].items()},
                     "gap": None if g["rate"] is None or s["rate"] is None else round(g["rate"] - s["rate"], 3)})
    rows.sort(key=lambda r: (-(r["gen"]["rate"] or 0), -(r["seo"]["rate"] or 0), r["name"]))
    table = [r for r in rows if r["ours"]] + [r for r in rows if not r["ours"]][:15]
    table.sort(key=lambda r: (-(r["gen"]["rate"] or 0), -(r["seo"]["rate"] or 0), r["name"]))
    brief = lambda r: {"name": r["name"], "ours": r["ours"], "ai_rate": r["gen"]["rate"], "seo_rate": r["seo"]["rate"]}
    ai_not_seo = [brief(r) for r in rows if seo and gen and r["gen"]["rate"] >= 0.25 and r["seo"]["count"] == 0][:5]
    seo_not_ai = [brief(r) for r in sorted(rows, key=lambda r: -(r["seo"]["rate"] or 0))
                  if seo and gen and (r["seo"]["rate"] or 0) >= 0.25 and r["gen"]["count"] == 0][:5]

    configured = cfg.get("questions", {}).get(category, [])
    qtext = {norm_q(q): q for q in configured}
    for (nq, _), r in latest.items():
        qtext.setdefault(nq, r["question"])
    questions = []
    for nq, text in qtext.items():
        seo_union = set()
        for e in cfg["engines"]:
            if kind[e] == "seo" and (nq, e) in parsed:
                seo_union |= set(parsed[(nq, e)])
        per = {}
        for e in cfg["engines"]:
            r = latest.get((nq, e))
            if not r:
                per[e] = None
                continue
            p = parsed[(nq, e)]
            per[e] = {"date": r["run_date"].isoformat(), "listed": len(p),
                      "ours": [{"name": x["name"], "rank": x["rank"]} for x in sorted(p.values(), key=lambda x: x["rank"]) if x["brand_id"]],
                      "top": [x["name"] for x in sorted(p.values(), key=lambda x: x["rank"])[:3]],
                      "overlap": round(len(set(p) & seo_union) / len(p), 2) if kind[e] == "generative" and seo_union and p else None}
        questions.append({"question": text, "configured": nq in {norm_q(q) for q in configured}, "engines": per})

    cites = Counter()
    for k in gen:
        cites.update({domain_of(c["url"]) for c in latest[k].get("citations", [])} - {None})

    def share(keys):
        return round(sum(1 for k in keys if any(e["brand_id"] for e in parsed[k].values())) / len(keys), 3) if keys else None

    def slots(keys):
        total = sum(len(parsed[k]) for k in keys)
        return round(sum(1 for k in keys for e in parsed[k].values() if e["brand_id"]) / total, 3) if total else None

    return {"category": category,
            "summary": {"runs_gen": len(gen), "runs_seo": len(seo), "ours_gen": share(gen), "ours_seo": share(seo),
                        "ours_gen_slots": slots(gen), "ours_seo_slots": slots(seo)},
            "table": table, "ai_not_seo": ai_not_seo, "seo_not_ai": seo_not_ai, "questions": questions,
            "sources": [{"domain": d, "count": n, "ours": _our_domain(d, brands)} for d, n in cites.most_common(10)]}


def overview(runs, brands, since, cfg=None):
    cfg = cfg or config()
    out = []
    for c in registry.category_list():
        a = analyze(runs, brands, c["id"], since, cfg)
        s = a["summary"]
        if c["id"] == "uncategorized" and not (s["runs_gen"] or s["runs_seo"]):
            continue
        combos = len(a["questions"]) * len(cfg["engines"])
        done = sum(1 for q in a["questions"] for v in q["engines"].values() if v)
        out.append({"id": c["id"], "label": c["label"], "runs_gen": s["runs_gen"], "runs_seo": s["runs_seo"],
                    "ours_gen": s["ours_gen"], "ours_seo": s["ours_seo"], "ours_gen_slots": s["ours_gen_slots"],
                    "ours_seo_slots": s["ours_seo_slots"], "missing": combos - done, "combos": combos})
    return out


def report(days, category, demo_mode):
    cfg, brands = config(), registry.active_brands()
    since = date.today() - timedelta(days=days - 1)
    if category and category not in {c["id"] for c in registry.category_list()}:
        raise ValueError("Unknown category")
    runs = _be(demo_mode).research_runs(since.isoformat())
    return {"categories": overview(runs, brands, since, cfg), "detail": analyze(runs, brands, category, since, cfg) if category else None,
            "engines": [{"id": k, "label": v["label"], "kind": v.get("kind", "generative")} for k, v in cfg["engines"].items()]}


# ---------- demo data ----------
COMPETITORS = ["Acme Lending", "Summit Credit", "Harbor Finance", "Pinecrest Loans", "Bluebird Capital",
               "Northgate Funding", "Redwood Lending", "Clearpath Loans", "Oakline Credit", "Silverton Finance"]


def demo_runs(today):
    """Deterministic sample answers: AI engines and Google favour different companies."""
    cfg, brands, runs = config(), registry.all_brands(), []
    for cat in registry.categories():
        ours = [b for b in brands if b["category"] == cat["id"] and b["active"]]
        for qi, q in enumerate(cfg.get("questions", {}).get(cat["id"], [])):
            for eng, meta in cfg["engines"].items():
                rng = random.Random(f"{cat['id']}-{qi}-{eng}")
                if rng.random() < 0.15:
                    continue  # a few gaps, so "runs still needed" has something to show
                generative = meta.get("kind", "generative") == "generative"
                pool = [(c, f"{re.sub(r'[^a-z]', '', c.lower())}.example.net", 1.0 - 0.07 * i) for i, c in enumerate(COMPETITORS)]
                pool += [(b["name"], (b["sites"] or [None])[0], (demo.profile(b["id"])["share"] * 6) if generative else 0.55) for b in ours]
                top = sorted(pool, key=lambda p: -(rng.random() ** (1.0 / max(p[2], 0.05))))[:10]
                results = [{"rank": i + 1, "name": n, "url": (f"https://www.{d}" if d and not (generative and rng.random() < 0.3) else None)}
                           for i, (n, d, _) in enumerate(top)]
                cites = [{"url": f"https://{d}/guide", "title": ""} for d in ("reviews.example.net", "guide.example.com", "forum.example.org")[:rng.randint(2, 3)]]
                cites += [{"url": r["url"], "title": ""} for r in results[:2] if r["url"]]
                runs.append({"run_date": today - timedelta(days=rng.randint(0, 9)), "category": cat["id"], "question": q, "engine": eng,
                             "model": "", "location": "", "citations": cites if generative else [], "results": results})
    return runs
