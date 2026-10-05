import csv
import io
from datetime import datetime
from pathlib import Path

import yaml

from connectors.base import CONFIG


def inbox(*parts):
    import os

    home = os.environ.get("BRANDOPS_HOME")
    root = os.environ.get("INBOX_DIR") or (Path(home) / "data_inbox" if home else Path(__file__).resolve().parent.parent / "data_inbox")
    return Path(root).joinpath(*parts)


def files(folder, pattern):
    folder = Path(folder)
    return sorted(folder.glob(pattern)) if folder.is_dir() else []


def load_file_sources():
    with open(CONFIG / "file_sources.yaml") as f:
        return yaml.safe_load(f)


def load_yaml(filename):
    with open(CONFIG / filename) as f:
        return yaml.safe_load(f)


def parse_date(s):
    s = s.strip()
    for fmt in ("%Y-%m-%d", "%Y%m%d", "%m/%d/%Y", "%b %d, %Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            pass
    raise ValueError(f"Unrecognized date: {s!r}")


def to_float(s):
    s = (s or "").replace(",", "").replace("$", "").replace("%", "").strip()
    return 0.0 if s in ("", "-", "--") else float(s)


def match_brand(text, rules):
    t = text.lower()
    for rule in rules:
        if rule["contains"].lower() in t:
            return rule["brand_id"]
    return None


def read_table(path, required):
    """Read a CSV export, skipping any title lines above the real header row."""
    raw = Path(path).read_bytes()
    if raw.startswith((b"\xff\xfe", b"\xfe\xff")):  # Google Ads "Excel .csv"
        text, delim = raw.decode("utf-16"), "\t"
    else:
        text, delim = raw.decode("utf-8-sig"), ","
    rows = list(csv.reader(io.StringIO(text), delimiter=delim))
    for i, header in enumerate(rows):
        if all(c in header for c in required):
            return [dict(zip(header, r)) for r in rows[i + 1:] if any(x.strip() for x in r)]
    raise ValueError(f"{path}: no header row containing {required}")
