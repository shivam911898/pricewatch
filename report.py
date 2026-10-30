"""Weekly report: python report.py [days]  -> report.html   (also served at /report by the dashboard)"""
import base64
import io
import sys
import threading
import time
from collections import defaultdict
from datetime import datetime, timezone
from html import escape

from dotenv import load_dotenv

load_dotenv()
import core  # noqa: E402
import llm  # noqa: E402

PALETTE = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
_plot_lock = threading.Lock()      # matplotlib's pyplot state is not thread-safe


def history(days):
    con = core.db()
    rows = con.execute("SELECT * FROM checks WHERE ts >= ? ORDER BY id", (core.since(days=days),)).fetchall()
    al = con.execute("SELECT * FROM alerts WHERE ts >= ? ORDER BY id", (core.since(days=days),)).fetchall()
    con.close()
    return rows, al


def chart(name, my, rows, cur="$"):
    series = defaultdict(list)
    for r in rows:
        if r["product"] == name and r["price"] is not None:
            series[r["store"]].append(r["price"])
    if not series:
        return None
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt
    with _plot_lock:
        fig, ax = plt.subplots(figsize=(7, 3.2))
        for i, (store, ys) in enumerate(sorted(series.items())):
            ax.plot(range(1, len(ys) + 1), ys, marker="o", ms=4, lw=2, color=PALETTE[i % len(PALETTE)], label=store)
        ax.axhline(my, color="#14171f", ls="--", lw=1.4, label="My price")
        ax.set_xlabel("check #"); ax.set_ylabel(f"price ({cur})"); ax.set_title(name, loc="left", fontsize=11)
        ax.grid(axis="y", color="#eceef3"); ax.spines[["top", "right"]].set_visible(False)
        ax.set_xticks(range(1, max(len(v) for v in series.values()) + 1))
        if len(ax.get_xticks()) > 12:
            ax.locator_params(axis="x", nbins=10)
        ax.legend(fontsize=8, frameon=False, ncol=4, loc="upper left", bbox_to_anchor=(0, -0.22))
        fig.tight_layout()
        buf = io.BytesIO(); fig.savefig(buf, format="png", dpi=110); plt.close(fig)
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


def summary(f, n_alerts):
    text = ai_summary(f)
    if text:
        return text
    moves = [x for x in f if not x.startswith("ALERT")]
    t = [f"{len(moves)} competitor price change(s) and {n_alerts} alert(s) this period."]
    t += moves[:3] or ["No price changes detected."]
    t.append("Review products where a competitor undercuts you before adjusting prices.")
    return "\n".join(t[:5])


def build_html(days=7) -> str:
    cfg = core.load_config()
    cur = cfg["settings"]["currency"]
    rows, al = history(days)
    text = summary(facts(cfg, rows, al), len(al))
    imgs = ""
    for p in cfg["products"]:
        b64 = chart(p["name"], p["my_price"], rows, cur)
        imgs += (f"<img alt='Price history for {escape(p['name'], quote=True)}' src='data:image/png;base64,{b64}'>" if b64
                 else f"<p class='muted'>{escape(p['name'])}: no data yet.</p>")
    alr = "".join(f"<li><span class='muted'>{escape(a['ts'][:19].replace('T', ' '))} UTC</span> {escape(a['message'])}</li>" for a in al) or "<li>none</li>"
    summ = "<br>".join(escape(line) for line in text.splitlines())
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    return f"""<!doctype html><html lang='en'><head><meta charset='utf-8'><meta name='viewport' content='width=device-width, initial-scale=1'>
<title>PriceWatch weekly report</title><style>
body{{font:15px/1.55 system-ui,-apple-system,'Segoe UI',sans-serif;max-width:860px;margin:0 auto;padding:28px 20px;color:#14171f;background:#f4f5f7}}
.card{{background:#fff;border:1px solid #e3e6ec;border-radius:12px;padding:18px 22px;margin:16px 0}}
h1{{margin:0 0 4px}}h2{{font-size:1rem;margin:0 0 10px}}.muted{{color:#7b8497}}img{{max-width:100%;display:block;margin:6px 0 16px}}
ul{{padding-left:18px}}li{{margin:6px 0}}</style></head><body>
<h1>PriceWatch weekly report</h1><div class='muted'>Last {days} days &middot; generated {stamp}</div>
<div class='card'><h2>Summary</h2><p>{summ}</p></div>
<div class='card'><h2>Price history</h2>{imgs}</div>
<div class='card'><h2>Alerts ({len(al)})</h2><ul>{alr}</ul></div>
</body></html>"""


def main():
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 7
    with open("report.html", "w", encoding="utf-8") as f:
        f.write(build_html(days))
    print("wrote report.html")


if __name__ == "__main__":
    main()
