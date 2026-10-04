import json
import threading
import urllib.request
from datetime import date

from app import demo, server
from app.summary import build_summary
from connectors.base import load_brands

END = date(2026, 1, 10)


def row(day, source, metric, value, dims=None, brand="fla"):
    return {"brand_id": brand, "day": day, "source": source, "metric": metric, "value": value, "dimensions": dims or {}}


def test_metrics_for_one_brand_and_previous_window():
    cur, prev = date(2026, 1, 7), date(2026, 1, 3)
    rows = [
        row(cur, "google_ads", "ad_spend", 100), row(cur, "google_ads", "revenue", 300),
        row(prev, "google_ads", "ad_spend", 100), row(prev, "google_ads", "revenue", 200),
        row(cur, "ga4", "revenue", 999),
        row(cur, "ga4", "sessions", 1000, {"channel": "organic_search"}),
        row(cur, "ga4", "sessions", 100, {"channel": "ai_referral", "engine": "chatgpt"}),
        row(cur, "ga4", "transactions", 22),
        row(cur, "geo_tracker", "geo_prompt_runs", 10, {"engine": "chatgpt"}),
        row(cur, "geo_tracker", "geo_mentions", 2, {"engine": "chatgpt"}),
        row(cur, "trustpilot", "reviews_new", 3, {"stars": "5"}),
        row(cur, "trustpilot", "reviews_new", 1, {"stars": "1"}),
        row(cur, "trustpilot", "reviews_replied", 2),
    ]
    b = build_summary(rows, load_brands(), END, 5)["brands"][0]
    c = b["current"]
    assert (c["roas"], c["profit"]) == (3.0, 200.0)  # GA4 revenue is not counted as ad revenue
    assert b["previous"]["roas"] == 2.0
    assert c["citation_share"] == 0.2 and b["engines"] == {"chatgpt": 0.2}
    assert c["rating"] == 4.0 and c["negative_share"] == 0.25 and c["reply_rate"] == 0.5
    assert c["ai_sessions"] == 100 and c["conversion_rate"] == 0.02


def test_demo_data_tells_its_stories():
    end = date(2026, 1, 31)
    s = build_summary(demo.demo_rows(end), load_brands(), end, 30)
    by = {b["id"]: b for b in s["brands"]}
    assert len(by) == 7
    assert by["brand_1"]["current"]["roas"] < by["brand_1"]["previous"]["roas"]
    assert by["brand_2"]["current"]["bot_errors"] > 3 * by["brand_2"]["previous"]["bot_errors"]
    assert by["remarketing"]["current"]["citation_share"] is None and by["remarketing"]["current"]["rating"] is None
    assert by["fla"]["current"]["citation_share"] is not None


def test_server_serves_page_and_api_in_demo_mode():
    server.DEMO = True
    srv = server.make_server(0)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        data = json.load(urllib.request.urlopen(base + "/api/summary?days=30"))
        assert data["demo"] is True and len(data["brands"]) == 7
        assert len(json.load(urllib.request.urlopen(base + "/api/status"))) == 6
        assert b"Brand operations" in urllib.request.urlopen(base + "/").read()
    finally:
        srv.shutdown()
        server.DEMO = False
