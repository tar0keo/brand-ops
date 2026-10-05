import argparse
import csv
import io
import json
import os
import subprocess
import sys
import tempfile
import webbrowser
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import yaml

from app import demo, dossier, jira, media, registry, tasklog
from app.summary import build_summary
from app.tasks import generate_tasks
from connectors import base, paths, store
from connectors import run as runner
from connectors.files import inbox, load_yaml

STATIC = Path(__file__).parent / "static"
DEMO = False


_REAL_BRANDS = None


def enable_demo():
    """Demo mode runs on its own sample brands in a temp file, so your real brands.yaml is never touched."""
    global DEMO, _REAL_BRANDS
    if DEMO:
        return
    _REAL_BRANDS = base.BRANDS_PATH
    path = Path(tempfile.mkdtemp(prefix="brandops-demo-")) / "brands.yaml"
    path.write_text(yaml.safe_dump({"brands": demo.sample_brands()}, sort_keys=False))
    base.BRANDS_PATH = path
    DEMO = True


def disable_demo():
    global DEMO
    if DEMO and _REAL_BRANDS is not None:
        base.BRANDS_PATH = _REAL_BRANDS
    DEMO = False


def fetch_rows(start, end):
    if DEMO:
        return demo.cached_rows(date.today(), tuple(b["id"] for b in registry.all_brands()))
    return store.fetch_rows(start, end)


def fetch_status():
    if DEMO:
        now = datetime.now(timezone.utc)
        names = ["ga4", "google_ads", "meta_ads", "trustpilot", "geo_tracker", "bot_logs"]
        return [{"connector": n, "last_success": now.isoformat(), "last_error": None, "rows_loaded": 1200} for n in names]
    return store.fetch_status()


def get_summary(days):
    end = date.today()
    rows = fetch_rows(end - timedelta(days=2 * days), end)
    return build_summary(rows, registry.active_brands(), end, days, registry.category_list())


def dossier_html(days, category=None):
    end = date.today()
    rows = fetch_rows(end - timedelta(days=2 * days), end)
    brands = registry.active_brands()
    summary = build_summary(rows, brands, end, days, registry.category_list())
    tasks = generate_tasks(summary, load_yaml("task_rules.yaml"))
    try:
        status = fetch_status()
    except Exception:
        status = []
    series = dossier.daily_profit(rows, brands, end - timedelta(days=days - 1), end)
    return dossier.render(summary, tasks, series, status, DEMO, category)


def brand_action(path, body):
    if path == "/api/brands":
        return registry.add_brand(body.get("name", ""), body.get("category") or "uncategorized", body.get("id") or None)
    if path == "/api/brands/category":
        return registry.set_category(body.get("id", ""), body.get("category", ""))
    if path == "/api/brands/archive":
        return registry.set_active(body.get("id", ""), bool(body.get("active")))
    if path == "/api/brands/site":
        return registry.add_site(body.get("id", ""), body.get("domain", ""))
    if path == "/api/brands/site/remove":
        return registry.remove_site(body.get("id", ""), body.get("domain", ""))
    raise ValueError("Unknown action")


def current_tasks(days):
    rules = load_yaml("task_rules.yaml")
    tasks = generate_tasks(get_summary(days), rules)
    ticketed = tasklog.recent(DEMO, rules["cooldown_days"])
    for t in tasks:
        t["ticket"] = ticketed.get(t["key"])
    return tasks, rules


def live_jira(rules):
    return jira.configured(rules["jira"]) and not DEMO  # demo data never reaches a real Jira


def create_tasks(keys, days):
    tasks, rules = current_tasks(days)
    by_key = {t["key"]: t for t in tasks}
    live, results = live_jira(rules), []
    for k in keys:
        t = by_key.get(k)
        if t is None:
            results.append({"key": k, "error": "This task no longer applies"})
        elif t["ticket"]:
            results.append({"key": k, "ticket": t["ticket"], "skipped": True})
        else:
            try:
                if live:
                    ticket = jira.create_issue(rules["jira"], t)
                elif DEMO:
                    ticket = f"DEMO-{len(tasklog._MEM) + 1}"
                else:
                    raise RuntimeError("Jira is not configured. Set the JIRA_ variables or download the CSV.")
                tasklog.record(DEMO, k, ticket)
                results.append({"key": k, "ticket": ticket, "simulated": not live})
            except Exception as e:
                results.append({"key": k, "error": str(e)})
    return results


def tasks_csv(tasks):
    out = io.StringIO()
    w = csv.writer(out)
    w.writerow(["Summary", "Description", "Issue Type", "Priority", "Labels", "Labels", "Labels"])
    for t in tasks:
        if t["ticket"]:
            continue
        f = jira.build_fields({}, "", t)
        w.writerow([f["summary"], f["description"], "Task", t["priority"], *f["labels"]])
    return out.getvalue()


SOURCES = [("google_ads", "Google Ads", "google_ads/"), ("meta_ads", "Meta Ads", "meta_ads/"),
           ("trustpilot", "Trustpilot", "trustpilot/"), ("geo_tracker", "GEO tracker", "geo_tracker/"),
           ("bot_logs", "AI crawler logs", "bot_logs/<brand id>/"), ("ga4", "Google Analytics 4", "needs API access")]


def desktop():
    return os.environ.get("BRANDOPS_DESKTOP") == "1"


def info():
    return {"demo": DEMO, "desktop": desktop(), "inbox": str(inbox()),
            "database": "sqlite" if store.is_sqlite() else "postgres",
            "sources": [{"id": i, "label": label, "folder": folder} for i, label, folder in SOURCES]}


def sync(name, days):
    if DEMO:
        raise ValueError("Importing is turned off in demo mode.")
    if name not in {i for i, _, _ in SOURCES}:
        raise ValueError("Unknown source")
    try:
        return {"connector": name, "rows": runner.run(name, days)}
    except ImportError:
        raise ValueError("This connector needs a package that isn't included in this build.") from None
    except (RuntimeError, FileNotFoundError) as e:
        raise ValueError(str(e)) from None


def open_path(path):
    """Open a file or folder with the operating system's default app."""
    if sys.platform == "win32":
        os.startfile(str(path))
    else:
        subprocess.Popen(["open" if sys.platform == "darwin" else "xdg-open", str(path)])


def open_folder():
    if not desktop():
        raise ValueError("Only available in the desktop app")
    path = inbox()
    path.mkdir(parents=True, exist_ok=True)
    open_path(path)
    return {"opened": str(path)}


def open_url(url):
    """Open a saved media link in the default browser (the desktop window cannot open new tabs)."""
    if not desktop():
        raise ValueError("Only available in the desktop app")
    if not media.known_url(url, DEMO):
        raise ValueError("That link isn't in your list")
    webbrowser.open(url)
    return {"opened": url}


def export_file(kind, days, category):
    """Desktop only: save the dossier or the task CSV into the exports folder and open it."""
    if not desktop():
        raise ValueError("Only available in the desktop app")
    if category and category not in {c["id"] for c in registry.category_list()}:
        raise ValueError("Unknown category")
    out = paths.home() / "exports"
    out.mkdir(parents=True, exist_ok=True)
    stamp = str(date.today()) + (f"-{category}" if category else "")
    if kind == "dossier":
        path = out / f"brand-ops-dossier-{stamp}.html"
        path.write_text(dossier_html(days, category), encoding="utf-8")
    elif kind == "tasks":
        tasks, _ = current_tasks(days)
        if category:
            tasks = [t for t in tasks if t.get("category") == category]
        path = out / f"brand-ops-tasks-{stamp}.csv"
        with open(path, "w", encoding="utf-8", newline="") as f:
            f.write(tasks_csv(tasks))
    else:
        raise ValueError("Unknown export")
    try:
        open_path(path)
    except OSError:
        pass  # the file is saved either way
    return {"path": str(path)}


def media_action(path, body):
    if path == "/api/media/add":
        return media.add_links(str(body.get("text", "")), DEMO)
    if path == "/api/media/assign":
        return media.assign(int(body.get("id", 0)), body.get("brand_id") or None, DEMO)
    if path == "/api/media/remove":
        return media.remove(int(body.get("id", 0)), DEMO)
    if path == "/api/media/rematch":
        return media.rematch(DEMO)
    raise ValueError("Unknown action")


def set_demo(on):
    if not desktop():
        raise ValueError("Only available in the desktop app")
    enable_demo() if on else disable_demo()
    return {"demo": DEMO}


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype, headers=None):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        for k, v in (headers or {}).items():
            self.send_header(k, v)
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, default=str), "application/json")

    def _days(self, query):
        return max(7, min(60, int(parse_qs(query).get("days", ["30"])[0])))

    def _guard(self, post=False):
        host = self.headers.get("Host", "").rsplit(":", 1)[0]
        if host not in ("127.0.0.1", "localhost"):
            self._json({"error": "Forbidden"}, 403)
            return False
        if post and not self.headers.get("Content-Type", "").startswith("application/json"):
            self._json({"error": "Content-Type must be application/json"}, 415)
            return False
        return True

    def do_GET(self):
        if not self._guard():
            return
        url = urlparse(self.path)
        try:
            if url.path == "/":
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/summary":
                payload = get_summary(self._days(url.query))
                payload["demo"] = DEMO
                payload["desktop"] = desktop()
                self._json(payload)
            elif url.path == "/api/brands":
                self._json({"brands": registry.all_brands(), "categories": registry.category_list()})
            elif url.path == "/dossier":
                q = parse_qs(url.query)
                headers = {}
                if q.get("download"):
                    headers["Content-Disposition"] = f'attachment; filename="brand-ops-dossier-{date.today()}.html"'
                self._send(200, dossier_html(self._days(url.query), (q.get("category") or [None])[0] or None),
                           "text/html; charset=utf-8", headers)
            elif url.path == "/api/media":
                self._json({"items": media.list_items(DEMO), "demo": DEMO,
                            "brands": [{"id": b["id"], "name": b["name"], "category": b["category"]} for b in registry.active_brands()]})
            elif url.path == "/api/info":
                self._json(info())
            elif url.path == "/api/status":
                self._json(fetch_status())
            elif url.path == "/api/tasks":
                tasks, rules = current_tasks(self._days(url.query))
                self._json({"tasks": tasks, "demo": DEMO, "jira": {"configured": live_jira(rules)}})
            elif url.path == "/api/tasks.csv":
                tasks, _ = current_tasks(self._days(url.query))
                self._send(200, tasks_csv(tasks), "text/csv; charset=utf-8",
                           {"Content-Disposition": 'attachment; filename="brand-ops-tasks.csv"'})
            else:
                self._json({"error": "Not found"}, 404)
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:  # shown in the UI so setup problems are visible
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)

    def do_POST(self):
        if not self._guard(post=True):
            return
        url = urlparse(self.path)
        try:
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            if url.path.startswith("/api/brands"):
                return self._json({"brand": brand_action(url.path, body)})
            if url.path == "/api/sync":
                return self._json(sync(body.get("connector", ""), max(1, min(730, int(body.get("days", 90))))))
            if url.path.startswith("/api/media"):
                return self._json(media_action(url.path, body))
            if url.path == "/api/open-url":
                return self._json(open_url(str(body.get("url", ""))))
            if url.path == "/api/export":
                days = max(7, min(60, int(body.get("days", 30))))
                return self._json(export_file(body.get("kind", ""), days, body.get("category") or None))
            if url.path == "/api/open-folder":
                return self._json(open_folder())
            if url.path == "/api/demo":
                return self._json(set_demo(bool(body.get("on"))))
            if url.path != "/api/tasks/create":
                return self._json({"error": "Not found"}, 404)
            keys = body.get("keys")
            if not isinstance(keys, list) or not all(isinstance(k, str) for k in keys):
                return self._json({"error": "keys must be a list of task keys"}, 400)
            days = max(7, min(60, int(body.get("days", 30))))
            self._json({"results": create_tasks(keys, days)})
        except ValueError as e:
            self._json({"error": str(e)}, 400)
        except Exception as e:
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def make_server(port=8000):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="use built-in sample brands and fake data, no database needed")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    if args.demo:
        enable_demo()
    elif not os.environ.get("DATABASE_URL"):
        sys.exit("Set DATABASE_URL, or run with --demo to use built-in fake data.")
    print(f"Brand ops app at http://127.0.0.1:{args.port}" + (" (demo data, 30 sample brands)" if DEMO else ""))
    make_server(args.port).serve_forever()


if __name__ == "__main__":
    main()
