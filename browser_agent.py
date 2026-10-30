"""Optional backend for JavaScript-heavy shops: an AI agent opens the page in a real browser.

Per product competitor in products.yaml:   backend: browser_agent   (agent_hint: "optional extra instruction")

Uses the `browser-use` library with Groq (default, openai/gpt-oss-120b, text/DOM-only: Groq currently offers no
vision model, so the agent runs with use_vision=False) or Gemini (gemini-3.1-flash-lite, screenshots on) and
returns (price, in_stock). The provider comes from llm.py (LLM_PROVIDER, or whichever key is set). Pages whose price
is only visible in an image/canvas need the Gemini provider. It is OPTIONAL and slower/costlier than the default httpx + BeautifulSoup backend, so use it
only for pages where selectors do not work (heavy JS, anti-bot widgets, A/B layouts).

Requirements (not installed by default):
    pip install -r requirements-browser.txt      # browser-use, needs Python >= 3.11
    GROQ_API_KEY=... (or GEMINI_API_KEY=...)     # in .env
    Google Chrome or Edge on the machine (or `playwright install chromium`)

Without a key or the package the check is SKIPPED with a clear message (never a crash).
"""
import asyncio
from urllib.parse import urlparse

from pydantic import BaseModel

import llm

MAX_STEPS = 8
TIMEOUT_S = 180


class BackendUnavailable(Exception):
    """The backend cannot run here (missing key / package). The check is skipped, not failed."""


class Result(BaseModel):
    price: float | None = None
    in_stock: bool = True


def _task(url: str, hint: str | None) -> str:
    return (
        f"Open {url} and read the CURRENT selling price and availability of the main product on that page. "
        "Ignore related products, struck-through old prices, shipping costs and ads. "
        "Dismiss cookie banners if they block the page. Do not log in, add anything to a cart or buy anything. "
        "Return price as a plain number (no currency symbol, '.' as decimal separator) and in_stock as true/false. "
        "If the price is not visible, return price null."
        + (f" Extra instruction from the site owner: {hint}" if hint else "")
    )


def _groq_sdk_base_url() -> str:
    """browser-use's ChatGroq uses the `groq` SDK, which adds /openai/v1 itself, so strip it from GROQ_BASE_URL."""
    base = llm.groq_base_url()
    return base[: -len("/openai/v1")] if base.endswith("/openai/v1") else base


def chat_model():
    """The browser-use chat model for the configured provider. No network call is made here."""
    prov = llm.provider()
    key = llm.api_key(prov) if prov != "none" else None
    if not key:
        raise BackendUnavailable("browser_agent needs GROQ_API_KEY or GEMINI_API_KEY (set it in .env)")
    try:
        if prov == "groq":
            from browser_use import ChatGroq
            return ChatGroq(model=llm.browser_model("groq"), api_key=key, base_url=_groq_sdk_base_url(), temperature=0.0)
        from browser_use import ChatGoogle
        return ChatGoogle(model=llm.model("gemini"), api_key=key)
    except ImportError as e:
        raise BackendUnavailable("browser-use is not installed: pip install -r requirements-browser.txt") from e


def build(url: str, hint: str | None = None, chat=None):
    """Create (agent, browser) for one page. Constructing them does not touch the network or launch a browser."""
    chat = chat or chat_model()
    try:
        from browser_use import Agent, Browser
    except ImportError as e:
        raise BackendUnavailable("browser-use is not installed: pip install -r requirements-browser.txt") from e
    host = urlparse(url).hostname or ""
    browser = Browser(
        headless=True,
        allowed_domains=[host, f"*.{host}"],      # the agent may not wander off the competitor's site
        enable_default_extensions=False,
        keep_alive=False,
    )
    agent = Agent(
        task=_task(url, hint),
        llm=chat,
        browser=browser,
        output_model_schema=Result,
        use_judge=False,
        use_vision=getattr(chat, "provider", "") != "groq",   # Groq has no vision model right now: DOM/text only. Gemini keeps screenshots.
    )
    return agent, browser


def extract(url: str, hint: str | None = None):
    """Return (price, in_stock) for `url`. Raises BackendUnavailable when it cannot run here."""
    chat = chat_model()                           # fail fast (no key / no package) before starting an event loop

    async def go():
        agent, browser = build(url, hint, chat)
        try:
            history = await asyncio.wait_for(agent.run(max_steps=MAX_STEPS), TIMEOUT_S)
        finally:
            await browser.stop()
        raw = history.final_result()
        if not raw:
            raise ValueError("browser agent finished without an answer")
        return Result.model_validate_json(raw)

    out = asyncio.run(go())
    if out.price is None:
        raise ValueError("browser agent could not find a price on the page")
    return float(out.price), bool(out.in_stock)
