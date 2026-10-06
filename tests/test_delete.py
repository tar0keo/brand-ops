import shutil
import urllib.error
import urllib.request

import pytest

from app import media, registry
from connectors import base, store
from connectors import run as ingest
from tests.helpers import get, post


@pytest.fixture
def config_copy(tmp_path, monkeypatch):
    for attr, name in (("BRANDS_PATH", "brands.yaml"), ("CATEGORIES_PATH", "categories.yaml"), ("RESEARCH_PATH", "research.yaml")):
        p = tmp_path / name
        shutil.copy(getattr(base, attr), p)
        monkeypatch.setattr(base, attr, p)
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path / 'd.db'}")
    return tmp_path


def test_a_brand_can_be_removed_from_the_list_entirely(config_copy):
    registry.add_site("fla", "fla-example.com")
    gone = registry.delete_brand("fla")
    assert gone["id"] == "fla" and "fla" not in [b["id"] for b in registry.all_brands()]
    assert len(registry.all_brands()) == 6
    assert registry.add_site("paiio", "fla-example.com")["sites"] == ["fla-example.com"]  # its sites are free again
    with pytest.raises(ValueError):
        registry.delete_brand("fla")
    for b in [b["id"] for b in registry.all_brands()]:
        registry.delete_brand(b)
    assert registry.all_brands() == []  # even the last one can go


def test_deleting_a_brands_data_leaves_the_others(config_copy):
    ingest.run("example", 3)
    before = store.fetch_rows(__import__("datetime").date(2000, 1, 1), __import__("datetime").date(2100, 1, 1))
    mine = sum(1 for r in before if r["brand_id"] == "fla")
    assert mine > 0 and store.brand_metric_count("fla") == mine
    assert store.delete_brand_metrics("fla") == mine
    after = store.fetch_rows(__import__("datetime").date(2000, 1, 1), __import__("datetime").date(2100, 1, 1))
    assert len(after) == len(before) - mine and all(r["brand_id"] != "fla" for r in after)


def test_deleting_a_brand_releases_its_media_links_without_losing_them(config_copy):
    for n, bid in enumerate(("fla", "fla", "paiio"), 1):
        store.media_add({"url": f"https://a.example/{n}", "title": f"T{n}", "brand_id": bid, "manual": True, "matches": []})
    assert store.media_count_brand("fla") == 2
    assert store.media_release_brand("fla") == 2
    items = {i["title"]: i for i in store.media_list()}
    assert items["T1"]["brand_id"] is None and items["T1"]["manual"] is False and items["T3"]["brand_id"] == "paiio"


def test_the_app_shows_the_impact_then_deletes_brand_and_data(config_copy, app_url):
    ingest.run("example", 3)
    store.media_add({"url": "https://a.example/1", "title": "T1", "brand_id": "fla", "matches": []})
    impact = get(app_url + "/api/brands/impact?id=fla")
    assert impact["name"] == "FLA" and impact["metrics"] == store.brand_metric_count("fla") > 0 and impact["links"] == 1
    code, body = post(app_url + "/api/brands/delete", {"id": "fla"})
    assert code == 200 and body["brand"]["metrics_deleted"] == impact["metrics"] and body["brand"]["links_released"] == 1
    assert "fla" not in [b["id"] for b in get(app_url + "/api/brands")["brands"]]
    assert store.brand_metric_count("fla") == 0 and store.media_list()[0]["brand_id"] is None
    assert post(app_url + "/api/brands/delete", {"id": "fla"})[0] == 400
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(app_url + "/api/brands/impact?id=nope")
    assert e.value.code == 400


def test_deleting_in_demo_mode_never_touches_the_real_list(demo_mode, app_url, monkeypatch):
    monkeypatch.setattr(media, "fetch_page", lambda url: media.parse_page("<title>x</title>", url))
    real = (base.CONFIG / "brands.yaml").read_bytes()
    post(app_url + "/api/media/add", {"text": "https://news.example.com/brand-12-story"})
    item = get(app_url + "/api/media")["items"][0]
    assert item["brand_id"] == "brand_12"
    assert get(app_url + "/api/brands/impact?id=brand_12")["links"] == 1
    assert post(app_url + "/api/brands/delete", {"id": "brand_12"})[0] == 200
    assert "Brand 12" not in [b["name"] for b in get(app_url + "/api/summary?days=30")["brands"]]
    assert get(app_url + "/api/media")["items"][0]["brand_id"] is None
    assert (base.CONFIG / "brands.yaml").read_bytes() == real
