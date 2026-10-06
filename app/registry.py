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
    with open(base.CATEGORIES_PATH) as f:
        return list(yaml.safe_load(f)["categories"])


def category_options():
    """Every configured category, plus Uncategorized when some brand is in it (for the category pickers)."""
    used = {b["category"] for b in active_brands()}
    return categories() + ([UNCATEGORIZED] if "uncategorized" in used else [])


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


# ---------- editing the list of categories ----------
CATEGORY_HEADER = ("# Loan categories (or levels). Managed from the app's Brands tab or by hand.\n"
                   "# Rename freely. Keep ids lowercase with no spaces: brands and research data refer to them.\n")


def _save_categories(cats):
    text = CATEGORY_HEADER + yaml.safe_dump({"categories": cats}, sort_keys=False, allow_unicode=True)
    tmp = f"{base.CATEGORIES_PATH}.tmp"
    with open(tmp, "w") as f:
        f.write(text)
    os.replace(tmp, base.CATEGORIES_PATH)


def _clean_label(label, others):
    label = re.sub(r"\s+", " ", label or "").strip()
    if not label:
        raise ValueError("Name is required")
    if len(label) > 40:
        raise ValueError("Keep category names to 40 characters or fewer")
    if label.lower() == "uncategorized" or label.lower() in {c["label"].lower() for c in others}:
        raise ValueError("A category with that name already exists")
    return label


def _find_category(cats, cat_id):
    for c in cats:
        if c["id"] == cat_id:
            return c
    raise ValueError(f"Unknown category: {cat_id!r}")


def add_category(label, cat_id=None):
    with _LOCK:
        cats = categories()
        label = _clean_label(label, cats)
        cid = cat_id or slug(label)
        if not ID.match(cid) or cid == "uncategorized":
            raise ValueError("Id must be 2 to 31 characters: lowercase letters, numbers, underscores, starting with a letter")
        if any(c["id"] == cid for c in cats):
            raise ValueError(f"A category with id {cid!r} already exists")
        cats.append({"id": cid, "label": label})
        _save_categories(cats)
        return cats[-1]


def rename_category(cat_id, label):
    with _LOCK:
        cats = categories()
        c = _find_category(cats, cat_id)
        c["label"] = _clean_label(label, [x for x in cats if x is not c])
        _save_categories(cats)
        return c


def move_category(cat_id, direction):
    if direction not in ("up", "down"):
        raise ValueError("Direction must be up or down")
    with _LOCK:
        cats = categories()
        i = cats.index(_find_category(cats, cat_id))
        j = i - 1 if direction == "up" else i + 1
        if 0 <= j < len(cats):
            cats[i], cats[j] = cats[j], cats[i]
            _save_categories(cats)
        return cats


def remove_category(cat_id):
    """Remove a category. Its brands fall back to Uncategorized; research data stored under it is kept."""
    with _LOCK:
        cats = categories()
        gone = _find_category(cats, cat_id)
        moved = sum(1 for b in all_brands() if b["category"] == cat_id)
        _save_categories([c for c in cats if c is not gone])
        return {"removed": gone, "brands_moved": moved}


def delete_brand(brand_id):
    """Remove a brand from the list entirely (unlike archiving, which keeps it)."""
    with _LOCK:
        brands = all_brands()
        gone = _find(brands, brand_id)
        _save([b for b in brands if b is not gone])
        return gone
