"""Real-key smoke test for the Groq integration (not part of verify.py, which needs no key).

    set GROQ_API_KEY=gsk_...            (or put it in .env)
    python smoke_groq.py                # generates one weekly-style summary and prints provider / model / text
    python smoke_groq.py --models       # also lists GET <base>/models and checks the two configured model ids exist

Exit code 0 = got a real answer from Groq, 1 = call failed, 2 = no key.
"""
import logging
import os
import sys
import time

import httpx
from dotenv import load_dotenv

load_dotenv()
logging.basicConfig(level=logging.WARNING, format="%(levelname)s %(name)s: %(message)s")
os.environ["LLM_PROVIDER"] = "groq"          # this script tests Groq specifically, whatever .env says

import llm  # noqa: E402
import report  # noqa: E402

SAMPLE_FACTS = [
    "Steel Water Bottle 1L @ AlphaMart: $24.00 -> $21.50 (my price $24.00)",
    "Wireless Mouse M200 @ BetaShop: $18.00 -> $18.00 (my price $18.50)",
    "ALERT undercut: AlphaMart undercuts Steel Water Bottle 1L: $21.50 vs my $24.00 (-10.4%)",
    "ALERT out_of_stock: BetaShop is OUT OF STOCK for Yoga Mat 6mm",
]


def list_models() -> bool:
    url = llm.groq_base_url() + "/models"
    try:
        r = httpx.get(url, headers={"Authorization": f"Bearer {llm.api_key('groq')}"}, timeout=30)
        r.raise_for_status()
        ids = sorted(m["id"] for m in r.json()["data"])
    except Exception as e:
        print(f"could not list models from {url}: {type(e).__name__}")
        return False
    print(f"\n{len(ids)} models available at {url}:")
    for i in ids:
        print("  ", i)
    good = True
    for label, mid in (("GROQ_MODEL (summary)", llm.model("groq")), ("GROQ_BROWSER_MODEL (browser agent)", llm.browser_model("groq"))):
        found = mid in ids
        good &= found
        print(f"{label}: {mid} -> {'available' if found else 'NOT in the list, set a current id in .env'}")
    return good


def main() -> int:
    if not os.getenv("GROQ_API_KEY", "").strip():
        print("GROQ_API_KEY is not set. Put it in .env or the environment, then run again.")
        return 2
    print(f"provider : {llm.provider()}")
    print(f"model    : {llm.model('groq')}")
    print(f"endpoint : {llm.groq_base_url()}/chat/completions")
    t0 = time.time()
    text, used = report.ai_summary(SAMPLE_FACTS)
    dt = time.time() - t0
    if not text:
        print(f"\nFAILED after {dt:.1f}s: no summary returned (see warnings above: bad key, wrong model id, or rate limit).")
        return 1
    print(f"\nOK in {dt:.1f}s (answered by {used}). Summary text:\n")
    print(text)
    if "--models" in sys.argv:
        list_models()
    return 0


if __name__ == "__main__":
    sys.exit(main())
