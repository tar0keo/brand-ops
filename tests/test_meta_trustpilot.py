from datetime import date

import pytest

from connectors.meta_ads import Connector as MetaAds
from connectors.trustpilot import Connector as Trustpilot

START, END = date(2026, 1, 1), date(2026, 1, 3)


def put(tmp_path, monkeypatch, rel, text):
    monkeypatch.setenv("INBOX_DIR", str(tmp_path))
    p = tmp_path / rel
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text)


META_CFG = {
    "columns": {"day": "Day", "campaign": "Campaign name", "cost": "Amount spent (USD)", "clicks": "Link clicks",
                "impressions": "Impressions", "conversions": "Purchases", "conv_value": "Purchases conversion value"},
    "campaign_rules": [{"contains": "FLA", "brand_id": "fla"}, {"contains": "Paiio", "brand_id": "paiio"}],
}
META = '''Day,Campaign name,Amount spent (USD),Impressions,Link clicks,Purchases,Purchases conversion value
2026-01-02,FLA | Prospecting,350.25,"12,000",240,6,"900.00"
2026-01-02,Paiio | Retargeting,80,3000,,1,150
'''


def test_meta_ads_parses_export(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "meta_ads/a.csv", META)
    rows = list(MetaAds(META_CFG).fetch(START, END))
    got = {(r.brand_id, r.metric): r.value for r in rows}
    assert len(rows) == 10
    assert all(r.source == "meta_ads" for r in rows)
    assert got[("fla", "ad_spend")] == 350.25
    assert got[("fla", "impressions")] == 12000
    assert got[("paiio", "clicks")] == 0
    assert got[("paiio", "revenue")] == 150


def test_meta_ads_unmatched_campaign_stops(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "meta_ads/a.csv", META + "2026-01-02,Mystery,5,1,1,0,0\n")
    with pytest.raises(ValueError, match="Mystery"):
        list(MetaAds(META_CFG).fetch(START, END))


TP_CFG = {
    "columns": {"review_id": "Review ID", "date": "Review Created (UTC)", "stars": "Review Stars",
                "brand_column": "Domain URL", "replied": "Business Reply Date (UTC)"},
    "brand_rules": [{"contains": "fla-example", "brand_id": "fla"}, {"contains": "paiio-example", "brand_id": "paiio"}],
}
HEAD = "Review ID,Review Created (UTC),Review Stars,Domain URL,Business Reply Date (UTC)\n"


def test_trustpilot_counts_stars_and_replies_and_dedupes(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "trustpilot/a.csv", HEAD +
        "r1,2026-01-02 10:00:00,5,www.fla-example.com,2026-01-03 09:00:00\n"
        "r2,2026-01-02 11:00:00,1,www.fla-example.com,\n"
        "r3,2026-01-02 12:00:00,5,www.paiio-example.com,\n")
    put(tmp_path, monkeypatch, "trustpilot/b.csv", HEAD +
        "r1,2026-01-02 10:00:00,5,www.fla-example.com,2026-01-03 09:00:00\n"
        "r4,2026-01-03 08:00:00,4,www.fla-example.com,\n")
    rows = list(Trustpilot(TP_CFG).fetch(START, END))
    new = {(r.brand_id, r.day, r.dimensions["stars"]): r.value for r in rows if r.metric == "reviews_new"}
    replied = {(r.brand_id, r.day): r.value for r in rows if r.metric == "reviews_replied"}
    assert new[("fla", date(2026, 1, 2), "5")] == 1
    assert new[("fla", date(2026, 1, 2), "1")] == 1
    assert new[("fla", date(2026, 1, 3), "4")] == 1
    assert new[("paiio", date(2026, 1, 2), "5")] == 1
    assert sum(new.values()) == 4
    assert replied[("fla", date(2026, 1, 2))] == 1
    assert replied[("paiio", date(2026, 1, 2))] == 0


def test_trustpilot_unmatched_domain_stops(tmp_path, monkeypatch):
    put(tmp_path, monkeypatch, "trustpilot/a.csv", HEAD + "r9,2026-01-02 10:00:00,5,www.other.com,\n")
    with pytest.raises(ValueError, match="other.com"):
        list(Trustpilot(TP_CFG).fetch(START, END))
