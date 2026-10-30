"""PriceWatch web app.   DEMO_MODE=1 uvicorn app:app --port 8000

DEMO_MODE=1  one process: dashboard + embedded fake competitor shop (/demo-store) + background
             scheduler (every CHECK_INTERVAL_SECONDS, default 60). Needs no keys, no internet.
DEMO_MODE=0  monitors the real URLs in products.yaml every CHECK_INTERVAL_SECONDS (default 3600).
             SCHEDULER=0 turns the built-in scheduler off if you prefer cron + `python monitor.py --once`.
"""
import logging
import os
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()

from fastapi import FastAPI  # noqa: E402
from fastapi.staticfiles import StaticFiles  # noqa: E402

import core  # noqa: E402
import dashboard  # noqa: E402
from scheduler import Scheduler  # noqa: E402

core.setup_logging()
log = logging.getLogger("pricewatch")
DEMO = core.demo_mode()
BASE = Path(__file__).parent

interval = int(os.getenv("CHECK_INTERVAL_SECONDS", "60" if DEMO else "3600"))
if not DEMO and interval < 900:
    log.warning("CHECK_INTERVAL_SECONDS=%s is aggressive for real sites; hourly or slower is the polite default", interval)
use_scheduler = os.getenv("SCHEDULER", "1").strip().lower() not in ("0", "false", "no", "off")
sched = Scheduler(interval=interval, warmup_ticks=int(os.getenv("DEMO_WARMUP_TICKS", "3")) if DEMO else 0)
dashboard.SCHED = sched


@asynccontextmanager
async def lifespan(_app):
    if use_scheduler:
        sched.start()
    elif DEMO:
        log.info("SCHEDULER=0: no background checks; use the 'Run check now' button")
    if not DEMO and not os.getenv("DASHBOARD_PASSWORD"):
        log.warning("DASHBOARD_PASSWORD is not set: anyone who can reach this port can edit products. Set it before exposing the app.")
    yield
    sched.stop()


app = FastAPI(title="PriceWatch", version="1.0", lifespan=lifespan,
              description="Competitor price & stock monitoring with alerts.")
app.mount("/static", StaticFiles(directory=str(BASE / "static")), name="static")

if DEMO:
    from demo_store.app import app as demo_store_app
    app.mount("/demo-store", demo_store_app)
    core.register_internal_app(app)          # relative '/demo-store/...' URLs are fetched in-process
    dashboard.SEED = core.load_config()      # what "Reset demo" restores

app.include_router(dashboard.router)


@app.get("/healthz", include_in_schema=False)
def healthz():
    return {"ok": True}
