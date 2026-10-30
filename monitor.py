"""Command line / cron entry point.

    python monitor.py --once          one check run, then exit (use with cron / Task Scheduler)
    python monitor.py --every 3600    keep running, one check per interval
The web dashboard is `uvicorn app:app` (see README). With DEMO_MODE=1 the embedded demo store is used.
"""
import argparse
import logging
import time

from dotenv import load_dotenv

load_dotenv()
import core  # noqa: E402


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--once", action="store_true")
    g.add_argument("--every", type=int, metavar="SECONDS")
    a = ap.parse_args()
    core.setup_logging()
    if core.demo_mode():
        import app  # noqa: F401  (registers the embedded demo store so '/demo-store/...' URLs resolve)
    if a.once:
        r = core.run_once()
        print(f"done: {r['checked']} checked, {r['alerts']} alert(s), {r['errors']} error(s), {r['skipped']} skipped")
        return
    while True:
        r = core.run_once()
        logging.info("cycle done, %d alert(s); sleeping %ss", r["alerts"], a.every)
        time.sleep(a.every)


if __name__ == "__main__":
    main()
