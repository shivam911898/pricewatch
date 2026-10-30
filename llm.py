"""Tiny LLM provider layer for the optional AI features (weekly-report summary, browser agent).

    LLM_PROVIDER = groq | gemini | none      (default: groq if GROQ_API_KEY is set, else gemini if GEMINI_API_KEY, else none)
    GROQ_API_KEY, GROQ_MODEL (openai/gpt-oss-120b), GROQ_BASE_URL (https://api.groq.com/openai/v1)
    GEMINI_API_KEY, GEMINI_MODEL (gemini-3.1-flash-lite)

Groq speaks the OpenAI chat-completions protocol, so it is called with plain httpx (no SDK). Gemini keeps using
the google-genai SDK. `generate()` NEVER raises: any failure returns None and the caller falls back to its
templated text, so a missing key, a rate limit or an outage cannot break a report.
"""
import logging
import os
import time

import httpx

log = logging.getLogger("pricewatch.llm")

PROVIDERS = ("groq", "gemini", "none")
GROQ_BASE_URL = "https://api.groq.com/openai/v1"
GROQ_MODEL = "openai/gpt-oss-120b"            # reasoning model: ~200 hidden reasoning tokens count against max_tokens
GROQ_BROWSER_MODEL = "openai/gpt-oss-120b"    # browser_agent on Groq is text/DOM-only (no vision model on Groq right now)
GEMINI_MODEL = "gemini-3.1-flash-lite"

MAX_RETRIES = 3                  # retries after the first attempt (so up to 4 calls) on 429 / 5xx / network errors
RETRY_BASE_DELAY = 1.0           # seconds; doubles each retry (1, 2, 4). Tests set this to 0.
RETRY_AFTER_CAP = 10.0           # never sleep longer than this because of a Retry-After header
TIMEOUT_S = 60.0
_transport: httpx.BaseTransport | None = None   # test hook: verify.py injects an httpx.MockTransport here


def provider() -> str:
    """The configured provider: LLM_PROVIDER if valid, else auto-detect from whichever key is set."""
    explicit = os.getenv("LLM_PROVIDER", "").strip().lower()
    if explicit in PROVIDERS:
        return explicit
    if explicit:
        log.warning("LLM_PROVIDER=%r is not one of %s; auto-detecting", explicit, "/".join(PROVIDERS))
    if os.getenv("GROQ_API_KEY"):
        return "groq"
    if os.getenv("GEMINI_API_KEY"):
        return "gemini"
    return "none"


def api_key(prov: str | None = None) -> str | None:
    prov = prov or provider()
    return os.getenv({"groq": "GROQ_API_KEY", "gemini": "GEMINI_API_KEY"}.get(prov, ""), "").strip() or None


def configured() -> bool:
    """True when the chosen provider has a key, i.e. generate() will really call out."""
    prov = provider()
    return prov != "none" and api_key(prov) is not None


def model(prov: str | None = None) -> str | None:
    prov = prov or provider()
    if prov == "groq":
        return os.getenv("GROQ_MODEL", "").strip() or GROQ_MODEL
    if prov == "gemini":
        return os.getenv("GEMINI_MODEL", "").strip() or GEMINI_MODEL
    return None


def browser_model(prov: str | None = None) -> str | None:
    """Model for the browser agent (needs structured output; screenshots/vision only work on the Gemini branch)."""
    prov = prov or provider()
    if prov == "groq":
        return os.getenv("GROQ_BROWSER_MODEL", "").strip() or GROQ_BROWSER_MODEL
    return model(prov)


def groq_base_url() -> str:
    return (os.getenv("GROQ_BASE_URL", "").strip() or GROQ_BASE_URL).rstrip("/")


def describe() -> dict:
    prov = provider()
    return {"provider": prov, "model": model(prov), "configured": configured()}


def generate(prompt: str, *, system: str | None = None, max_tokens: int = 1024, temperature: float = 0.3) -> str | None:
    """Return the model's text, or None if no provider is configured or the call failed.

    Keep max_tokens >= 1024: reasoning models such as gpt-oss spend ~200 tokens thinking before the visible answer,
    and a small cap would cut the answer short (or empty)."""
    prov = provider()
    if prov == "none" or not api_key(prov):
        return None
    try:
        text = _groq(prompt, system, max_tokens, temperature) if prov == "groq" else _gemini(prompt, system, max_tokens, temperature)
    except Exception as e:                        # never let an AI hiccup break the caller
        log.warning("%s call failed: %s", prov, type(e).__name__)
        return None
    return text.strip() if text and text.strip() else None


def _retry_delay(attempt: int, resp: httpx.Response | None) -> float:
    delay = RETRY_BASE_DELAY * (2 ** attempt)
    if resp is not None:
        try:
            delay = max(delay, min(float(resp.headers.get("retry-after", 0)), RETRY_AFTER_CAP))
        except ValueError:
            pass
    return delay


def _groq(prompt: str, system: str | None, max_tokens: int, temperature: float) -> str | None:
    url = groq_base_url() + "/chat/completions"
    messages = ([{"role": "system", "content": system}] if system else []) + [{"role": "user", "content": prompt}]
    body = {"model": model("groq"), "messages": messages, "max_tokens": max_tokens, "temperature": temperature}
    headers = {"Authorization": f"Bearer {api_key('groq')}", "Content-Type": "application/json", "User-Agent": "PriceWatch/1.0"}
    with httpx.Client(timeout=TIMEOUT_S, transport=_transport) as client:
        for attempt in range(MAX_RETRIES + 1):
            resp = None
            try:
                resp = client.post(url, json=body, headers=headers)
            except httpx.TransportError as e:                       # timeout / connection reset: worth retrying
                log.warning("groq network error (%s), attempt %d/%d", type(e).__name__, attempt + 1, MAX_RETRIES + 1)
            else:
                if resp.status_code == 200:
                    try:
                        return resp.json()["choices"][0]["message"]["content"]
                    except (ValueError, KeyError, IndexError, TypeError):
                        log.warning("groq returned an unexpected response shape")
                        return None
                if resp.status_code != 429 and resp.status_code < 500:    # 400 / 401 / 403 / 404: retrying cannot help
                    log.warning("groq HTTP %d: %s", resp.status_code, _error_text(resp))
                    return None
                log.warning("groq HTTP %d, attempt %d/%d", resp.status_code, attempt + 1, MAX_RETRIES + 1)
            if attempt < MAX_RETRIES:
                time.sleep(_retry_delay(attempt, resp))
    return None


def _error_text(resp: httpx.Response) -> str:
    try:
        return str(resp.json()["error"]["message"])[:150]
    except Exception:
        return resp.text[:150]


def _gemini(prompt: str, system: str | None, max_tokens: int, temperature: float) -> str | None:
    from google import genai
    client = genai.Client(api_key=api_key("gemini"), http_options=genai.types.HttpOptions(
        timeout=90000, retry_options=genai.types.HttpRetryOptions(attempts=5, initial_delay=4, http_status_codes=[429, 500, 502, 503, 504])))
    # no max_output_tokens here: Gemini 3.x counts "thinking" tokens against it and could truncate a short answer
    cfg = genai.types.GenerateContentConfig(system_instruction=system, temperature=temperature)
    return client.models.generate_content(model=model("gemini"), contents=prompt, config=cfg).text
