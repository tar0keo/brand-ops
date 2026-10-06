"""Turn an engine's answer into the ranked list of companies the app imports."""
import re
from urllib.parse import urlparse

LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")
BOLD = re.compile(r"\*\*([^*]+)\*\*|__([^_]+)__")
NUMBERED = re.compile(r"^\s*(?:#{1,6}\s*)?(?:\*\*)?(\d{1,2})[.)](?:\*\*)?\s+(\S.*)$")
BULLET = re.compile(r"^ ?[-*\u2022]\s+(\S.*)$")
CUT = re.compile(r"\s+[-\u2013\u2014|]\s+|:\s|\s\(|,\s|;\s|\.\s")
SMALL = {"of", "and", "the", "for", "&", "a", "an", "to", "in", "on"}
VERBS = {"compare", "check", "apply", "gather", "choose", "review", "consider", "look", "get", "use", "make", "find", "pay",
         "know", "understand", "read", "ask", "shop", "research", "calculate", "decide", "determine", "avoid", "start",
         "improve", "build", "set", "submit", "wait", "keep", "try", "visit", "contact", "prepare", "pick", "select"}
MIN_COMPANIES, MIN_SHARE = 3, 0.6


def _candidate(rest):
    url, m, b = None, LINK.search(rest), BOLD.search(rest)
    if m:
        url = m.group(2)
    if b:
        name = b.group(1) or b.group(2)
    elif m and rest.lstrip().startswith("["):
        name = m.group(1)
    else:
        name = rest
    name = LINK.sub(lambda x: x.group(1), name)
    name = re.sub(r"[*_`#\u00ae\u2122]+", "", name)
    name = CUT.split(name, maxsplit=1)[0]
    return name.strip(" .:\"'-\u2013\u2014"), url


def _acceptable(name):
    words = name.split()
    if not words or len(name) > 50 or len(words) > 7 or words[0].lower() in VERBS:
        return False
    if not (any(c.isupper() for c in words[0]) or words[0][0].isdigit()):
        return False
    big = [w for w in words if w[0].isupper() or w[0].isdigit() or w.lower() in SMALL]
    return len(big) >= (len(words) + 1) // 2


def _blocks(text):
    """Groups of list items. A numbered list starts a new group each time the numbering restarts."""
    numbered, cur, last = [], [], 0
    for line in text.splitlines():
        m = NUMBERED.match(line)
        if m:
            n = int(m.group(1))
            if cur and n <= last:
                numbered.append(cur)
                cur = []
            cur.append(m.group(2))
            last = n
    if cur:
        numbered.append(cur)
    if numbered:
        return numbered
    bullets, cur = [], []
    for line in text.splitlines():
        m = BULLET.match(line)
        if m:
            cur.append(m.group(1))
        elif line.strip() and not line.startswith((" ", "\t")) and cur:
            bullets.append(cur)
            cur = []
    if cur:
        bullets.append(cur)
    return bullets


def _label(host):
    return re.sub(r"[^a-z0-9]", "", (host or "").removeprefix("www.").split(".")[0].lower())


def link_citations(results, citations):
    """Give a company a web address when a cited source clearly belongs to it (best effort)."""
    for it in results:
        if it["url"]:
            continue
        key = re.sub(r"[^a-z0-9]", "", it["name"].lower())
        if len(key) < 4:
            continue
        for c in citations:
            h = _label(urlparse(c["url"]).hostname)
            if h and (key == h or (len(key) >= 4 and h.startswith(key)) or (len(h) >= 5 and key.startswith(h))):
                it["url"] = c["url"]
                break


def extract_companies(text, citations=(), limit=15):
    """Returns {results, ok, reason, seen}. ok is False when the list looks wrong and a person should check it."""
    best, seen = [], 0
    for block in _blocks(text):
        accepted, names = [], set()
        for rest in block:
            name, url = _candidate(rest)
            if _acceptable(name) and name.lower() not in names:
                names.add(name.lower())
                accepted.append({"name": name, "url": url})
        if len(accepted) > len(best):
            best, seen = accepted, len(block)
    results = [{"rank": i + 1, "name": c["name"], "url": c["url"]} for i, c in enumerate(best[:limit])]
    link_citations(results, list(citations))
    if len(best) < MIN_COMPANIES:
        reason = f"Found only {len(best)} company names in the answer"
    elif len(best) / max(seen, 1) < MIN_SHARE:
        reason = f"Only {len(best)} of {seen} list items looked like company names"
    else:
        reason = None
    return {"results": results, "ok": reason is None, "reason": reason, "seen": seen}
