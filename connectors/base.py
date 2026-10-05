import os
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path
from typing import Iterable
import yaml

_HOME = os.environ.get("BRANDOPS_HOME")  # set by the desktop app: all user data lives in one folder
CONFIG = Path(_HOME) / "config" if _HOME else Path(__file__).resolve().parent.parent / "config"
BRANDS_PATH = CONFIG / "brands.yaml"


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
    with open(BRANDS_PATH) as f:
        return yaml.safe_load(f)["brands"]
