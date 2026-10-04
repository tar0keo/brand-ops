from collections import defaultdict
from datetime import timedelta

AD_SOURCES = {"google_ads", "meta_ads", "example_ads"}


def totals(rows, start, end):
    """Sum raw warehouse rows into per-brand accumulators for one window."""
    out = defaultdict(lambda: defaultdict(float))
    for r in rows:
        if not start <= r["day"] <= end:
            continue
        a, m, v = out[r["brand_id"]], r["metric"], r["value"]
        d, s = r.get("dimensions") or {}, r["source"]
        if m == "ad_spend" and s in AD_SOURCES:
            a["spend"] += v
        elif m == "revenue" and s in AD_SOURCES:
            a["revenue"] += v
        elif m == "sessions" and s == "ga4":
            a["sessions"] += v
            if d.get("channel") == "ai_referral":
                a["ai_sessions"] += v
        elif m == "transactions" and s == "ga4":
            a["transactions"] += v
        elif m == "geo_prompt_runs":
            a["geo_runs"] += v
            a["runs:" + str(d.get("engine"))] += v
        elif m == "geo_mentions":
            a["geo_mentions"] += v
            a["men:" + str(d.get("engine"))] += v
        elif m == "reviews_new":
            stars = int(d["stars"])
            a["reviews"] += v
            a["stars_sum"] += stars * v
            if stars <= 2:
                a["negative"] += v
        elif m == "reviews_replied":
            a["replied"] += v
        elif m == "ai_crawler_hits":
            a["bot_hits"] += v
        elif m == "ai_crawler_errors":
            a["bot_errors"] += v
    return out


def _ratio(n, d):
    return round(n / d, 4) if d else None


def derive(a):
    has_ads = bool(a["spend"] or a["revenue"])
    return {
        "spend": round(a["spend"], 2),
        "revenue": round(a["revenue"], 2),
        "profit": round(a["revenue"] - a["spend"], 2) if has_ads else None,  # provisional definition
        "roas": _ratio(a["revenue"], a["spend"]),
        "sessions": a["sessions"],
        "ai_sessions": a["ai_sessions"],
        "conversion_rate": _ratio(a["transactions"], a["sessions"]),
        "citation_share": _ratio(a["geo_mentions"], a["geo_runs"]),
        "bot_hits": a["bot_hits"],
        "bot_errors": a["bot_errors"],
        "rating": round(a["stars_sum"] / a["reviews"], 2) if a["reviews"] else None,
        "reviews": a["reviews"],
        "negative_share": _ratio(a["negative"], a["reviews"]),
        "reply_rate": _ratio(a["replied"], a["reviews"]),
    }


def engine_shares(a):
    return {k[5:]: _ratio(a["men:" + k[5:]], v) for k, v in a.items() if k.startswith("runs:")}


def build_summary(rows, brands, end, days):
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    cur, prev = totals(rows, start, end), totals(rows, prev_start, prev_end)

    def merged(t):
        m = defaultdict(float)
        for acc in t.values():
            for k, v in acc.items():
                m[k] += v
        return m

    return {
        "end": end.isoformat(),
        "days": days,
        "portfolio": {"current": derive(merged(cur)), "previous": derive(merged(prev))},
        "brands": [
            {
                "id": b["id"], "name": b["name"], "kind": b["kind"],
                "current": derive(cur[b["id"]]),
                "previous": derive(prev[b["id"]]),
                "engines": engine_shares(cur[b["id"]]),
            }
            for b in brands
        ],
    }
