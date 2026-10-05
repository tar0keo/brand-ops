"""Entries added separately, at different times, all stay saved."""
from datetime import date

from app import research
from connectors import run as runner
from connectors import store
from connectors.base import MetricRow

BRANDS = [{"id": "b1", "name": "Brand 1", "category": "auto", "sites": []}]
HEAD = "date,category,question,engine,rank,name\n"


def use_db(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'h.db'}")
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox"))


def test_research_files_imported_at_different_times_accumulate(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    first = HEAD + "2026-09-01,auto,Q one?,chatgpt,1,Acme\n"
    second = HEAD + "2026-10-04,auto,Q two?,gemini,1,Zed\n"
    third = HEAD + "2026-10-05,auto,Q one?,chatgpt,1,Brand 1\n"  # the same question and engine, asked again later
    for name, text in (("a.csv", first), ("b.csv", second), ("c.csv", third)):
        assert research.import_text(name, text, False)["added"] == 1
    everything = store.research_runs("2000-01-01")
    assert len(everything) == 3  # nothing was overwritten or dropped
    assert [r["run_date"] for r in everything] == [date(2026, 9, 1), date(2026, 10, 4), date(2026, 10, 5)]
    # The screens show the latest answer to each question within the period; the older one is kept, just not used there.
    now = research.analyze(everything, BRANDS, "auto", date(2026, 8, 1))
    assert "Acme" not in [t["name"] for t in now["table"]] and now["summary"]["runs_gen"] == 2
    assert [r["run_date"] for r in store.research_runs("2026-10-01")] == [date(2026, 10, 4), date(2026, 10, 5)]
    # Only importing the exact same run again (same date, question, engine) replaces it.
    again = research.import_text("c2.csv", HEAD + "2026-10-05,auto,Q one?,chatgpt,1,Zed\n", False)
    assert (again["added"], again["replaced"]) == (0, 1) and len(store.research_runs("2000-01-01")) == 3


def test_metric_imports_for_other_days_and_sources_stay(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    store.load_rows([MetricRow("fla", date(2026, 1, 5), "bot_logs", "ai_crawler_hits", 7.0, {"bot": "gptbot"})], "bot_logs")
    short = runner.run("example", 3)
    longer = runner.run("example", 10)  # a later, wider import
    rows = store.fetch_rows(date(2000, 1, 1), date(2100, 1, 1))
    assert longer > short and len(rows) == longer + 1  # every example row once, plus the earlier bot-log row
    assert any(r["source"] == "bot_logs" and r["value"] == 7.0 for r in rows)


def test_saved_media_links_accumulate(tmp_path, monkeypatch):
    use_db(tmp_path, monkeypatch)
    store.media_add({"url": "https://a.example/1", "title": "One", "matches": []})
    store.media_add({"url": "https://a.example/2", "title": "Two", "matches": []})
    assert sorted(m["title"] for m in store.media_list()) == ["One", "Two"]
