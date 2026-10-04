import random
from datetime import timedelta

# spend/day, ROAS, conversion rate, sessions/day, citation share, rating, drift, has_geo, has_reviews
PROFILES = {
    "fla": (1000, 3.1, 0.034, 3000, 0.22, 4.4, 0.05, True, True),
    "paiio": (700, 2.7, 0.029, 2200, 0.14, 4.1, 0.12, True, True),
    "brand_1": (600, 2.5, 0.027, 1800, 0.13, 4.0, -0.35, True, True),  # declining on every measure
    "brand_2": (450, 2.5, 0.026, 1500, 0.11, 4.0, 0.0, True, True),    # AI crawlers blocked recently
    "remarketing": (250, 5.8, 0.048, 900, 0, 0, 0.05, False, False),
    "whitelabel_a": (150, 2.0, 0.020, 700, 0.06, 3.8, -0.10, True, True),
    "whitelabel_b": (120, 1.9, 0.018, 600, 0.05, 3.7, -0.05, True, True),
}
ENGINES = ("chatgpt", "gemini", "perplexity")


def demo_rows(end, days=120):
    """Deterministic fake warehouse rows with a few built-in stories."""
    rows = []

    def add(b, d, src, metric, v, dims=None):
        rows.append({"brand_id": b, "day": d, "source": src, "metric": metric,
                     "value": float(v), "dimensions": dims or {}})

    for b, (spend, roas, conv, sess, share, rating, drift, geo, rev) in PROFILES.items():
        for i in range(days):
            d = end - timedelta(days=days - 1 - i)
            rng = random.Random(f"{b}-{d}")
            k = 1 + drift * i / days
            s = spend * rng.uniform(0.85, 1.15)
            add(b, d, "google_ads", "ad_spend", s, {"campaign": "demo"})
            add(b, d, "google_ads", "revenue", s * roas * k * rng.uniform(0.85, 1.15), {"campaign": "demo"})
            n, ai = sess * rng.uniform(0.85, 1.15), sess * 0.03 * k
            add(b, d, "ga4", "sessions", n, {"channel": "organic_search"})
            add(b, d, "ga4", "sessions", ai, {"channel": "ai_referral", "engine": "chatgpt"})
            add(b, d, "ga4", "transactions", (n + ai) * conv * k * rng.uniform(0.9, 1.1), {"channel": "all"})
            hits = rng.randint(80, 200)
            blocked = b == "brand_2" and i >= days - 14
            add(b, d, "bot_logs", "ai_crawler_hits", hits, {"bot": "gptbot"})
            add(b, d, "bot_logs", "ai_crawler_errors", hits * 0.5 if blocked else rng.randint(0, 3),
                {"bot": "gptbot", "status": "403"})
            if geo:
                for e in ENGINES:
                    add(b, d, "geo_tracker", "geo_prompt_runs", 10, {"engine": e})
                    add(b, d, "geo_tracker", "geo_mentions", sum(rng.random() < share * k for _ in range(10)), {"engine": e})
            if rev:
                stars = {}
                n_rev = rng.randint(2, 6)
                replied = 0
                for _ in range(n_rev):
                    st = str(int(min(5, max(1, round(rng.gauss(rating + 0.5 + drift * 1.5, 0.9))))))
                    stars[st] = stars.get(st, 0) + 1
                    replied += rng.random() < 0.7
                for st, c in stars.items():
                    add(b, d, "trustpilot", "reviews_new", c, {"stars": st})
                add(b, d, "trustpilot", "reviews_replied", replied)
    return rows
