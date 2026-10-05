import json
from datetime import date

import pytest

from app import research, server
from connectors import store
from tests.helpers import get, post

CFG = research.config()
CSV = """Date,Category,Question,Engine,Rank,Name,URL
2026-10-01,Auto loans,What are the best auto lenders?,ChatGPT,1,Acme Lending,https://www.acme.example.com/auto
2026-10-01,auto,What are the best auto lenders?,chatgpt,2,Brand 7,
2026-10-01,auto,What are the best auto lenders?,google_organic,1,Brand 7,brand7.example.com
"""
BR = [{"id": "b1", "name": "Brand 1", "category": "auto", "sites": ["brand1.example.com"]},
      {"id": "b2", "name": "Brand 2", "category": "auto", "sites": []}]


@pytest.fixture(autouse=True)
def clean():
    research._MEM.clear()
    yield
    research._MEM.clear()


def test_csv_is_grouped_into_runs_and_names_are_normalised():
    runs, errors = research.parse_text("a.csv", CSV, CFG)
    assert errors == [] and len(runs) == 2
    gpt = next(r for r in runs if r["engine"] == "chatgpt")
    assert gpt["category"] == "auto" and gpt["date"] == "2026-10-01" and [x["rank"] for x in gpt["results"]] == [1, 2]
    assert gpt["results"][1]["url"] is None


def test_csv_accepts_other_headings_excel_bom_and_semicolons():
    text = "\ufeffRun date;Loan type;Prompt;Source;Position;Company;Link\n10/01/2026;Auto loans;Best lenders?;Gemini;#3;Acme;\n"
    runs, errors = research.parse_text("x.csv", text, CFG)
    assert errors == [] and runs[0]["engine"] == "gemini" and runs[0]["results"][0]["rank"] == 3 and runs[0]["date"] == "2026-10-01"


def test_a_file_with_any_bad_row_imports_nothing(demo_mode):
    bad = CSV + "2026-10-01,auto,Q?,chatgp,1,Acme,\n2026-10-01,auto,Q?,chatgpt,x,Acme,\n2026-10-01,auto,Q?,chatgpt,1,,\n"
    out = research.import_text("bad.csv", bad, True, CFG)
    assert out["runs"] == 0 and out["added"] == 0 and out["error_count"] == 3
    assert "Row 5" in out["errors"][0] and "chatgp" in out["errors"][0] and "Rank 'x'" in out["errors"][1] and "Name is empty" in out["errors"][2]
    assert "Missing columns" in research.import_text("e.csv", "date,category\n", True, CFG)["errors"][0]


def test_json_lines_and_json_arrays_are_read():
    line1 = {"date": "2026-10-02", "category": "auto", "question": "Q one?", "engine": "gemini",
             "results": ["Acme", {"name": "Brand 1", "url": "https://brand1.example.com"}], "citations": ["https://a.example.org/x", {"url": "https://b.example.org", "title": "B"}]}
    line2 = {"date": "2026-10-02", "category": "personal", "question": "Q two?", "engine": "perplexity", "results": [{"rank": 4, "name": "Zed"}]}
    runs, errors = research.parse_text("r.jsonl", json.dumps(line1) + "\n\n" + json.dumps(line2), CFG)
    assert errors == [] and [x["rank"] for x in runs[0]["results"]] == [1, 2] and len(runs[0]["citations"]) == 2 and runs[1]["results"][0]["rank"] == 4
    runs, errors = research.parse_text("r.json", json.dumps([line1, line2]), CFG)
    assert errors == [] and len(runs) == 2
    runs, errors = research.parse_text("r.jsonl", json.dumps(line1) + "\nnot json\n" + json.dumps({"date": "x"}), CFG)
    assert len(runs) == 1 and errors[0].startswith("Line 2") and errors[1].startswith("Line 3")


def test_resolving_listed_companies_to_our_brands():
    assert research.resolve_brand("Whatever", "https://www.brand1.example.com/auto", BR) == "b1"  # the site wins
    assert research.resolve_brand("Brand 2 Loans", None, BR) == "b2"
    assert research.resolve_brand("Brand 22", None, BR) is None  # whole names only
    assert research.domain_of("Brand 7") is None and research.domain_of("www.Acme.example.com/x") == "acme.example.com"


def run(day, engine, q, items, cites=()):
    return {"run_date": date(2026, 10, day), "category": "auto", "question": q, "engine": engine, "model": "", "location": "",
            "citations": [{"url": c, "title": ""} for c in cites],
            "results": [{"rank": i + 1, "name": n, "url": u} for i, (n, u) in enumerate(items)]}


Q = "What are the best auto lenders?"
RUNS = [
    run(3, "chatgpt", Q, [("Acme Lending", "https://acme.example.com"), ("Brand 1", None), ("Zed Loans", None)],
        ["https://news.example.org/a", "https://brand1.example.com/x"]),
    run(3, "gemini", Q, [("Acme Lending", "acme.example.com"), ("Zed Loans", None)]),
    run(3, "google_organic", Q, [("Brand 1", "https://www.brand1.example.com/auto"), ("Brand 2", None), ("Acme Lending", "https://acme.example.com")]),
    run(1, "chatgpt", Q, [("Old Co", None)]),  # an older answer to the same question is ignored
]


def test_analysis_compares_ai_answers_with_seo():
    a = research.analyze(RUNS, BR, "auto", date(2026, 10, 1), CFG)
    assert a["summary"] == {"runs_gen": 2, "runs_seo": 1, "ours_gen": 0.5, "ours_seo": 1.0, "ours_gen_slots": 0.2, "ours_seo_slots": 0.667}
    rows = {r["name"]: r for r in a["table"]}
    assert "Old Co" not in rows
    assert rows["Acme Lending"]["gen"]["rate"] == 1.0 and rows["Acme Lending"]["seo"]["avg_rank"] == 3.0  # one company, three spellings of the link
    assert rows["Brand 1"]["ours"] and rows["Brand 1"]["gen"]["rate"] == 0.5 and rows["Brand 1"]["gap"] == -0.5
    assert rows["Brand 2"]["gen"]["count"] == 0 and rows["Brand 2"]["seo"]["count"] == 1  # our brand missing from AI answers
    assert [x["name"] for x in a["ai_not_seo"]] == ["Zed Loans"] and [x["name"] for x in a["seo_not_ai"]] == ["Brand 2"]
    q = next(x for x in a["questions"] if x["question"] == Q)
    assert q["engines"]["perplexity"] is None and q["engines"]["chatgpt"]["overlap"] == 0.67 and q["engines"]["chatgpt"]["ours"] == [{"name": "Brand 1", "rank": 2}]
    assert {s["domain"]: s["ours"] for s in a["sources"]} == {"news.example.org": False, "brand1.example.com": True}


def test_period_and_overview():
    assert research.analyze(RUNS, BR, "auto", date(2026, 10, 4), CFG)["summary"]["runs_gen"] == 0
    row = next(c for c in research.overview(RUNS, BR, date(2026, 10, 1), CFG) if c["id"] == "auto")
    assert row["combos"] - row["missing"] == 3 and row["ours_gen"] == 0.5


def test_runs_are_stored_replaced_not_duplicated(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'r.db'}")
    out = research.import_text("a.csv", CSV, False, CFG)
    assert (out["added"], out["replaced"]) == (2, 0)
    out = research.import_text("a.csv", CSV, False, CFG)
    assert (out["added"], out["replaced"]) == (0, 2)
    stored = store.research_runs("2026-01-01")
    assert len(stored) == 2 and stored[0]["run_date"] == date(2026, 10, 1) and isinstance(stored[0]["results"], list)
    assert store.research_runs("2026-10-02") == []


def test_demo_data_covers_every_category_with_our_brands_in_the_lists():
    runs = research.demo_runs(date(2026, 10, 5))
    assert {r["category"] for r in runs} == {c["id"] for c in research.registry.categories()}
    assert runs == research.demo_runs(date(2026, 10, 5))  # deterministic


def test_research_in_the_app(demo_mode, app_url, tmp_path, monkeypatch):
    r = get(app_url + "/api/research?days=30")
    assert r["detail"] is None and r["categories"] and {e["id"] for e in r["engines"]} >= {"chatgpt", "google_organic"}
    auto = research.registry.categories()[1]["id"]
    d = get(app_url + f"/api/research?days=30&category={auto}")["detail"]
    assert d["summary"]["runs_gen"] > 0 and d["summary"]["runs_seo"] > 0 and any(t["ours"] for t in d["table"]) and len(d["questions"]) >= 3
    new_q = "Brand new question about car loans?"
    text = f"date,category,question,engine,rank,name\n{date.today()},{auto},{new_q},chatgpt,1,Brand 12\n"
    code, body = post(app_url + "/api/research/import", {"files": [{"name": "m.csv", "text": text}]})
    assert code == 200 and body["results"][0]["added"] == 1
    d = get(app_url + f"/api/research?days=30&category={auto}")["detail"]
    assert any(q["question"] == new_q for q in d["questions"])
    code, body = post(app_url + "/api/research/import", {"files": [{"name": "bad.csv", "text": "nonsense"}]})
    assert code == 200 and body["results"][0]["error_count"] == 1
    assert post(app_url + "/api/research/import", {"files": []})[0] == 400


def test_importing_the_inbox_folder_and_unknown_category(app_url, tmp_path, monkeypatch):
    import urllib.error, urllib.request
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'i.db'}")
    monkeypatch.setenv("INBOX_DIR", str(tmp_path / "inbox"))
    assert post(app_url + "/api/research/import", {"inbox": True})[0] == 400  # nothing there yet
    (tmp_path / "inbox" / "research").mkdir(parents=True, exist_ok=True)
    (tmp_path / "inbox" / "research" / "a.csv").write_text(CSV)
    (tmp_path / "inbox" / "research" / "b.jsonl").write_text(json.dumps({"date": "2026-10-02", "category": "auto", "question": "Q?", "engine": "claude", "results": ["Acme"]}))
    code, body = post(app_url + "/api/research/import", {"inbox": True})
    assert code == 200 and [f["file"] for f in body["results"]] == ["a.csv", "b.jsonl"] and sum(f["added"] for f in body["results"]) == 3
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(app_url + "/api/research?category=nope")
    assert e.value.code == 400


def test_sample_files_in_the_repo_import_cleanly():
    from pathlib import Path
    for name in ("example.csv", "example.jsonl"):
        text = (Path(__file__).resolve().parent.parent / "sample_data" / "research" / name).read_text(encoding="utf-8")
        runs, errors = research.parse_text(name, text, CFG)
        assert errors == [] and runs
