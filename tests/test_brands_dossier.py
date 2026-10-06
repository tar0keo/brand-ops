import shutil
import urllib.error
import urllib.request
from datetime import date, timedelta

import pytest

from app import demo, dossier, registry
from app.summary import build_summary
from app.tasks import generate_tasks
from connectors import base
from connectors.files import load_yaml
from connectors.trustpilot import Connector as Trustpilot
from tests.helpers import get, post

RULES = load_yaml("task_rules.yaml")


@pytest.fixture
def brands_file(tmp_path, monkeypatch):
    p = tmp_path / "brands.yaml"
    shutil.copy(base.BRANDS_PATH, p)
    monkeypatch.setattr(base, "BRANDS_PATH", p)
    return p


def test_add_brand_persists_with_category(brands_file):
    b = registry.add_brand("Zeta Co", "auto")
    assert b["id"] == "zeta_co" and b["category"] == "auto" and b["sites"] == []
    ids = [x["id"] for x in base.load_brands()]
    assert len(ids) == 8 and "fla" in ids and ids[-1] == "zeta_co"


def test_add_brand_rejects_bad_input(brands_file):
    for args, kw in [(("FLA",), {}), (("New",), {"brand_id": "Bad Id"}), (("  ",), {}), (("X Brand", "nonsense"), {})]:
        with pytest.raises(ValueError):
            registry.add_brand(*args, **kw)


def test_set_category_and_legacy_files(brands_file):
    assert registry.set_category("fla", "home")["category"] == "home"
    with pytest.raises(ValueError):
        registry.set_category("fla", "nonsense")
    brands_file.write_text("brands:\n  - {id: old, name: Old, kind: whitelabel}\n")
    assert registry.all_brands()[0]["category"] == "uncategorized"


def test_archive_hides_brand_and_restore_returns_it(brands_file):
    registry.set_active("brand_2", False)
    assert "brand_2" not in [b["id"] for b in registry.active_brands()]
    assert "brand_2" in [b["id"] for b in registry.all_brands()]
    registry.set_active("brand_2", True)
    assert "brand_2" in [b["id"] for b in registry.active_brands()]


def test_sites_are_normalized_unique_and_removable(brands_file):
    assert registry.add_site("fla", "https://www.Example.com/shop?x=1:8080")["sites"] == ["example.com"]
    with pytest.raises(ValueError):
        registry.add_site("paiio", "example.com")
    with pytest.raises(ValueError):
        registry.add_site("fla", "notadomain")
    assert registry.remove_site("fla", "www.example.com")["sites"] == []
    with pytest.raises(ValueError):
        registry.remove_site("fla", "example.com")


def test_trustpilot_uses_brand_sites_as_rules(brands_file, tmp_path, monkeypatch):
    registry.add_site("fla", "fla-example.com")
    monkeypatch.setenv("INBOX_DIR", str(tmp_path))
    f = tmp_path / "trustpilot" / "a.csv"
    f.parent.mkdir()
    f.write_text("Review ID,Review Created (UTC),Review Stars,Domain URL\nr1,2026-01-02 10:00:00,5,www.fla-example.com\n")
    cfg = {"columns": {"review_id": "Review ID", "date": "Review Created (UTC)", "stars": "Review Stars", "brand_column": "Domain URL"}, "brand_rules": []}
    rows = list(Trustpilot(cfg).fetch(date(2026, 1, 1), date(2026, 1, 3)))
    assert rows and all(r.brand_id == "fla" for r in rows)


def _demo(end=date(2026, 1, 31)):
    brands = demo.sample_brands()
    rows = demo.demo_rows(end)
    s = build_summary(rows, brands, end, 30, registry.category_list())
    return s, generate_tasks(s, RULES), dossier.daily_profit(rows, brands, end - timedelta(days=29), end)


def test_dossier_is_separated_by_category():
    s, tasks, series = _demo()
    html = dossier.render(s, tasks, series, [{"connector": "ga4", "last_success": "2026-01-31T10:00:00", "rows_loaded": 5, "last_error": None}], True)
    n = len(s["categories"])
    assert html.count("<svg") == 4 * n and html.count("Proposed actions") == n and "<script" not in html
    for c in s["categories"]:
        assert f'>{c["label"]} <span class="mut">' in html
    assert "By category" in html and "Demo data" in html


def test_dossier_single_category_and_unknown_category():
    s, tasks, series = _demo()
    a, b = registry.categories()[0], registry.categories()[1]
    html = dossier.render(s, tasks, series, [], False, category=a["id"])
    assert html.count("<svg") == 4 and a["label"] in html and b["label"] not in html and "By category" not in html
    with pytest.raises(ValueError):
        dossier.render(s, tasks, series, [], False, category="nope")


def test_dossier_escapes_names_and_handles_empty_data():
    s, tasks, series = _demo()
    s["brands"][0]["name"] = "<img src=x>"
    html = dossier.render(s, tasks, series, [], False)
    assert "<img src=x>" not in html and "&lt;img src=x&gt;" in html
    empty = {"end": "2026-01-31", "days": 30, "portfolio": s["portfolio"], "categories": [], "brands": []}
    assert "Brand operations dossier" in dossier.render(empty, [], {"days": [], "series": []}, [], False)


def test_server_brand_management_categories_and_dossier(demo_mode, app_url):
    count = lambda cat: next(c for c in get(app_url + "/api/summary?days=30")["categories"] if c["id"] == cat)["brand_count"]
    auto = registry.categories()[1]["id"]
    before = count(auto)
    code, body = post(app_url + "/api/brands", {"name": "Zeta", "category": auto})
    assert code == 200 and body["brand"]["id"] == "zeta" and count(auto) == before + 1
    assert post(app_url + "/api/brands/site", {"id": "zeta", "domain": "zeta.example.com"})[0] == 200
    code, body = post(app_url + "/api/brands", {"name": "Zeta"})
    assert code == 400 and "already exists" in body["error"]
    other = registry.categories()[2]["id"]
    assert post(app_url + "/api/brands/category", {"id": "zeta", "category": other})[0] == 200 and count(auto) == before
    post(app_url + "/api/brands/archive", {"id": "zeta", "active": False})
    assert "Zeta" not in [b["name"] for b in get(app_url + "/api/summary?days=30")["brands"]]
    assert "zeta" in [b["id"] for b in get(app_url + "/api/brands")["brands"]]
    r = urllib.request.urlopen(app_url + f"/dossier?days=30&category={auto}&download=1")
    assert "attachment" in r.headers["Content-Disposition"] and registry.categories()[1]["label"].encode() in r.read()
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(app_url + "/dossier?category=nope")
    assert e.value.code == 400
