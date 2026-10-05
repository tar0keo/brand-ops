"""Warehouse access. A local SQLite file by default (no setup); PostgreSQL when DATABASE_URL points at one."""
import json
import os
import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path

from connectors import paths

SCHEMA = """
create table if not exists fact_metrics (
  brand_id text not null, day text not null, source text not null, metric text not null,
  value real not null, dimensions text not null default '{}',
  loaded_at text not null default (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  primary key (brand_id, day, source, metric, dimensions));
create index if not exists ix_fact_day on fact_metrics (day);
create table if not exists sync_status (connector text primary key, last_success text, last_error text, rows_loaded integer);
create table if not exists task_log (task_key text primary key, jira_key text not null,
  created_at text not null default (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
"""
NOW = "strftime('%Y-%m-%dT%H:%M:%SZ','now')"
PG_TASK_LOG = ("create table if not exists task_log (task_key text primary key, "
               "jira_key text not null, created_at timestamptz not null default now())")
SYNC_KEYS = ("connector", "last_success", "last_error", "rows_loaded")


def is_sqlite():
    url = os.environ.get("DATABASE_URL", "")
    return not url or url.startswith("sqlite")


def db_path():
    if os.environ.get("BRANDOPS_DB"):
        return Path(os.environ["BRANDOPS_DB"])
    url = os.environ.get("DATABASE_URL", "")
    if url.startswith("sqlite:///"):
        return Path(url[len("sqlite:///"):])
    return paths.home() / "data" / "brandops.db"


@contextmanager
def session():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30)
    try:
        conn.executescript(SCHEMA)
        with conn:  # commits on success, rolls back on error
            yield conn
    finally:
        conn.close()


@contextmanager
def _pg():
    import psycopg

    with psycopg.connect(os.environ["DATABASE_URL"]) as conn, conn.cursor() as cur:
        yield cur


def load_rows(rows, connector):
    if not is_sqlite():
        from psycopg.types.json import Jsonb

        from connectors.base import load_brands

        with _pg() as cur:
            cur.executemany(
                "insert into brands (brand_id, name, kind) values (%s,%s,%s) "
                "on conflict (brand_id) do update set name=excluded.name, kind=excluded.kind",
                [(b["id"], b["name"], b.get("category", "uncategorized")) for b in load_brands()])
            cur.executemany(
                "insert into fact_metrics (brand_id, day, source, metric, value, dimensions) values (%s,%s,%s,%s,%s,%s) "
                "on conflict (brand_id, day, source, metric, dimensions) do update set value=excluded.value, loaded_at=now()",
                [(r.brand_id, r.day, r.source, r.metric, r.value, Jsonb(r.dimensions)) for r in rows])
            cur.execute(
                "insert into sync_status (connector, last_success, last_error, rows_loaded) values (%s, now(), null, %s) "
                "on conflict (connector) do update set last_success=now(), last_error=null, rows_loaded=excluded.rows_loaded",
                (connector, len(rows)))
        return
    data = [(r.brand_id, r.day.isoformat(), r.source, r.metric, r.value, json.dumps(r.dimensions, sort_keys=True)) for r in rows]
    with session() as c:
        c.executemany(
            "insert into fact_metrics (brand_id, day, source, metric, value, dimensions) values (?,?,?,?,?,?) "
            f"on conflict(brand_id, day, source, metric, dimensions) do update set value=excluded.value, loaded_at={NOW}",
            data)
        c.execute(
            f"insert into sync_status (connector, last_success, last_error, rows_loaded) values (?, {NOW}, null, ?) "
            f"on conflict(connector) do update set last_success={NOW}, last_error=null, rows_loaded=excluded.rows_loaded",
            (connector, len(rows)))


def record_error(connector, err):
    msg = str(err)[:500]
    if not is_sqlite():
        with _pg() as cur:
            cur.execute("insert into sync_status (connector, last_error) values (%s,%s) "
                        "on conflict (connector) do update set last_error=excluded.last_error", (connector, msg))
        return
    with session() as c:
        c.execute("insert into sync_status (connector, last_error) values (?,?) "
                  "on conflict(connector) do update set last_error=excluded.last_error", (connector, msg))


def fetch_rows(start, end):
    keys = ("brand_id", "day", "source", "metric", "value", "dimensions")
    if not is_sqlite():
        with _pg() as cur:
            cur.execute("select brand_id, day, source, metric, value, dimensions from fact_metrics where day between %s and %s", (start, end))
            return [dict(zip(keys, r)) for r in cur.fetchall()]
    with session() as c:
        cur = c.execute("select brand_id, day, source, metric, value, dimensions from fact_metrics where day between ? and ?",
                        (start.isoformat(), end.isoformat()))
        return [{"brand_id": b, "day": date.fromisoformat(d), "source": s, "metric": m, "value": v, "dimensions": json.loads(x)}
                for b, d, s, m, v, x in cur.fetchall()]


def fetch_status():
    q = "select connector, last_success, last_error, rows_loaded from sync_status order by connector"
    if not is_sqlite():
        with _pg() as cur:
            cur.execute(q)
            return [dict(zip(SYNC_KEYS, r)) for r in cur.fetchall()]
    with session() as c:
        return [dict(zip(SYNC_KEYS, r)) for r in c.execute(q).fetchall()]


def tasklog_recent(days):
    """{task_key: ticket} for tasks ticketed within the cooldown window."""
    if not is_sqlite():
        with _pg() as cur:
            cur.execute(PG_TASK_LOG)
            cur.execute("select task_key, jira_key from task_log where created_at > now() - make_interval(days => %s)", (days,))
            return dict(cur.fetchall())
    with session() as c:
        cur = c.execute("select task_key, jira_key from task_log where created_at > strftime('%Y-%m-%dT%H:%M:%SZ','now', ?)",
                        (f"-{int(days)} days",))
        return dict(cur.fetchall())


def tasklog_record(key, ticket):
    if not is_sqlite():
        with _pg() as cur:
            cur.execute(PG_TASK_LOG)
            cur.execute("insert into task_log (task_key, jira_key) values (%s,%s) "
                        "on conflict (task_key) do update set jira_key=excluded.jira_key, created_at=now()", (key, ticket))
        return
    with session() as c:
        c.execute("insert into task_log (task_key, jira_key) values (?,?) "
                  f"on conflict(task_key) do update set jira_key=excluded.jira_key, created_at={NOW}", (key, ticket))
