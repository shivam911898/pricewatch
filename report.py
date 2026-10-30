"""Weekly report: python report.py [days]  -> report.html   (also served at /report by the dashboard)

The page is self-contained (stylesheet inlined from static/style.css, charts as PNG data URIs, favicon as a data URI),
so a saved report.html can be emailed, opened offline, or printed / saved as PDF from the browser.
"""
import base64
import io
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from html import escape
from pathlib import Path
from urllib.parse import quote

from dotenv import load_dotenv

load_dotenv()
import core  # noqa: E402
import llm  # noqa: E402

BASE = Path(__file__).parent
PALETTE = ["#4F46E5", "#14B8A6", "#F59E0B", "#EC4899", "#0EA5E9", "#84CC16", "#8B5CF6", "#EF4444"]   # mirrors --s1..--s8 in static/style.css
INK, MUTED, GRID, AXIS = "#0F172A", "#64748B", "#E2E8F0", "#CBD5E1"
FONT_LINK = "https://fonts.googleapis.com/css2?family=Inter:wght@400;500;600&display=swap"
STATUS_LABEL = {"undercut": "Undercut", "oos": "Out of stock", "above": "Priced above you", "inline": "In line", "pending": "No data"}
KIND_LABEL = {"undercut": "Undercut", "price_drop": "Price drop", "out_of_stock": "Out of stock"}
_plot_lock = threading.Lock()      # matplotlib's pyplot state is not thread-safe


def history(days):
    con = core.db()
    rows = con.execute("SELECT * FROM checks WHERE ts >= ? ORDER BY id", (core.since(days=days),)).fetchall()
    al = con.execute("SELECT * FROM alerts WHERE ts >= ? ORDER BY id", (core.since(days=days),)).fetchall()
    con.close()
    return rows, al


def _fmt_ts(ts, multi_day):
    d = datetime.fromisoformat(ts).astimezone(timezone.utc)
    return d.strftime("%d %b %H:%M") if multi_day else d.strftime("%H:%M:%S")


def chart(name, my, rows, cur="$"):
    """Price history PNG (base64) in the dashboard's palette, or None when the product has no priced checks yet."""
    mine = [r for r in rows if r["product"] == name]
    series = defaultdict(dict)                       # store -> {check index: price}
    stamps = sorted({r["ts"] for r in mine})
    idx = {t: i for i, t in enumerate(stamps)}
    for r in mine:
        if r["price"] is not None:
            series[r["store"]][idx[r["ts"]]] = r["price"]
    if not series:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    from matplotlib.ticker import FuncFormatter, MaxNLocator
    multi_day = datetime.fromisoformat(stamps[0]).date() != datetime.fromisoformat(stamps[-1]).date()
    with _plot_lock, plt.rc_context({"font.family": "sans-serif",
                                     "font.sans-serif": ["Inter", "Segoe UI", "Helvetica Neue", "Arial", "DejaVu Sans"]}):
        fig, ax = plt.subplots(figsize=(7.6, 3.1))
        for i, (store, pts) in enumerate(sorted(series.items())):
            xs = sorted(pts)
            ax.plot(xs, [pts[x] for x in xs], marker="o", ms=4.5, mew=1.5, mec="white", lw=2.2,
                    color=PALETTE[i % len(PALETTE)], label=store)
        ax.axhline(my, color=INK, ls=(0, (5, 4)), lw=1.3, label="My price")
        step = max(1, -(-len(stamps) // 7))
        ticks = list(range(0, len(stamps), step))
        ax.set_xticks(ticks)
        ax.set_xticklabels([_fmt_ts(stamps[t], multi_day) for t in ticks])
        ax.set_xlim(-0.35, max(len(stamps) - 1, 0) + 0.35)
        ax.yaxis.set_major_locator(MaxNLocator(nbins=5))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _p: f"{cur}{v:,.2f}"))
        ax.grid(axis="y", color=GRID, lw=0.9)
        ax.set_axisbelow(True)
        for side in ("top", "right", "left"):
            ax.spines[side].set_visible(False)
        ax.spines["bottom"].set_color(AXIS)
        ax.tick_params(colors=MUTED, labelsize=8.5, length=0, pad=6)
        ax.legend(fontsize=9, frameon=False, ncol=len(series) + 1, loc="lower left", bbox_to_anchor=(-0.01, 1.0),
                  labelcolor=INK, handlelength=1.6, columnspacing=1.6)
        fig.tight_layout()
        buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=200, facecolor="white"); plt.close(fig)
    return base64.b64encode(buf.getvalue()).decode()


def facts(cfg, rows, al):
    cur, lines = cfg["settings"]["currency"], []
    for p in cfg["products"]:
        for comp in p["competitors"]:
            pr = [r["price"] for r in rows if r["product"] == p["name"] and r["store"] == comp["store"] and r["price"] is not None]
            if len(pr) >= 2 and pr[0] != pr[-1]:
                lines.append(f"{p['name']} @ {comp['store']}: {cur}{pr[0]:.2f} -> {cur}{pr[-1]:.2f} (my price {cur}{p['my_price']:.2f})")
    for a in al:
        lines.append(f"ALERT {a['kind']}: {a['message']}")
    return lines


_AI_CACHE: dict = {}                 # (provider, model, facts) -> (timestamp, text). /report is public on the demo, so repeated
AI_CACHE_TTL = 600                   # page loads within 10 minutes reuse one answer instead of spending the owner's quota


def ai_summary(f):
    """5 plain-text lines from the configured LLM provider (Groq or Gemini), or None -> caller uses the template."""
    if not f or not llm.configured():
        return None
    facts_text = "\n".join(f[:60])
    key = (llm.provider(), llm.model(), facts_text)
    hit = _AI_CACHE.get(key)
    if hit and time.time() - hit[0] < AI_CACHE_TTL:
        return hit[1]
    text = llm.generate(
        "Write EXACTLY 5 short lines (plain text, no bullets or markdown, no preamble) summarising these "
        "competitor pricing moves and what to do:\n" + facts_text,
        system="You advise a small e-commerce seller.", max_tokens=1024)   # gpt-oss thinks ~200 tokens first
    if not text:
        print(f"{llm.provider()} summary unavailable, using template")
        return None
    lines = [ln.strip().lstrip("-*•# ").strip() for ln in text.splitlines()]
    out = "\n".join([ln for ln in lines if ln][:5]) or None
    if out:
        if len(_AI_CACHE) > 20:
            _AI_CACHE.clear()
        _AI_CACHE[key] = (time.time(), out)
    return out


def summary_with_source(f, n_alerts):
    """(text, is_ai): the report labels the panel 'AI summary' or 'Template summary' from the second value."""
    text = ai_summary(f)
    if text:
        return text, True
    moves = [x for x in f if not x.startswith("ALERT")]
    t = [f"{len(moves)} competitor price change(s) and {n_alerts} alert(s) this period."]
    t += moves[:3] or ["No price changes detected."]
    t.append("Review products where a competitor undercuts you before adjusting prices.")
    return "\n".join(t[:5]), False


def summary(f, n_alerts):
    return summary_with_source(f, n_alerts)[0]


# --------------------------------------------------------------------------- HTML helpers

def _read_asset(name):
    try:
        return (BASE / "static" / name).read_text(encoding="utf-8")
    except OSError:
        return ""


def _money(v, cur):
    return "-" if v is None else f"{cur}{v:,.2f}"


def _pct(v):
    return "&ndash;" if v is None else f"{v:+.1f}%".replace("-", "&minus;")


def _state(my, price, in_stock, thr):
    """Same rule as the dashboard: (status key, % difference vs my price)."""
    if price is None:
        return "pending", None
    diff = (price - my) / my * 100
    if not in_stock:
        return "oos", diff
    if diff <= -thr:
        return "undercut", diff
    if diff >= thr:
        return "above", diff
    return "inline", diff


def _competitor_rows(p, rows, cfg):
    """Table rows for one product: latest price, % vs mine, change over the period, stock, status."""
    cur, thr = cfg["settings"]["currency"], float(p.get("undercut_pct", cfg["settings"]["undercut_pct"]))
    out = []
    for comp in p["competitors"]:
        mine = [r for r in rows if r["product"] == p["name"] and r["store"] == comp["store"] and r["price"] is not None]
        if not mine:
            out.append(f"<tr><td>{escape(comp['store'])}</td><td colspan='5' class='muted'>No checks in this period.</td></tr>")
            continue
        first, last = mine[0]["price"], mine[-1]["price"]
        status, diff = _state(p["my_price"], last, bool(mine[-1]["in_stock"]), thr)
        delta = last - first
        if len(mine) < 2 or abs(delta) < 0.005:
            change = "<span class='muted'>no change</span>"
        else:
            sign = "&minus;" if delta < 0 else "+"
            change = (f"<span class='diff {'neg' if delta < 0 else 'pos'}'>{sign}{cur}{abs(delta):,.2f} "
                      f"({sign}{abs(delta) / first * 100:.1f}%)</span>")
        cls = {"undercut": "neg", "above": "pos"}.get(status, "flat")
        stock = "<span class='pill in-stock'>In stock</span>" if mine[-1]["in_stock"] else "<span class='pill out'>Out of stock</span>"
        out.append(f"<tr><td><strong>{escape(comp['store'])}</strong></td><td class='num'>{_money(last, cur)}</td>"
                   f"<td class='num'><span class='diff {cls}'>{_pct(diff)}</span></td><td class='num'>{change}</td>"
                   f"<td>{stock}</td><td><span class='pill {status}'>{STATUS_LABEL[status]}</span></td></tr>")
    return "".join(out)


def _period(days, end):
    start = end - timedelta(days=days)
    fmt = "%d %b" if start.year == end.year else "%d %b %Y"
    return f"{start.strftime(fmt)} &ndash; {end.strftime('%d %b %Y')}"


MAX_ALERTS_SHOWN = 100


def build_html(days=7, back_url=None) -> str:
    cfg = core.load_config()
    cur = cfg["settings"]["currency"]
    rows, al = history(days)
    f = facts(cfg, rows, al)
    text, is_ai = summary_with_source(f, len(al))
    now = datetime.now(timezone.utc)
    stamp = now.strftime("%Y-%m-%d %H:%M UTC")

    cards = ""
    for p in cfg["products"]:
        b64 = chart(p["name"], p["my_price"], rows, cur)
        img = (f"<img class='chart-img' alt='Price history for {escape(p['name'], quote=True)}' src='data:image/png;base64,{b64}'>" if b64
               else "<p class='empty'>No price data for this product in this period yet.</p>")
        n = sum(1 for a in al if a["product"] == p["name"])
        badge = (f"<span class='pill error'>{n} alert{'' if n == 1 else 's'}</span>" if n else "<span class='pill inline'>No alerts</span>")
        cards += (f"<section class='card product-card' aria-label='{escape(p['name'], quote=True)}'>"
                  f"<div class='card-head'><div><h2>{escape(p['name'])}</h2><p>My price {_money(p['my_price'], cur)}</p></div>{badge}</div>"
                  f"<div class='mini-wrap'><table class='mini'><thead><tr><th>Competitor</th><th class='num'>Latest</th><th class='num'>vs me</th>"
                  f"<th class='num'>Change in period</th><th>Stock</th><th>Status</th></tr></thead>"
                  f"<tbody>{_competitor_rows(p, rows, cfg)}</tbody></table></div>{img}</section>")
    if not cards:
        cards = "<section class='card'><p class='empty'>No products are tracked yet.</p></section>"

    shown = list(reversed(al))[:MAX_ALERTS_SHOWN]
    items = "".join(
        f"<li><span class='pill k-{escape(a['kind'])}'>{escape(KIND_LABEL.get(a['kind'], a['kind']))}</span><span class='alert-msg'>{escape(a['message']).replace('-&gt;', '&rarr;')}</span>"
        f"<span class='alert-time'>{escape(datetime.fromisoformat(a['ts']).astimezone(timezone.utc).strftime('%d %b, %H:%M'))} UTC</span></li>"
        for a in shown)
    more = f"<p class='muted small'>Showing the {len(shown)} most recent of {len(al)} alerts.</p>" if len(al) > len(shown) else ""
    alerts_html = f"<ul class='alerts'>{items}</ul>{more}" if items else "<p class='empty'>No alerts in this period.</p>"

    moves = sum(1 for x in f if not x.startswith("ALERT"))
    undercuts = sum(1 for a in al if a["kind"] == "undercut")
    pages = sum(len(p["competitors"]) for p in cfg["products"])
    stat = lambda label, value, sub: (f"<div class='card stat'><div class='stat-label'>{label}</div>"   # noqa: E731
                                      f"<div class='stat-value'>{value}</div><div class='stat-sub'>{sub}</div></div>")
    stats = (stat("Products tracked", len(cfg["products"]), "in this report")
             + stat("Competitor pages", pages, "checked on schedule")
             + stat("Price changes", moves, "since the period began")
             + stat("Alerts", len(al), f"{undercuts} undercut{'' if undercuts == 1 else 's'}"))

    summ = "".join(f"<li>{escape(line)}</li>" for line in text.splitlines())
    badge = ("<span class='source-badge'>AI summary</span>" if is_ai else "<span class='source-badge template'>Template summary</span>")
    title = "Weekly price report" if days == 7 else f"Price report, last {days} days"
    back = f"<a class='btn no-print' href='{escape(back_url, quote=True)}'>Back to dashboard</a>" if back_url else ""
    favicon = "data:image/svg+xml," + quote(_read_asset("favicon.svg"), safe="")
    mark = _read_asset("favicon.svg") and f"<img class='brand-mark' src='{favicon}' alt='' width='32' height='32'>"
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>PriceWatch weekly report | {_period(days, now).replace('&ndash;', '-')}</title>
<meta name='description' content='PriceWatch competitor price report for the last {days} days: price moves, alerts and a plain-language summary.'>
<meta name='theme-color' content='#4F46E5'>
<link rel='icon' type='image/svg+xml' href='{favicon}'>
<link rel='stylesheet' href='{FONT_LINK}' media='print' onload="this.media='all'">
<noscript><link rel='stylesheet' href='{FONT_LINK}'></noscript>
<style>{_read_asset('style.css')}</style></head><body>
<div class='report'>
<div class='report-top'><div class='brand-name'>{mark}PriceWatch</div>
<div class='report-actions no-print'>{back}<button class='btn btn-primary' id='print-btn' type='button'>Print or save as PDF</button></div></div>
<header class='report-title'><div class='eyebrow'>PriceWatch report</div><h1>{title}</h1>
<div class='report-meta'><strong>{_period(days, now)}</strong><span>&middot;</span><span>Last {days} days</span><span>&middot;</span><span>Generated {stamp}</span></div></header>
<div class='cards'>{stats}</div>
<section class='summary-panel' aria-label='Summary'><div class='summary-head'><h2>What changed and what to do</h2>{badge}</div><ul class='summary-list'>{summ}</ul></section>
{cards}
<section class='card'><div class='card-head'><div><h2>Alerts ({len(al)})</h2><p>Newest first, times in UTC.</p></div></div>{alerts_html}</section>
<footer class='report-foot'><span>Generated by PriceWatch on {stamp}.</span><span>Prices are read from public competitor pages on a polite schedule.</span></footer>
</div>
<script>document.getElementById('print-btn').addEventListener('click',function(){{window.print();}});</script>
</body></html>"""


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(build_html(days))
    print("wrote report.html")


if __name__ == "__main__":
    main()
