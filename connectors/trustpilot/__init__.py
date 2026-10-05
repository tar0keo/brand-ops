import re
from collections import defaultdict

from connectors.base import BaseConnector, MetricRow, load_brands
from connectors.files import files, inbox, load_yaml, match_brand, parse_date, read_table, to_float


class Connector(BaseConnector):
    """Reads Trustpilot review exports from data_inbox/trustpilot/.

    Emits reviews_new (dimension: stars) and reviews_replied per brand and review day.
    Average rating = sum(stars * count) / sum(count) over any window.
    Reviews are de-duplicated by review ID across files, so overlapping exports are safe.
    """

    name = "trustpilot"

    def __init__(self, config=None):
        self.config = config if config is not None else load_yaml("trustpilot.yaml")

    def fetch(self, start, end):
        cols = self.config["columns"]
        rules = list(self.config.get("brand_rules") or [])
        rules += [{"contains": d, "brand_id": b["id"]} for b in load_brands() for d in b.get("sites") or []]
        bad = {r["brand_id"] for r in rules} - {b["id"] for b in load_brands()}
        if bad:
            raise ValueError(f"Unknown brand ids in brand_rules: {sorted(bad)}")
        paths = files(inbox("trustpilot"), "*.csv")
        if not paths:
            raise RuntimeError("No CSV files found in data_inbox/trustpilot/")

        required = [cols["review_id"], cols["date"], cols["stars"], cols["brand_column"]]
        reviews, unmatched = {}, set()
        for path in paths:
            for row in read_table(path, required):
                review_id = row[cols["review_id"]].strip()
                if not review_id:
                    continue
                text = row[cols["date"]].strip()
                m = re.match(r"\d{4}-\d{2}-\d{2}", text)
                day = parse_date(m.group(0) if m else text)
                if not start <= day <= end:
                    continue
                where = row[cols["brand_column"]].strip()
                brand = match_brand(where, rules)
                if brand is None:
                    unmatched.add(where or "(blank)")
                    continue
                stars = str(int(to_float(row[cols["stars"]])))
                replied = bool(row.get(cols.get("replied") or "", "").strip())
                reviews[review_id] = (brand, day, stars, replied)  # later files win
        if unmatched:
            raise ValueError(f"Reviews with no brand rule in config/trustpilot.yaml: {sorted(unmatched)[:10]}")

        counts, replies = defaultdict(float), defaultdict(float)
        for brand, day, stars, replied in reviews.values():
            counts[(brand, day, stars)] += 1
            replies[(brand, day)] += int(replied)
        for (brand, day, stars), value in counts.items():
            yield MetricRow(brand, day, self.name, "reviews_new", value, {"stars": stars})
        for (brand, day), value in replies.items():
            yield MetricRow(brand, day, self.name, "reviews_replied", value)
