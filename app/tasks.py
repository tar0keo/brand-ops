PRIORITY = {"High": 0, "Medium": 1, "Low": 2}
MEDIA, PRODUCT, GEO, REP = "Media Buying", "Product", "PR / GEO / SEO", "Brand Reputation Protection"


def _drop(cur, prev):
    """Relative fall from prev to cur (0.2 = fell 20%). None if not comparable."""
    if cur is None or not prev:
        return None
    return (prev - cur) / prev


def generate_tasks(summary, rules):
    """Turn per-brand summary metrics into proposed tasks. Pure and deterministic."""
    th = rules["thresholds"]
    tasks = []
    for b in summary["brands"]:
        c, p, n = b["current"], b["previous"], b["name"]

        def add(rule, function, priority, title, why, actions):
            tasks.append({"key": f"{rule}:{b['id']}", "rule": rule, "brand_id": b["id"], "brand": n, "category": b.get("category"),
                          "function": function, "priority": priority, "title": title,
                          "why": why, "actions": actions})

        if c["roas"] is not None and c["spend"] >= th["min_spend"]:
            d = _drop(c["roas"], p["roas"])
            if c["roas"] < th["roas_min"]:
                trend = f" It was {p['roas']:.2f} in the previous period." if p["roas"] else ""
                add("roas_low", MEDIA, "High" if c["roas"] < th["roas_min"] * 0.75 else "Medium",
                    f"Fix low ad efficiency for {n} (ROAS {c['roas']:.2f})",
                    f"ROAS is {c['roas']:.2f} against a floor of {th['roas_min']:.2f}, on ${c['spend']:,.0f} of spend.{trend}",
                    ["Rank campaigns by ROAS and pause or cut the weakest",
                     "Check whether the landing page conversion rate changed",
                     "Confirm conversion tracking still fires"])
            elif d is not None and d >= th["roas_drop_pct"]:
                add("roas_drop", MEDIA, "Medium", f"Investigate falling ROAS for {n} ({d:.0%} drop)",
                    f"ROAS fell from {p['roas']:.2f} to {c['roas']:.2f}.",
                    ["Compare campaign-level ROAS against the previous period",
                     "Check for audience, creative, or budget changes",
                     "Check conversion tracking"])

        d = _drop(c["conversion_rate"], p["conversion_rate"])
        if d is not None and d >= th["conversion_drop_pct"]:
            add("conversion_drop", PRODUCT, "High" if d >= 2 * th["conversion_drop_pct"] else "Medium",
                f"Find why conversion fell for {n} ({d:.0%} drop)",
                f"Conversion rate fell from {p['conversion_rate']:.1%} to {c['conversion_rate']:.1%}.",
                ["Check releases and site changes since the drop began",
                 "Review each funnel step for new drop-off",
                 "Verify tracking and the checkout flow work end to end"])

        if c["citation_share"] is not None and p["citation_share"] is not None:
            pts = p["citation_share"] - c["citation_share"]
            if pts >= th["citation_drop_pts"]:
                add("citation_drop", GEO, "Medium", f"Recover AI citations for {n} (down {pts * 100:.1f} pts)",
                    f"Share of tracked prompts citing the brand fell from {p['citation_share']:.1%} to {c['citation_share']:.1%}.",
                    ["Find the prompts where the brand stopped appearing and who replaced it",
                     "Check which sources the AI answers now cite",
                     "Confirm AI crawlers can reach key pages"])

        if c["bot_hits"] and c["bot_errors"] >= th["crawler_min_errors"] \
                and c["bot_errors"] / c["bot_hits"] >= th["crawler_error_rate"]:
            rate = c["bot_errors"] / c["bot_hits"]
            add("crawler_errors", PRODUCT, "High", f"Unblock AI crawlers for {n} ({rate:.0%} of requests fail)",
                f"{c['bot_errors']:.0f} of {c['bot_hits']:.0f} AI crawler requests returned errors.",
                ["Check robots.txt, WAF, and CDN rules for AI bot user agents",
                 "Look at the error status codes in the access logs",
                 "Re-test with the affected crawlers after the fix"])

        if c["rating"] is not None and c["reviews"] >= th["min_reviews"]:
            fell = p["rating"] is not None and p["rating"] - c["rating"] >= th["rating_drop"]
            if c["rating"] < th["rating_min"] or fell:
                add("rating", REP, "High" if c["rating"] < th["rating_min"] - 0.3 else "Medium",
                    f"Improve review rating for {n} ({c['rating']:.2f})",
                    f"Average rating is {c['rating']:.2f} from {c['reviews']:.0f} reviews"
                    + (f", down from {p['rating']:.2f}." if fell else "."),
                    ["Read the 1 and 2 star reviews and group them by cause",
                     "Reply to unanswered negative reviews",
                     "Pass recurring causes to Product or the brand owner"])
            if c["negative_share"] is not None and c["negative_share"] >= th["negative_share_max"]:
                add("negative_reviews", REP, "Medium", f"Reduce negative reviews for {n} ({c['negative_share']:.0%} are 1 to 2 stars)",
                    f"{c['negative_share']:.0%} of {c['reviews']:.0f} new reviews were 1 or 2 stars.",
                    ["Identify the top complaint themes", "Review the review-invitation flow for timing problems"])
            if c["reply_rate"] is not None and c["reply_rate"] < th["reply_rate_min"]:
                add("reply_rate", REP, "Low", f"Reply to more reviews for {n} ({c['reply_rate']:.0%} answered)",
                    f"Only {c['reply_rate']:.0%} of new reviews have a business reply.",
                    ["Reply to unanswered reviews, starting with the lowest ratings", "Agree a reply target and owner"])

    return sorted(tasks, key=lambda t: (PRIORITY[t["priority"]], t["brand"], t["rule"]))
