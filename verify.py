"""End-to-end check, fully in-process (no servers, no keys, no internet):  python verify.py

1. unit checks: price parsing, alert rules, robots.txt helper, SSRF guard
2. demo store via FastAPI TestClient
3. three pipeline runs against the embedded demo store (scrape -> SQLite -> alerts), assert alerts fired
4. dashboard HTML renders with the products table; JSON API; add-product form flow + validation
5. weekly report.html is generated with charts
6. LLM provider layer (Groq default, Gemini optional) against a mock OpenAI-compatible endpoint: success, 429 then
   success (retry), persistent 500 (template fallback), `none` mode, provider selection, browser agent construction
"""
import os
import shutil
import sys
import tempfile
import warnings

warnings.filterwarnings("ignore", message=".*starlette.testclient.*")   # cosmetic httpx/httpx2 notice

HERE = os.path.dirname(os.path.abspath(__file__))
work = tempfile.mkdtemp(prefix="pricewatch-verify-")
shutil.copy(os.path.join(HERE, "products.yaml"), os.path.join(work, "products.yaml"))
os.environ.update(DEMO_MODE="1", SCHEDULER="0", PM_DB=os.path.join(work, "test.db"),
                  PM_CONFIG=os.path.join(work, "products.yaml"), DASHBOARD_PASSWORD="",
                  TELEGRAM_BOT_TOKEN="", GEMINI_API_KEY="", GROQ_API_KEY="", LLM_PROVIDER="", GROQ_MODEL="",
                  GROQ_BASE_URL="", GROQ_BROWSER_MODEL="", GEMINI_MODEL="")   # "" also stops load_dotenv() pulling a real .env in
os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
os.chdir(work)
sys.path.insert(0, HERE)

from fastapi.testclient import TestClient  # noqa: E402

import core  # noqa: E402
import polite  # noqa: E402
from app import app  # noqa: E402  (DEMO_MODE=1 mounts the demo store and registers it for in-process fetches)

XHR = {"X-PriceWatch": "1"}
ok = lambda cond, msg: (print(("PASS  " if cond else "FAIL  ") + msg), cond or sys.exit(1))  # noqa: E731

# 1. unit checks ---------------------------------------------------------------------------
ok(core.parse_price("$1,299.00") == 1299.0 and core.parse_price("EUR 1.299,00") == 1299.0
   and core.parse_price("12,99 EUR") == 12.99 and core.parse_price("GBP24.99") == 24.99 and core.parse_price("n/a") is None,
   "price parsing (US/EU formats)")
prod = {"name": "X", "my_price": 100.0}
cfgs = {"undercut_pct": 5, "drop_pct": 5, "currency": "$"}
comp = {"store": "S"}
prev = {"price": 100.0, "in_stock": 1}
ok([k for k, _ in core.evaluate(prod, comp, 90.0, True, prev, cfgs)] == ["undercut", "price_drop"], "rules: undercut + drop fire")
ok(core.evaluate(prod, comp, 90.0, True, {"price": 90.0, "in_stock": 1}, cfgs) == [], "rules: no repeat alert while price is unchanged")
ok([k for k, _ in core.evaluate(prod, comp, 100.0, False, prev, cfgs)] == ["out_of_stock"], "rules: out of stock fires once")
ok(core.evaluate({**prod, "undercut_pct": 20}, comp, 90.0, True, {"price": 91.0, "in_stock": 1}, cfgs) == [], "rules: per-product threshold")
robots = "User-agent: *\nDisallow: /private/\n"
ok(polite.robots_allowed_from_text(robots, "PriceWatch/1.0", "https://x.com/p/1")
   and not polite.robots_allowed_from_text(robots, "PriceWatch/1.0", "https://x.com/private/1"), "robots.txt helper")
ok(polite.url_problem("http://127.0.0.1:8000/x") is not None and polite.url_problem("ftp://x.com") is not None, "SSRF guard blocks local/odd URLs")

# 2. demo store ----------------------------------------------------------------------------
c = TestClient(app)
ok(c.get("/demo-store/alpha/1").status_code == 200 and c.get("/demo-store/beta/api/1").json()["product"]["price"] > 0, "demo store serves HTML + JSON")
ok(c.get("/demo-store/alpha/99").status_code == 404, "demo store 404 for unknown product")
c.post("/demo-store/reset")

# 3. pipeline: 3 runs -----------------------------------------------------------------------
cfg = core.load_config(); cfg["settings"]["delay_seconds"] = 0
results = [core.run_once(cfg) for _ in range(3)]
n_alerts = sum(r["alerts"] for r in results)
con = core.db()
n_checks = con.execute("select count(*) from checks").fetchone()[0]
kinds = {r[0] for r in con.execute("select distinct kind from alerts")}
con.close()
ok(n_checks == 18 and sum(r["errors"] for r in results) == 0, f"3 runs stored 18 checks, 0 errors (got {n_checks})")
ok(n_alerts >= 1 and results[0]["alerts"] == 0, f"alerts fired only after prices moved ({n_alerts} total: {sorted(kinds)})")

# 4. dashboard -------------------------------------------------------------------------------
r = c.get("/")
ok(r.status_code == 200 and "<table class=\"prices\">" in r.text and "Steel Water Bottle 1L" in r.text
   and "AlphaMart" in r.text and "Alert log" in r.text and "Add product" in r.text, "GET / renders dashboard with products table")
ok(c.get("/fragment").status_code == 200 and c.get("/static/app.js").status_code == 200 and c.get("/static/chart.umd.min.js").status_code == 200,
   "fragment + static assets served")
st = c.get("/api/state").json()
ok(st["cards"]["products"] == 3 and st["cards"]["alerts_24h"] == n_alerts and len(st["rows"]) == 6, "API state: cards match")
h = c.get("/api/history", params={"product": "Steel Water Bottle 1L"}).json()
ok(len(h["labels"]) == 3 and len(h["series"]) == 2 and h["series"][0]["prices"][-1] is not None, "API history: 3 points x 2 stores")
ok(c.post("/api/run").status_code == 403, "mutating call without X-PriceWatch header is rejected (CSRF guard)")
run = c.post("/api/run", headers=XHR)
ok(run.status_code == 200 and run.json()["checked"] == 6, "POST /api/run checks all 6 pages")
new = {"name": "LED Desk Lamp", "my_price": 38.5, "store": "AlphaMart", "url": "/demo-store/alpha/6",
       "css_selector": ".price", "stock_selector": ".stock"}
add = c.post("/api/products", json=new, headers=XHR)
ok(add.status_code == 200 and add.json()["created"] and add.json()["last"]["price"] > 0, "add product via form API runs an immediate check")
ok("LED Desk Lamp" in c.get("/").text and "LED Desk Lamp" in open(os.environ["PM_CONFIG"], encoding="utf-8").read(), "new product shown and written to products.yaml")
bad = c.post("/api/products", json={**new, "name": "Broken", "css_selector": ".nope"}, headers=XHR)
ok(bad.status_code == 422 and "Broken" not in open(os.environ["PM_CONFIG"], encoding="utf-8").read(), "bad selector rejected, nothing saved")
ext = c.post("/api/products", json={**new, "name": "Ext", "url": "https://example.com/p"}, headers=XHR)
ok(ext.status_code == 422, "demo mode refuses external URLs")
ok(c.delete("/api/products", params={"name": "LED Desk Lamp"}, headers=XHR).status_code == 200, "delete product")
ok(c.post("/api/demo/reset", headers=XHR).status_code == 200 and c.get("/api/state").json()["cards"]["products"] == 3, "demo reset restores seed")

cfg_text = open(os.environ["PM_CONFIG"], encoding="utf-8").read()
ok(cfg_text.startswith("# PriceWatch configuration") and "backend: browser_agent" in cfg_text, "hand-written comment header survives a save")

# optional backends degrade gracefully without keys / packages
cfg2 = core.load_config()
cfg2["settings"].update(respect_robots=False, delay_seconds=0)
cfg2["products"] = [{"name": "JS page", "my_price": 10.0, "competitors": [
    {"store": "AgentShop", "url": "https://example.com/p", "backend": "browser_agent"},
    {"store": "PwShop", "url": "https://example.com/q", "css_selector": ".price", "backend": "playwright"}]}]
res = core.run_once(cfg2)        # no GROQ_API_KEY / GEMINI_API_KEY in the environment here
ok(res["skipped"] >= 1 and res["checked"] == 0, f"browser_agent without an AI key is skipped, not crashed (skipped={res['skipped']}, errors={res['errors']})")
core.reset_data(); c.post("/demo-store/reset")
for _ in range(3):
    core.run_once()

# 5. report ---------------------------------------------------------------------------------
import report  # noqa: E402
report.main()
html = open("report.html", encoding="utf-8").read()
ok("data:image/png;base64" in html and "PriceWatch weekly report" in html, "report.html generated with charts")
ok(c.get("/report").status_code == 200, "GET /report")

# 6. LLM provider layer against a mock OpenAI-compatible endpoint (no real key, no network) ----------------------
import importlib.util  # noqa: E402
import json  # noqa: E402
import logging  # noqa: E402

import httpx  # noqa: E402

import browser_agent  # noqa: E402
import llm  # noqa: E402

LLM_VARS = ("LLM_PROVIDER", "GROQ_API_KEY", "GEMINI_API_KEY", "GROQ_MODEL", "GROQ_BASE_URL", "GROQ_BROWSER_MODEL", "GEMINI_MODEL")
MOCK_BASE = "http://mock-groq.test/openai/v1"
SECRET = "gsk_verify_secret_123"
calls, script = [], []


def set_env(**kw):
    for k in LLM_VARS:
        os.environ[k] = ""
    os.environ.update(kw)


def mock_endpoint(request):                       # stands in for POST https://api.groq.com/openai/v1/chat/completions
    calls.append(request)
    step = script[min(len(calls), len(script)) - 1]
    if isinstance(step, Exception):
        raise step
    status, payload, headers = step
    return httpx.Response(status, json=payload, headers=headers, request=request)


def reply(text):
    return (200, {"choices": [{"message": {"role": "assistant", "content": text}}]}, {})


def run_script(*steps):
    calls.clear(); script.clear(); script.extend(steps)


llm._transport = httpx.MockTransport(mock_endpoint)   # every llm call in this section goes to the mock
llm.RETRY_BASE_DELAY = 0                              # no real sleeping between retries
captured = []
class _Cap(logging.Handler):
    def emit(self, record): captured.append(record.getMessage())
logging.getLogger("pricewatch.llm").addHandler(_Cap())
logging.getLogger("pricewatch.llm").propagate = False     # keep the expected retry warnings out of the console

# provider selection
set_env();                                   ok(llm.provider() == "none" and not llm.configured(), "provider: no keys -> none")
set_env(GEMINI_API_KEY="g");                 ok(llm.provider() == "gemini" and llm.configured(), "provider: only GEMINI_API_KEY -> gemini")
set_env(GROQ_API_KEY="k");                   ok(llm.provider() == "groq" and llm.configured(), "provider: only GROQ_API_KEY -> groq")
set_env(GROQ_API_KEY="k", GEMINI_API_KEY="g"); ok(llm.provider() == "groq", "provider: both keys -> groq is the default")
set_env(GROQ_API_KEY="k", GEMINI_API_KEY="g", LLM_PROVIDER="gemini"); ok(llm.provider() == "gemini", "provider: LLM_PROVIDER=gemini wins")
set_env(GROQ_API_KEY="k", LLM_PROVIDER="none"); ok(llm.provider() == "none" and not llm.configured(), "provider: LLM_PROVIDER=none switches AI off")
set_env(GROQ_API_KEY="k", LLM_PROVIDER="bogus"); ok(llm.provider() == "groq", "provider: invalid LLM_PROVIDER falls back to auto-detect")
set_env(LLM_PROVIDER="groq");                ok(llm.provider() == "groq" and not llm.configured() and llm.generate("hi") is None, "provider: groq without a key -> generate() returns None")

# successful summary
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE)
run_script(reply("  Line one\n\n- Line two  \nLine three"))
out = llm.generate("say hi", system="be brief", max_tokens=50)
req = calls[0] if calls else None
body = json.loads(req.content) if req else {}
ok(out == "Line one\n\n- Line two  \nLine three" and len(calls) == 1, "groq: successful call returns the stripped text (1 request)")
ok(req is not None and str(req.url) == MOCK_BASE + "/chat/completions" and req.headers["authorization"] == "Bearer " + SECRET,
   "groq: POST <GROQ_BASE_URL>/chat/completions with Bearer auth")
ok(body.get("model") == "openai/gpt-oss-120b" and body["messages"][0]["role"] == "system" and body["messages"][-1]["content"] == "say hi"
   and body["max_tokens"] == 50, "groq: default model + OpenAI-style messages body")
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE, GROQ_MODEL="my-model")
run_script(reply("x")); llm.generate("q")
ok(json.loads(calls[0].content)["model"] == "my-model", "groq: GROQ_MODEL override is used")
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE)

# 429 then success -> retry works
run_script((429, {"error": {"message": "rate limited"}}, {"retry-after": "0"}), reply("after retry"))
ok(llm.generate("q") == "after retry" and len(calls) == 2, "groq: 429 then 200 -> retried and succeeded (2 requests)")
run_script((503, {}, {}), (502, {}, {}), reply("third time lucky"))
ok(llm.generate("q") == "third time lucky" and len(calls) == 3, "groq: 503, 502 then 200 -> still succeeds (3 requests)")
run_script(httpx.ConnectTimeout("boom"), reply("recovered"))
ok(llm.generate("q") == "recovered" and len(calls) == 2, "groq: network timeout is retried")

# persistent failure -> None (caller falls back to template)
run_script((500, {"error": {"message": "server down"}}, {}))
ok(llm.generate("q") is None and len(calls) == llm.MAX_RETRIES + 1, f"groq: persistent 500 -> None after {llm.MAX_RETRIES} retries ({len(calls)} requests)")
run_script((401, {"error": {"message": "Invalid API Key"}}, {}))
ok(llm.generate("q") is None and len(calls) == 1, "groq: 401 is not retried -> None")
run_script((200, {"unexpected": True}, {}))
ok(llm.generate("q") is None, "groq: 200 with unexpected body -> None")
ok(not any(SECRET in m for m in captured), "API key never appears in log output")

# weekly report summary: Groq text, template fallback, `none` mode
facts = ["Steel Water Bottle 1L @ AlphaMart: $24.00 -> $21.00 (my price $24.00)", "ALERT undercut: AlphaMart undercuts Steel Water Bottle 1L"]
run_script(reply("- AlphaMart cut the bottle to $21.\n* You are now 12% above them.\n\nConsider matching.\nCheck stock.\nReview weekly.\nSixth line dropped."))
s = report.summary(facts, 1)
ok(s.splitlines()[0] == "AlphaMart cut the bottle to $21." and len(s.splitlines()) == 5 and len(calls) == 1,
   "report.summary uses the Groq text (bullets stripped, max 5 lines)")
ok(json.loads(calls[0].content)["max_tokens"] >= 1024, "report summary requests max_tokens >= 1024 (gpt-oss spends ~200 reasoning tokens first)")
ok(report.summary(facts, 1) == s and len(calls) == 1, "report.summary: an identical second request is served from the 10-minute cache (no new API call)")
report._AI_CACHE.clear()
run_script(reply("Mock AI summary for the weekly report."))
ok("Mock AI summary for the weekly report." in report.build_html(7) and len(calls) == 1, "weekly report HTML carries the AI summary")
report._AI_CACHE.clear()
run_script((429, {}, {"retry-after": "0"}))
s = report.summary(facts, 1)
ok("competitor price change(s)" in s and len(calls) == llm.MAX_RETRIES + 1, "report.summary falls back to the template when Groq keeps failing")
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE, LLM_PROVIDER="none")
run_script(reply("should never be used"))
s = report.summary(facts, 1)
ok("competitor price change(s)" in s and not calls, "report.summary in `none` mode: template, zero requests")
set_env()
s = report.summary(facts, 1)
ok("competitor price change(s)" in s and not calls, "report.summary with no keys: template, zero requests (unchanged behaviour)")
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE)
run_script(reply("should not be called for empty facts"))
ok("No price changes detected." in report.summary([], 0) and not calls, "report.summary with no price moves skips the AI call")

# dashboard footer reflects the provider
ok("AI summary <strong>on (groq)</strong>" in c.get("/").text, "dashboard footer: AI summary on (groq) when a Groq key is set")
set_env()
ok("AI summary <strong>template</strong>" in c.get("/").text, "dashboard footer: AI summary template when no key")

# browser agent: provider-aware, graceful without key, builds the agent offline when browser-use is installed
for env, label in (({}, "no key"), ({"GROQ_API_KEY": "k", "LLM_PROVIDER": "none"}, "LLM_PROVIDER=none")):
    set_env(**env)
    try:
        browser_agent.chat_model(); got = None
    except browser_agent.BackendUnavailable as e:
        got = str(e)
    ok(got is not None and "GROQ_API_KEY" in got, f"browser_agent ({label}) -> BackendUnavailable('needs GROQ_API_KEY or GEMINI_API_KEY')")
if importlib.util.find_spec("browser_use"):
    set_env(GROQ_API_KEY="k", GROQ_BASE_URL=MOCK_BASE)
    agent, browser = browser_agent.build("https://example.com/p", "hint")
    ok(type(agent.llm).__name__ == "ChatGroq" and agent.llm.model == "openai/gpt-oss-120b"
       and str(agent.llm.get_client().base_url).rstrip("/") == "http://mock-groq.test", "browser_agent + Groq: Agent constructed offline with ChatGroq (gpt-oss-120b)")
    ok(agent.settings.use_vision is False, "browser_agent + Groq: runs text/DOM-only (use_vision=False)")
    set_env(GROQ_API_KEY="k", GROQ_BROWSER_MODEL="openai/gpt-oss-20b")
    ok(browser_agent.chat_model().model == "openai/gpt-oss-20b", "browser_agent: GROQ_BROWSER_MODEL override")
    set_env(GEMINI_API_KEY="g")
    agent, browser = browser_agent.build("https://example.com/p")
    ok(type(agent.llm).__name__ == "ChatGoogle" and agent.settings.use_vision is True, "browser_agent + Gemini: ChatGoogle branch kept, screenshots (vision) on")
else:
    set_env(GROQ_API_KEY="k")
    try:
        browser_agent.build("https://example.com/p"); got = None
    except browser_agent.BackendUnavailable as e:
        got = str(e)
    ok(got is not None and "browser-use is not installed" in got, "browser_agent + Groq key, browser-use not installed -> BackendUnavailable (skipped, no crash)")
    print("NOTE  browser-use is not installed in this environment: Agent construction was not exercised here")
set_env()
print("\nALL CHECKS PASSED")
