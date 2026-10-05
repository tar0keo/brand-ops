import os
import re
import threading

import yaml

from connectors import base
from connectors.files import load_yaml

ID = re.compile(r"^[a-z][a-z0-9_]{1,30}$")
DOMAIN = re.compile(r"^(?:[a-z0-9](?:[a-z0-9-]*[a-z0-9])?\.)+[a-z]{2,}$")
UNCATEGORIZED = {"id": "uncategorized", "label": "Uncategorized"}
HEADER = "# Managed from the app's Brands view or by hand. Archive brands instead of deleting them: their data is kept.\n"
_LOCK = threading.Lock()


def categories():
    return list(load_yaml("categories.yaml")["categories"])


def category_list():
    return categories() + [UNCATEGORIZED]


def _norm(b, valid):
    cat = b.get("category")
    return {"id": b["id"], "name": b["name"], "category": cat if cat in valid else "uncategorized",
            "active": b.get("active", True), "sites": list(b.get("sites") or [])}


def all_brands():
    valid = {c["id"] for c in category_list()}
    return [_norm(b, valid) for b in base.load_brands()]


def active_brands():
    return [b for b in all_brands() if b["active"]]


def _save(brands):
    text = HEADER + yaml.safe_dump({"brands": brands}, sort_keys=False, allow_unicode=True)
    tmp = f"{base.BRANDS_PATH}.tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, base.BRANDS_PATH)


def _find(brands, brand_id):
    for b in brands:
        if b["id"] == brand_id:
            return b
    raise ValueError(f"Unknown brand: {brand_id!r}")


def _check_category(category):
    if category not in {c["id"] for c in category_list()}:
        raise ValueError(f"Unknown category: {category!r}")


def slug(name):
    return re.sub(r"[^a-z0-9]+", "_", name.lower()).strip("_")


def normalize_domain(raw):
    d = re.sub(r"^[a-z][a-z0-9+.-]*://", "", raw.strip().lower())
    d = re.split(r"[/?#:]", d)[0]
    if d.startswith("www."):
        d = d[4:]
    if not DOMAIN.match(d):
        raise ValueError(f"Not a valid domain: {raw!r}")
    return d


def add_brand(name, category="uncategorized", brand_id=None):
    name = (name or "").strip()
    if not name:
        raise ValueError("Name is required")
    _check_category(category)
    bid = brand_id or slug(name)
    if not ID.match(bid):
        raise ValueError("Id must be 2 to 31 characters: lowercase letters, numbers, underscores, starting with a letter")
    with _LOCK:
        brands = all_brands()
        if any(b["id"] == bid for b in brands):
            raise ValueError(f"A brand with id {bid!r} already exists")
        if any(b["name"].lower() == name.lower() for b in brands):
            raise ValueError("A brand with that name already exists")
        brands.append({"id": bid, "name": name, "category": category, "active": True, "sites": []})
        _save(brands)
        return brands[-1]


def set_category(brand_id, category):
    _check_category(category)
    with _LOCK:
        brands = all_brands()
        b = _find(brands, brand_id)
        b["category"] = category
        _save(brands)
        return b


def set_active(brand_id, active):
    with _LOCK:
        brands = all_brands()
        b = _find(brands, brand_id)
        b["active"] = bool(active)
        _save(brands)
        return b


def add_site(brand_id, domain):
    d = normalize_domain(domain)
    with _LOCK:
        brands = all_brands()
        b = _find(brands, brand_id)
        owner = next((x["name"] for x in brands if d in x["sites"]), None)
        if owner:
            raise ValueError(f"{d} already belongs to {owner}")
        b["sites"].append(d)
        _save(brands)
        return b


def remove_site(brand_id, domain):
    d = normalize_domain(domain)
    with _LOCK:
        brands = all_brands()
        b = _find(brands, brand_id)
        if d not in b["sites"]:
            raise ValueError(f"{d} is not a site of {b['name']}")
        b["sites"].remove(d)
        _save(brands)
        return b
