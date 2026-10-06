import random
import re
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


# ---------- sample press coverage for the demo ----------
LINK_SOURCES = {"Finance Daily": "financedaily.example.com", "Lending Weekly": "lendingweekly.example.com",
                "Consumer Money Review": "consumermoneyreview.example.com", "Market Ledger": "marketledger.example.com",
                "Tech and Lending": "techandlending.example.com"}
LINK_STORIES = [  # (brand id, days ago, source, headline, summary); {b} is the brand's name
    ("brand_14", 4, "Consumer Money Review", "Borrowers say refunds at {b} are taking over a month",
     "Several customers told reporters that refunds from {b} took more than a month to arrive. {b} says it is hiring support staff to clear the backlog. Consumer groups have asked it to publish clearer refund terms."),
    ("brand_14", 19, "Finance Daily", "{b} slips to 3.4 stars as complaints about fees grow",
     "Reviews of {b} have turned sharply negative this quarter, mostly over unexpected fees. The company says it is reviewing how it discloses fees. Competitors have been quick to promote their own lower rates."),
    ("brand_21", 6, "Lending Weekly", "{b} left out of the latest online lender rankings",
     "A widely read ranking of online lenders no longer lists {b}, which featured last year. The authors say they weighted customer service scores more heavily. Analysts expect the change to cost {b} referral traffic."),
    ("brand_21", 28, "Market Ledger", "Why AI assistants name some lenders and not others, including {b}",
     "Assistants appear to favour lenders with clear, well-cited pages and recent coverage. {b} is among the names appearing less often than a year ago. Lenders are being urged to keep their facts current."),
    ("brand_3", 9, "Finance Daily", "{b} cuts its marketing budget as returns slow",
     "{b} has reduced advertising spending by about a quarter after returns on paid campaigns fell. A spokesperson said the company is focusing on customers it already has. Analysts say the move may protect margins but slow growth."),
    ("brand_8", 12, "Tech and Lending", "{b} redesigns its website, and some pages vanish from search",
     "{b} launched a redesigned website last month, and several of its old pages no longer appear in search results. The company says a fix is under way. Search specialists point to blocked crawlers as a likely cause."),
    ("brand_17", 3, "Lending Weekly", "{b} opens a new customer centre and plans to hire 200",
     "{b} opened a customer centre this week and plans to hire 200 people over the next year. The company reported its strongest quarter for new loans. Its chief executive said service speed is the priority."),
    ("brand_5", 15, "Consumer Money Review", "{b} named a top pick for first-time borrowers",
     "Reviewers praised {b} for plain-language terms and fast decisions. The company scored above average for customer satisfaction. Its rates were competitive but not the lowest."),
    ("brand_27", 22, "Market Ledger", "{b} raises rates for some borrowers",
     "{b} has increased rates for borrowers with lower credit scores, effective next month. The company says rising funding costs are the reason. Customers can refinance or pay early without a penalty."),
    ("brand_11", 7, "Finance Daily", "{b} partners with a credit union to widen access",
     "{b} announced a partnership with a regional credit union to offer loans in new areas. The deal is expected to add about 40,000 eligible borrowers. Both groups said terms would stay unchanged for current customers."),
]
GENERAL_STORIES = [  # coverage that names none of the brands, so it stays unassigned
    (2, "Market Ledger", "Regulators propose new disclosure rules for online lenders",
     "Regulators have proposed rules that would require online lenders to show total borrowing costs up front. Industry groups say the change will be costly but manageable. A public comment period opens next month."),
    (11, "Lending Weekly", "How AI search is changing the way people compare loans",
     "More borrowers now ask AI assistants which lender to choose before visiting any website. Lenders with clear, well-sourced pages are named more often. Marketers are adjusting their content to keep up."),
    (24, "Finance Daily", "Interest rate outlook: what borrowers should expect this winter",
     "Analysts expect borrowing costs to hold steady through the winter. Lenders say demand for refinancing has picked up. Borrowers are advised to compare offers before committing."),
]


def _link(source, title, text, when):
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower()).strip("-")[:60]
    return {"url": f"https://{LINK_SOURCES[source]}/{slug}", "title": title, "source": source, "published": when.isoformat(),
            "excerpt": text[:160], "summary": text, "body": text, "status": "ok"}


def demo_links(today, brands):
    """Sample articles about the demo brands: some tell the same story as their scorecard, some mention no brand, one cannot be read."""
    names = {b["id"]: b["name"] for b in brands}
    out = [_link(src, head.format(b=names[bid]), text.format(b=names[bid]), today - timedelta(days=ago))
           for bid, ago, src, head, text in LINK_STORIES if bid in names]
    out += [_link(src, head, text, today - timedelta(days=ago)) for ago, src, head, text in GENERAL_STORIES]
    if "brand_8" in names:
        out.append({"url": "https://brand8.example.com/blog/new-site", "title": "New Site", "source": "brand8.example.com",
                    "published": None, "excerpt": "", "summary": "", "body": "", "status": "unreadable"})
    return out
