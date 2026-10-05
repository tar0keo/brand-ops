import argparse
import importlib
import re
from datetime import date, timedelta

from connectors import store


def run(name, days=7, dry_run=False):
    """Fetch rows from a connector and load them into the warehouse. Returns the row count."""
    if not re.fullmatch(r"[a-z0-9_]+", name):
        raise ValueError("Invalid connector name")
    connector = importlib.import_module(f"connectors.{name}").Connector()
    end = date.today()
    try:
        rows = list(connector.fetch(end - timedelta(days=days), end))
    except Exception as e:
        if not dry_run:
            store.record_error(name, e)
        raise
    if not dry_run:
        store.load_rows(rows, connector.name)
    return len(rows)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("connector")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    n = run(args.connector, args.days, args.dry_run)
    print(f"{args.connector}: {n} rows" + ("" if args.dry_run else " loaded"))


if __name__ == "__main__":
    main()
