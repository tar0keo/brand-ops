import gzip
import re
from collections import defaultdict
from datetime import datetime

from connectors.base import BaseConnector, MetricRow, load_brands
from connectors.files import inbox, load_file_sources

LINE = re.compile(r'\[(?P<ts>[^\]]+)\] "[^"]*" (?P<status>\d{3}) \S+ "[^"]*" "(?P<ua>[^"]*)"')


def open_text(path):
    if path.suffix == ".gz":
        return gzip.open(path, "rt", errors="replace")
    return open(path, errors="replace")


class Connector(BaseConnector):
    """Counts AI crawler requests in access logs (Apache/Nginx combined format).

    Put logs in data_inbox/bot_logs/<brand_id>/. All files are summed, so do not drop duplicate copies.
    """

    name = "bot_logs"

    def __init__(self, config=None):
        self.config = config if config is not None else load_file_sources()["bot_logs"]

    def fetch(self, start, end):
        root = inbox("bot_logs")
        if not root.is_dir():
            raise RuntimeError("No log folders found in data_inbox/bot_logs/<brand_id>/")
        known = {b["id"] for b in load_brands()}
        bots = {k.lower(): v for k, v in self.config["bots"].items()}
        totals = defaultdict(float)
        for brand_dir in sorted(p for p in root.iterdir() if p.is_dir()):
            brand = brand_dir.name
            if brand not in known:
                raise ValueError(f"Folder {brand!r} in bot_logs is not a brand id in config/brands.yaml")
            for path in sorted(p for p in brand_dir.iterdir() if p.is_file() and ".log" in p.name):
                with open_text(path) as f:
                    for line in f:
                        m = LINE.search(line)
                        if not m:
                            continue
                        ua = m["ua"].lower()
                        bot = next((label for key, label in bots.items() if key in ua), None)
                        if bot is None:
                            continue
                        day = datetime.strptime(m["ts"].split(":")[0], "%d/%b/%Y").date()
                        if not start <= day <= end:
                            continue
                        totals[(brand, day, "ai_crawler_hits", (("bot", bot),))] += 1
                        if int(m["status"]) >= 400:
                            totals[(brand, day, "ai_crawler_errors", (("bot", bot), ("status", m["status"])))] += 1
        for (brand, day, metric, dims), value in totals.items():
            yield MetricRow(brand, day, "bot_logs", metric, value, dict(dims))
