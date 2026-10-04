from collections import defaultdict

from connectors.base import BaseConnector, MetricRow, load_brands
from connectors.files import files, inbox, load_file_sources, match_brand, parse_date, read_table, to_float

# export column key -> warehouse metric
METRICS = {
    "cost": "ad_spend",
    "clicks": "clicks",
    "impressions": "impressions",
    "conversions": "conversions",
    "conv_value": "revenue",
}


class Connector(BaseConnector):
    """Reads Google Ads CSV reports from data_inbox/google_ads/."""

    name = "google_ads"

    def __init__(self, config=None):
        self.config = config if config is not None else load_file_sources()["google_ads"]

    def fetch(self, start, end):
        cols = self.config["columns"]
        rules = self.config.get("campaign_rules") or []
        bad = {r["brand_id"] for r in rules} - {b["id"] for b in load_brands()}
        if bad:
            raise ValueError(f"Unknown brand ids in campaign_rules: {sorted(bad)}")
        paths = files(inbox("google_ads"), "*.csv")
        if not paths:
            raise RuntimeError("No CSV files found in data_inbox/google_ads/")

        merged, unmatched = {}, set()
        for path in paths:
            current = defaultdict(float)
            for row in read_table(path, [cols["day"], cols["campaign"], cols["cost"]]):
                day_text = row.get(cols["day"], "").strip()
                if not day_text or day_text.lower().startswith("total"):
                    continue
                day = parse_date(day_text)
                if not start <= day <= end:
                    continue
                campaign = row[cols["campaign"]].strip()
                brand = match_brand(campaign, rules)
                if brand is None:
                    unmatched.add(campaign)
                    continue
                for key, metric in METRICS.items():
                    col = cols.get(key)
                    if col and col in row:
                        current[(brand, day, metric, campaign)] += to_float(row[col])
            merged.update(current)  # on overlapping files, the later file name wins
        if unmatched:
            raise ValueError(f"Campaigns with no brand rule in config/file_sources.yaml: {sorted(unmatched)[:10]}")
        for (brand, day, metric, campaign), value in merged.items():
            yield MetricRow(brand, day, "google_ads", metric, round(value, 2), {"campaign": campaign})
