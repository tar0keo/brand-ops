import html
from datetime import date, datetime, timedelta

from app.summary import AD_SOURCES

E = html.escape
PALETTE = ["#1c4fd6", "#d9622b", "#17794a", "#8a4fd3", "#c4961a", "#0f8fa8", "#b8362b", "#5d6975"]


def money(v):
    if v is None:
        return "n/a"
    a = abs(v)
    s = f"{a / 1e6:.2f}M" if a >= 1e6 else f"{a / 1e3:.1f}k" if a >= 1e3 else f"{a:.0f}"
    return ("-" if v < 0 else "") + "$" + s


def ratio(v):
    return "n/a" if v is None else f"{v:.2f}"


def pct(v):
    return "n/a" if v is None else f"{v * 100:.1f}%"


def num(v):
    return "n/a" if v is None else f"{round(v):,}"


COLS = [("Profit", "profit", money, "rel", "up"), ("ROAS", "roas", ratio, "abs", "up"),
        ("Conversion", "conversion_rate", pct, "pt", "up"), ("AI citations", "citation_share", pct, "pt", "up"),
        ("Rating", "rating", ratio, "abs", "up"), ("Crawler errors", "bot_errors", num, "rel", "down")]


def delta(cur, prev, kind, good):
    if cur is None or prev is None:
        return ""
    d = cur - prev
    if kind == "rel":
        if not prev:
            return ""
        d /= abs(prev)
        txt = f"{d:+.0%}"
    elif kind == "pt":
        txt = f"{d * 100:+.1f} pt"
    else:
        txt = f"{d:+.2f}"
    sign = 0 if abs(d) < 1e-9 else (1 if d > 0 else -1) * (-1 if good == "down" else 1)
    return f'<span class="d {"fl" if sign == 0 else "up" if sign > 0 else "dn"}">{txt}</span>'


def legend(items, x0, y0, per_row=4):
    out = []
    for r in range(0, len(items), per_row):
        x, y = x0, y0 + (r // per_row) * 16
        for name, color in items[r:r + per_row]:
            out.append(f'<rect x="{x}" y="{y - 9}" width="10" height="10" fill="{color}"/>'
                       f'<text x="{x + 15}" y="{y}">{E(name)}</text>')
            x += 15 + 7 * len(name) + 20
    return "".join(out)


def _svg(w, h, title, body):
    return f'<svg viewBox="0 0 {w} {h}" role="img" aria-label="{E(title)}"><title>{E(title)}</title>{body}</svg>'


def bar_chart(title, labels, series, fmt):
    W, L, R, ROW, TOP = 760, 150, 80, 38, 30
    cols = ["#1c4fd6", "#b8c0cc"]
    vals = [v for _, vs in series for v in vs if v is not None]
    mx = max(vals) if vals and max(vals) > 0 else 1
    p = [legend([(n, cols[j]) for j, (n, _) in enumerate(series)], L, 14, per_row=2)]
    for i, lab in enumerate(labels):
        y0 = TOP + i * ROW
        p.append(f'<text x="{L - 10}" y="{y0 + ROW / 2 + 2}" text-anchor="end">{E(lab)}</text>')
        for j, (_, vs) in enumerate(series):
            v, y = vs[i], y0 + 5 + j * 14
            if v is None:
                p.append(f'<text x="{L + 6}" y="{y + 10}" fill="#5d6975">n/a</text>')
                continue
            w = (W - L - R) * v / mx
            p.append(f'<rect x="{L}" y="{y}" width="{w:.1f}" height="12" fill="{cols[j]}"/>'
                     f'<text x="{L + w + 6:.1f}" y="{y + 10}">{E(fmt(v))}</text>')
    return _svg(W, TOP + ROW * len(labels) + 6, title, "".join(p))


def line_chart(title, days, series):
    W, H, L, R, T, B = 760, 310, 60, 14, 12, 64
    vals = [v for _, vs in series for v in vs]
    lo, hi = min(0.0, min(vals)), max(vals)
    if hi <= lo:
        hi = lo + 1
    n = len(days)
    X = lambda i: L + (W - L - R) * i / max(n - 1, 1)
    Y = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))
    p = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        p.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#e3e6e3"/>'
                 f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" fill="#5d6975">{E(money(v))}</text>')
    for i in sorted({0, n // 2, n - 1}):
        p.append(f'<text x="{X(i):.1f}" y="{H - B + 18}" text-anchor="middle" fill="#5d6975">{days[i].strftime("%d %b")}</text>')
    for idx, (_, vs) in enumerate(series):
        pts = " ".join(f"{X(i):.1f},{Y(v):.1f}" for i, v in enumerate(vs))
        p.append(f'<polyline fill="none" stroke="{PALETTE[idx % len(PALETTE)]}" stroke-width="2" points="{pts}"/>')
    p.append(legend([(n_, PALETTE[i % len(PALETTE)]) for i, (n_, _) in enumerate(series)], L, H - 22))
    return _svg(W, H, title, "".join(p))


def daily_profit(rows, brands, start, end):
    """7-day rolling average of ad revenue minus ad spend, per brand."""
    days = [start + timedelta(days=i) for i in range((end - start).days + 1)]
    idx = {d: i for i, d in enumerate(days)}
    raw = {b["id"]: [0.0] * len(days) for b in brands}
    for r in rows:
        if r["brand_id"] in raw and r["source"] in AD_SOURCES and r["day"] in idx:
            if r["metric"] == "revenue":
                raw[r["brand_id"]][idx[r["day"]]] += r["value"]
            elif r["metric"] == "ad_spend":
                raw[r["brand_id"]][idx[r["day"]]] -= r["value"]
    out = []
    for b in brands:
        vs = raw[b["id"]]
        if any(vs):
            out.append((b["id"], b["name"], [sum(vs[max(0, i - 6):i + 1]) / len(vs[max(0, i - 6):i + 1]) for i in range(len(vs))]))
    return {"days": days, "series": out}


CSS = """
body{margin:0;background:#eef0ee;color:#17202a;font:15px/1.55 ui-sans-serif,system-ui,"Segoe UI",Roboto,sans-serif}
.page{max-width:880px;margin:24px auto;background:#fff;padding:40px 48px;box-shadow:0 0 0 1px #dfe3e0}
h1{font-size:26px;margin:0 0 4px;letter-spacing:-.01em}
h2{font-size:18px;margin:32px 0 8px;padding-top:12px;border-top:2px solid #17202a}
.mut{color:#5d6975;font-size:13px}.cap{color:#5d6975;font-size:13px;margin:0 0 8px}
.glance{display:grid;grid-template-columns:repeat(3,1fr);border-bottom:1px solid #dfe3e0;margin-top:16px}
.glance div{padding:12px 12px 10px 0}.glance b{display:block;font-size:26px;font-variant-numeric:tabular-nums}
table{width:100%;border-collapse:collapse;font-variant-numeric:tabular-nums;font-size:14px}
th,td{padding:7px 8px;text-align:right;border-bottom:1px solid #dfe3e0;vertical-align:top}
th:first-child,td:first-child,.t th,.t td{text-align:left}
.d{display:block;font-size:12px}.up{color:#17794a}.dn{color:#b8362b}.fl{color:#5d6975}
svg{width:100%;height:auto;display:block;margin-bottom:4px}svg text{font:12px ui-sans-serif,system-ui,sans-serif;fill:#17202a}
.banner{background:#fff4d6;border:1px solid #e3c35a;padding:6px 10px;font-size:13px;margin:12px 0}
.sec{break-inside:avoid}ul{padding-left:20px}h3{font-size:15px;margin:18px 0 6px}.cat{break-before:page}
@media print{body{background:#fff}.page{margin:0;padding:0;box-shadow:none}}
"""


def _table(brands):
    head = "<tr><th>Brand</th>" + "".join(f"<th>{c[0]}</th>" for c in COLS) + "</tr>"
    body = "".join(
        f"<tr><td>{E(b['name'])}</td>" + "".join(
            f"<td>{fmt(b['current'][k])}{delta(b['current'][k], b['previous'][k], dk, good)}</td>"
            for _, k, fmt, dk, good in COLS) + "</tr>" for b in brands)
    return f"<table><thead>{head}</thead><tbody>{body}</tbody></table>"


def _rate(m):
    return m["bot_errors"] / m["bot_hits"] if m["bot_hits"] else None


def render(summary, tasks, series, status, demo, category=None):
    end = date.fromisoformat(summary["end"])
    n = summary["days"]
    cats = [c for c in summary["categories"] if not category or c["id"] == category]
    if category and not cats:
        raise ValueError(f"Unknown category: {category!r}")
    cat_of = {c["id"]: [b for b in summary["brands"] if b["category"] == c["id"]] for c in cats}
    brands = [b for bs in cat_of.values() for b in bs]
    port = cats[0] if category else summary["portfolio"]
    scope = cats[0]["label"] if category else "All categories"
    this, prev = "This period", "Previous period"

    notes = []
    with_profit = [b for b in brands if b["current"]["profit"] is not None]
    if with_profit:
        top = max(with_profit, key=lambda b: b["current"]["profit"])
        notes.append(f"{E(top['name'])} earned the most profit ({money(top['current']['profit'])}).")
    with_roas = [b for b in brands if b["current"]["roas"] is not None]
    if with_roas:
        low = min(with_roas, key=lambda b: b["current"]["roas"])
        notes.append(f"{E(low['name'])} has the lowest ROAS ({ratio(low['current']['roas'])}).")
    ids = {b["id"] for b in brands}
    scoped = [t for t in tasks if t["brand_id"] in ids]
    highs = sum(t["priority"] == "High" for t in scoped)
    notes.append(f"{len(scoped)} actions are proposed, {highs} of them high priority." if scoped
                 else "No actions are proposed: nothing crossed a threshold.")
    empty = [b["name"] for b in brands if all(b["current"][k] is None for k in ("roas", "citation_share", "rating"))]
    if empty:
        notes.append("No data yet for: " + E(", ".join(empty)) + ".")

    glance = "".join(
        f"<div><b>{fmt(port['current'][k])}</b>{label}{delta(port['current'][k], port['previous'][k], dk, good)}</div>"
        for label, k, fmt, dk, good in COLS)

    overview = ""
    if not category:
        head = "<tr><th>Category</th><th>Brands</th>" + "".join(f"<th>{c[0]}</th>" for c in COLS) + "</tr>"
        body = "".join(
            f"<tr><td>{E(c['label'])}</td><td>{c['brand_count']}</td>" + "".join(
                f"<td>{fmt(c['current'][k])}{delta(c['current'][k], c['previous'][k], dk, good)}</td>"
                for _, k, fmt, dk, good in COLS) + "</tr>" for c in cats)
        overview = f"<div class='sec'><h2>By category</h2><table><thead>{head}</thead><tbody>{body}</tbody></table></div>"

    sections = []
    for c in cats:
        bs = cat_of[c["id"]]
        names = [b["name"] for b in bs]
        mine = {b["id"] for b in bs}
        ser = [x for x in series["series"] if x[0] in mine]
        top8 = sorted(ser, key=lambda x: -sum(x[2]) / max(len(x[2]), 1))[:8]
        cap = "Ad revenue minus ad spend, smoothed over 7 days." + (
            f" The {len(top8)} brands with the most profit are shown, out of {len(ser)}." if len(ser) > len(top8) else "")
        profit = (f'<h3>Profit trend</h3><p class="cap">{cap}</p>'
                  + line_chart(f"Daily profit, {c['label']}", series["days"], [(x[1], x[2]) for x in top8])) if top8 else \
            '<h3>Profit trend</h3><p class="cap">No ad data in this period.</p>'
        ctasks = [t for t in tasks if t["brand_id"] in mine]
        tasks_html = ("<table class='t'><thead><tr><th>Priority</th><th>Brand</th><th>Task</th><th>Owner</th></tr></thead><tbody>"
                      + "".join(f"<tr><td>{E(t['priority'])}</td><td>{E(t['brand'])}</td><td><b>{E(t['title'])}</b>"
                                f"<div class='mut'>{E(t['why'])}</div></td><td>{E(t['function'])}</td></tr>" for t in ctasks)
                      + "</tbody></table>") if ctasks else "<p class='mut'>No actions proposed.</p>"
        g = "".join(
            f"<div><b>{fmt(c['current'][k])}</b>{label}{delta(c['current'][k], c['previous'][k], dk, good)}</div>"
            for label, k, fmt, dk, good in COLS)
        sections.append(f"""<div class="cat"><h2>{E(c['label'])}</h2><div class="mut">{c['brand_count']} brands</div>
<div class="glance">{g}</div>
<div class="sec"><h3>Brand scorecard</h3>{_table(bs)}</div>
<div class="sec">{profit}</div>
<div class="sec"><h3>Return on ad spend</h3><p class="cap">Revenue per dollar of ad spend.</p>
{bar_chart(f"ROAS, {c['label']}", names, [(this, [b['current']['roas'] for b in bs]), (prev, [b['previous']['roas'] for b in bs])], ratio)}</div>
<div class="sec"><h3>AI citation share</h3><p class="cap">Share of tracked prompts where the brand is mentioned.</p>
{bar_chart(f"AI citation share, {c['label']}", names, [(this, [b['current']['citation_share'] for b in bs]), (prev, [b['previous']['citation_share'] for b in bs])], pct)}</div>
<div class="sec"><h3>AI crawler errors</h3><p class="cap">Share of AI crawler requests that failed. High values mean AI engines may not be reading the site.</p>
{bar_chart(f"AI crawler error rate, {c['label']}", names, [(this, [_rate(b['current']) for b in bs]), (prev, [_rate(b['previous']) for b in bs])], pct)}</div>
<div class="sec"><h3>Proposed actions</h3>{tasks_html}</div></div>""")

    status_html = ("<table class='t'><thead><tr><th>Connector</th><th>Last success</th><th>Rows loaded</th><th>Last error</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>{E(str(s['connector']))}</td><td>{E(str(s.get('last_success') or 'never')[:16].replace('T', ' '))}</td>"
                             f"<td>{E(str(s.get('rows_loaded') if s.get('rows_loaded') is not None else 'n/a'))}</td>"
                             f"<td>{E(str(s.get('last_error') or 'none'))}</td></tr>" for s in status)
                   + "</tbody></table>") if status else "<p class='mut'>No sync records yet.</p>"

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brand operations dossier</title><style>{CSS}</style></head><body><div class="page">
<h1>Brand operations dossier{': ' + E(scope) if category else ''}</h1>
<div class="mut">{scope}. {(end - timedelta(days=n - 1)).strftime('%d %b %Y')} to {end.strftime('%d %b %Y')} ({n} days), compared with the {n} days before. Generated {datetime.now().strftime('%d %b %Y %H:%M')}.</div>
{'<div class="banner">Demo data. These figures are not real.</div>' if demo else ''}
<div class="glance">{glance}</div>
<h2>What stands out</h2><ul>{''.join(f'<li>{x}</li>' for x in notes)}</ul>
{overview}
{''.join(sections)}
<div class="sec"><h2>Data sources</h2>{status_html}
<p class="mut">Profit is ad revenue minus ad spend and stays provisional until the profit definition is agreed. Revenue is platform-reported and overlaps across platforms. Changes compare with the previous period of the same length.</p></div>
</div></body></html>"""
