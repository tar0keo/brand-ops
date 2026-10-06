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


def test_trend_view_is_present():
    assert "Trends over time" in PAGE and "/api/research/trend" in PAGE and 'id="trange"' in PAGE


def test_header_is_not_duplicated_and_ids_are_unique():
    import re
    top = PAGE.split("<script>")[0]
    assert top.count("<h1>") == 1 and top.count('id="sub"') == 1
    ids = re.findall(r'id="([^"]+)"', top)
    assert len(ids) == len(set(ids))


def test_brand_delete_button_asks_twice_and_shows_the_impact():
    assert 'data-act="delete"' in PAGE and "/api/brands/impact" in PAGE and "/api/brands/delete" in PAGE


def test_brands_can_be_picked_by_typing():
    assert 'list="mbrands"' in PAGE and "<datalist" in PAGE and "Re-check automatic matches" in PAGE


def test_period_has_today_and_tasks_show_their_coverage():
    assert '<option value="1">Today</option>' in PAGE and "Related coverage that goes into the ticket" in PAGE and "summaries written" in PAGE
