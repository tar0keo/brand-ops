"""Media releases: save links to articles or posts and match each one to a brand."""
import html
import ipaddress
import re
import socket
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from datetime import date, datetime, timezone
from html.parser import HTMLParser
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

from app import registry
from connectors import store

MAX_URLS, MAX_BYTES, TIMEOUT, BODY_CAP, AUTO_MIN = 20, 1_500_000, 8, 30_000, 2
TRACKING = ("utm_", "fbclid", "gclid", "mc_cid", "mc_eid")


# ---------- links ----------
def normalize_url(u):
    p = urlparse(u.strip())
    q = [(k, v) for k, v in parse_qsl(p.query, keep_blank_values=True) if not k.lower().startswith(TRACKING)]
    return urlunparse((p.scheme.lower(), p.netloc.lower(), p.path.rstrip("/"), "", urlencode(q), ""))


def extract_urls(text):
    """Pull links out of pasted text. Returns (urls, number skipped beyond the per-paste limit)."""
    seen, out = set(), []
    for token in re.split(r"\s+", text or ""):
        t = token.strip("<>()[]\"'").rstrip(".,;:!?")
        if not t:
            continue
        if not re.match(r"https?://", t, re.I):
            if not re.match(r"^[\w-]+(\.[\w-]+)*\.[a-z]{2,}(/\S*)?$", t, re.I):
                continue
            t = "https://" + t
        key = normalize_url(t)
        if key not in seen:
            seen.add(key)
            out.append(t)
    return out[:MAX_URLS], max(0, len(out) - MAX_URLS)


def _resolve(host):
    return sorted({ai[4][0].split("%")[0] for ai in socket.getaddrinfo(host, None)})


def check_url(url):
    """Refuse anything that is not an ordinary public web address (this app runs on your own computer)."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise ValueError("Only http and https links are supported")
    if p.username or p.password:
        raise ValueError("Links with a login in them are not allowed")
    if p.port not in (None, 80, 443):
        raise ValueError("That port is not allowed")
    host = p.hostname.lower()
    if host == "localhost" or host.endswith((".localhost", ".local", ".internal")):
        raise ValueError("That address is on a private network and can't be fetched")
    try:
        addrs = [ipaddress.ip_address(p.hostname)]
    except ValueError:
        addrs = [ipaddress.ip_address(a) for a in _resolve(p.hostname)]  # a DNS failure raises OSError
    for a in addrs:
        a = getattr(a, "ipv4_mapped", None) or a
        if not a.is_global:
            raise ValueError("That address is on a private network and can't be fetched")


class _Redirect(urllib.request.HTTPRedirectHandler):
    max_redirections = 5

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        check_url(newurl)  # every hop is checked, not just the first
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_html(url):
    check_url(url)
    req = urllib.request.Request(url, headers={"User-Agent": "Mozilla/5.0 (compatible; BrandOps/1.0)",
                                               "Accept": "text/html,application/xhtml+xml"})
    with urllib.request.build_opener(_Redirect).open(req, timeout=TIMEOUT) as r:
        ctype = r.headers.get("Content-Type", "").lower()
        if "html" not in ctype and "xml" not in ctype:
            return None, r.geturl()
        raw, charset = r.read(MAX_BYTES), r.headers.get_content_charset() or "utf-8"
        final = r.geturl()
    try:
        return raw.decode(charset, errors="replace"), final
    except LookupError:
        return raw.decode("utf-8", errors="replace"), final


# ---------- reading a page ----------
class _Page(HTMLParser):
    SKIP = {"script", "style", "noscript", "template", "svg", "iframe", "nav", "footer"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.meta, self.title, self.h1, self.time, self.text = {}, "", "", "", []
        self._skip, self._in_title, self._in_h1, self._size = 0, False, False, 0

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag in self.SKIP:
            self._skip += 1
        elif tag == "meta":
            k = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if k and a.get("content") and k not in self.meta:
                self.meta[k] = a["content"].strip()
        elif tag == "title":
            self._in_title = True
        elif tag == "h1" and not self.h1:
            self._in_h1 = True
        elif tag == "time" and not self.time and a.get("datetime"):
            self.time = a["datetime"]

    def handle_endtag(self, tag):
        if tag in self.SKIP and self._skip:
            self._skip -= 1
        elif tag == "title":
            self._in_title = False
        elif tag == "h1":
            self._in_h1 = False

    def handle_data(self, d):
        if self._in_title:
            self.title += d
            return
        s = d.strip()
        if self._skip or not s:
            return
        if self._in_h1:
            self.h1 += " " + s
        if self._size < 60_000:
            self.text.append(s)
            self._size += len(s)


def _clean(s):
    return re.sub(r"\s+", " ", s or "").strip()


def _date(s):
    m = re.match(r"\d{4}-\d{2}-\d{2}", s or "")
    if m:
        try:
            date.fromisoformat(m.group(0))
            return m.group(0)
        except ValueError:
            pass
    return None


def title_from_url(url):
    p = urlparse(url)
    last = p.path.rstrip("/").rsplit("/", 1)[-1]
    words = re.sub(r"[-_+]+", " ", re.sub(r"\.\w{2,5}$", "", last)).strip()
    return words.title() if len(words) > 3 else (p.hostname or url)


def parse_page(html_text, url):
    p = _Page()
    try:
        p.feed(html_text)
        p.close()
    except Exception:
        pass
    m = p.meta
    host = (urlparse(url).hostname or "").removeprefix("www.")
    desc = _clean(m.get("og:description") or m.get("description") or m.get("twitter:description"))
    body = _clean(" ".join(p.text))
    return {
        "title": _clean(m.get("og:title") or m.get("twitter:title") or p.title or p.h1) or title_from_url(url),
        "source": _clean(m.get("og:site_name")) or host,
        "published": _date(m.get("article:published_time") or m.get("og:article:published_time")
                           or m.get("datepublished") or m.get("date") or m.get("pubdate") or p.time),
        "excerpt": (desc if len(desc) >= 30 else body[:200])[:240],
        "body": f"{desc} {body}".strip()[:BODY_CAP],
    }


def fetch_page(url):
    text, final = fetch_html(url)
    if text is None:
        raise RuntimeError("not a web page (for example a PDF)")
    return parse_page(text, final)


# ---------- matching ----------
def _name_re(name):
    flags = 0 if len(name) <= 3 else re.I  # very short names must match case exactly
    return re.compile(r"(?<!\w)" + re.escape(name) + r"(?!\w)", flags)


def match_brands(url, title, body, brands):
    """Score every brand against a link. Title mentions count most, then the site, the link text, and the body."""
    p = urlparse(url)
    host = (p.hostname or "").removeprefix("www.")
    path_words = re.sub(r"[-_/.+%]+", " ", p.path)
    low_body, low_url = (body or "").lower(), url.lower()
    out = []
    for b in brands:
        pat, score = _name_re(b["name"]), 0
        score += min(len(pat.findall(title or "")), 2) * 5
        score += min(len(pat.findall(body or "")), 5)
        score += 3 if pat.search(path_words) else 0
        for site in b.get("sites") or []:
            if host == site or host.endswith("." + site):
                score += 10
            elif site in low_body or site in low_url:
                score += 5
        if score:
            out.append({"brand_id": b["id"], "name": b["name"], "score": score})
    return sorted(out, key=lambda m: -m["score"])


def choose_brand(matches):
    """Assign automatically only when one brand clearly stands out; otherwise leave it for you to pick."""
    if not matches or matches[0]["score"] < AUTO_MIN:
        return None
    if len(matches) > 1 and matches[1]["score"] == matches[0]["score"]:
        return None
    return matches[0]["brand_id"]


# ---------- storage (demo mode keeps everything in memory) ----------
def _now():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class MemStore:
    def __init__(self):
        self.clear()

    def clear(self):
        self.items, self.next = [], 1

    def media_exists(self, url):
        return any(i["url"] == url for i in self.items)

    def media_add(self, item):
        if self.media_exists(item["url"]):
            return None
        row = {**item, "id": self.next, "added_at": _now()}
        self.next += 1
        self.items.append(row)
        return row["id"]

    def media_list(self):
        rows = sorted(self.items, key=lambda i: (i.get("published") or i["added_at"][:10], i["id"]), reverse=True)
        return [{k: v for k, v in r.items() if k != "body"} for r in rows]

    def media_update(self, item_id, **fields):
        for i in self.items:
            if i["id"] == item_id:
                i.update({k: v for k, v in fields.items() if k in ("brand_id", "matches", "manual")})
                return True
        return False

    def media_remove(self, item_id):
        n = len(self.items)
        self.items = [i for i in self.items if i["id"] != item_id]
        return len(self.items) < n

    def media_unassigned(self):
        return [{"id": i["id"], "url": i["url"], "title": i["title"], "body": i.get("body") or ""}
                for i in self.items if not i["manual"] and not i["brand_id"]]


_MEM = MemStore()


def _be(demo):
    return _MEM if demo else store


# ---------- actions ----------
def _reason(e):
    if isinstance(e, urllib.error.HTTPError):
        return f"HTTP {e.code}"
    if isinstance(e, urllib.error.URLError):
        return str(e.reason)[:80]
    return (str(e) or type(e).__name__)[:80]


def list_items(demo):
    return _be(demo).media_list()


def known_url(url, demo):
    be = _be(demo)
    return be.media_exists(url) or be.media_exists(normalize_url(url))


def add_links(text, demo, fetcher=None):
    fetcher = fetcher or fetch_page
    urls, skipped = extract_urls(text)
    if not urls:
        raise ValueError("No links found. Paste full web addresses, one per line.")
    be, brands = _be(demo), registry.active_brands()
    results, todo = [], []
    for u in urls:
        n = normalize_url(u)
        try:
            check_url(n)
        except ValueError as e:
            results.append({"url": u, "status": "error", "error": str(e)})
            continue
        except OSError:
            pass  # the site could not be looked up; it is saved as unreadable below
        if be.media_exists(n):
            results.append({"url": u, "status": "duplicate"})
        else:
            todo.append((u, n))

    def read(pair):
        try:
            return pair, fetcher(pair[1]), None
        except ValueError as e:
            return pair, None, ("blocked", str(e))
        except Exception as e:
            return pair, None, ("unreadable", _reason(e))

    with ThreadPoolExecutor(max_workers=4) as pool:
        fetched = list(pool.map(read, todo))
    for (u, n), page, err in fetched:
        if err and err[0] == "blocked":
            results.append({"url": u, "status": "error", "error": err[1]})
            continue
        readable = page is not None
        if not readable:
            page = {"title": title_from_url(n), "source": (urlparse(n).hostname or "").removeprefix("www."),
                    "published": None, "excerpt": "", "body": ""}
        matches = match_brands(n, page["title"], page["body"], brands)
        brand_id = choose_brand(matches)
        item_id = be.media_add({**page, "url": n, "brand_id": brand_id, "matches": matches,
                                "status": "ok" if readable else "unreadable", "manual": False})
        if item_id is None:
            results.append({"url": u, "status": "duplicate"})
        else:
            results.append({"url": u, "status": "added", "id": item_id, "read": readable,
                            "brand": next((m["name"] for m in matches if m["brand_id"] == brand_id), None),
                            "note": None if readable else err[1]})
    return {"results": results, "skipped": skipped}


def assign(item_id, brand_id, demo):
    if brand_id and brand_id not in {b["id"] for b in registry.all_brands()}:
        raise ValueError("Unknown brand")
    if not _be(demo).media_update(item_id, brand_id=brand_id, manual=True):
        raise ValueError("Unknown link")
    return {"ok": True}


def remove(item_id, demo):
    if not _be(demo).media_remove(item_id):
        raise ValueError("Unknown link")
    return {"ok": True}


def rematch(demo):
    """Check unassigned links again, for example after adding a new brand."""
    be, brands, n = _be(demo), registry.active_brands(), 0
    for it in be.media_unassigned():
        matches = match_brands(it["url"], it["title"], it["body"], brands)
        brand_id = choose_brand(matches)
        be.media_update(it["id"], matches=matches, brand_id=brand_id)
        n += bool(brand_id)
    return {"updated": n}
