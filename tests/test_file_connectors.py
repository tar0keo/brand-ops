from datetime import date

import pytest

from connectors.bot_logs import Connector as BotLogs
from connectors.geo_tracker import Connector as GeoTracker
from connectors.google_ads import Connector as GoogleAds

START, END = date(2026, 1, 1), date(2026, 1, 3)


def put(tmp_path, monkeypatch, rel, text):
    monkeypatch.setenv("INBOX_DIR", str(tmp_path))
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


ADS_CFG = {
    "columns": {"day": "Day", "campaign": "Campaign", "cost": "Cost", "clicks": "Clicks",
                "impressions": "Impr.", "conversions": "Conversions", "conv_value": "Conv. value"},
    "campaign_rules": [{"contains": "FLA", "brand_id": "fla"}, {"contains": "Paiio", "brand_id": "paiio"}],
}
ADS = '''Campaign performance
"January 1, 2026 - January 3, 2026"
Day,Campaign,Cost,Clicks,Impr.,Conversions,Conv. value
2026-01-02,FLA | Search | Brand,"1,200.50",300,"10,000",12.0,"3,400.00"
2026-01-02,Paiio | PMax,50,5,100,0,0
Total: account,"1,250.50",305,"10,100",12.0,"3,400.00"
'''


def test_google_ads_parses_export(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "google_ads/a.csv", ADS)
    rows = list(GoogleAds(ADS_CFG).fetch(START, END))
    got = {(r.brand_id, r.metric): r.value for r in rows}
    assert len(rows) == 10
    assert got[("fla", "ad_spend")] == 1200.5
    assert got[("fla", "impressions")] == 10000
    assert got[("fla", "revenue")] == 3400
    assert got[("paiio", "ad_spend")] == 50


def test_google_ads_unmatched_campaign_stops(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "google_ads/a.csv", ADS + "2026-01-02,Mystery,5,1,1,0,0\n")
    with pytest.raises(ValueError, match="Mystery"):
        list(GoogleAds(ADS_CFG).fetch(START, END))


def test_google_ads_later_file_wins_on_overlap(tmp_path, monkeypatch):
    head = "Day,Campaign,Cost\n"
    put(tmp_path, monkeypatch, "google_ads/a.csv", head + "2026-01-02,FLA x,100\n")
    put(tmp_path, monkeypatch, "google_ads/b.csv", head + "2026-01-02,FLA x,200\n")
    rows = list(GoogleAds(ADS_CFG).fetch(START, END))
    assert [r.value for r in rows if r.metric == "ad_spend"] == [200]


GEO_CFG = {
    "columns": {"date": "Date", "engine": "Engine", "prompt": "Prompt", "mentioned": "Mentioned", "brand": "Brand"},
    "mentioned_values": ["yes", "true", "1"],
}
PROMPTS = [
    {"id": "fla_d1", "brand_id": "fla", "text": "best widget for travel"},
    {"id": "fla_t1", "brand_id": "fla", "text": "is FLA legit"},
]


def test_geo_tracker_counts_runs_and_mentions(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "geo_tracker/a.csv",
        "Date,Engine,Prompt,Mentioned\n"
        "2026-01-02,ChatGPT,best widget for travel,yes\n"
        "2026-01-02,ChatGPT,best widget for travel,no\n"
        "2026-01-02,Perplexity,is fla legit,Yes\n")
    rows = list(GeoTracker(GEO_CFG, PROMPTS).fetch(START, END))
    got = {(r.dimensions["engine"], r.metric): r.value for r in rows}
    assert got[("chatgpt", "geo_prompt_runs")] == 2
    assert got[("chatgpt", "geo_mentions")] == 1
    assert got[("perplexity", "geo_prompt_runs")] == 1
    assert got[("perplexity", "geo_mentions")] == 1
    assert all(r.brand_id == "fla" for r in rows)


def test_geo_tracker_unknown_prompt_stops(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "geo_tracker/a.csv", "Date,Engine,Prompt,Mentioned\n2026-01-02,Gemini,unknown q,no\n")
    with pytest.raises(ValueError, match="unknown q"):
        list(GeoTracker(GEO_CFG, PROMPTS).fetch(START, END))


BOTS_CFG = {"bots": {"GPTBot": "gptbot", "ClaudeBot": "claudebot"}}
LOG = (
    '1.2.3.4 - - [02/Jan/2026:10:00:00 +0000] "GET /a HTTP/1.1" 200 512 "-" "Mozilla/5.0 (compatible; GPTBot/1.1)"\n'
    '1.2.3.4 - - [02/Jan/2026:10:00:05 +0000] "GET /b HTTP/1.1" 403 12 "-" "Mozilla/5.0 (compatible; GPTBot/1.1)"\n'
    '5.6.7.8 - - [02/Jan/2026:11:00:00 +0000] "GET /a HTTP/1.1" 200 512 "-" "Mozilla/5.0 Chrome/120"\n'
    '9.9.9.9 - - [02/Jan/2026:12:00:00 +0000] "GET /a HTTP/1.1" 200 512 "-" "ClaudeBot/1.0"\n'
)


def test_bot_logs_counts_ai_crawlers_only(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "bot_logs/fla/access.log", LOG)
    rows = list(BotLogs(BOTS_CFG).fetch(START, END))
    hits = {r.dimensions["bot"]: r.value for r in rows if r.metric == "ai_crawler_hits"}
    errors = [r for r in rows if r.metric == "ai_crawler_errors"]
    assert hits == {"gptbot": 2, "claudebot": 1}
    assert len(errors) == 1 and errors[0].dimensions == {"bot": "gptbot", "status": "403"}
    assert all(r.brand_id == "fla" for r in rows)


def test_bot_logs_unknown_brand_folder_stops(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "bot_logs/nope/access.log", LOG)
    with pytest.raises(ValueError, match="nope"):
        list(BotLogs(BOTS_CFG).fetch(START, END))
