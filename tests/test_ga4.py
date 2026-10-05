from datetime import date

import pytest

from connectors.ga4 import Connector, classify

AI = {"chatgpt.com": "chatgpt", "chat.openai.com": "chatgpt", "perplexity": "perplexity"}
CFG = {"properties": {"fla": "111", "paiio": None}, "ai_referrers": AI}

ROWS = [
    (["20260102", "Referral", "chatgpt.com"], ["10", "2", "1", "50.5"]),
    (["20260102", "Referral", "chat.openai.com"], ["5", "1", "0", "0"]),
    (["20260102", "Organic Search", "google"], ["100", "10", "4", "200"]),
]


def make(rows, config=CFG):
    c = Connector(config=config)
    c.report_rows = lambda prop, start, end: rows
    return c


def run(c):
    return list(c.fetch(date(2026, 1, 1), date(2026, 1, 3)))


def test_classify():
    assert classify("Referral", "chatgpt.com", AI) == ("ai_referral", "chatgpt")
    assert classify("Referral", "www.chatgpt.com", AI) == ("ai_referral", "chatgpt")
    assert classify("Referral", "notchatgpt.com", AI) == ("referral", None)
    assert classify("Organic Search", "google", AI) == ("organic_search", None)


def test_ai_sources_are_merged_per_engine():
    rows = run(make(ROWS))
    ai = {r.metric: r for r in rows if r.dimensions.get("channel") == "ai_referral"}
    assert ai["sessions"].value == 15
    assert ai["revenue"].value == 50.5
    assert ai["sessions"].dimensions == {"channel": "ai_referral", "engine": "chatgpt"}
    assert all(r.brand_id == "fla" and r.source == "ga4" for r in rows)
    assert len(rows) == 8


def test_unconfigured_brands_are_skipped():
    assert {r.brand_id for r in run(make(ROWS))} == {"fla"}


def test_no_properties_raises():
    with pytest.raises(RuntimeError):
        run(make(ROWS, {"properties": {"fla": None}, "ai_referrers": AI}))


def test_unknown_brand_raises():
    with pytest.raises(ValueError):
        run(make(ROWS, {"properties": {"nope": "1"}, "ai_referrers": AI}))
