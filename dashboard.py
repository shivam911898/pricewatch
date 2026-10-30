"""Dashboard routes: HTML pages (Jinja2 templates) + a small JSON API used by the page's JavaScript."""
import logging
import os
import re
import secrets
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Literal

from bs4 import BeautifulSoup
from fastapi import APIRouter, Depends, Header, HTTPException, Request
from fastapi.responses import HTMLResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel, ConfigDict, Field

import core
import polite

log = logging.getLogger("pricewatch.dashboard")
BASE = Path(__file__).parent
templates = Jinja2Templates(directory=str(BASE / "templates"))

SCHED = None          # scheduler.Scheduler, set by app.py
SEED = None           # pristine config snapshot used by "Reset demo", set by app.py in demo mode
_last_manual = -1e9
_basic = HTTPBasic(auto_error=False)

KIND_LABEL = {"undercut": "Undercut", "price_drop": "Price drop", "out_of_stock": "Out of stock"}
STATUS_LABEL = {"undercut": "Undercut", "oos": "Out of stock", "above": "Priced above you",
                "inline": "In line", "pending": "Waiting for first check", "error": "Check failed",
                "skipped": "Skipped"}


# --------------------------------------------------------------------------- guards

def require_auth(creds: HTTPBasicCredentials | None = Depends(_basic)):
    """Optional HTTP Basic auth: set DASHBOARD_PASSWORD (user 'admin') for real client deployments."""
    pw = os.getenv("DASHBOARD_PASSWORD")
    if not pw or core.demo_mode():
        return
    ok = creds and secrets.compare_digest(creds.username, "admin") and secrets.compare_digest(creds.password, pw)
    if not ok:
        raise HTTPException(401, "Login required", headers={"WWW-Authenticate": 'Basic realm="PriceWatch"'})


def require_xhr(x_pricewatch: str | None = Header(None)):
    """State-changing calls must carry a custom header -> cross-site forms cannot trigger them (CSRF)."""
    if x_pricewatch != "1":
        raise HTTPException(403, "missing X-PriceWatch header")


router = APIRouter(dependencies=[Depends(require_auth)])


# --------------------------------------------------------------------------- view model

def ago(ts: str | None) -> str:
    if not ts:
        return "never"
    try:
        secs = (datetime.now(timezone.utc) - datetime.fromisoformat(ts)).total_seconds()
    except ValueError:
        return ts
    secs = max(0, int(secs))
    if secs < 5:
        return "just now"
    if secs < 90:
        return f"{secs} s ago"
    if secs < 5400:
        return f"{round(secs / 60)} min ago"
    if secs < 172800:
        return f"{round(secs / 3600)} h ago"
    return f"{round(secs / 86400)} d ago"


def _status(my, price, stock, thr):
    if price is None:
        return "pending", None
    diff = (price - my) / my * 100
    if not stock:
        return "oos", diff
    if diff <= -thr:
        return "undercut", diff
    if diff >= thr:
        return "above", diff
    return "inline", diff


def snapshot() -> dict:
    cfg = core.load_config()
    st = cfg["settings"]
    con = core.db()
    last2: dict = {}
    for r in con.execute("""SELECT * FROM (SELECT *, ROW_NUMBER() OVER (PARTITION BY product, store
            ORDER BY id DESC) rn FROM checks) WHERE rn <= 2 ORDER BY id DESC"""):
        last2.setdefault((r["product"], r["store"]), []).append(r)
    errors = {(r["product"], r["store"]): r for r in con.execute(
        """SELECT e.* FROM scrape_errors e JOIN (SELECT product, store, MAX(id) m FROM scrape_errors
           GROUP BY product, store) l ON e.id = l.m""")}
    alerts = [dict(a) for a in con.execute("SELECT * FROM alerts ORDER BY id DESC LIMIT 40")]
    n24 = con.execute("SELECT COUNT(*) FROM alerts WHERE ts >= ?", (core.since(hours=24),)).fetchone()[0]
    last_check = con.execute("SELECT MAX(ts) FROM checks").fetchone()[0]
    con.close()

    rows, gaps, stores = [], [], set()
    for p in cfg["products"]:
        thr = float(p.get("undercut_pct", st["undercut_pct"]))
        for c in p["competitors"]:
            stores.add(c["store"])
            hist = last2.get((p["name"], c["store"]), [])
            cur, prev = (hist[0] if hist else None), (hist[1] if len(hist) > 1 else None)
            err = errors.get((p["name"], c["store"]))
            err_is_new = bool(err and (cur is None or err["ts"] > cur["ts"]))
            price = cur["price"] if cur else None
            stock = bool(cur["in_stock"]) if cur else True
            status, diff = _status(p["my_price"], price, stock, thr)
            if err_is_new:
                status = "skipped" if err["message"].startswith("skipped") else "error"
            if status in ("undercut", "above", "inline") and diff is not None:
                gaps.append(diff)
            rows.append({
                "product": p["name"], "my_price": p["my_price"], "store": c["store"], "url": c["url"],
                "backend": c.get("backend") or ("playwright" if c.get("use_playwright") else "http"),
                "price": price, "in_stock": stock, "diff": diff, "status": status,
                "label": STATUS_LABEL[status], "threshold": thr,
                "delta": (price - prev["price"]) if (cur and prev and price is not None and prev["price"] is not None) else None,
                "ts": cur["ts"] if cur else None, "error": err["message"] if err_is_new else None,
            })
    for a in alerts:
        a["label"] = KIND_LABEL.get(a["kind"], a["kind"])
    sched = SCHED.state() if SCHED else {"enabled": False, "interval": None, "last_run": None, "next_run": None,
                                          "running": False, "ticks": 0}
    return {
        "demo": core.demo_mode(), "currency": st["currency"], "rows": rows, "alerts": alerts,
        "cards": {"products": len(cfg["products"]), "stores": len(stores), "pages": len(rows),
                  "alerts_24h": n24, "last_alert": alerts[0]["ts"] if alerts else None,
                  "avg_gap": (sum(gaps) / len(gaps)) if gaps else None,
                  "undercuts_now": sum(1 for r in rows if r["status"] == "undercut"),
                  "last_check": last_check},
        # True until the first check (or the first failure) is recorded, e.g. right after a restart on a host with an ephemeral disk
        "no_data": bool(rows) and all(r["status"] == "pending" for r in rows),
        "scheduler": sched, "channels": core.channels_status(),
        "product_names": [p["name"] for p in cfg["products"]],
    }


def until(ts: str | None) -> str:
    if not ts:
        return "soon"
    secs = int((datetime.fromisoformat(ts) - datetime.now(timezone.utc)).total_seconds())
    if secs <= 5:
        return "in a moment"
    return f"in {duration(secs)}"


def duration(secs) -> str:
    secs = int(secs or 0)
    if secs < 90:
        return f"{secs} s"
    if secs < 5400:
        return f"{round(secs / 60)} min"
    return f"{secs / 3600:.0f} h" if secs % 3600 == 0 else f"{secs / 3600:.1f} h"


def money(value, currency="$") -> str:
    return "-" if value is None else f"{currency}{value:,.2f}"


def _asset_version() -> int:
    """Cache-buster for static/style.css and app.js so a redeploy is picked up without a hard refresh."""
    try:
        return int(max((BASE / "static" / n).stat().st_mtime for n in ("style.css", "app.js")))
    except OSError:
        return 0


def exact(ts: str | None) -> str:
    """Full timestamp for a title attribute (the page's script swaps it for the visitor's local time)."""
    if not ts:
        return ""
    try:
        return datetime.fromisoformat(ts).astimezone(timezone.utc).strftime("%d %b %Y, %H:%M:%S UTC")
    except ValueError:
        return ts


def signed_pct(value) -> str:
    """+8.3% / -6.3% with a real minus sign; en dash when there is no value."""
    return "–" if value is None else f"{value:+.1f}%".replace("-", "−")


templates.env.filters.update(ago=ago, until=until, duration=duration, money=money, exact=exact, signed_pct=signed_pct)
templates.env.globals["asset_v"] = _asset_version()


def _ctx(request: Request) -> dict:
    snap = snapshot()
    snap["request"] = request
    snap["stores"] = sorted({r["store"] for r in snap["rows"]})
    groups: dict = {}
    for r in snap["rows"]:
        g = groups.setdefault(r["product"], {"product": r["product"], "my_price": r["my_price"], "rows": []})
        g["rows"].append(r)
    snap["groups"] = list(groups.values())
    return snap


# --------------------------------------------------------------------------- pages

@router.get("/", response_class=HTMLResponse)
def index(request: Request):
    return templates.TemplateResponse(request, "index.html", _ctx(request))


@router.get("/fragment", response_class=HTMLResponse)
def fragment(request: Request):
    """Server-rendered live section (cards, table, alerts); the page re-fetches it every few seconds."""
    return templates.TemplateResponse(request, "_fragment.html", _ctx(request))


@router.get("/report", response_class=HTMLResponse)
def weekly_report(days: int = 7):
    import report
    return HTMLResponse(report.build_html(max(1, min(days, 90)), back_url="./"))


# --------------------------------------------------------------------------- JSON API

@router.get("/api/state")
def api_state():
    return snapshot()


@router.get("/api/history")
def api_history(product: str, limit: int = 60):
    cfg = core.load_config()
    prod = next((p for p in cfg["products"] if p["name"] == product), None)
    if not prod:
        raise HTTPException(404, "unknown product")
    con = core.db()
    rows = con.execute("""SELECT ts, store, price, in_stock FROM checks WHERE product=? AND ts IN
        (SELECT DISTINCT ts FROM checks WHERE product=? ORDER BY ts DESC LIMIT ?) ORDER BY ts""",
                       (product, product, max(1, min(limit, 500)))).fetchall()
    con.close()
    labels = sorted({r["ts"] for r in rows})
    idx = {t: i for i, t in enumerate(labels)}
    series = {c["store"]: {"store": c["store"], "prices": [None] * len(labels), "stock": [True] * len(labels)}
              for c in prod["competitors"]}
    for r in rows:
        s = series.get(r["store"])
        if s:
            s["prices"][idx[r["ts"]]] = r["price"]
            s["stock"][idx[r["ts"]]] = bool(r["in_stock"])
    return {"product": product, "my_price": prod["my_price"], "currency": cfg["settings"]["currency"],
            "labels": labels, "series": list(series.values())}


@router.post("/api/run", dependencies=[Depends(require_xhr)])
def api_run():
    global _last_manual
    gap = 3 - (time.monotonic() - _last_manual)
    if gap > 0:
        raise HTTPException(429, f"Please wait {int(gap) + 1}s before running another check.")
    res = core.locked_run()
    if res is None:
        raise HTTPException(409, "A check is already running.")
    _last_manual = time.monotonic()
    if SCHED:
        SCHED.last_run = datetime.now(timezone.utc)
    return {"ok": True, **res}


class NewProduct(BaseModel):
    model_config = ConfigDict(str_strip_whitespace=True)
    name: str = Field(min_length=1, max_length=80)
    my_price: float = Field(gt=0, lt=1_000_000)
    store: str = Field(min_length=1, max_length=60)
    url: str = Field(min_length=1, max_length=500)
    css_selector: str | None = Field(None, max_length=200)
    stock_selector: str | None = Field(None, max_length=200)
    json_path: str | None = Field(None, max_length=120)
    stock_path: str | None = Field(None, max_length=120)
    backend: Literal["http", "playwright", "browser_agent"] = "http"
    undercut_pct: float | None = Field(None, ge=0, le=100)
    drop_pct: float | None = Field(None, ge=0, le=100)


def _bad(msg: str):
    raise HTTPException(422, msg)


def _validate(p: NewProduct, cfg: dict) -> None:
    demo = core.demo_mode()
    if demo and p.backend != "http":
        _bad("Demo mode only offers the HTTP backend. Playwright and the AI browser backend are enabled in client deployments.")
    if polite.is_internal(p.url):
        if not (demo and p.url.startswith("/demo-store/")):
            _bad("Relative URLs only work for the built-in demo store (/demo-store/alpha/4 ...).")
    elif demo and os.getenv("DEMO_ALLOW_EXTERNAL") != "1":
        _bad("This public demo only monitors its built-in demo store. Try /demo-store/alpha/4 (HTML) or /demo-store/beta/api/4 (JSON). "
             "A real deployment accepts any public product page.")
    elif (why := polite.url_problem(p.url, allow_private=os.getenv("ALLOW_PRIVATE_URLS") == "1")):
        _bad(why)
    if p.backend != "browser_agent" and not (p.css_selector or p.json_path):
        _bad("Give a CSS selector (HTML page) or a JSON path (API) for the price.")
    for sel in (p.css_selector, p.stock_selector):
        if sel:
            try:
                BeautifulSoup("", "html.parser").select_one(sel)
            except Exception:
                _bad(f"Invalid CSS selector: {sel!r}")
    for path in (p.json_path, p.stock_path):
        if path and not re.fullmatch(r"[\w\-]+(\.[\w\-]+)*", path):
            _bad("JSON paths look like product.price or items.0.price")
    limit = int(os.getenv("MAX_PRODUCTS", "12" if demo else "500"))
    known = {x["name"].lower() for x in cfg["products"]}
    if p.name.lower() not in known and len(known) >= limit:
        _bad(f"Product limit reached ({limit}). Remove one or use 'Reset demo'.")
    prod = next((x for x in cfg["products"] if x["name"].lower() == p.name.lower()), None)
    if prod and len(prod["competitors"]) >= 8 and p.store.lower() not in {c["store"].lower() for c in prod["competitors"]}:
        _bad("At most 8 competitors per product.")


@router.post("/api/products", dependencies=[Depends(require_xhr)])
def api_add_product(body: NewProduct):
    _validate(body, core.load_config())
    created, name = core.add_product(body.model_dump())
    res = core.locked_run(wait=25, product=name, store=body.store)
    if res is None:
        return {"ok": True, "created": created, "product": name, "pending": True,
                "message": "Saved. Another check is still running; this page will be checked on the next run."}
    if res["errors"]:
        msg = (res["last"] or {}).get("error", "check failed")
        core.remove_competitor(name, body.store)
        _bad(f"Not saved - the first check failed: {msg}")
    return {"ok": True, "created": created, "product": name, **res}


@router.delete("/api/products", dependencies=[Depends(require_xhr)])
def api_delete_product(name: str):
    if not core.remove_product(name):
        raise HTTPException(404, "unknown product")
    return {"ok": True}


@router.post("/api/demo/reset", dependencies=[Depends(require_xhr)])
def api_demo_reset():
    if not (core.demo_mode() and SEED):
        raise HTTPException(404, "only available in demo mode")
    from demo_store.app import reset_counters
    with core.RUN_LOCK:
        core.save_config(SEED)
        core.reset_data()
        reset_counters()
        for _ in range(3):
            core.run_once()
            time.sleep(1.1)
    return {"ok": True}
