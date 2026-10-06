import json
import os
import threading
import urllib.error
from datetime import date
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

from app import registry, research
from connectors import store
from runner import engines, extract, run

NUMBERED = """Here are the best options:

1. **Acme Lending** - Great rates for good credit.
2. **Zed Loans**: Fast funding, fair credit welcome.
3. [Harbor Finance](https://www.harborfinance.example.com) offers flexible terms.
4. **Upstart (best for thin credit)**
5. **Wells Fargo Bank, N.A.** is a large bank.

Tips:
1. Compare rates from several lenders.
2. Check the fees before you apply.
"""


def names(text, cites=()):
    return [r["name"] for r in extract.extract_companies(text, cites)["results"]]


def test_numbered_list_with_bold_links_and_a_second_list_of_tips():
    ex = extract.extract_companies(NUMBERED)
    assert [r["name"] for r in ex["results"]] == ["Acme Lending", "Zed Loans", "Harbor Finance", "Upstart", "Wells Fargo Bank"]
    assert [r["rank"] for r in ex["results"]] == [1, 2, 3, 4, 5] and ex["ok"] and ex["seen"] == 5  # the tips list is ignored
    assert ex["results"][2]["url"] == "https://www.harborfinance.example.com" and ex["results"][0]["url"] is None


def test_other_list_styles():
    assert names("### 1. Acme Lending\nText\n### 2. Zed Loans\nText\n### 3. Harbor Finance\nText") == ["Acme Lending", "Zed Loans", "Harbor Finance"]
    assert names("**1. Acme Lending**: text\n**2. Zed Loans**: text\n**3) Harbor Finance**: text") == ["Acme Lending", "Zed Loans", "Harbor Finance"]
    assert names("Top picks:\n- **Acme Lending** - text\n- **Zed Loans** - text\n  - a sub point\n- **Harbor Finance** - text") == ["Acme Lending", "Zed Loans", "Harbor Finance"]
    assert names("1. Acme\n2. Zed\n3. Acme\n4. Harbor") == ["Acme", "Zed", "Harbor"]  # repeats dropped


def test_steps_and_prose_are_not_mistaken_for_companies():
    steps = extract.extract_companies("1. Compare rates.\n2. Check your credit score.\n3. Apply online.")
    assert steps["ok"] is False and steps["results"] == [] and "only 0" in steps["reason"]
    few = extract.extract_companies("1. **Acme Lending** - good\n2. **Zed Loans** - ok")
    assert few["ok"] is False and len(few["results"]) == 2
    mixed = extract.extract_companies("1. Your credit score matters\n2. Why rates differ by lender\n3. How lenders decide\n4. **Acme Lending** - good\n5. **Zed Loans**\n6. **Harbor Finance**")
    assert mixed["ok"] is False and "Only 3 of 6" in mixed["reason"]  # half the items are not companies


def test_companies_get_a_web_address_from_a_matching_source_only():
    cites = [{"url": "https://www.acmelending.com/personal", "title": ""}, {"url": "https://start.example.com/x", "title": ""}]
    res = extract.extract_companies("1. **Acme Lending**\n2. **Upstart**\n3. **Zed Loans**", cites)["results"]
    assert res[0]["url"] == "https://www.acmelending.com/personal" and res[1]["url"] is None and res[2]["url"] is None


# ---------------------------------------------------------------- the engine
DOC = {"role": "assistant", "model": "claude-sonnet-5-5", "stop_reason": "end_turn",
       "usage": {"input_tokens": 6000, "output_tokens": 900, "server_tool_use": {"web_search_requests": 2}},
       "content": [
           {"type": "text", "text": "I'll search for that."},
           {"type": "server_tool_use", "id": "srvtoolu_1", "name": "web_search", "input": {"query": "best auto loans"}},
           {"type": "web_search_tool_result", "tool_use_id": "srvtoolu_1", "content": [
               {"type": "web_search_result", "url": "https://reviews.example.net/auto", "title": "Auto loans reviewed", "encrypted_content": "abc", "page_age": "May 1, 2026"},
               {"type": "web_search_result", "url": "https://other.example.org/x", "title": "Other", "encrypted_content": "def"}]},
           {"type": "text", "text": "1. **Acme Lending** - cheap.\n2. **Zed Loans** - fast.\n3. **Harbor Finance** - flexible.", "citations": [
               {"type": "web_search_result_location", "url": "https://reviews.example.net/auto", "title": "Auto loans reviewed", "encrypted_index": "x", "cited_text": "..."}]}]}


class Fake:
    """Stands in for the network: replays scripted (status, body, headers) replies and records requests."""
    def __init__(self, *replies):
        self.replies, self.calls, self.sleeps = list(replies), [], []

    def post(self, url, headers, body, timeout):
        self.calls.append((url, headers, body))
        r = self.replies.pop(0)
        if isinstance(r, Exception):
            raise r
        return r

    def engine(self, **kw):
        return engines.AnthropicEngine("claude", kw.pop("settings", None), post=self.post, sleep=self.sleeps.append, api_key=kw.pop("api_key", "sk-test-key"), **kw)


def ok(data=DOC):
    return 200, data, {}


def test_a_search_answer_is_read_the_way_the_docs_describe_it():
    f = Fake(ok())
    ans = f.engine(system="Be brief.").ask("What are the best auto loans?")
    assert ans.text.startswith("I'll search for that.\n\n1. **Acme Lending**") and ans.model == "claude-sonnet-5-5"
    assert ans.citations == [{"url": "https://reviews.example.net/auto", "title": "Auto loans reviewed"}]  # cited sources, not every result seen
    assert (ans.searches, ans.input_tokens, ans.output_tokens) == (2, 6000, 900)
    url, headers, body = f.calls[0]
    assert url == engines.API_URL and headers["x-api-key"] == "sk-test-key" and headers["anthropic-version"] == "2023-06-01"
    assert body["model"] == "claude-sonnet-5-5" and body["max_tokens"] == 2000 and body["system"] == "Be brief."
    assert body["tools"] == [{"type": "web_search_20250305", "name": "web_search", "max_uses": 4}]
    assert body["messages"] == [{"role": "user", "content": "What are the best auto loans?"}] and "sk-test-key" not in json.dumps(body)


def test_request_options():
    f = Fake(ok(), ok(), ok())
    f.engine(settings={"web_search": False}).ask("q")
    assert "tools" not in f.calls[0][2] and "system" not in f.calls[0][2]
    e = f.engine(settings={"country": "us", "max_searches": 2, "model": "m1"})
    e.ask("q")
    assert e.location == "US" and f.calls[1][2]["tools"][0]["user_location"] == {"type": "approximate", "country": "US"} and f.calls[1][2]["model"] == "m1"
    f.engine(settings={"tool_version": "web_search_20260318"}).ask("q")
    assert f.calls[2][2]["tools"][0]["allowed_callers"] == ["direct"]


def test_sources_fall_back_to_search_results_when_nothing_is_cited():
    data = json.loads(json.dumps(DOC))
    data["content"][3].pop("citations")
    assert [c["url"] for c in Fake(ok(data)).engine().ask("q").citations] == ["https://reviews.example.net/auto", "https://other.example.org/x"]


def test_a_paused_turn_is_sent_back_unchanged_and_the_text_joined():
    first = {"stop_reason": "pause_turn", "usage": {"input_tokens": 10, "output_tokens": 5, "server_tool_use": {"web_search_requests": 1}},
             "content": [{"type": "text", "text": "Searching."}, {"type": "server_tool_use", "id": "s1", "name": "web_search", "input": {"query": "x"}}]}
    f = Fake(ok(first), ok())
    ans = f.engine().ask("q")
    assert f.calls[1][2]["messages"] == [{"role": "user", "content": "q"}, {"role": "assistant", "content": first["content"]}]
    assert ans.text.startswith("Searching.\n\nI'll search for that.") and (ans.searches, ans.input_tokens) == (3, 6010)
    assert len(f.calls[0][2]["messages"]) == 1  # the first request was not altered afterwards


def test_rate_limits_are_retried_and_auth_problems_stop_at_once():
    f = Fake((429, {"error": {"message": "slow down"}}, {"retry-after": "7"}), ok())
    assert f.engine().ask("q").text and f.sleeps == [7.0]
    f = Fake((529, {}, {}), (529, {}, {}), (529, {"error": {"message": "overloaded"}}, {}))
    with pytest.raises(engines.EngineError, match="overloaded"):
        f.engine(retries=2).ask("q")
    assert f.sleeps == [5, 10] and len(f.calls) == 3
    f = Fake((401, {"error": {"message": "invalid x-api-key"}}, {}))
    with pytest.raises(engines.AuthError):
        f.engine().ask("q")
    assert len(f.calls) == 1


def test_helpful_messages_for_common_setup_problems(monkeypatch):
    with pytest.raises(engines.EngineError, match="Claude Console"):
        Fake((400, {"error": {"message": "Web search is not enabled for this organization"}}, {})).engine().ask("q")
    with pytest.raises(engines.EngineError, match="config/research.yaml"):
        Fake((404, {"error": {"message": "model: nope"}}, {})).engine().ask("q")
    with pytest.raises(engines.EngineError, match="Could not reach"):
        Fake(*[urllib.error.URLError("down")] * 2).engine(retries=1).ask("q")
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(engines.AuthError, match="ANTHROPIC_API_KEY"):
        Fake().engine(api_key=None).ask("q")


def test_odd_responses_become_warnings_or_errors():
    err = {"role": "assistant", "stop_reason": "max_tokens", "content": [
        {"type": "web_search_tool_result", "tool_use_id": "s", "content": {"type": "web_search_tool_result_error", "error_code": "max_uses_exceeded"}},
        {"type": "text", "text": "1. **Acme Lending**"}]}
    ans = Fake(ok(err)).engine().ask("q")
    assert ans.warnings == ["max_uses_exceeded", "answer was cut off at max_tokens"] and ans.citations == []
    with pytest.raises(engines.EngineError, match="no text"):
        Fake(ok({"content": [], "stop_reason": "end_turn"})).engine().ask("q")


def test_the_real_network_code_against_a_local_stand_in_for_the_api():
    seen = []

    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            seen.append((self.path, {k.lower(): v for k, v in self.headers.items()}, body))
            code, data = (401, {"error": {"type": "authentication_error", "message": "invalid x-api-key"}}) if self.path == "/denied" else (200, DOC)
            raw = json.dumps(data).encode()
            self.send_response(code)
            self.send_header("Content-Type", "application/json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    try:
        ans = engines.AnthropicEngine("claude", {"api_url": base + "/v1/messages"}, api_key="secret").ask("What are the best auto loans?")
        assert ans.searches == 2 and [r["name"] for r in extract.extract_companies(ans.text, ans.citations)["results"]] == ["Acme Lending", "Zed Loans", "Harbor Finance"]
        path, headers, body = seen[0]
        assert path == "/v1/messages" and headers["x-api-key"] == "secret" and headers["anthropic-version"] == "2023-06-01"
        assert headers["content-type"] == "application/json" and body["messages"][0]["content"] == "What are the best auto loans?"
        with pytest.raises(engines.AuthError, match="invalid x-api-key"):
            engines.AnthropicEngine("claude", {"api_url": base + "/denied"}, api_key="bad").ask("q")
    finally:
        srv.shutdown()


# ------------------------------------------------------------- the command line
class FakeEngine:
    location = "US"

    def __init__(self, replies=None):
        self.replies, self.asked = replies or {}, []

    def ask(self, q):
        self.asked.append(q)
        r = self.replies.get(len(self.asked))
        if isinstance(r, Exception):
            raise r
        text = r if isinstance(r, str) else "1. **Acme Lending** - a\n2. **Zed Loans** - b\n3. **Harbor Finance** - c"
        return engines.Answer(text, [{"url": "https://reviews.example.net/x", "title": ""}], "m", 1, 100, 50)


@pytest.fixture
def home(tmp_path, monkeypatch):
    monkeypatch.setenv("BRANDOPS_HOME", str(tmp_path))
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'brandops.db'}")
    return tmp_path


def go(home, *args, engine=None, factory=None):
    lines = []
    fake = engine or FakeEngine()
    code = run.main(["--home", str(home), "--delay", "0", *args], engine_factory=factory or (lambda *a: fake), say=lines.append,
                    sleep=lambda s: None, today=date(2026, 10, 5))
    return code, "\n".join(lines), fake


def inbox_files(home):
    return sorted((home / "data_inbox" / "research").glob("runner-*.jsonl"))


def test_the_plan_skips_questions_answered_recently_and_respects_limits():
    cfg, cats = research.config(), registry.categories()
    auto = cfg["questions"]["auto"]
    plan, skipped = run.build_plan(cfg, cats, "claude", only="auto", per_category=2, existing={("auto", research.norm_q(auto[0]), "claude")}, norm=research.norm_q)
    assert [p["question"] for p in plan] == [auto[1]] and skipped == 1
    assert len(run.build_plan(cfg, cats, "claude", norm=research.norm_q)[0]) == sum(len(v) for v in cfg["questions"].values())
    assert len(run.build_plan(cfg, cats, "claude", only="auto", existing={("auto", research.norm_q(auto[0]), "claude")}, force=True, norm=research.norm_q)[0]) == len(auto)


def test_a_dry_run_asks_nothing_and_writes_nothing(home):
    def boom(*a):
        raise AssertionError("the engine must not be created on a dry run")

    code, out, _ = go(home, "--dry-run", "--category", "auto", factory=boom)
    assert code == 0 and "questions to ask claude" in out and "Search fees would be at most" in out and not (home / "data_inbox").exists()


def test_a_run_writes_a_file_the_app_accepts_and_can_load_it(home):
    code, out, eng = go(home, "--category", "auto", "--questions", "2", "--import")
    assert code == 0 and len(eng.asked) == 2 and "imported it: 2 added" in out
    (path,) = inbox_files(home)
    runs, errors = research.parse_text(path.name, path.read_text(encoding="utf-8"))
    assert errors == [] and len(runs) == 2 and runs[0]["engine"] == "claude" and runs[0]["location"] == "US"
    assert [r["name"] for r in runs[0]["results"]] == ["Acme Lending", "Zed Loans", "Harbor Finance"] and runs[0]["answer"].startswith("1.")
    assert len(store.research_runs("2026-10-01")) == 2
    code, out, eng = go(home, "--category", "auto", "--questions", "2")  # asking again within the week finds nothing to do
    assert code == 0 and eng.asked == [] and "Nothing to do" in out and "2 skipped" in out
    assert go(home, "--category", "auto", "--questions", "1", "--force")[2].asked  # --force asks anyway


def test_answers_that_cannot_be_read_are_held_for_a_person_to_check(home):
    code, out, _ = go(home, "--category", "auto", "--questions", "2", engine=FakeEngine({1: "I could not find a clear ranking."}))
    assert code == 0 and "needs a person to check" in out
    held = list((home / "data_inbox" / "research" / "needs_review").glob("*.json"))
    assert len(held) == 1 and json.loads(held[0].read_text())["reason"].startswith("Found only 0")
    assert len(inbox_files(home)) == 1 and "1 needs a check" not in out and "needs a check 1" in out


def test_a_bad_key_stops_the_run_but_keeps_the_answers_so_far(home):
    eng = FakeEngine({2: engines.AuthError("401: invalid x-api-key")})
    code, out, _ = go(home, "--category", "auto", engine=eng)
    assert code == 1 and len(eng.asked) == 2 and "Stopping: 401" in out
    (path,) = inbox_files(home)
    assert len(path.read_text().strip().splitlines()) == 1


def test_three_failures_in_a_row_stop_the_run(home):
    eng = FakeEngine({i: engines.EngineError("overloaded") for i in range(1, 9)})
    code, out, _ = go(home, "--category", "auto", engine=eng)
    assert code == 1 and len(eng.asked) == 3 and "3 failures in a row" in out and inbox_files(home) == []


def test_the_safety_cap_and_unknown_engines(home):
    code, out, eng = go(home, "--max-runs", "3")
    assert len(eng.asked) == 3 and "held back by --max-runs 3" in out
    code, out, _ = go(home, "--engine", "nope")
    assert code == 2 and "Unknown engine" in out
    code, out, _ = go(home, "--engine", "chatgpt", factory=engines.make_engine)
    assert code == 2 and "no API settings yet" in out


def test_end_to_end_with_the_real_engine_against_a_stand_in_api(home, monkeypatch):
    class Stub(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_POST(self):
            self.rfile.read(int(self.headers["Content-Length"]))
            raw = json.dumps(DOC).encode()
            self.send_response(200)
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), Stub)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    url = f"http://127.0.0.1:{srv.server_address[1]}/v1/messages"
    try:
        code, out, _ = go(home, "--category", "auto", "--questions", "1", "--import",
                          factory=lambda eid, api, system, model: engines.AnthropicEngine(eid, {**api, "api_url": url}, system=system))
    finally:
        srv.shutdown()
    assert code == 0 and "imported it: 1 added" in out and "Used 2 searches" in out
    assert store.research_runs("2026-10-01")[0]["results"][0]["name"] == "Acme Lending"
    assert os.environ["BRANDOPS_HOME"] == str(home)


def test_the_bundled_config_names_the_runnable_engine():
    api = research.config()["engines"]["claude"]["api"]
    assert api["provider"] == "anthropic" and api["web_search"] is True


def test_a_fresh_data_folder_gets_default_settings_and_the_command_really_runs(tmp_path):
    import subprocess
    import sys
    from pathlib import Path

    keep = tmp_path / "config"
    keep.mkdir()
    (keep / "categories.yaml").write_text("categories:\n  - {id: mine, label: Mine}\n")  # your own file must survive
    env = {k: v for k, v in os.environ.items() if k not in ("BRANDOPS_HOME", "DATABASE_URL", "BRANDOPS_DB", "ANTHROPIC_API_KEY")}
    done = subprocess.run([sys.executable, "-m", "runner", "--dry-run", "--home", str(tmp_path)], capture_output=True, text=True,
                          cwd=Path(run.__file__).resolve().parent.parent, env=env, timeout=60)
    assert done.returncode == 0, done.stderr
    assert "questions to ask claude" in done.stdout and (tmp_path / "config" / "research.yaml").exists()
    assert "Mine" in (keep / "categories.yaml").read_text()


def test_a_missing_key_is_reported_before_anything_is_asked(home, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    code, out, _ = go(home, "--category", "auto", factory=lambda eid, api, system, model: engines.AnthropicEngine(eid, api, system=system))
    assert code == 2 and "ANTHROPIC_API_KEY" in out and "Answered" not in out and inbox_files(home) == []
