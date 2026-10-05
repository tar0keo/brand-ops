import urllib.request
from datetime import date

from app import demo, registry
from app.summary import build_summary
from connectors.base import load_brands
from tests.helpers import get

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


def test_category_totals_add_up_and_exclude_archived():
    brands = [{"id": "a", "name": "A", "category": "auto"}, {"id": "b", "name": "B", "category": "auto"},
              {"id": "c", "name": "C", "category": "home"}]
    day = date(2026, 1, 7)
    rows = [row(day, "google_ads", "ad_spend", 100, brand="a"), row(day, "google_ads", "revenue", 300, brand="a"),
            row(day, "google_ads", "ad_spend", 100, brand="b"), row(day, "google_ads", "revenue", 100, brand="b"),
            row(day, "google_ads", "ad_spend", 50, brand="c"), row(day, "google_ads", "revenue", 50, brand="c"),
            row(day, "google_ads", "ad_spend", 999, brand="gone")]  # archived brand, not in the list
    cats = [{"id": "auto", "label": "Auto"}, {"id": "home", "label": "Home"}, {"id": "student", "label": "Student"}]
    s = build_summary(rows, brands, END, 5, cats)
    by = {c["id"]: c for c in s["categories"]}
    assert list(by) == ["auto", "home"]  # a category with no brands is left out
    assert by["auto"]["brand_count"] == 2 and by["auto"]["current"]["roas"] == 2.0 and by["auto"]["current"]["profit"] == 200
    assert s["portfolio"]["current"]["spend"] == 250


def test_demo_data_tells_its_stories():
    end = date(2026, 1, 31)
    s = build_summary(demo.demo_rows(end), demo.sample_brands(), end, 30, registry.category_list())
    by = {b["id"]: b for b in s["brands"]}
    assert len(by) == 30 and len(s["categories"]) == len(registry.categories())
    assert sum(c["brand_count"] for c in s["categories"]) == 30
    assert by["brand_3"]["current"]["roas"] < by["brand_3"]["previous"]["roas"]
    assert by["brand_8"]["current"]["bot_errors"] > 3 * by["brand_8"]["previous"]["bot_errors"]
    assert by["brand_14"]["current"]["rating"] < 4.0


def test_server_serves_page_and_api_in_demo_mode(demo_mode, app_url):
    data = get(app_url + "/api/summary?days=30")
    assert data["demo"] is True and len(data["brands"]) == 30 and data["categories"]
    assert len(get(app_url + "/api/status")) == 6
    assert b"Brand operations" in urllib.request.urlopen(app_url + "/").read()
