from collections import defaultdict

import yaml

from connectors.base import CONFIG, BaseConnector, MetricRow, load_brands
from connectors.files import files, inbox, load_file_sources, parse_date, read_table


def load_prompts():
    with open(CONFIG / "prompts.yaml") as f:
        return yaml.safe_load(f)["prompts"]


class Connector(BaseConnector):
    """Reads GEO tracker CSV exports from data_inbox/geo_tracker/.

    Emits geo_prompt_runs and geo_mentions per brand, day, and engine.
    Citation share = geo_mentions / geo_prompt_runs.
    """

    name = "geo_tracker"

    def __init__(self, config=None, prompts=None):
        self.config = config if config is not None else load_file_sources()["geo_tracker"]
        self.prompts = prompts if prompts is not None else load_prompts()

    def fetch(self, start, end):
        cols = self.config["columns"]
        yes = {str(v).lower() for v in self.config["mentioned_values"]}
        by_name = {}
        for b in load_brands():
            by_name[b["id"].lower()] = b["id"]
            by_name[b["name"].lower()] = b["id"]
        by_prompt = {}
        for p in self.prompts:
            by_prompt[p["text"].lower()] = p["brand_id"]
            by_prompt[p["id"].lower()] = p["brand_id"]
        paths = files(inbox("geo_tracker"), "*.csv")
        if not paths:
            raise RuntimeError("No CSV files found in data_inbox/geo_tracker/")

        merged, unmatched = {}, set()
        for path in paths:
            current = defaultdict(float)
            for row in read_table(path, [cols["date"], cols["engine"], cols["mentioned"]]):
                day = parse_date(row[cols["date"]])
                if not start <= day <= end:
                    continue
                brand_val = row.get(cols.get("brand") or "", "").strip()
                prompt_val = row.get(cols.get("prompt") or "", "").strip()
                brand = by_name.get(brand_val.lower()) if brand_val else by_prompt.get(prompt_val.lower())
                if brand is None:
                    unmatched.add(brand_val or prompt_val or "(blank)")
                    continue
                engine = row[cols["engine"]].strip().lower().replace(" ", "_")
                mentioned = row[cols["mentioned"]].strip().lower() in yes
                current[(brand, day, "geo_prompt_runs", engine)] += 1
                current[(brand, day, "geo_mentions", engine)] += int(mentioned)
            merged.update(current)  # on overlapping files, the later file name wins
        if unmatched:
            raise ValueError(
                f"No brand match (check brand names or config/prompts.yaml): {sorted(unmatched)[:10]}"
            )
        for (brand, day, metric, engine), value in merged.items():
            yield MetricRow(brand, day, "geo_tracker", metric, float(value), {"engine": engine})
