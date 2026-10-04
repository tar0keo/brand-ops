from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable
import yaml

CONFIG = Path(__file__).resolve().parent.parent / "config"


@dataclass
class MetricRow:
    brand_id: str
    day: date
    source: str
    metric: str
    value: float
    dimensions: dict = field(default_factory=dict)


class BaseConnector:
    """Every connector yields MetricRow objects and nothing else."""

    name = "base"

    def fetch(self, start: date, end: date) -> Iterable[MetricRow]:
        raise NotImplementedError


def load_brands() -> list[dict]:
    with open(CONFIG / "brands.yaml") as f:
        return yaml.safe_load(f)["brands"]
