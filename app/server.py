import argparse
import json
import os
import sys
from datetime import date, datetime, timedelta, timezone
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs, urlparse

from app import demo
from app.summary import build_summary
from connectors.base import load_brands

STATIC = Path(__file__).parent / "static"
DEMO = False


def _connect():
    import psycopg

    return psycopg.connect(os.environ["DATABASE_URL"])


def fetch_rows(start, end):
    if DEMO:
        return demo.demo_rows(date.today())
    with _connect() as conn, conn.cursor() as cur:
        cur.execute(
            "select brand_id, day, source, metric, value, dimensions from fact_metrics where day between %s and %s",
            (start, end),
        )
        keys = ("brand_id", "day", "source", "metric", "value", "dimensions")
        return [dict(zip(keys, r)) for r in cur.fetchall()]


def fetch_status():
    if DEMO:
        now = datetime.now(timezone.utc)
        names = ["ga4", "google_ads", "meta_ads", "trustpilot", "geo_tracker", "bot_logs"]
        return [{"connector": n, "last_success": now.isoformat(), "last_error": None, "rows_loaded": 1200} for n in names]
    with _connect() as conn, conn.cursor() as cur:
        cur.execute("select connector, last_success, last_error, rows_loaded from sync_status order by connector")
        keys = ("connector", "last_success", "last_error", "rows_loaded")
        return [dict(zip(keys, r)) for r in cur.fetchall()]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def _send(self, code, body, ctype):
        data = body if isinstance(body, bytes) else body.encode()
        self.send_response(code)
        self.send_header("Content-Type", ctype)
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def _json(self, payload, code=200):
        self._send(code, json.dumps(payload, default=str), "application/json")

    def do_GET(self):
        url = urlparse(self.path)
        try:
            if url.path == "/":
                self._send(200, (STATIC / "index.html").read_bytes(), "text/html; charset=utf-8")
            elif url.path == "/api/summary":
                days = max(7, min(60, int(parse_qs(url.query).get("days", ["30"])[0])))
                end = date.today()
                rows = fetch_rows(end - timedelta(days=2 * days), end)
                payload = build_summary(rows, load_brands(), end, days)
                payload["demo"] = DEMO
                self._json(payload)
            elif url.path == "/api/status":
                self._json(fetch_status())
            else:
                self._json({"error": "Not found"}, 404)
        except Exception as e:  # shown in the UI so setup problems are visible
            self._json({"error": f"{type(e).__name__}: {e}"}, 500)


def make_server(port=8000):
    return ThreadingHTTPServer(("127.0.0.1", port), Handler)


def main():
    global DEMO
    p = argparse.ArgumentParser()
    p.add_argument("--demo", action="store_true", help="use built-in fake data, no database needed")
    p.add_argument("--port", type=int, default=8000)
    args = p.parse_args()
    DEMO = args.demo
    if not DEMO and not os.environ.get("DATABASE_URL"):
        sys.exit("Set DATABASE_URL, or run with --demo to use built-in fake data.")
    print(f"Brand ops app at http://127.0.0.1:{args.port}" + (" (demo data)" if DEMO else ""))
    make_server(args.port).serve_forever()


if __name__ == "__main__":
    main()
