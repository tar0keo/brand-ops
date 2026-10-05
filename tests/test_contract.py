from datetime import date
from connectors.base import load_brands
from connectors.example import Connector


def rows():
    return list(Connector().fetch(date(2026, 1, 1), date(2026, 1, 3)))


def test_rows_use_known_brands():
    ids = {b["id"] for b in load_brands()}
    assert rows() and all(r.brand_id in ids for r in rows())


def test_rows_are_well_formed():
    for r in rows():
        assert isinstance(r.value, float) and r.value >= 0
        assert r.metric and r.source and isinstance(r.dimensions, dict)


def test_output_is_deterministic():
    assert rows() == rows()
