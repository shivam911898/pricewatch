"""PriceWatch core: config, SQLite history, scraping backends, alert rules, notifiers."""
import asyncio
import json
import logging
import os
import re
import sqlite3
import tempfile
import threading
import time
from datetime import datetime, timedelta, timezone

import httpx
import yaml
from bs4 import BeautifulSoup

import llm
import polite
from browser_agent import BackendUnavailable

log = logging.getLogger("pricewatch")

DEFAULT_SETTINGS = {
    "undercut_pct": 5.0,       # alert if a competitor is more than this % below my price
    "drop_pct": 5.0,           # alert if a competitor drops more than this % since its last check
    "delay_seconds": 1.0,      # minimum pause between two requests to the same host
    "currency": "$",
    "respect_robots": True,    # skip pages that robots.txt disallows
    "user_agent": "PriceWatch/1.0 (+https://github.com/shivam911898/pricewatch; contact: sak23571113@gmail.com)",
}
CONFIG_LOCK = threading.RLock()
RUN_LOCK = threading.Lock()          # one check run at a time (scheduler / button / add-product)
_internal_app = None                 # ASGI app that serves relative URLs (the embedded demo store)


def db_path() -> str:
    return os.getenv("PM_DB", "prices.db")


def config_path() -> str:
    return os.getenv("PM_CONFIG", "products.yaml")


def setup_logging():
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    # Per-request HTTP logs would include the Telegram bot token (it is part of the URL).
    for name in ("httpx", "httpcore", "google_genai", "urllib3"):
        logging.getLogger(name).setLevel(logging.WARNING)


# --------------------------------------------------------------------------- config

def load_config(path=None) -> dict:
    path = path or config_path()
    with CONFIG_LOCK:
        raw = {}
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                raw = yaml.safe_load(f) or {}
    raw["settings"] = {**DEFAULT_SETTINGS, **(raw.get("settings") or {})}
    raw["products"] = raw.get("products") or []
    for p in raw["products"]:
        p["competitors"] = p.get("competitors") or []
    return raw


def save_config(cfg: dict, path=None) -> None:
    path = path or config_path()
    body = yaml.safe_dump({"settings": cfg["settings"], "products": cfg["products"]},
                          sort_keys=False, allow_unicode=True)
    with CONFIG_LOCK:
        header = ""                      # keep the hand-written comment block at the top of the file
        if os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                for line in f:
                    if not line.startswith("#"):
                        break
                    header += line
        header = header or "# PriceWatch configuration. Edit by hand or via the dashboard 'Add product' form.\n"
        fd, tmp = tempfile.mkstemp(dir=os.path.dirname(os.path.abspath(path)), suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(header + body)
        os.replace(tmp, path)


def add_product(spec: dict) -> bool:
    """Add a competitor to an existing product (matched by name, case-insensitive) or create the product.

    `spec` keys: name, my_price, store, url, css_selector, stock_selector, json_path, stock_path,
    backend, undercut_pct, drop_pct. Returns (created, canonical product name).
    """
    with CONFIG_LOCK:
        cfg = load_config()
        comp = {k: spec[k] for k in ("store", "url", "css_selector", "stock_selector", "json_path",
                                    "stock_path", "agent_hint") if spec.get(k)}
        if spec.get("backend") and spec["backend"] != "http":
            comp["backend"] = spec["backend"]
        prod = next((p for p in cfg["products"] if p["name"].lower() == spec["name"].lower()), None)
        created = prod is None
        if created:
            prod = {"name": spec["name"], "my_price": float(spec["my_price"])}
            for k in ("undercut_pct", "drop_pct"):
                if spec.get(k) is not None:
                    prod[k] = float(spec[k])
            prod["competitors"] = []
            cfg["products"].append(prod)
        prod["competitors"] = [c for c in prod["competitors"] if c["store"].lower() != comp["store"].lower()] + [comp]
        save_config(cfg)
        return created, prod["name"]


def remove_competitor(name: str, store: str) -> None:
    """Undo add_product for one competitor (drops the product too if it has no competitors left)."""
    with CONFIG_LOCK:
        cfg = load_config()
        for p in cfg["products"]:
            if p["name"] == name:
                p["competitors"] = [c for c in p["competitors"] if c["store"] != store]
        cfg["products"] = [p for p in cfg["products"] if p["competitors"] or p["name"] != name]
        save_config(cfg)
    con = db()
    con.execute("DELETE FROM scrape_errors WHERE product=? AND store=?", (name, store))
    con.commit(); con.close()


def demo_mode() -> bool:
    return os.getenv("DEMO_MODE", "0").strip().lower() in ("1", "true", "yes", "on")


def remove_product(name: str) -> bool:
    with CONFIG_LOCK:
        cfg = load_config()
        keep = [p for p in cfg["products"] if p["name"] != name]
        if len(keep) == len(cfg["products"]):
            return False
        cfg["products"] = keep
        save_config(cfg)
    con = db()
    for t in ("checks", "alerts", "scrape_errors"):
        con.execute(f"DELETE FROM {t} WHERE product=?", (name,))
    con.commit(); con.close()
    return True


# --------------------------------------------------------------------------- database

def db():
    c = sqlite3.connect(db_path(), timeout=15)
    c.row_factory = sqlite3.Row
    c.executescript("""
    CREATE TABLE IF NOT EXISTS checks(id INTEGER PRIMARY KEY, product TEXT, store TEXT,
        price REAL, in_stock INTEGER, ts TEXT);
    CREATE TABLE IF NOT EXISTS alerts(id INTEGER PRIMARY KEY, product TEXT, store TEXT,
        kind TEXT, message TEXT, ts TEXT);
    CREATE TABLE IF NOT EXISTS scrape_errors(id INTEGER PRIMARY KEY, product TEXT, store TEXT,
        message TEXT, ts TEXT);
    CREATE INDEX IF NOT EXISTS ix_checks_ps ON checks(product, store, id);""")
    return c


def reset_data():
    con = db()
    for t in ("checks", "alerts", "scrape_errors"):
        con.execute(f"DELETE FROM {t}")
    con.commit(); con.close()


def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def since(hours=0, days=0) -> str:
    """ISO cutoff string comparable with the stored `ts` values."""
    return (datetime.now(timezone.utc) - timedelta(hours=hours, days=days)).isoformat(timespec="milliseconds")


# --------------------------------------------------------------------------- scraping

def parse_price(text):
    """'$1,299.00' -> 1299.0, '12,99 EUR' -> 12.99, '1.299,00' -> 1299.0. None if no number."""
    m = re.search(r"\d[\d.,]*", str(text))
    if not m:
        return None
    s = m.group().rstrip(".,")
    if "," in s and "." in s:                                    # last separator is the decimal one
        dec = "," if s.rfind(",") > s.rfind(".") else "."
        s = s.replace("." if dec == "," else ",", "").replace(dec, ".")
    elif "," in s:
        s = s.replace(",", ".") if (s.count(",") == 1 and re.search(r",\d{1,2}$", s)) else s.replace(",", "")
    elif s.count(".") > 1:
        s = s.replace(".", "")
    return float(s)


def _dig(data, path):
    for part in path.split("."):
        data = data[int(part)] if isinstance(data, list) else data[part]
    return data


_OOS = re.compile(r"out[\s-]?of[\s-]?stock|sold[\s-]?out|unavailable|not available", re.I)


def _stock_from_value(v) -> bool:
    if isinstance(v, str):
        return v.strip().lower() in ("true", "1", "yes", "instock", "in stock", "in_stock", "available")
    return bool(v)


def register_internal_app(asgi_app) -> None:
    """Relative URLs ('/demo-store/...') are served in-process by this ASGI app (no network)."""
    global _internal_app
    _internal_app = asgi_app


def _internal_get(url: str) -> str:
    if _internal_app is None:
        raise ValueError("relative URL needs DEMO_MODE=1 (embedded demo store); use a full https:// URL")

    async def go():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=_internal_app),
                                     base_url="http://internal") as c:
            r = await c.get(url, timeout=10)
            r.raise_for_status()
            return r.text
    return asyncio.run(go())


def fetch_text(url: str, ua: str, playwright: bool = False) -> str:
    if polite.is_internal(url):
        return _internal_get(url)
    if playwright:
        try:
            from playwright.sync_api import sync_playwright  # optional dependency
        except ImportError as e:
            raise BackendUnavailable("playwright is not installed: pip install playwright && playwright install chromium") from e
        with sync_playwright() as p:
            b = p.chromium.launch()
            try:
                pg = b.new_page(user_agent=ua)
                pg.goto(url, wait_until="networkidle", timeout=30000)
                return pg.content()
            finally:
                b.close()
    r = httpx.get(url, headers={"User-Agent": ua}, timeout=15, follow_redirects=True)
    r.raise_for_status()
    return r.text


def scrape(comp: dict, ua: str):
    """Return (price, in_stock) for one competitor entry. Raises on any failure."""
    backend = comp.get("backend") or ("playwright" if comp.get("use_playwright") else "http")
    if backend == "browser_agent":
        import browser_agent
        return browser_agent.extract(comp["url"], comp.get("agent_hint"))
    if backend not in ("http", "playwright"):
        raise ValueError(f"unknown backend {backend!r}")
    body = fetch_text(comp["url"], ua, backend == "playwright")
    if comp.get("json_path"):
        data = json.loads(body)
        price = parse_price(_dig(data, comp["json_path"]))
        stock = _stock_from_value(_dig(data, comp["stock_path"])) if comp.get("stock_path") else True
    else:
        if not comp.get("css_selector"):
            raise ValueError("competitor needs css_selector or json_path")
        tree = BeautifulSoup(body, "html.parser")
        node = tree.select_one(comp["css_selector"])
        if node is None:
            raise ValueError(f"selector {comp['css_selector']!r} not found on the page")
        price = parse_price(node.get_text(" ", strip=True))
        stock = True
        if comp.get("stock_selector"):
            s = tree.select_one(comp["stock_selector"])
            stock = not (s and _OOS.search(s.get_text(" ", strip=True)))
    if price is None:
        raise ValueError("no price found in the selected element")
    return price, stock


# --------------------------------------------------------------------------- alert rules

def evaluate(product, comp, price, stock, prev, st):
    """Return a list of (kind, message). Alerts fire when a condition *starts*, not on every check."""
    out, my, cur = [], product["my_price"], st.get("currency", "$")
    s, name = comp["store"], product["name"]
    u = float(product.get("undercut_pct", st["undercut_pct"]))
    d = float(product.get("drop_pct", st["drop_pct"]))
    if stock is False and (prev is None or prev["in_stock"]):
        out.append(("out_of_stock", f"{s} is OUT OF STOCK for {name}"))
    if price is not None:
        floor = my * (1 - u / 100)
        was_under = prev is not None and prev["price"] is not None and prev["price"] < floor
        if price < floor and not was_under:
            out.append(("undercut", f"{s} undercuts {name}: {cur}{price:.2f} vs my {cur}{my:.2f} (-{(my - price) / my * 100:.1f}%)"))
        if prev and prev["price"] and price < prev["price"] * (1 - d / 100):
            out.append(("price_drop", f"{s} dropped {name} {cur}{prev['price']:.2f} -> {cur}{price:.2f} (-{(prev['price'] - price) / prev['price'] * 100:.1f}%)"))
    return out


# --------------------------------------------------------------------------- notifiers

def channels_status() -> dict:
    return {
        "telegram": bool(os.getenv("TELEGRAM_BOT_TOKEN") and os.getenv("TELEGRAM_CHAT_ID")),
        "google_sheet": bool(os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON") and os.getenv("SHEET_ID")),
        "ai": llm.configured(),                       # Groq or Gemini key present (weekly summary + browser agent)
        "ai_provider": llm.provider() if llm.configured() else None,
    }


def notify_telegram(msg):
    tok, chat = os.getenv("TELEGRAM_BOT_TOKEN"), os.getenv("TELEGRAM_CHAT_ID")
    if not (tok and chat):
        log.debug("Telegram not configured, skipping")
        return
    try:
        httpx.post(f"https://api.telegram.org/bot{tok}/sendMessage",
                   json={"chat_id": chat, "text": "PriceWatch: " + msg}, timeout=10)
    except Exception as e:
        log.warning("Telegram failed: %s", type(e).__name__)


def notify_sheet(row):
    cred, sid = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON"), os.getenv("SHEET_ID")
    if not (cred and sid):
        log.debug("Google Sheet not configured, skipping")
        return
    try:
        import gspread
        gspread.service_account(filename=cred).open_by_key(sid).sheet1.append_row(row)
    except Exception as e:
        log.warning("Sheet append failed: %s", e)


# --------------------------------------------------------------------------- run

def run_once(cfg=None, product=None, store=None) -> dict:
    """Check every (or one) competitor page, store history, fire alerts. Returns a result summary."""
    cfg = cfg or load_config()
    st = cfg["settings"]
    res = {"checked": 0, "alerts": 0, "errors": 0, "skipped": 0, "alert_messages": [], "last": None}
    con = db()
    ts = now()                                   # one timestamp per run -> aligned chart points
    try:
        for p in cfg["products"]:
            if product and p["name"] != product:
                continue
            for comp in p["competitors"]:
                if store and comp["store"] != store:
                    continue
                url, err = comp["url"], None
                try:
                    if st.get("respect_robots") and not polite.robots_allowed(url, st["user_agent"]):
                        raise PermissionError("blocked by robots.txt - not fetched")
                    polite.throttle.wait(url, float(st.get("delay_seconds", 1)))
                    price, stock = scrape(comp, st["user_agent"])
                except BackendUnavailable as e:
                    err, res["skipped"] = f"skipped: {e}", res["skipped"] + 1
                except Exception as e:
                    err, res["errors"] = f"{type(e).__name__}: {e}"[:240], res["errors"] + 1
                if err:
                    (log.info if err.startswith("skipped") else log.warning)("check %s / %s: %s", p["name"], comp["store"], err)
                    con.execute("INSERT INTO scrape_errors(product,store,message,ts) VALUES(?,?,?,?)",
                                (p["name"], comp["store"], err, ts))
                    con.commit()
                    res["last"] = {"store": comp["store"], "error": err}
                    continue
                prev = con.execute("SELECT * FROM checks WHERE product=? AND store=? ORDER BY id DESC LIMIT 1",
                                   (p["name"], comp["store"])).fetchone()
                con.execute("INSERT INTO checks(product,store,price,in_stock,ts) VALUES(?,?,?,?,?)",
                            (p["name"], comp["store"], price, int(stock), ts))
                res["checked"] += 1
                res["last"] = {"store": comp["store"], "price": price, "in_stock": stock}
                for kind, msg in evaluate(p, comp, price, stock, prev, st):
                    con.execute("INSERT INTO alerts(product,store,kind,message,ts) VALUES(?,?,?,?,?)",
                                (p["name"], comp["store"], kind, msg, ts))
                    log.warning("ALERT %s", msg)
                    notify_telegram(msg)
                    notify_sheet([ts, p["name"], comp["store"], kind, msg])
                    res["alerts"] += 1
                    res["alert_messages"].append(msg)
                con.commit()
    finally:
        con.close()
    return res


def locked_run(wait: float = 0, **kw):
    """run_once() that never overlaps another run. Returns None if another run is still going."""
    got = RUN_LOCK.acquire(timeout=wait) if wait else RUN_LOCK.acquire(blocking=False)
    if not got:
        return None
    try:
        return run_once(**kw)
    finally:
        RUN_LOCK.release()
