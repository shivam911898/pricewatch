"""Background scheduler: one daemon thread that runs the checks every N seconds.

Demo mode  : default every 60 s, plus a short burst of warm-up checks at start so the dashboard is
             never empty (these are real checks of the embedded demo store, not fake history).
Real mode  : default every hour (CHECK_INTERVAL_SECONDS). Set SCHEDULER=0 to use cron instead.
"""
import logging
import threading
import time
from datetime import datetime, timedelta, timezone

import core

log = logging.getLogger("pricewatch.scheduler")


def _iso(dt):
    return dt.astimezone(timezone.utc).isoformat(timespec="seconds") if dt else None


class Scheduler:
    def __init__(self, interval: int, warmup_ticks: int = 0, warmup_gap: float = 1.5, start_delay: float = 1.0):
        self.interval, self.warmup_ticks, self.warmup_gap, self.start_delay = interval, warmup_ticks, warmup_gap, start_delay
        self.last_run: datetime | None = None
        self.next_run: datetime | None = None
        self.last_result: dict | None = None
        self.ticks = 0
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    # -- state for the dashboard
    def state(self) -> dict:
        return {"enabled": self._thread is not None and self._thread.is_alive(), "interval": self.interval,
                "last_run": _iso(self.last_run), "next_run": _iso(self.next_run),
                "running": core.RUN_LOCK.locked(), "ticks": self.ticks}

    def tick(self, **kw):
        try:
            res = core.locked_run(**kw)
        except Exception:
            log.exception("check run crashed; will retry on the next tick")
            return None
        if res is None:
            log.info("previous run still going, skipping this tick")
            return None
        self.last_run, self.last_result = datetime.now(timezone.utc), res
        self.ticks += 1
        log.info("check run: %(checked)d checked, %(alerts)d alert(s), %(errors)d error(s), %(skipped)d skipped", res)
        return res

    def warmup(self):
        for i in range(self.warmup_ticks):
            if self._stop.wait(self.warmup_gap if i else 0):
                return
            self.tick()

    def _loop(self):
        if self._stop.wait(self.start_delay):
            return
        self.warmup()
        while not self._stop.is_set():
            self.next_run = datetime.now(timezone.utc) + timedelta(seconds=self.interval)
            if self._stop.wait(self.interval):
                return
            self.tick()

    def start(self):
        if self._thread is None:
            self._thread = threading.Thread(target=self._loop, name="pricewatch-scheduler", daemon=True)
            self._thread.start()
            log.info("scheduler started: every %ss (warm-up ticks: %s)", self.interval, self.warmup_ticks)

    def stop(self):
        self._stop.set()
