from pathlib import Path

PAGE = (Path(__file__).resolve().parent.parent / "app" / "static" / "index.html").read_text(encoding="utf-8")


def test_actions_are_buttons_not_links():
    assert "<a " not in PAGE  # every action, such as Open dossier, is a button
    for label in ("Open dossier", "Download dossier", "Export CSV for Jira import", "Add links"):
        assert f">{label}</button>" in PAGE


def test_buttons_share_one_style_system():
    assert PAGE.count("\n.btn{") == 1 and ".btn.primary{" in PAGE and ".btn.danger" in PAGE
    # no plain unstyled action buttons: every <button ...> inside the page's templates carries a class
    import re
    plain = [m for m in re.findall(r"<button(?![^>]*class=)[^>]*>", PAGE) if "data-t=" not in m]
    assert plain == []


def test_media_tab_is_present():
    assert "releases: ['Media releases', null]" in PAGE and "renderMedia" in PAGE


def test_market_research_tab_is_present():
    assert "research: ['Market research', null]" in PAGE and "renderResearch" in PAGE


def test_category_editor_is_present():
    assert "Loan categories" in PAGE and "/api/categories/add" in PAGE and "Edit the questions for this category" in PAGE
