import json
import os
from collections import defaultdict
from datetime import datetime

import yaml

from connectors.base import CONFIG, BaseConnector, MetricRow, load_brands

# GA4 API metric name -> warehouse metric name
METRICS = {
    "sessions": "sessions",
    "keyEvents": "key_events",
    "transactions": "transactions",
    "totalRevenue": "revenue",
}
DIMENSIONS = ["date", "sessionDefaultChannelGroup", "sessionSource"]


def load_config():
    with open(CONFIG / "ga4.yaml") as f:
        return yaml.safe_load(f)


def classify(channel_group, source, ai_referrers):
    """Return (channel, engine). AI referrals get their own channel."""
    s = (source or "").lower()
    for domain, engine in ai_referrers.items():
        if s == domain or s.endswith("." + domain):
            return "ai_referral", engine
    return (channel_group or "unassigned").lower().replace(" ", "_"), None


class Connector(BaseConnector):
    name = "ga4"

    def __init__(self, config=None):
        self.config = config if config is not None else load_config()

    def _client(self):
        from google.analytics.data_v1beta import BetaAnalyticsDataClient

        raw = os.environ.get("GA4_SERVICE_ACCOUNT_JSON")
        if raw:
            return BetaAnalyticsDataClient.from_service_account_info(json.loads(raw))
        return BetaAnalyticsDataClient()  # uses GOOGLE_APPLICATION_CREDENTIALS

    def report_rows(self, property_id, start, end):
        """Return [(dimension_values, metric_values)] for one property, paginated."""
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, RunReportRequest,
        )

        client = self._client()
        out, offset = [], 0
        while True:
            resp = client.run_report(
                RunReportRequest(
                    property=f"properties/{property_id}",
                    dimensions=[Dimension(name=d) for d in DIMENSIONS],
                    metrics=[Metric(name=m) for m in METRICS],
                    date_ranges=[DateRange(start_date=start.isoformat(), end_date=end.isoformat())],
                    limit=100000,
                    offset=offset,
                )
            )
            out += [
                ([d.value for d in r.dimension_values], [m.value for m in r.metric_values])
                for r in resp.rows
            ]
            offset += len(resp.rows)
            if not resp.rows or offset >= resp.row_count:
                return out

    def fetch(self, start, end):
        props = {b: p for b, p in self.config["properties"].items() if p}
        if not props:
            raise RuntimeError("No GA4 properties configured in config/ga4.yaml")
        known = {b["id"] for b in load_brands()}
        unknown = set(props) - known
        if unknown:
            raise ValueError(f"Unknown brand ids in ga4.yaml: {sorted(unknown)}")

        for brand_id, property_id in props.items():
            totals = defaultdict(float)
            for dims, vals in self.report_rows(property_id, start, end):
                day = datetime.strptime(dims[0], "%Y%m%d").date()
                channel, engine = classify(dims[1], dims[2], self.config["ai_referrers"])
                for metric, value in zip(METRICS.values(), vals):
                    totals[(day, metric, channel, engine)] += float(value)
            for (day, metric, channel, engine), value in totals.items():
                dimensions = {"channel": channel}
                if engine:
                    dimensions["engine"] = engine
                yield MetricRow(brand_id, day, "ga4", metric, round(value, 2), dimensions)
