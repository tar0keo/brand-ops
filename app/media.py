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

from app import demo, registry
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
        self.meta, self.title, self.h1, self.time, self.text, self.hosts = {}, "", "", "", [], []
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
        elif tag == "a" and not self._skip and a.get("href", "").startswith(("http://", "https://")):
            try:
                h = (urlparse(a["href"]).hostname or "").lower().removeprefix("www.")
            except ValueError:
                h = ""
            if h and h not in self.hosts and len(self.hosts) < 100:
                self.hosts.append(h)

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
    links = [h for h in p.hosts if h != host and not h.endswith("." + host)]
    return {
        "title": _clean(m.get("og:title") or m.get("twitter:title") or p.title or p.h1) or title_from_url(url),
        "source": _clean(m.get("og:site_name")) or host,
        "published": _date(m.get("article:published_time") or m.get("og:article:published_time")
                           or m.get("datepublished") or m.get("date") or m.get("pubdate") or p.time),
        "excerpt": (desc if len(desc) >= 30 else body[:200])[:240],
        "body": f"{desc} {body}".strip()[:BODY_CAP] + (LINKS_MARK + " ".join(links) if links else ""),
    }


def fetch_page(url):
    text, final = fetch_html(url)
    if text is None:
        raise RuntimeError("not a web page (for example a PDF)")
    return parse_page(text, final)


# ---------- matching ----------
LINKS_MARK = "\n\n[links] "  # parse_page lists the sites an article links to after this marker
_WORD = re.compile(r"[^\W\d_]+|\d+")
_CAMEL = re.compile(r"[A-Z]+(?![a-z])|[A-Z]?[a-z]+")
AFTER = {"loans", "loan", "lending", "lender", "finance", "financial", "credit", "bank", "capital", "funding", "mortgage",
         "mortgages", "cash", "money", "online", "group", "inc", "llc", "co", "usa", "us", "official", "app", "hq"}
BEFORE = {"get", "my", "the", "try", "join", "go", "use", "with", "visit", "apply", "hello"}
SECOND_LEVEL = {"co", "com", "org", "net", "gov", "edu", "ac"}


def tokens(text):
    """Words and numbers, however they are joined: Brand30, brand-30, Brand 30, and BrandThirty all split the same way."""
    out = []
    for w in _WORD.findall(text or ""):
        out += _CAMEL.findall(w) if w.isascii() and w.isalpha() else [w]
    return out


def compact(name):
    return re.sub(r"[^a-z0-9]", "", name.lower())


def _exact_case(name):
    return len(compact(name)) <= 3 and bool(re.fullmatch(r"[A-Za-z ]+", name.strip()))  # very short names must match capitals exactly


def _count(text_tokens, name_tokens, exact):
    seq = text_tokens if exact else [t.lower() for t in text_tokens]
    pat = name_tokens if exact else [t.lower() for t in name_tokens]
    n, i, m = 0, 0, len(pat)
    while m and i <= len(seq) - m:
        if seq[i:i + m] == pat:
            n, i = n + 1, i + m
        else:
            i += 1
    return n


def mentions(text, name):
    """Whether a name appears in some text, ignoring how its words are spaced, hyphenated, or capitalised."""
    toks = tokens(name)
    return bool(toks) and _count(tokens(text), toks, _exact_case(name)) > 0


def _labels(host):
    parts = [p for p in (host or "").lower().removeprefix("www.").split(".") if p]
    if len(parts) >= 3 and parts[-2] in SECOND_LEVEL and len(parts[-1]) == 2:
        return parts[:-2]
    return parts[:-1] if len(parts) >= 2 else parts


def label_score(host, brand):
    """How well a website's name fits a brand: brand30.com for Brand 30, getbrand30.com, brand-30.net, brand30loans.com."""
    key, ntoks = compact(brand["name"]), [t.lower() for t in tokens(brand["name"])]
    best = 0
    for lab in _labels(host):
        if len(key) >= 3 and lab == key:
            best = max(best, 10)
        elif len(key) >= 4 and ((lab.startswith(key) and lab[len(key):] in AFTER) or (lab.endswith(key) and lab[:-len(key)] in BEFORE)):
            best = max(best, 6)
        elif len(key) >= 4 and _count([t.lower() for t in tokens(lab)], ntoks, False):
            best = max(best, 8)
    return best


def match_brands(url, title, body, brands):
    """Score every brand against a link. Returns matches best first, each with the reasons it matched."""
    p = urlparse(url)
    host = (p.hostname or "").removeprefix("www.")
    text, _, hosts = (body or "").partition(LINKS_MARK)
    t_title, t_text, t_path = tokens(title or ""), tokens(text), tokens(p.path)
    link_hosts, low_text, low_url = hosts.split(), text.lower(), url.lower()
    out = []
    for b in brands:
        ntoks = tokens(b["name"])
        if not ntoks:
            continue
        exact, score, why = _exact_case(b["name"]), 0, []
        c = _count(t_title, ntoks, exact)
        if c:
            score += min(c, 2) * 5
            why.append("name in the headline")
        c = _count(t_text, ntoks, exact)
        if c:
            score += min(c, 5)
            why.append("name in the text")
        if _count(t_path, ntoks, exact):
            score += 3
            why.append("name in the link")
        sites = b.get("sites") or []
        reg = max([10 if host == s or host.endswith("." + s) else 5 if s in low_text or s in low_url else 0 for s in sites] + [0])
        lab = label_score(host, b)
        if max(reg, lab):
            score += max(reg, lab)
            why.append("its website address" if max(reg, lab) >= 6 else "a mention of its website")
        if any(label_score(h, b) >= 6 or any(h == s or h.endswith("." + s) for s in sites) for h in link_hosts):
            score += 4
            why.append("the article links to its website")
        if score:
            out.append({"brand_id": b["id"], "name": b["name"], "score": score, "why": why})
    return sorted(out, key=lambda m: -m["score"])


def choose_brand(matches):
    """Assign automatically only when one brand clearly stands out; otherwise leave it for you to pick."""
    if not matches or matches[0]["score"] < AUTO_MIN:
        return None
    if len(matches) > 1 and matches[1]["score"] == matches[0]["score"]:
        return None
    return matches[0]["brand_id"]


# ---------- summaries ----------
STOP = {"the", "a", "an", "and", "or", "of", "to", "in", "on", "for", "with", "at", "by", "from", "is", "are", "was", "were", "be",
        "as", "that", "this", "it", "its", "has", "have", "will", "new", "after", "over", "into", "about", "says", "say"}
BOILER = re.compile(r"subscribe|sign up|cookie|all rights reserved|read more|advertisement|click here|privacy policy|terms of use|"
                    r"follow us|newsletter|share this|log in", re.I)
SENT = re.compile(r"(?<=[.!?])\s+(?=[\"'(\u201c]?[A-Z0-9$])")


def summarize(title, text, focus=(), max_sentences=3, max_chars=450):
    """A short summary built from the article's own sentences: those that echo the headline, come early, name the brand, and carry facts."""
    text = _clean((text or "").partition(LINKS_MARK)[0])
    if not text:
        return ""
    keep = [s.strip() for s in SENT.split(text)[:60] if 30 <= len(s.strip()) <= 320 and not BOILER.search(s)]
    if not keep:
        short = text[:200]
        return (short.rsplit(" ", 1)[0] if len(text) > 200 else short) if len(text) >= 20 else ""
    tkeys = {t.lower() for t in tokens(title) if t.lower() not in STOP and len(t) > 2}
    head = re.sub(r"\W+", "", (title or "").lower())[:60]
    scored = []
    for i, s in enumerate(keep[:40]):
        words = {t.lower() for t in tokens(s)}
        score = 1.0 / (1 + 0.3 * i) + 1.5 * len(tkeys & words) / max(len(tkeys), 1)
        score += 0.8 if any(mentions(s, n) for n in focus) else 0
        score += 0.3 if re.search(r"[\d$%]", s) else 0
        scored.append((score, i, s))
    chosen, seen = [], {head} if head else set()
    for _, i, s in sorted(scored, key=lambda x: -x[0]):
        key = re.sub(r"\W+", "", s.lower())[:60]
        if key not in seen:
            seen.add(key)
            chosen.append((i, s))
        if len(chosen) == max_sentences:
            break
    summary = " ".join(s for _, s in sorted(chosen))
    if len(summary) > max_chars:
        summary = summary[:max_chars].rsplit(" ", 1)[0].rstrip(",;:") + "..."
    return summary


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

    def media_count_brand(self, brand_id):
        return sum(1 for i in self.items if i.get("brand_id") == brand_id)

    def media_release_brand(self, brand_id):
        n = 0
        for i in self.items:
            if i.get("brand_id") == brand_id:
                i["brand_id"], i["manual"] = None, False
                n += 1
        return n

    def media_automatic(self):
        return [{"id": i["id"], "url": i["url"], "title": i["title"], "body": i.get("body") or "", "brand_id": i.get("brand_id")}
                for i in self.items if not i["manual"]]

    def media_missing_summary(self):
        return [{"id": i["id"], "title": i["title"], "body": i.get("body") or "", "brand_id": i.get("brand_id")}
                for i in self.items if not i.get("summary") and i.get("status") == "ok" and i.get("body")]

    def media_set_summary(self, item_id, summary):
        for i in self.items:
            if i["id"] == item_id:
                i["summary"] = summary
                return True
        return False

    def media_unassigned(self):
        return [{"id": i["id"], "url": i["url"], "title": i["title"], "body": i.get("body") or ""}
                for i in self.items if not i["manual"] and not i["brand_id"]]


_MEM = MemStore()


def seed_demo(today=None):
    """Fill the demo's in-memory list with sample coverage, matched the same way real links are."""
    today, brands = today or date.today(), registry.active_brands()
    _MEM.clear()
    for it in demo.demo_links(today, brands):
        matches = match_brands(it["url"], it["title"], it["body"], brands)
        _MEM.media_add({**it, "brand_id": choose_brand(matches), "matches": matches, "manual": False})


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
        summary = summarize(page["title"], page["body"], focus=[m["name"] for m in matches[:1]]) if readable else ""
        item_id = be.media_add({**page, "url": n, "brand_id": brand_id, "matches": matches, "summary": summary,
                                "status": "ok" if readable else "unreadable", "manual": False})
        if item_id is None:
            results.append({"url": u, "status": "duplicate"})
        else:
            results.append({"url": u, "status": "added", "id": item_id, "read": readable,
                            "brand": next((m["name"] for m in matches if m["brand_id"] == brand_id), None),
                            "note": None if readable else err[1]})
    return {"results": results, "skipped": skipped}


def count_brand(brand_id, demo):
    return _be(demo).media_count_brand(brand_id)


def release_brand(brand_id, demo):
    return _be(demo).media_release_brand(brand_id)


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


def backfill_summaries(demo):
    """Write a summary for saved links that do not have one yet (links saved before summaries existed)."""
    be, names, n = _be(demo), {b["id"]: b["name"] for b in registry.all_brands()}, 0
    for it in be.media_missing_summary():
        s = summarize(it["title"], it["body"], focus=[names[it["brand_id"]]] if it["brand_id"] in names else [])
        if s and be.media_set_summary(it["id"], s):
            n += 1
    return n


def rematch(demo):
    """Check automatic matches again, for example after adding a brand or improving detection. Matches you set by hand are never touched.
    Links saved without a summary get one too."""
    be, brands, newly, changed = _be(demo), registry.active_brands(), 0, 0
    for it in be.media_automatic():
        matches = match_brands(it["url"], it["title"], it["body"], brands)
        brand_id = choose_brand(matches)
        if brand_id != it["brand_id"]:
            newly += it["brand_id"] is None
            changed += it["brand_id"] is not None
        be.media_update(it["id"], matches=matches, brand_id=brand_id)
    return {"updated": newly, "changed": changed, "summaries": backfill_summaries(demo)}
