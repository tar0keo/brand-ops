import urllib.error
import urllib.request
from datetime import date, timedelta

import pytest

from app import demo, dossier, registry, research
from app.summary import build_summary
from tests.helpers import get

BR = [{"id": "b1", "name": "Brand 1", "category": "auto", "sites": []}]
Q = "Best lenders?"


def run(d, engine, names):
    return {"run_date": d, "category": "auto", "question": Q, "engine": engine, "model": "", "location": "", "citations": [],
            "results": [{"rank": i + 1, "name": n, "url": None} for i, n in enumerate(names)]}


RUNS = [
    run(date(2026, 9, 14), "chatgpt", ["Acme", "Zed", "Yan"]), run(date(2026, 9, 14), "google_organic", ["Acme", "Zed"]),
    run(date(2026, 9, 21), "chatgpt", ["Brand 1", "Acme", "Zed"]),
    # nothing in the week of 28 Sep, so that week is a gap
    run(date(2026, 10, 5), "chatgpt", ["Acme", "Zed"]), run(date(2026, 10, 6), "chatgpt", ["Brand 1", "Acme"]),  # same week: the later run counts
    run(date(2026, 10, 5), "google_organic", ["Brand 1", "Zed"]),
]
SINCE, END = date(2026, 9, 14), date(2026, 10, 8)


def test_weekly_series_use_the_latest_run_and_leave_gaps():
    t = research.trend(RUNS, BR, "auto", SINCE, END)
    assert t["weeks"] == [date(2026, 9, 14), date(2026, 9, 21), date(2026, 9, 28), date(2026, 10, 5)]
    assert t["ours_gen"] == [0.0, 0.333, None, 0.5] and t["ours_seo"] == [0.0, None, None, 0.5]
    assert t["runs_gen"] == [1, 1, 0, 1] and t["runs_seo"] == [1, 0, 0, 1] and t["enough"] and t["has_data"]
    brand = t["brands"][0]
    assert brand["name"] == "Brand 1" and brand["gen"] == [0.0, 1.0, None, 1.0] and brand["seo"] == [0.0, None, None, 1.0]
    assert [c["name"] for c in t["competitors"]] == ["Acme", "Zed", "Yan"]


def test_movers_and_summary_compare_the_two_halves():
    t = research.trend(RUNS, BR, "auto", SINCE, END)
    assert [m["name"] for m in t["movers"]["rising"]] == ["Brand 1"] and t["movers"]["rising"][0]["ours"] is True
    assert [m["name"] for m in t["movers"]["falling"]] == ["Zed", "Yan"]
    assert t["movers"]["falling"][0] == {"name": "Zed", "ours": False, "before": 1.0, "now": 0.0, "change": -1.0}
    s = t["summary"]
    assert (s["ours_gen_before"], s["ours_gen_after"], s["ours_gen_change"]) == (0.167, 0.5, 0.333)
    assert (s["ours_seo_before"], s["ours_seo_after"], s["ours_seo_change"]) == (0.0, 0.5, 0.5)


def test_one_week_is_not_enough_for_a_trend():
    t = research.trend(RUNS[:1], BR, "auto", SINCE, date(2026, 9, 20))
    assert t["enough"] is False and t["has_data"] is True
    assert "at least two different weeks" in dossier.trend_html(t)
    empty = research.trend([], BR, "auto", SINCE, END)
    assert empty["has_data"] is False and empty["ours_gen"] == [None] * 4


def test_overview_has_one_row_per_category():
    rows = {r["id"]: r for r in research.trend_overview(RUNS, BR, SINCE, END)}
    assert rows["auto"]["enough"] and rows["auto"]["weeks"] == 3 and rows["auto"]["ours_gen_now"] == 0.5 and rows["auto"]["ours_gen_change"] == 0.333
    assert rows["personal"]["enough"] is False and rows["personal"]["weeks"] == 0


def test_trend_html_has_charts_and_tables():
    html = dossier.trend_html(research.trend(RUNS, BR, "auto", SINCE, END))
    assert html.count("<svg") == 3 and "Our share of listed spots" in html and "Rising in AI answers" in html and "Falling in AI answers" in html
    assert "Brand 1 <b>(ours)</b>" in html and "+33 pts" in html


def test_a_line_chart_leaves_a_gap_for_missing_weeks():
    svg = dossier.line_chart("t", [date(2026, 1, 1) + timedelta(days=7 * i) for i in range(5)], [("a", [1, 2, None, 3, 4])], dossier.pct, dots=True)
    assert svg.count("<polyline") == 2 and svg.count("<circle") == 4
    assert dossier.line_chart("t", [date(2026, 1, 1)], [("a", [None])]) == ""


def test_trend_endpoints(demo_mode, app_url):
    auto = registry.categories()[1]["id"]
    r = get(app_url + f"/api/research/trend?days=90&category={auto}")
    assert r["trend"]["enough"] is True and len(r["trend"]["weeks"]) >= 12 and r["html"].count("<svg") >= 2
    overview = get(app_url + "/api/research/trend?days=90")["overview"]
    assert len(overview) == len(registry.categories()) and all(row["enough"] for row in overview)
    assert get(app_url + f"/api/research/trend?days=5&category={auto}")["trend"]["days"] == 30  # the shortest range is 30 days
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(app_url + "/api/research/trend?category=nope")
    assert e.value.code == 400


def _report_inputs():
    end, brands = date.today(), demo.sample_brands()
    rows = demo.demo_rows(end)
    summary = build_summary(rows, brands, end, 30, registry.category_list())
    series = dossier.daily_profit(rows, brands, end - timedelta(days=29), end)
    trends = research.trends_for(brands, [c["id"] for c in summary["categories"]], 90, True)
    return summary, series, trends


def test_report_categories_are_dropdowns_with_trends(demo_mode):
    summary, series, trends = _report_inputs()
    n = len(summary["categories"])
    html = dossier.render(summary, [], series, [], True, None, trends)
    assert html.count('class="tg"') == n and " checked>" not in html and 'class="expall"' in html  # all collapsed, with an expand-all switch
    assert html.count("<title>Our share of listed spots") == n and "AI visibility trend by category" in html
    assert html.count("<svg") >= n * 6 and "<script" not in html
    assert "@media print" in html and ".bd{display:block!important}" in html  # printing opens everything
    single = dossier.render(summary, [], series, [], True, summary["categories"][0]["id"], trends)
    assert single.count(" checked>") == 1 and 'class="expall"' not in single and "AI visibility trend by category" not in single


def test_report_without_research_history_omits_the_trend_section(demo_mode):
    summary, series, _ = _report_inputs()
    html = dossier.render(summary, [], series, [], True, None, None)
    assert "<title>Our share of listed spots" not in html and "AI visibility trend by category" not in html
    quiet = {c["id"]: research.trend([], [], c["id"], date(2026, 1, 1), date(2026, 3, 1)) for c in summary["categories"]}
    assert "AI answers versus SEO over time" not in dossier.render(summary, [], series, [], True, None, quiet)


def test_the_exported_report_from_the_app_includes_trends(demo_mode, app_url):
    html = urllib.request.urlopen(app_url + "/dossier?days=30").read().decode()
    assert "AI answers versus SEO over time" in html and html.count('class="tg"') >= 5
