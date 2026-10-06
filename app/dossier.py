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
    flat = abs(d) < (0.0005 if kind == "pt" else 0.005)  # would print as zero, so show it as no change
    txt = {"rel": f"{d:+.0%}", "pt": f"{d * 100:+.1f} pt"}.get(kind, f"{d:+.2f}")
    if flat:
        txt = {"rel": "0%", "pt": "0.0 pt"}.get(kind, "0.00")
    sign = 0 if flat else (1 if d > 0 else -1) * (-1 if good == "down" else 1)
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


def line_chart(title, days, series, fmt=money, dots=None, ymax=None):
    """Lines over time. A None value leaves a gap. Dots are drawn on shorter charts."""
    W, H, L, R, T, B = 760, 310, 60, 14, 12, 64
    vals = [v for _, vs in series for v in vs if v is not None]
    if not vals:
        return ""
    lo, hi = min(0.0, min(vals)), (ymax if ymax is not None else max(vals))
    if hi <= lo:
        hi = lo + 1
    n = len(days)
    show_dots = n <= 30 if dots is None else dots
    X = lambda i: L + (W - L - R) * i / max(n - 1, 1)
    Y = lambda v: T + (H - T - B) * (1 - (v - lo) / (hi - lo))
    p = []
    for k in range(5):
        v = lo + (hi - lo) * k / 4
        p.append(f'<line x1="{L}" x2="{W - R}" y1="{Y(v):.1f}" y2="{Y(v):.1f}" stroke="#e3e6e3"/>'
                 f'<text x="{L - 8}" y="{Y(v) + 4:.1f}" text-anchor="end" fill="#5d6975">{E(fmt(v))}</text>')
    for i in sorted({0, n // 2, n - 1}):
        anchor = "end" if i == n - 1 and n > 1 else "start" if i == 0 and n > 1 else "middle"
        p.append(f'<text x="{X(i):.1f}" y="{H - B + 18}" text-anchor="{anchor}" fill="#5d6975">{days[i].strftime("%d %b")}</text>')
    for idx, (_, vs) in enumerate(series):
        color, seg = PALETTE[idx % len(PALETTE)], []
        for i, v in enumerate(list(vs) + [None]):
            if v is not None:
                seg.append((X(i), Y(v)))
                if show_dots:
                    p.append(f'<circle cx="{X(i):.1f}" cy="{Y(v):.1f}" r="2.5" fill="{color}"/>')
            else:
                if len(seg) > 1:
                    pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in seg)
                    p.append(f'<polyline fill="none" stroke="{color}" stroke-width="2" points="{pts}"/>')
                seg = []
    p.append(legend([(name, PALETTE[i % len(PALETTE)]) for i, (name, _) in enumerate(series)], L, H - 22))
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
.sec{break-inside:avoid}ul{padding-left:20px}h3{font-size:15px;margin:18px 0 6px}.tg,.all{position:absolute;opacity:0;pointer-events:none}
.hd{display:block;cursor:pointer;font-size:18px;font-weight:650;padding:12px 8px;border-top:2px solid #17202a;margin-top:18px}
.hd::before{content:"+ ";font-weight:700;color:#1c4fd6}
.tg:checked + .hd::before{content:"- "}
.tg:focus-visible + .hd,.all:focus-visible + .expall{outline:2px solid #1c4fd6;outline-offset:2px}
.bd{display:none;padding:0 8px 12px}
.tg:checked + .hd + .bd,.all:checked ~ .accs .bd{display:block}
.expall{display:inline-block;cursor:pointer;border:1px solid #1c4fd6;color:#1c4fd6;border-radius:6px;padding:6px 12px;font-size:14px;margin:8px 0}
h4{font-size:14px;margin:14px 0 4px}
.cols{display:grid;grid-template-columns:repeat(2,1fr);gap:16px}
@media print{body{background:#fff}.page{margin:0;padding:0;box-shadow:none}.bd{display:block!important}.expall{display:none}.hd::before{content:""}.acc{break-before:page}}
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


def _chg(v):
    if v is None:
        return "n/a"
    if abs(v) < 0.005:
        return '<span class="fl">0 pts</span>'
    return f'<span class="{"up" if v > 0 else "dn"}">{v * 100:+.0f} pts</span>'


def pct0(v):
    return f"{v * 100:.0f}%"


def share_top(*lists):
    """A tidy top for a chart of shares, so the axis ticks are round numbers."""
    top = max([v for vs in lists for v in vs if v is not None] or [0])
    return next((c for c in (0.04, 0.08, 0.12, 0.2, 0.4, 0.6, 0.8, 1.0) if c >= top), 1.0)


def trend_html(t, tc="t"):
    """Charts and tables showing how AI answers and SEO results change week by week."""
    if not t["enough"]:
        return ('<div class="trend"><p class="cap note">Trends need results from at least two different weeks. '
                'Import more runs over time to see how the answers change.</p></div>')
    s, label = t["summary"], t["label"]
    first, last = t["weeks"][0].strftime("%d %b %Y"), t["weeks"][-1].strftime("%d %b %Y")
    out = [f'<p class="cap note">Weekly, {first} to {last}. Each week uses the latest answer to each question in each engine. '
           f'Our share is the portion of listed spots held by our brands. Before and now are the first and second half of the range.</p>',
           f'<p>Our share of AI listings: {pct(s["ours_gen_before"])} before, {pct(s["ours_gen_after"])} now ({_chg(s["ours_gen_change"])}). '
           f'In SEO results: {pct(s["ours_seo_before"])} before, {pct(s["ours_seo_after"])} now ({_chg(s["ours_seo_change"])}).</p>',
           line_chart(f"Our share of listed spots, {label}", t["weeks"], [("AI answers", t["ours_gen"]), ("SEO results", t["ours_seo"])], pct0, dots=True,
                      ymax=share_top(t["ours_gen"], t["ours_seo"]))]
    brands = [b for b in t["brands"] if any(v for v in b["gen"] if v is not None)][:8]
    if brands:
        out.append('<h4>How often each of our brands is listed in AI answers</h4>')
        out.append(line_chart(f"Our brands in AI answers, {label}", t["weeks"], [(b["name"], b["gen"]) for b in brands], pct0, dots=True, ymax=share_top(*(b["gen"] for b in brands))))
    if t["competitors"]:
        out.append('<h4>The companies AI answers list most</h4>')
        out.append(line_chart(f"Top companies in AI answers, {label}", t["weeks"], [(c["name"], c["gen"]) for c in t["competitors"]], pct0, dots=True, ymax=share_top(*(c["gen"] for c in t["competitors"]))))

    def movers(title, rows):
        if not rows:
            return f'<div><h4>{title}</h4><p class="note mut">None.</p></div>'
        body = "".join(f"<tr><td>{E(r['name'])}{' <b>(ours)</b>' if r['ours'] else ''}</td><td>{pct(r['before'])}</td>"
                       f"<td>{pct(r['now'])}</td><td>{_chg(r['change'])}</td></tr>" for r in rows)
        return (f'<div><h4>{title}</h4><table class="{tc}"><thead><tr><th>Company</th><th>Before</th><th>Now</th><th>Change</th></tr>'
                f'</thead><tbody>{body}</tbody></table></div>')

    out.append(f'<div class="cols">{movers("Rising in AI answers", t["movers"]["rising"])}{movers("Falling in AI answers", t["movers"]["falling"])}</div>')
    return '<div class="trend">' + "".join(out) + '</div>'


def _accordion(cid, label, count, body, open_):
    return (f'<div class="acc"><input type="checkbox" class="tg" id="c-{E(cid)}"{" checked" if open_ else ""}>'
            f'<label class="hd" for="c-{E(cid)}">{E(label)} <span class="mut">{count} brands</span></label>'
            f'<div class="bd">{body}</div></div>')


def render(summary, tasks, series, status, demo, category=None, trends=None):
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
        shown = [(c, trends[c["id"]]) for c in cats if trends and c["id"] in trends and trends[c["id"]]["enough"]]
        if shown:
            rows = "".join(f"<tr><td>{E(c['label'])}</td><td>{pct(t['summary']['ours_gen_after'])} {_chg(t['summary']['ours_gen_change'])}</td>"
                           f"<td>{pct(t['summary']['ours_seo_after'])} {_chg(t['summary']['ours_seo_change'])}</td></tr>" for c, t in shown)
            overview += (f"<div class='sec'><h2>AI visibility trend by category</h2><p class='cap'>Our share of the spots listed in research answers "
                         f"over the last {shown[0][1]['days']} days: the second half of the range, and the change from the first half.</p>"
                         f"<table><thead><tr><th>Category</th><th>AI answers</th><th>SEO results</th></tr></thead><tbody>{rows}</tbody></table></div>")

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
        tr = (trends or {}).get(c["id"])
        trend_block = (f'<div class="sec"><h3>AI answers versus SEO over time</h3>{trend_html(tr, "t")}</div>'
                       if tr and tr["has_data"] else "")
        body = f"""<div class="glance">{g}</div>
<div class="sec"><h3>Brand scorecard</h3>{_table(bs)}</div>
<div class="sec">{profit}</div>
<div class="sec"><h3>Return on ad spend</h3><p class="cap">Revenue per dollar of ad spend.</p>
{bar_chart(f"ROAS, {c['label']}", names, [(this, [b['current']['roas'] for b in bs]), (prev, [b['previous']['roas'] for b in bs])], ratio)}</div>
<div class="sec"><h3>AI citation share</h3><p class="cap">Share of tracked prompts where the brand is mentioned.</p>
{bar_chart(f"AI citation share, {c['label']}", names, [(this, [b['current']['citation_share'] for b in bs]), (prev, [b['previous']['citation_share'] for b in bs])], pct)}</div>
<div class="sec"><h3>AI crawler errors</h3><p class="cap">Share of AI crawler requests that failed. High values mean AI engines may not be reading the site.</p>
{bar_chart(f"AI crawler error rate, {c['label']}", names, [(this, [_rate(b['current']) for b in bs]), (prev, [_rate(b['previous']) for b in bs])], pct)}</div>
{trend_block}
<div class="sec"><h3>Proposed actions</h3>{tasks_html}</div>"""
        sections.append(_accordion(c["id"], c["label"], c["brand_count"], body, len(cats) == 1))

    status_html = ("<table class='t'><thead><tr><th>Connector</th><th>Last success</th><th>Rows loaded</th><th>Last error</th></tr></thead><tbody>"
                   + "".join(f"<tr><td>{E(str(s['connector']))}</td><td>{E(str(s.get('last_success') or 'never')[:16].replace('T', ' '))}</td>"
                             f"<td>{E(str(s.get('rows_loaded') if s.get('rows_loaded') is not None else 'n/a'))}</td>"
                             f"<td>{E(str(s.get('last_error') or 'none'))}</td></tr>" for s in status)
                   + "</tbody></table>") if status else "<p class='mut'>No sync records yet.</p>"
    expand = ('<input type="checkbox" class="all" id="all"><label class="expall" for="all">Expand or collapse all categories</label>'
              '<p class="mut">Click a category to open it. When you print or save as PDF, every category prints open.</p>') if len(cats) > 1 else ""

    return f"""<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width, initial-scale=1">
<title>Brand operations dossier</title><style>{CSS}</style></head><body><div class="page">
<h1>Brand operations dossier{': ' + E(scope) if category else ''}</h1>
<div class="mut">{scope}. {(end - timedelta(days=n - 1)).strftime('%d %b %Y')} to {end.strftime('%d %b %Y')} ({n} days), compared with the {n} days before. Generated {datetime.now().strftime('%d %b %Y %H:%M')}.</div>
{'<div class="banner">Demo data. These figures are not real.</div>' if demo else ''}
<div class="glance">{glance}</div>
<h2>What stands out</h2><ul>{''.join(f'<li>{x}</li>' for x in notes)}</ul>
{overview}
{expand}<div class="accs">{''.join(sections)}</div>
<div class="sec"><h2>Data sources</h2>{status_html}
<p class="mut">Profit is ad revenue minus ad spend and stays provisional until the profit definition is agreed. Revenue is platform-reported and overlaps across platforms. Changes compare with the previous period of the same length.</p></div>
</div></body></html>"""
