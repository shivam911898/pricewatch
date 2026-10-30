"""Fake competitor shop for the PriceWatch demo.

Mounted at /demo-store by the main app when DEMO_MODE=1, or run standalone:
    uvicorn demo_store.app:app --port 8001

Every page cycles through a price script. A step lasts N requests per page (default 2), so repeated
checks show price drops, undercuts and out-of-stock events, then the cycle starts again.
Two storefront styles: AlphaMart serves HTML (CSS selector), BetaShop serves a JSON API (JSON path).
"""
import os
import threading
from collections import defaultdict
from html import escape

from fastapi import FastAPI, HTTPException
from fastapi.responses import HTMLResponse

app = FastAPI(title="Demo competitor store", docs_url=None, redoc_url=None, openapi_url=None)
N = int(os.getenv("DEMO_STORE_N", "2"))
counts: dict[str, int] = defaultdict(int)
_lock = threading.Lock()
T, F = True, False

# product id -> name + per-store price script [(price, in_stock), ...]; looped forever.
# Ids 1-3 are tracked in the shipped products.yaml; 4-6 are there for the "Add product" form.
CATALOG = {
    "1": {"name": "Steel Water Bottle 1L",
          "alpha": [(24.99, T), (21.49, T), (21.49, T), (22.49, T), (24.99, T), (24.99, T), (23.99, T), (24.49, T)],
          "beta": [(26.50, T), (26.50, T), (25.90, T), (25.90, T), (22.49, T), (24.90, T), (26.50, T), (26.50, T)]},
    "2": {"name": "Wireless Mouse M200",
          "alpha": [(18.00, T), (18.00, T), (17.50, T), (17.50, F), (17.50, F), (18.20, T), (18.90, T), (18.00, T)],
          "beta": [(19.99, T), (17.49, T), (17.49, T), (18.99, T), (19.99, T), (19.99, T), (17.99, T), (18.99, T)]},
    "3": {"name": "Yoga Mat 6mm",
          "alpha": [(32.00, T), (32.00, F), (32.00, F), (32.00, T), (29.00, T), (32.00, T), (32.00, T), (32.00, T)],
          "beta": [(30.00, T), (30.00, T), (28.00, T), (28.00, T), (29.50, T), (30.00, T), (30.00, T), (31.50, T)]},
    "4": {"name": "USB-C Charging Cable 2m",
          "alpha": [(12.99, T), (12.99, T), (10.99, T), (10.99, T), (12.49, T), (12.99, F), (12.99, T), (12.99, T)],
          "beta": [(11.49, T), (11.49, T), (11.49, T), (9.99, T), (9.99, T), (11.49, T), (11.99, T), (11.49, T)]},
    "5": {"name": "Ceramic Coffee Mug Set",
          "alpha": [(34.00, T), (34.00, T), (34.00, T), (29.50, T), (29.50, T), (31.00, T), (34.00, T), (34.00, T)],
          "beta": [(32.50, T), (32.50, F), (32.50, F), (32.50, T), (30.00, T), (32.50, T), (32.50, T), (33.00, T)]},
    "6": {"name": "LED Desk Lamp",
          "alpha": [(39.99, T), (39.99, T), (35.99, T), (35.99, T), (35.99, T), (38.99, T), (39.99, T), (39.99, T)],
          "beta": [(41.00, T), (41.00, T), (41.00, T), (37.50, T), (37.50, F), (41.00, T), (41.00, T), (40.00, T)]},
}


def _state(store: str, pid: str):
    if pid not in CATALOG:
        raise HTTPException(404, "no such product")
    with _lock:
        key = f"{store}:{pid}"
        counts[key] += 1
        step = ((counts[key] - 1) // N) % len(CATALOG[pid][store])
    price, stock = CATALOG[pid][store][step]
    return CATALOG[pid]["name"], price, stock


_CSS = ("body{font-family:system-ui,sans-serif;margin:0;background:#f6f7f9;color:#1c2330}"
        "header{background:#1c2330;color:#fff;padding:14px 24px;font-weight:600}"
        "main{max-width:560px;margin:32px auto;padding:0 16px}"
        ".box{background:#fff;border:1px solid #dfe3ea;border-radius:12px;padding:24px}"
        ".price{font-size:2rem;font-weight:700}.stock{margin-left:12px;font-size:.9rem;color:#2f7d4f}"
        ".note{color:#667085;font-size:.85rem;margin-top:16px}a{color:#2563eb}li{margin:6px 0}")


def _page(title: str, body: str) -> str:
    return (f"<!doctype html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width'>"
            f"<title>{escape(title)}</title><style>{_CSS}</style></head><body><header>{escape(title)}</header>"
            f"<main>{body}</main></body></html>")


@app.get("/", response_class=HTMLResponse)
async def index():
    items = "".join(f"<li>{escape(p['name'])} - <a href='alpha/{i}'>AlphaMart page</a> | "
                    f"<a href='beta/api/{i}'>BetaShop JSON</a></li>" for i, p in CATALOG.items())
    return _page("Demo competitor store",
                 f"<div class='box'><h2>Fake competitor shops</h2><ul>{items}</ul>"
                 "<p class='note'>These pages exist only so PriceWatch has something to monitor. "
                 "Prices change every 2nd request.</p></div>")


@app.get("/alpha/{pid}", response_class=HTMLResponse)
async def alpha(pid: str):
    name, price, stock = _state("alpha", pid)
    badge = "In stock" if stock else "Out of stock"
    color = "" if stock else " style='color:#b42318'"
    return _page("AlphaMart",
                 f"<div class='box'><h1>{escape(name)}</h1><span class='price'>${price:.2f}</span>"
                 f"<span class='stock'{color}>{badge}</span>"
                 "<p class='note'>Demo page for PriceWatch. <a href='../'>All demo products</a></p></div>")


@app.get("/beta/api/{pid}")
async def beta(pid: str):
    name, price, stock = _state("beta", pid)
    return {"product": {"title": name, "price": price, "available": stock}}


def reset_counters():
    with _lock:
        counts.clear()


@app.post("/reset")
async def reset():
    reset_counters()
    return {"ok": True}
