import sqlite3
import urllib.request
from datetime import date

import pytest

from app import jira, media, registry, server
from app.tasks import attach_media
from connectors import base, store
from tests.helpers import get

ARTICLE = ("Brand 14 customers say refunds are taking more than a month to arrive. Subscribe to our newsletter for daily updates. "
           "Several customers told reporters they waited 45 days for money owed. Cookie policy: we use cookies to improve your experience. "
           "Brand 14 says it is hiring 30 support staff to clear the backlog. The weather was mild on Tuesday across much of the region. "
           "Consumer groups have asked for clearer refund terms.")


@pytest.fixture(autouse=True)
def clean():
    media._MEM.clear()
    yield
    media._MEM.clear()


def test_a_summary_keeps_the_useful_sentences_and_drops_boilerplate():
    s = media.summarize("Borrowers say refunds at Brand 14 are slow", ARTICLE, focus=["Brand 14"])
    assert s.startswith("Brand 14 customers say refunds") and "Brand 14 says it is hiring 30 support staff" in s and "45 days" in s
    assert not any(w in s for w in ("Subscribe", "Cookie", "weather")) and len(s) <= 450 and s.endswith(".")


def test_summaries_are_trimmed_and_cope_with_thin_text():
    long = " ".join(f"Sentence number {i} says something rather long about lending and borrowers and the wider market today." * 3 for i in range(5))
    s = media.summarize("Lending news", long)
    assert len(s) <= 454 and s.endswith("...")
    assert media.summarize("x", "") == "" and media.summarize("x", "Too short.") == ""
    assert media.summarize("x", "A short but usable line of text.") == "A short but usable line of text."
    assert "[links]" not in media.summarize("x", ARTICLE + media.LINKS_MARK + "brand14.com")


def test_a_summary_is_written_when_a_link_is_added_unless_the_page_cannot_be_read(demo_mode):
    page = media.parse_page(f"<html><head><title>Brand 14 refunds</title></head><body><p>{ARTICLE}</p></body></html>", "https://news.example.com/a")

    def fetch(url):
        if "bad" in url:
            raise OSError("down")
        return page

    media.add_links("https://news.example.com/a\nhttps://news.example.com/bad", True, fetch)
    by = {i["url"].rsplit("/", 1)[1]: i for i in media.list_items(True)}
    assert "Brand 14 says it is hiring" in by["a"]["summary"] and by["a"]["brand_id"] == "brand_14" and by["bad"]["summary"] == ""


def test_links_saved_without_a_summary_get_one_when_rechecked(demo_mode):
    media._MEM.media_add({"url": "https://a.example/1", "title": "Brand 7 launches", "source": "s", "published": None, "excerpt": "", "summary": "",
                          "body": "Brand 7 launched a new product in the spring. The company expects strong demand this year.", "brand_id": "brand_7",
                          "matches": [], "status": "ok", "manual": True})
    assert media.rematch(True)["summaries"] == 1
    assert media.list_items(True)[0]["summary"].startswith("Brand 7 launched") and media.rematch(True)["summaries"] == 0


def link(i, brand, **kw):
    return {"id": i, "brand_id": brand, "status": "ok", "manual": False, "title": f"T{i}", "source": "S", "published": None,
            "added_at": "2026-10-01T00:00:00Z", "url": f"https://x/{i}", "summary": f"sum{i}", **kw}


def test_coverage_is_attached_only_where_it_helps():
    links = [link(1, "b1", published="2026-05-01"),                                              # too old
             link(2, "b1", published="2026-09-30"),
             link(3, "b1", status="unreadable", added_at="2026-10-02T00:00:00Z"),                # unreadable and automatic: left out
             link(4, "b1", status="unreadable", manual=True, added_at="2026-10-03T00:00:00Z"),   # assigned by you: kept
             link(5, "b2"), link(6, None)]
    tasks = lambda: [{"rule": "rating", "brand_id": "b1"}, {"rule": "roas_low", "brand_id": "b1"}, {"rule": "rating", "brand_id": "b2"},
                     {"rule": "citation_drop", "brand_id": "b3"}]
    t = attach_media(tasks(), links, {}, today=date(2026, 10, 5))
    assert [m["url"] for m in t[0]["media"]] == ["https://x/4", "https://x/2"]  # newest first
    assert t[0]["media"][1] == {"title": "T2", "source": "S", "date": "2026-09-30", "url": "https://x/2", "summary": "sum2"}
    assert t[1]["media"] == [] and [m["url"] for m in t[2]["media"]] == ["https://x/5"] and t[3]["media"] == []
    assert len(attach_media(tasks(), links, {"max_links": 1}, today=date(2026, 10, 5))[0]["media"]) == 1
    assert len(attach_media(tasks(), links, {"rules": ["roas_low"]}, today=date(2026, 10, 5))[1]["media"]) == 2
    assert len(attach_media(tasks(), links, {"days": 200}, today=date(2026, 10, 5))[0]["media"]) == 3


TASK = {"key": "rating:fla", "brand": "FLA", "function": "Brand Reputation Protection", "priority": "High", "title": "Improve review rating for FLA",
        "why": "Average rating is 3.50.", "actions": ["Read the 1 and 2 star reviews"],
        "media": [{"title": "Borrowers [say] refunds | slow", "source": "Finance Daily", "date": "2026-10-01", "url": "https://news.example.com/a b",
                   "summary": "Customers {waited} over a month."}, {"title": "Second", "source": "S", "date": "2026-09-20", "url": "https://x/2", "summary": ""}]}


def test_the_ticket_text_carries_the_coverage_safely():
    d = jira.build_fields({}, "BRAND", TASK)["description"]
    assert "h3. Related media coverage" in d
    assert "* [Borrowers say refunds slow|https://news.example.com/a%20b] (Finance Daily, 2026-10-01): Customers waited over a month." in d
    assert "* [Second|https://x/2] (S, 2026-09-20)\n" in d
    assert d.index("Suggested steps") < d.index("Related media coverage") < d.index("Brand: FLA")
    plain = jira.build_fields({}, "BRAND", {k: v for k, v in TASK.items() if k != "media"})["description"]
    assert "media coverage" not in plain


def test_demo_links_are_seeded_and_matched_like_real_ones(demo_mode):
    media.seed_demo()
    items = media.list_items(True)
    assert 12 <= len(items) <= 20 and len({i["url"] for i in items}) == len(items)
    assert len([i for i in items if i["brand_id"]]) >= 10 and any(i["brand_id"] is None for i in items)
    assert [i["status"] for i in items].count("unreadable") == 1 and all(i["summary"] for i in items if i["status"] == "ok")
    refunds = next(i for i in items if "refunds" in i["title"])
    assert refunds["brand_id"] == "brand_14" and refunds["matches"][0]["why"]
    assert next(i for i in items if i["url"].endswith("/blog/new-site"))["brand_id"] == "brand_8"  # matched from its website alone


def test_starting_the_demo_seeds_the_links(monkeypatch):
    for attr in ("BRANDS_PATH", "CATEGORIES_PATH", "RESEARCH_PATH"):
        monkeypatch.setattr(base, attr, getattr(base, attr))
    media._MEM.clear()
    server.enable_demo()
    try:
        assert len(media.list_items(True)) >= 12
    finally:
        server.disable_demo()


def test_tasks_in_the_app_carry_the_coverage_and_so_do_the_ticket_and_csv(demo_mode, app_url):
    media.seed_demo()
    tasks = {t["key"]: t for t in get(app_url + "/api/tasks?days=30")["tasks"]}
    t = tasks["rating:brand_14"]
    assert len(t["media"]) == 2 and all(m["summary"] and m["url"].startswith("https://") for m in t["media"])
    assert tasks["roas_low:brand_3"]["media"] == []  # an ad problem: press coverage is not the context
    assert "Related media coverage" in urllib.request.urlopen(app_url + "/api/tasks.csv?days=30").read().decode()


def test_databases_from_before_summaries_are_upgraded(tmp_path, monkeypatch):
    path = tmp_path / "old.db"
    con = sqlite3.connect(path)
    con.executescript("create table media_items (id integer primary key autoincrement, url text not null unique, title text, source text, "
                      "published text, excerpt text, body text, brand_id text, matches text not null default '[]', status text not null default 'ok', "
                      "manual integer not null default 0, added_at text not null default current_timestamp);"
                      "insert into media_items (url, title, body, status) values ('https://a.example/1', 'T', 'Stored text that is long enough to summarise well.', 'ok');")
    con.commit()
    con.close()
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{path}")
    rows = store.media_list()
    assert rows[0]["summary"] == "" and [m["id"] for m in store.media_missing_summary()] == [rows[0]["id"]]
    assert store.media_set_summary(rows[0]["id"], "Hello") and store.media_list()[0]["summary"] == "Hello" and store.media_missing_summary() == []
    assert store.media_add({"url": "https://a.example/2", "title": "New", "summary": "Fresh summary", "matches": []})
    assert {m["url"]: m["summary"] for m in store.media_list()}["https://a.example/2"] == "Fresh summary"


def test_today_is_a_period(demo_mode, app_url):
    s = get(app_url + "/api/summary?days=1")
    assert s["days"] == 1 and len(s["brands"]) == 30
    html = urllib.request.urlopen(app_url + "/dossier?days=1").read().decode()
    assert "compared with yesterday" in html and "1 days" not in html
    assert isinstance(get(app_url + "/api/tasks?days=1")["tasks"], list)
    assert get(app_url + "/api/summary?days=0")["days"] == 1  # never less than a day
