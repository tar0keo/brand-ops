import random
from datetime import timedelta
from functools import lru_cache

from app import registry

ENGINES = ("chatgpt", "gemini", "perplexity")
STORIES = {  # brand id -> overrides to the random profile
    "brand_3": {"drift": -0.35, "roas": 2.6},   # declining on ads and conversion
    "brand_8": {"blocked": True},               # AI crawlers blocked recently
    "brand_14": {"rating": 3.3},                # poor reviews
    "brand_21": {"share_drop": True, "share": 0.2},  # losing AI citations
    "brand_27": {"drift": -0.30, "roas": 1.7},  # weak ad returns
}


def sample_brands(n=30):
    """Brand 1..n, spread over the configured categories in even blocks."""
    ids = [c["id"] for c in registry.categories()]
    return [{"id": f"brand_{i}", "name": f"Brand {i}", "category": ids[(i - 1) * len(ids) // n],
             "active": True, "sites": [f"brand{i}.example.com"]} for i in range(1, n + 1)]


def profile(brand_id):
    rng = random.Random("profile-" + brand_id)
    p = {"spend": rng.uniform(150, 1200), "roas": rng.uniform(2.4, 3.6), "conv": rng.uniform(0.02, 0.042),
         "sess": rng.uniform(600, 3200), "share": rng.uniform(0.05, 0.24), "rating": rng.uniform(3.9, 4.5),
         "drift": rng.uniform(-0.05, 0.12), "blocked": False, "share_drop": False}
    p.update(STORIES.get(brand_id, {}))
    return p


@lru_cache(maxsize=2)
def cached_rows(end, brand_ids):
    return demo_rows(end, brand_ids)


def demo_rows(end, brand_ids=None, days=120):
    """Deterministic fake warehouse rows for any brand ids, with a few built-in stories."""
    ids = brand_ids or [b["id"] for b in sample_brands()]
    rows = []

    def add(b, d, src, metric, v, dims=None):
        rows.append({"brand_id": b, "day": d, "source": src, "metric": metric,
                     "value": float(v), "dimensions": dims or {}})

    for b in ids:
        p = profile(b)
        for i in range(days):
            d = end - timedelta(days=days - 1 - i)
            rng = random.Random(f"{b}-{d}")
            k = 1 + p["drift"] * i / days
            ks = 1 - 0.65 * max(0, (i - (days - 45)) / 45) if p["share_drop"] else k
            s = p["spend"] * rng.uniform(0.85, 1.15)
            add(b, d, "google_ads", "ad_spend", s, {"campaign": "demo"})
            add(b, d, "google_ads", "revenue", s * p["roas"] * k * rng.uniform(0.85, 1.15), {"campaign": "demo"})
            n, ai = p["sess"] * rng.uniform(0.85, 1.15), p["sess"] * 0.03 * k
            add(b, d, "ga4", "sessions", n, {"channel": "organic_search"})
            add(b, d, "ga4", "sessions", ai, {"channel": "ai_referral", "engine": "chatgpt"})
            add(b, d, "ga4", "transactions", (n + ai) * p["conv"] * k * rng.uniform(0.9, 1.1), {"channel": "all"})
            hits = rng.randint(80, 200)
            blocked = p["blocked"] and i >= days - 14
            add(b, d, "bot_logs", "ai_crawler_hits", hits, {"bot": "gptbot"})
            add(b, d, "bot_logs", "ai_crawler_errors", hits * 0.5 if blocked else rng.randint(0, 3),
                {"bot": "gptbot", "status": "403"})
            for e in ENGINES:
                add(b, d, "geo_tracker", "geo_prompt_runs", 10, {"engine": e})
                add(b, d, "geo_tracker", "geo_mentions", sum(rng.random() < p["share"] * ks for _ in range(10)), {"engine": e})
            stars, replied = {}, 0
            for _ in range(rng.randint(2, 6)):
                st = str(int(min(5, max(1, round(rng.gauss(p["rating"] + 0.5 + p["drift"] * 1.5, 0.9))))))
                stars[st] = stars.get(st, 0) + 1
                replied += rng.random() < 0.7
            for st, c in stars.items():
                add(b, d, "trustpilot", "reviews_new", c, {"stars": st})
            add(b, d, "trustpilot", "reviews_replied", replied)
    return rows
