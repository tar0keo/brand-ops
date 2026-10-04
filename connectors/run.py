import argparse
import importlib
import os
import re
import sys
from datetime import date, timedelta
from connectors.base import load_brands


def load_to_db(rows, connector_name):
    import psycopg
    from psycopg.types.json import Jsonb

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        cur.executemany(
            "insert into brands (brand_id, name, kind) values (%s,%s,%s) "
            "on conflict (brand_id) do update set name=excluded.name, kind=excluded.kind",
            [(b["id"], b["name"], b["kind"]) for b in load_brands()],
        )
        cur.executemany(
            "insert into fact_metrics (brand_id, day, source, metric, value, dimensions) "
            "values (%s,%s,%s,%s,%s,%s) "
            "on conflict (brand_id, day, source, metric, dimensions) "
            "do update set value=excluded.value, loaded_at=now()",
            [(r.brand_id, r.day, r.source, r.metric, r.value, Jsonb(r.dimensions)) for r in rows],
        )
        cur.execute(
            "insert into sync_status (connector, last_success, last_error, rows_loaded) "
            "values (%s, now(), null, %s) on conflict (connector) do update "
            "set last_success=now(), last_error=null, rows_loaded=excluded.rows_loaded",
            (connector_name, len(rows)),
        )


def main():
    p = argparse.ArgumentParser()
    p.add_argument("connector")
    p.add_argument("--days", type=int, default=7)
    p.add_argument("--dry-run", action="store_true")
    args = p.parse_args()
    if not re.fullmatch(r"[a-z0-9_]+", args.connector):
        sys.exit("Invalid connector name")
    connector = importlib.import_module(f"connectors.{args.connector}").Connector()
    end = date.today()
    rows = list(connector.fetch(end - timedelta(days=args.days), end))
    print(f"{connector.name}: {len(rows)} rows")
    if not args.dry_run:
        load_to_db(rows, connector.name)
        print("Loaded to warehouse")


if __name__ == "__main__":
    main()
