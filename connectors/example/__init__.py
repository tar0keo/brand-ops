import random
from datetime import timedelta
from connectors.base import BaseConnector, MetricRow, load_brands


class Connector(BaseConnector):
    """Fake ad data so the pipeline runs end to end before real credentials exist."""

    name = "example"

    def fetch(self, start, end):
        day = start
        while day <= end:
            for b in load_brands():
                rng = random.Random(f"{b['id']}-{day}")
                spend = round(rng.uniform(200, 2000), 2)
                revenue = round(spend * rng.uniform(1.5, 4.0), 2)
                dims = {"channel": "search"}
                yield MetricRow(b["id"], day, "example_ads", "ad_spend", spend, dims)
                yield MetricRow(b["id"], day, "example_ads", "revenue", revenue, dims)
            day += timedelta(days=1)
