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


def build_summary(rows, brands, end, days, categories=None):
    start = end - timedelta(days=days - 1)
    prev_end = start - timedelta(days=1)
    prev_start = prev_end - timedelta(days=days - 1)
    cur, prev = totals(rows, start, end), totals(rows, prev_start, prev_end)

    def cat_of(b):
        return b.get("category") or "uncategorized"

    def merged(t, ids):
        m = defaultdict(float)
        for bid, acc in t.items():
            if bid in ids:
                for k, v in acc.items():
                    m[k] += v
        return m

    def entry(mc, mp):
        return {"current": derive(mc), "previous": derive(mp), "engines": engine_shares(mc)}

    cats = list(categories or [])
    known = {c["id"] for c in cats}
    for b in brands:
        if cat_of(b) not in known:
            known.add(cat_of(b))
            cats.append({"id": cat_of(b), "label": "Uncategorized" if cat_of(b) == "uncategorized" else cat_of(b)})
    groups = []
    for c in cats:
        ids = {b["id"] for b in brands if cat_of(b) == c["id"]}
        if ids:
            groups.append({"id": c["id"], "label": c["label"], "brand_count": len(ids), **entry(merged(cur, ids), merged(prev, ids))})
    all_ids = {b["id"] for b in brands}  # archived brands are excluded from totals
    return {
        "end": end.isoformat(),
        "days": days,
        "portfolio": entry(merged(cur, all_ids), merged(prev, all_ids)),
        "categories": groups,
        "brands": [
            {"id": b["id"], "name": b["name"], "category": cat_of(b),
             "current": derive(cur[b["id"]]), "previous": derive(prev[b["id"]]), "engines": engine_shares(cur[b["id"]])}
            for b in brands
        ],
    }
