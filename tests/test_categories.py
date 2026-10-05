import shutil
from pathlib import Path

import pytest
import yaml

from app import registry, research
from connectors import base
from tests.helpers import get, post


@pytest.fixture
def config_copy(tmp_path, monkeypatch):
    for attr, name in (("CATEGORIES_PATH", "categories.yaml"), ("RESEARCH_PATH", "research.yaml"), ("BRANDS_PATH", "brands.yaml")):
        p = tmp_path / name
        shutil.copy(getattr(base, attr), p)
        monkeypatch.setattr(base, attr, p)
    return tmp_path


def ids():
    return [c["id"] for c in registry.categories()]


def test_add_rename_and_reorder_categories(config_copy):
    assert registry.add_category("Payday loans") == {"id": "payday_loans", "label": "Payday loans"}
    assert ids()[-1] == "payday_loans"
    registry.rename_category("payday_loans", "Short-term loans")
    assert registry.categories()[-1]["label"] == "Short-term loans" and ids()[-1] == "payday_loans"  # the id never changes
    registry.move_category("payday_loans", "up")
    assert ids()[-2] == "payday_loans"
    registry.move_category("payday_loans", "down")
    registry.move_category("payday_loans", "down")  # already last: nothing happens
    assert ids()[-1] == "payday_loans"
    assert yaml.safe_load((config_copy / "categories.yaml").read_text())["categories"][-1]["id"] == "payday_loans"  # saved to the file


def test_category_input_is_checked(config_copy):
    for call in (lambda: registry.add_category("personal LOANS"), lambda: registry.add_category("Uncategorized"),
                 lambda: registry.add_category("  "), lambda: registry.add_category("x" * 41),
                 lambda: registry.add_category("Fine name", "Bad Id"), lambda: registry.add_category("Another", "auto"),
                 lambda: registry.rename_category("auto", "Home loans"), lambda: registry.rename_category("nope", "X"),
                 lambda: registry.move_category("auto", "sideways"), lambda: registry.remove_category("nope")):
        with pytest.raises(ValueError):
            call()
    assert registry.rename_category("auto", "AUTO LOANS")["label"] == "AUTO LOANS"  # renaming to its own name in another case is fine


def test_removing_a_category_moves_its_brands_to_uncategorized(config_copy):
    registry.set_category("fla", "auto")
    registry.set_category("paiio", "auto")
    out = registry.remove_category("auto")
    assert out["brands_moved"] == 2 and "auto" not in ids()
    assert {b["id"]: b["category"] for b in registry.all_brands()}["fla"] == "uncategorized"
    assert "uncategorized" in [c["id"] for c in registry.category_options()]


def test_research_questions_can_be_edited(config_copy):
    out = research.set_questions("auto", ["  Q one?  ", "q one?", "", "Q two?"])
    assert out["questions"] == ["Q one?", "Q two?"]  # blanks and repeats are dropped
    cfg = research.config()
    assert cfg["questions"]["auto"] == ["Q one?", "Q two?"] and "personal" in cfg["questions"] and "chatgpt" in cfg["engines"]
    assert research.set_questions("auto", [])["questions"] == []
    for bad in (("nope", ["x"]), ("auto", "not a list"), ("auto", [f"Q{i}?" for i in range(21)]), ("auto", ["x" * 201])):
        with pytest.raises(ValueError):
            research.set_questions(*bad)


def test_editing_categories_in_the_app_never_touches_the_real_config(demo_mode, app_url):
    real = base.CONFIG / "categories.yaml"
    before = real.read_bytes()
    assert base.CATEGORIES_PATH != real  # demo mode works on its own copy
    code, body = post(app_url + "/api/categories/add", {"label": "Payday loans"})
    assert code == 200 and body["categories"][-2]["id"] == "payday_loans"
    s = get(app_url + "/api/summary?days=30")
    assert "payday_loans" in [c["id"] for c in s["category_options"]] and "payday_loans" not in [c["id"] for c in s["categories"]]  # selectable before it has brands
    assert post(app_url + "/api/brands/category", {"id": "brand_1", "category": "payday_loans"})[0] == 200
    assert "payday_loans" in [c["id"] for c in get(app_url + "/api/summary?days=30")["categories"]]
    r = get(app_url + "/api/research?days=30")
    assert "payday_loans" in [c["id"] for c in r["categories"]]  # researchable straight away
    code, body = post(app_url + "/api/research/questions", {"category": "payday_loans", "questions": ["What are the 10 best payday loan sites?"]})
    assert code == 200 and body["questions"] == ["What are the 10 best payday loan sites?"]
    detail = get(app_url + "/api/research?days=30&category=payday_loans")["detail"]
    assert [(q["question"], q["configured"]) for q in detail["questions"]] == [("What are the 10 best payday loan sites?", True)]
    assert post(app_url + "/api/categories/rename", {"id": "payday_loans", "label": "Short-term loans"})[0] == 200
    assert post(app_url + "/api/categories/move", {"id": "payday_loans", "direction": "up"})[0] == 200
    code, body = post(app_url + "/api/categories/remove", {"id": "payday_loans"})
    assert code == 200 and body["brands_moved"] == 1
    brand = next(b for b in get(app_url + "/api/summary?days=30")["brands"] if b["id"] == "brand_1")
    assert brand["category"] == "uncategorized"
    assert post(app_url + "/api/categories/add", {"label": "Home loans"})[0] == 400
    assert post(app_url + "/api/research/questions", {"category": "nope", "questions": []})[0] == 400
    assert real.read_bytes() == before  # your real categories file was never written
