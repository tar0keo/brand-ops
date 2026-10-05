import urllib.error
import urllib.request
from datetime import date, datetime, timedelta

import pytest

from app import server
from connectors import run as runner
from connectors import store
from tests.helpers import get, post


@pytest.fixture
def sqlite_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 't.db'}")
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox"))
    return tmp_path


def test_sqlite_load_is_idempotent_and_round_trips(sqlite_db):
    n = runner.run("example", 3)
    window = (date.today() - timedelta(days=5), date.today())
    rows = store.fetch_rows(*window)
    assert len(rows) == n and isinstance(rows[0]["day"], date) and rows[0]["dimensions"] == {"channel": "search"}
    runner.run("example", 3)
    assert len(store.fetch_rows(*window)) == n
    st = store.fetch_status()[0]
    assert st["connector"] == "example" and st["rows_loaded"] == n and st["last_error"] is None


def test_failed_run_records_the_error(sqlite_db):
    with pytest.raises(RuntimeError):
        runner.run("google_ads", 3)
    st = {s["connector"]: s for s in store.fetch_status()}
    assert "No CSV files" in st["google_ads"]["last_error"]


def test_task_log_round_trips(sqlite_db):
    store.tasklog_record("k:1", "BRAND-1")
    assert store.tasklog_recent(14) == {"k:1": "BRAND-1"}
    store.tasklog_record("k:1", "BRAND-2")
    assert store.tasklog_recent(14) == {"k:1": "BRAND-2"}


def test_sync_endpoint_imports_files_into_the_local_database(sqlite_db, app_url):
    log = sqlite_db / "inbox" / "bot_logs" / "fla" / "access.log"
    log.parent.mkdir(parents=True)
    today = datetime.now().strftime("%d/%b/%Y")
    ua = "Mozilla/5.0 (compatible; GPTBot/1.1)"
    log.write_text(f'1.1.1.1 - - [{today}:10:00:00 +0000] "GET /a HTTP/1.1" 200 5 "-" "{ua}"\n'
                   f'1.1.1.1 - - [{today}:10:00:05 +0000] "GET /b HTTP/1.1" 403 5 "-" "{ua}"\n')
    code, body = post(app_url + "/api/sync", {"connector": "bot_logs", "days": 30})
    assert code == 200 and body["rows"] == 2
    fla = next(b for b in get(app_url + "/api/summary?days=30")["brands"] if b["id"] == "fla")
    assert fla["current"]["bot_hits"] == 2 and fla["current"]["bot_errors"] == 1
    assert any(s["connector"] == "bot_logs" for s in get(app_url + "/api/status"))


def test_sync_endpoint_reports_problems_plainly(sqlite_db, app_url):
    code, body = post(app_url + "/api/sync", {"connector": "google_ads", "days": 30})
    assert code == 400 and "No CSV files" in body["error"]
    assert post(app_url + "/api/sync", {"connector": "os_system", "days": 30})[0] == 400


def test_sync_is_off_in_demo_mode(demo_mode, app_url):
    code, body = post(app_url + "/api/sync", {"connector": "bot_logs", "days": 30})
    assert code == 400 and "demo" in body["error"]
    info = get(app_url + "/api/info")
    assert info["demo"] is True and {"google_ads", "trustpilot"} <= {s["id"] for s in info["sources"]}
