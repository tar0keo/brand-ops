import urllib.error
from pathlib import Path

import pytest

from app import media, registry, server
from connectors import store
from tests.helpers import get, post

PAGE = """<html><head><title>Fallback title</title>
<meta property="og:title" content="Brand 7 launches a new loan">
<meta property="og:site_name" content="Finance Daily">
<meta property="og:description" content="Brand 7 announced a new lending product for small businesses today.">
<meta property="article:published_time" content="2026-09-30T08:00:00Z">
<style>.x{}</style><script>var Brand99 = 1;</script></head>
<body><nav>Brand 3 menu</nav><h1>Brand 7 launches a new loan</h1>
<p>Brand 7 said it will start next month. Brand 70 is a different company.</p></body></html>"""
BRANDS = [{"id": "brand_7", "name": "Brand 7", "sites": ["brand7.example.com"]},
          {"id": "brand_70", "name": "Brand 70", "sites": []}, {"id": "fla", "name": "FLA", "sites": []}]


@pytest.fixture(autouse=True)
def clean_memory(monkeypatch):
    media._MEM.clear()
    monkeypatch.setattr(media, "_resolve", lambda host: ["93.184.216.34"])  # no real DNS in tests
    yield
    media._MEM.clear()


def fake_fetch(url):
    if "forbidden" in url:
        raise urllib.error.HTTPError(url, 403, "Forbidden", {}, None)
    if "private" in url:
        raise ValueError("That address is on a private network and can't be fetched")
    return media.parse_page(PAGE, url)


def test_parse_page_reads_title_site_date_and_visible_text_only():
    p = media.parse_page(PAGE, "https://www.financedaily.example/a")
    assert p["title"] == "Brand 7 launches a new loan" and p["source"] == "Finance Daily" and p["published"] == "2026-09-30"
    assert p["excerpt"].startswith("Brand 7 announced") and "Brand 70 is a different" in p["body"]
    assert "Brand 3" not in p["body"] and "Brand99" not in p["body"]  # navigation and scripts are skipped
    bare = media.parse_page("<p>hello</p>", "https://x.example/some-big-news")
    assert bare["title"] == "Some Big News" and bare["published"] is None


def test_matching_uses_whole_names_and_clear_winners_only():
    m = media.match_brands("https://n.example/a", "Brand 7 grows", "Brand 70 grew too. Brand 70 again.", BRANDS)
    assert [x["brand_id"] for x in m] == ["brand_7", "brand_70"]  # "Brand 7" is not found inside "Brand 70"
    assert media.choose_brand(m) == "brand_7"
    tie = media.match_brands("https://n.example/a", "", "Brand 7 and Brand 7. Brand 70 and Brand 70.", BRANDS)
    assert media.choose_brand(tie) is None  # two equally strong matches are left for you
    weak = media.match_brands("https://n.example/a", "", "once Brand 7 only", BRANDS)
    assert weak and media.choose_brand(weak) is None  # a single passing mention is only a suggestion
    assert media.match_brands("https://n.example/a", "", "fla and inflation", BRANDS) == []  # short names are case-exact
    assert media.match_brands("https://n.example/a", "", "FLA said", BRANDS)[0]["brand_id"] == "fla"


def test_matching_uses_the_link_and_brand_sites():
    on_site = media.match_brands("https://www.brand7.example.com/news/x", "", "", BRANDS)
    assert media.choose_brand(on_site) == "brand_7"
    in_path = media.match_brands("https://news.example/brand-7-launches", "", "", BRANDS)
    assert media.choose_brand(in_path) == "brand_7"


def test_extract_and_normalize_urls():
    urls, skipped = media.extract_urls("See https://a.example/x?utm_source=z#top, and https://a.example/x/. Also b.example/news i.e. nothing")
    assert urls == ["https://a.example/x?utm_source=z#top", "https://b.example/news"] and skipped == 0
    assert media.normalize_url("HTTPS://A.Example/x/?utm_source=z&id=5#top") == "https://a.example/x?id=5"
    many = " ".join(f"https://s{i}.example/p" for i in range(25))
    got, skipped = media.extract_urls(many)
    assert len(got) == 20 and skipped == 5


@pytest.mark.parametrize("url", ["http://127.0.0.1/x", "http://localhost/x", "http://[::1]/x", "http://169.254.169.254/latest",
                                 "http://10.1.2.3/", "ftp://example.com/f", "file:///etc/passwd", "http://u:p@example.com/",
                                 "http://example.com:22/"])
def test_unsafe_links_are_refused(url):
    with pytest.raises(ValueError):
        media.check_url(url)


def test_public_names_pass_but_names_resolving_to_private_addresses_do_not(monkeypatch):
    media.check_url("https://news.example.com/a")
    monkeypatch.setattr(media, "_resolve", lambda host: ["10.0.0.5"])
    with pytest.raises(ValueError):
        media.check_url("https://sneaky.example.com/a")


def test_add_links_matches_dedupes_and_keeps_unreadable_links(demo_mode):
    text = ("https://news.example.com/a?utm_source=x\nhttps://news.example.com/a\nhttps://forbidden.example.org/brand-12-story\n"
            "https://private.example.org/x\nhttp://127.0.0.1/admin")
    res = media.add_links(text, True, fake_fetch)["results"]
    by = {r["url"]: r for r in res}
    ok = by["https://news.example.com/a?utm_source=x"]
    assert ok["status"] == "added" and ok["brand"] == "Brand 7" and ok["read"] is True
    unread = by["https://forbidden.example.org/brand-12-story"]
    assert unread["status"] == "added" and unread["read"] is False and unread["brand"] == "Brand 12" and unread["note"] == "HTTP 403"
    assert by["https://private.example.org/x"]["status"] == "error" and by["http://127.0.0.1/admin"]["status"] == "error"
    assert media.add_links("https://news.example.com/a", True, fake_fetch)["results"][0]["status"] == "duplicate"
    assert len(media.list_items(True)) == 2
    with pytest.raises(ValueError):
        media.add_links("no links here", True, fake_fetch)


def test_assign_remove_and_rematch_after_adding_a_brand(demo_mode):
    page = dict(title="Zeta Labs news", source="x", published=None, excerpt="", body="Zeta Labs and Zeta Labs again.")
    media.add_links("https://news.example.com/zeta", True, lambda u: page)
    item = media.list_items(True)[0]
    assert item["brand_id"] is None  # Zeta Labs is not a brand yet
    registry.add_brand("Zeta Labs", "auto")
    assert media.rematch(True) == {"updated": 1} and media.list_items(True)[0]["brand_id"] == "zeta_labs"
    media.assign(item["id"], "brand_5", True)
    assert media.list_items(True)[0]["brand_id"] == "brand_5" and media.list_items(True)[0]["manual"] is True
    media.assign(item["id"], None, True)
    assert media.rematch(True) == {"updated": 0} and media.list_items(True)[0]["brand_id"] is None  # your choice is kept
    with pytest.raises(ValueError):
        media.assign(item["id"], "nope", True)
    media.remove(item["id"], True)
    with pytest.raises(ValueError):
        media.remove(item["id"], True)


def test_media_endpoints_in_the_app(demo_mode, app_url, monkeypatch):
    monkeypatch.setattr(media, "fetch_page", fake_fetch)
    code, body = post(app_url + "/api/media/add", {"text": "https://news.example.com/a"})
    assert code == 200 and body["results"][0]["brand"] == "Brand 7"
    r = get(app_url + "/api/media")
    assert len(r["items"]) == 1 and r["items"][0]["brand_id"] == "brand_7" and any(b["id"] == "brand_7" for b in r["brands"])
    item_id = r["items"][0]["id"]
    assert post(app_url + "/api/media/assign", {"id": item_id, "brand_id": "brand_12"})[0] == 200
    assert get(app_url + "/api/media")["items"][0]["manual"] is True
    assert post(app_url + "/api/media/assign", {"id": item_id, "brand_id": "nope"})[0] == 400
    assert post(app_url + "/api/media/add", {"text": "hello"})[0] == 400
    assert post(app_url + "/api/media/remove", {"id": item_id})[0] == 200 and get(app_url + "/api/media")["items"] == []


def test_open_link_and_exports_are_desktop_only(demo_mode, app_url, monkeypatch, tmp_path):
    monkeypatch.setattr(media, "fetch_page", fake_fetch)
    post(app_url + "/api/media/add", {"text": "https://news.example.com/a"})
    assert post(app_url + "/api/open-url", {"url": "https://news.example.com/a"})[0] == 400
    assert post(app_url + "/api/export", {"kind": "dossier"})[0] == 400
    monkeypatch.setenv("BRANDOPS_DESKTOP", "1")
    monkeypatch.setenv("BRANDOPS_HOME", str(tmp_path))
    opened_urls, opened_files = [], []
    monkeypatch.setattr(server.webbrowser, "open", lambda u: opened_urls.append(u))
    monkeypatch.setattr(server, "open_path", lambda p: opened_files.append(str(p)))
    assert post(app_url + "/api/open-url", {"url": "https://news.example.com/a"})[0] == 200 and opened_urls == ["https://news.example.com/a"]
    assert post(app_url + "/api/open-url", {"url": "https://evil.example/"})[0] == 400  # only saved links can be opened
    cat = registry.categories()[0]["id"]
    code, body = post(app_url + "/api/export", {"kind": "dossier", "days": 30, "category": cat})
    assert code == 200 and Path(body["path"]).parent == tmp_path / "exports" and opened_files[-1] == body["path"]
    assert "Brand operations dossier" in Path(body["path"]).read_text(encoding="utf-8")
    code, body = post(app_url + "/api/export", {"kind": "tasks", "days": 30})
    assert code == 200 and Path(body["path"]).read_text(encoding="utf-8").startswith("Summary,")
    assert post(app_url + "/api/export", {"kind": "dossier", "category": "../x"})[0] == 400
    assert post(app_url + "/api/export", {"kind": "zip"})[0] == 400


def test_media_storage_in_the_local_database(tmp_path, monkeypatch):
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'm.db'}")
    item = {"url": "https://a.example/x", "title": "T", "source": "a.example", "published": "2026-01-02", "excerpt": "e",
            "body": "Zeta body", "brand_id": None, "matches": [{"brand_id": "z", "name": "Zeta", "score": 1}], "status": "ok", "manual": False}
    first = store.media_add(item)
    assert first and store.media_add(item) is None and store.media_exists("https://a.example/x")
    row = store.media_list()[0]
    assert row["matches"][0]["name"] == "Zeta" and row["brand_id"] is None and row["manual"] is False and "body" not in row
    assert store.media_unassigned()[0]["body"] == "Zeta body"
    assert store.media_update(first, brand_id="z", manual=True) and store.media_unassigned() == []
    assert store.media_list()[0]["brand_id"] == "z"
    assert store.media_remove(first) and not store.media_remove(first) and store.media_list() == []


def test_real_fetching_follows_redirects_checks_every_hop_and_skips_non_pages(monkeypatch):
    import threading
    from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

    class H(BaseHTTPRequestHandler):
        def log_message(self, *a):
            pass

        def do_GET(self):
            if self.path == "/redir":
                self.send_response(302); self.send_header("Location", "/page"); self.end_headers(); return
            if self.path == "/redir-bad":
                self.send_response(302); self.send_header("Location", "/blocked"); self.end_headers(); return
            ctype, body = ("application/pdf", b"%PDF") if self.path == "/pdf" else ("text/html; charset=utf-8", PAGE.encode())
            self.send_response(200); self.send_header("Content-Type", ctype); self.end_headers(); self.wfile.write(body)

    srv = ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    base = f"http://127.0.0.1:{srv.server_address[1]}"
    seen = []

    def recorder(url):  # stands in for the public-address check, which would (rightly) refuse 127.0.0.1
        seen.append(url)
        if "/blocked" in url:
            raise ValueError("That address is on a private network and can't be fetched")

    monkeypatch.setattr(media, "check_url", recorder)
    try:
        page = media.fetch_page(base + "/redir")
        assert page["title"] == "Brand 7 launches a new loan" and seen == [base + "/redir", base + "/page"]
        with pytest.raises(ValueError):
            media.fetch_page(base + "/redir-bad")
        with pytest.raises(RuntimeError):
            media.fetch_page(base + "/pdf")
    finally:
        srv.shutdown()
