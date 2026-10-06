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


def _migrate(conn):
    """Bring a database made by an older version up to date."""
    cols = {r[1] for r in conn.execute("pragma table_info(media_items)")}
    if cols and "summary" not in cols:
        conn.execute("alter table media_items add column summary text not null default ''")


@contextmanager
def session():
    p = db_path()
    p.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(p, timeout=30)
    try:
        conn.executescript(SCHEMA)
        _migrate(conn)
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


# ---------- media releases (links saved from articles and posts) ----------
MEDIA_SQLITE = """
create table if not exists media_items (
  id integer primary key autoincrement, url text not null unique, title text, source text, published text,
  excerpt text, summary text not null default '', body text, brand_id text, matches text not null default '[]', status text not null default 'ok',
  manual integer not null default 0, added_at text not null default (strftime('%Y-%m-%dT%H:%M:%SZ','now')));
"""
MEDIA_PG = ("create table if not exists media_items (id bigserial primary key, url text not null unique, title text, "
            "source text, published text, excerpt text, summary text not null default '', body text, brand_id text, matches text not null default '[]', "
            "status text not null default 'ok', manual integer not null default 0, added_at timestamptz not null default now())")
MEDIA_COLS = "id, url, title, source, published, excerpt, brand_id, matches, status, manual, added_at, summary"
MEDIA_PG_MIGRATE = "alter table media_items add column if not exists summary text not null default ''"
SCHEMA += MEDIA_SQLITE


def _q(sql, params=(), fetch=False):
    """Run one statement on whichever database is in use (write ? placeholders)."""
    if is_sqlite():
        with session() as c:
            cur = c.execute(sql, params)
            return cur.fetchall() if fetch else cur.rowcount
    with _pg() as cur:
        cur.execute(MEDIA_PG)
        cur.execute(MEDIA_PG_MIGRATE)
        cur.execute(RESEARCH_PG)
        cur.execute(sql.replace("?", "%s"), params)
        return cur.fetchall() if fetch else cur.rowcount


def _media_row(r):
    return {"id": r[0], "url": r[1], "title": r[2], "source": r[3], "published": r[4], "excerpt": r[5],
            "brand_id": r[6] or None, "matches": json.loads(r[7] or "[]"), "status": r[8],
            "manual": bool(r[9]), "added_at": str(r[10]), "summary": r[11] or ""}


def media_list():
    rows = _q(f"select {MEDIA_COLS} from media_items "
              "order by coalesce(published, substr(cast(added_at as text), 1, 10)) desc, id desc", fetch=True)
    return [_media_row(r) for r in rows]


def media_exists(url):
    return bool(_q("select 1 from media_items where url = ?", (url,), fetch=True))


def media_add(item):
    """Insert a link. Returns its id, or None if that link is already saved."""
    vals = (item["url"], item.get("title"), item.get("source"), item.get("published"), item.get("excerpt"), item.get("summary") or "",
            item.get("body"), item.get("brand_id"), json.dumps(item.get("matches") or []), item.get("status", "ok"), int(bool(item.get("manual"))))
    q = ("insert into media_items (url, title, source, published, excerpt, summary, body, brand_id, matches, status, manual) "
         "values (?,?,?,?,?,?,?,?,?,?,?) on conflict(url) do nothing")
    if is_sqlite():
        with session() as c:
            cur = c.execute(q, vals)
            return cur.lastrowid if cur.rowcount else None
    with _pg() as cur:
        cur.execute(MEDIA_PG)
        cur.execute(MEDIA_PG_MIGRATE)
        cur.execute(q.replace("?", "%s") + " returning id", vals)
        row = cur.fetchone()
        return row[0] if row else None


def media_update(item_id, **fields):
    sets, vals = [], []
    if "brand_id" in fields:
        sets.append("brand_id = ?")
        vals.append(fields["brand_id"])
    if "matches" in fields:
        sets.append("matches = ?")
        vals.append(json.dumps(fields["matches"]))
    if "manual" in fields:
        sets.append("manual = ?")
        vals.append(int(bool(fields["manual"])))
    if not sets:
        return False
    return _q(f"update media_items set {', '.join(sets)} where id = ?", (*vals, item_id)) > 0


def media_remove(item_id):
    return _q("delete from media_items where id = ?", (item_id,)) > 0


def media_unassigned():
    rows = _q("select id, url, title, body from media_items where manual = 0 and (brand_id is null or brand_id = '')", fetch=True)
    return [{"id": r[0], "url": r[1], "title": r[2] or "", "body": r[3] or ""} for r in rows]


# ---------- market research runs (answers to consumer questions, per engine) ----------
RESEARCH_SQLITE = """
create table if not exists research_runs (
  id integer primary key autoincrement, run_date text not null, category text not null, question text not null,
  engine text not null, model text not null default '', location text not null default '', answer text,
  citations text not null default '[]', results text not null default '[]',
  imported_at text not null default (strftime('%Y-%m-%dT%H:%M:%SZ','now')),
  unique (run_date, category, question, engine, model, location));
"""
RESEARCH_PG = ("create table if not exists research_runs (id bigserial primary key, run_date text not null, category text not null, "
               "question text not null, engine text not null, model text not null default '', location text not null default '', "
               "answer text, citations text not null default '[]', results text not null default '[]', "
               "imported_at timestamptz not null default now(), unique (run_date, category, question, engine, model, location))")
SCHEMA += RESEARCH_SQLITE


def research_save_run(run):
    """Insert a run, or replace the same run imported again. Returns 'added' or 'replaced'."""
    key = (run["date"], run["category"], run["question"], run["engine"], run.get("model") or "", run.get("location") or "")
    exists = bool(_q("select 1 from research_runs where run_date=? and category=? and question=? and engine=? "
                     "and model=? and location=?", key, fetch=True))
    _q("insert into research_runs (run_date, category, question, engine, model, location, answer, citations, results) "
       "values (?,?,?,?,?,?,?,?,?) on conflict(run_date, category, question, engine, model, location) "
       "do update set answer=excluded.answer, citations=excluded.citations, results=excluded.results",
       (*key, run.get("answer") or "", json.dumps(run.get("citations") or []), json.dumps(run["results"])))
    return "replaced" if exists else "added"


def research_runs(since):
    rows = _q("select run_date, category, question, engine, model, location, citations, results from research_runs "
              "where run_date >= ? order by run_date, id", (since,), fetch=True)
    return [{"run_date": date.fromisoformat(str(r[0])), "category": r[1], "question": r[2], "engine": r[3], "model": r[4],
             "location": r[5], "citations": json.loads(r[6] or "[]"), "results": json.loads(r[7] or "[]")} for r in rows]


# ---------- removing a brand's saved data ----------
def brand_metric_count(brand_id):
    return _q("select count(*) from fact_metrics where brand_id = ?", (brand_id,), fetch=True)[0][0]


def delete_brand_metrics(brand_id):
    """Delete every saved metric row for a brand. Returns how many."""
    n = _q("delete from fact_metrics where brand_id = ?", (brand_id,))
    if not is_sqlite():
        _q("delete from brands where brand_id = ?", (brand_id,))  # PostgreSQL keeps a brands table
    return n


def media_count_brand(brand_id):
    return _q("select count(*) from media_items where brand_id = ?", (brand_id,), fetch=True)[0][0]


def media_release_brand(brand_id):
    """Unassign a brand's media links. The links stay in the list and can be matched again."""
    return _q("update media_items set brand_id = NULL, manual = 0 where brand_id = ?", (brand_id,))


def media_automatic():
    """Every link whose brand was chosen by the app, not by you (assigned or not), with the text used to match it."""
    rows = _q("select id, url, title, body, brand_id from media_items where manual = 0", fetch=True)
    return [{"id": r[0], "url": r[1], "title": r[2] or "", "body": r[3] or "", "brand_id": r[4] or None} for r in rows]


def media_missing_summary():
    """Readable links saved without a summary (for example, before summaries existed)."""
    rows = _q("select id, title, body, brand_id from media_items where (summary is null or summary = '') and status = 'ok' "
              "and body is not null and body != ''", fetch=True)
    return [{"id": r[0], "title": r[1] or "", "body": r[2] or "", "brand_id": r[3] or None} for r in rows]


def media_set_summary(item_id, summary):
    return _q("update media_items set summary = ? where id = ?", (summary, item_id)) > 0
