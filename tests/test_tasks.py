import urllib.request
from datetime import date

from app import demo, jira, registry
from app.summary import build_summary
from app.tasks import generate_tasks
from connectors.files import load_yaml
from tests.helpers import get, post

RULES = load_yaml("task_rules.yaml")
BASE = dict(spend=0, revenue=0, profit=None, roas=None, sessions=0, ai_sessions=0, conversion_rate=None,
            citation_share=None, bot_hits=0, bot_errors=0, rating=None, reviews=0, negative_share=None, reply_rate=None)


def summary(cur, prev):
    return {"brands": [{"id": "fla", "name": "FLA", "kind": "brand", "current": {**BASE, **cur}, "previous": {**BASE, **prev}}]}


def test_unhealthy_brand_gets_the_expected_tasks():
    s = summary(
        dict(spend=2000, roas=1.4, conversion_rate=0.0225, citation_share=0.10, bot_hits=200, bot_errors=40, rating=3.5, reviews=20),
        dict(spend=2000, roas=2.5, conversion_rate=0.03, citation_share=0.18, rating=4.0))
    got = {t["rule"]: t for t in generate_tasks(s, RULES)}
    assert {"roas_low", "conversion_drop", "citation_drop", "crawler_errors", "rating"} <= set(got)
    assert got["roas_low"]["priority"] == "High" and got["conversion_drop"]["priority"] == "High"
    assert got["rating"]["priority"] == "High" and got["crawler_errors"]["function"] == "Product"
    assert got["roas_low"]["key"] == "roas_low:fla"


def test_healthy_brand_and_low_volume_get_nothing():
    healthy = summary(dict(spend=2000, roas=3.0, conversion_rate=0.03, citation_share=0.2, bot_hits=200, bot_errors=2, rating=4.5, reviews=30, reply_rate=0.9),
                      dict(spend=2000, roas=3.0, conversion_rate=0.03, citation_share=0.2, rating=4.5))
    tiny = summary(dict(spend=100, roas=0.5, rating=3.0, reviews=3), dict())
    assert generate_tasks(healthy, RULES) == [] and generate_tasks(tiny, RULES) == []


def test_high_priority_sorts_first():
    s = summary(dict(spend=2000, roas=2.2, rating=3.5, reviews=20, reply_rate=0.1), dict(roas=2.9))
    pr = [t["priority"] for t in generate_tasks(s, RULES)]
    assert pr == sorted(pr, key=["High", "Medium", "Low"].index)


def test_demo_stories_become_tasks():
    end = date(2026, 1, 31)
    summary = build_summary(demo.demo_rows(end), demo.sample_brands(), end, 30, registry.category_list())
    tasks = generate_tasks(summary, RULES)
    keys = {t["key"] for t in tasks}
    assert {"crawler_errors:brand_8", "roas_low:brand_3", "rating:brand_14", "roas_low:brand_27"} <= keys
    assert all(t["category"] for t in tasks)


def test_issue_fields():
    task = {"key": "roas_low:fla", "brand": "FLA", "function": "Media Buying", "priority": "High",
            "title": "Fix it", "why": "Because.", "actions": ["Do a", "Do b"]}
    f = jira.build_fields({"issue_type": "Task"}, "BRAND", task)
    assert f["project"] == {"key": "BRAND"} and "priority" not in f
    assert "brandops-roas_low-fla" in f["labels"] and "media-buying" in f["labels"]
    assert "* Do a" in f["description"]
    assert jira.build_fields({"set_priority": True}, "BRAND", task)["priority"] == {"name": "High"}


def test_demo_flow_never_touches_jira_and_dedupes(demo_mode, app_url, monkeypatch):
    for k, v in {"JIRA_BASE_URL": "https://x.atlassian.net", "JIRA_EMAIL": "a@b.c", "JIRA_API_TOKEN": "t", "JIRA_PROJECT_KEY": "X"}.items():
        monkeypatch.setenv(k, v)
    r = get(app_url + "/api/tasks?days=30")
    assert r["jira"]["configured"] is False and r["tasks"]
    key = r["tasks"][0]["key"]
    first = post(app_url + "/api/tasks/create", {"keys": [key], "days": 30})[1]["results"][0]
    assert first["ticket"].startswith("DEMO-") and first["simulated"] is True
    assert post(app_url + "/api/tasks/create", {"keys": [key], "days": 30})[1]["results"][0]["skipped"] is True
    r2 = get(app_url + "/api/tasks?days=30")
    assert next(t for t in r2["tasks"] if t["key"] == key)["ticket"] == first["ticket"]
    csv_text = urllib.request.urlopen(app_url + "/api/tasks.csv?days=30").read().decode()
    assert csv_text.startswith("Summary,Description,Issue Type,Priority,Labels") and key.replace(":", "-") not in csv_text
