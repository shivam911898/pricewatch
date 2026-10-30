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
                  GROQ_BASE_URL="", GROQ_BROWSER_MODEL="", GROQ_FALLBACK_MODEL="", GEMINI_MODEL="")   # "" also stops load_dotenv() pulling a real .env in
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
page = r.text
ok(c.get("/static/favicon.svg").status_code == 200 and 'rel="icon"' in page and 'name="description"' in page and "static/style.css" in page
   and "Undercuts now" in page and "Last check" in page and "data-chart=" in page and "Demo: simulated shops" in page,
   "dashboard: favicon, meta description, stylesheet, summary cards, chart buttons, demo pill")
ok("<style" not in page.split("</head>")[0] and 'style="' not in page, "dashboard: no inline styles (one stylesheet in static/)")
st = c.get("/api/state").json()
ok(st["cards"]["products"] == 3 and st["cards"]["alerts_24h"] == n_alerts and len(st["rows"]) == 6, "API state: cards match")
ok(st["no_data"] is False and st["cards"]["last_check"] and st["cards"]["undercuts_now"] == sum(1 for x in st["rows"] if x["status"] == "undercut"),
   "API state: last_check and undercuts_now are consistent with the table")
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
empty = c.get("/")
ok(empty.status_code == 200 and "No price checks yet" in empty.text and "data-run" in empty.text and c.get("/api/state").json()["no_data"] is True,
   "empty state: card with a Run check now button before the first check")
for _ in range(3):
    core.run_once()

# 5. report ---------------------------------------------------------------------------------
import report  # noqa: E402
report.main()
html = open("report.html", encoding="utf-8").read()
ok("data:image/png;base64" in html and "PriceWatch weekly report" in html, "report.html generated with charts")
ok("Template summary" in html and "@media print" in html and "--primary: #4F46E5" in html and html.count("class='card product-card'") == 3,
   "report.html: template summary badge, print CSS, design tokens, one card per product")
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
    os.environ.pop("GROQ_FALLBACK_MODEL", None)   # unset = the default fallback model (an empty value would switch it off)
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

# daily token cap (TPD) on the primary model -> the SAME request once on GROQ_FALLBACK_MODEL, no backoff, model reported
TPD = {"error": {"message": "Rate limit reached for model `openai/gpt-oss-120b` in organization `org_x` service tier `on_demand` on tokens per day "
                            "(TPD): Limit 200000, Used 199724, Requested 923. Please try again in 4m39.504s."}}
run_script((429, TPD, {"retry-after": "280"}), reply("from the fallback"))
captured.clear()
out, used = llm.generate_with_model("q", system="s", max_tokens=77)
sent = [json.loads(c.content) for c in calls]
ok(out == "from the fallback" and used == "openai/gpt-oss-20b" and [b["model"] for b in sent] == ["openai/gpt-oss-120b", "openai/gpt-oss-20b"],
   f"groq: TPD 429 -> same request retried on the fallback model, clean text, model reported ({used}, {len(calls)} requests)")
ok(len(sent) == 2 and {k: v for k, v in sent[0].items() if k != "model"} == {k: v for k, v in sent[1].items() if k != "model"},
   "groq: the fallback request is identical apart from the model")
ok(sum("fallback model" in m for m in captured) == 1 and not any(SECRET in m for m in captured), "groq: fallback logs exactly one line, no API key in it")
run_script((429, TPD, {}), reply("again"))
ok(llm.generate("q") == "again", "groq: generate() also benefits from the fallback")
run_script(reply("ok"))
ok(llm.generate_with_model("q") == ("ok", "openai/gpt-oss-120b") and len(calls) == 1, "groq: healthy primary -> reported as the answering model, no fallback")
run_script((429, TPD, {}), (429, TPD, {}))
ok(llm.generate_with_model("q") == (None, None) and len(calls) == 2, "groq: daily cap on both models -> (None, None) after exactly one fallback try")
run_script((429, {"error": {"message": "slow down"}}, {"retry-after": "0"}))
ok(llm.generate_with_model("q") == (None, None) and len(calls) == 2 * (llm.MAX_RETRIES + 1)
   and [json.loads(c.content)["model"] for c in calls[-1:]] == ["openai/gpt-oss-20b"],
   f"groq: 429 that outlasts the retries -> the fallback model gets the same retries, then None ({len(calls)} requests)")
run_script((429, {"error": {"message": "slow down"}}, {}), (429, {}, {}), (429, {}, {}), (429, {}, {}), reply("late"))
ok(llm.generate_with_model("q") == ("late", "openai/gpt-oss-20b") and len(calls) == llm.MAX_RETRIES + 2, "groq: 429 after all retries, fallback model answers")
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE, GROQ_FALLBACK_MODEL="")
run_script((429, TPD, {}), reply("must not be used"))
ok(llm.generate_with_model("q") == (None, None) and len(calls) == 1 and llm.fallback_model() == "", "groq: GROQ_FALLBACK_MODEL empty -> fallback disabled, TPD 429 gives None as before")
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE, GROQ_MODEL="my-model", GROQ_FALLBACK_MODEL="other-model")
run_script((429, TPD, {}), reply("custom"))
ok(llm.generate_with_model("q") == ("custom", "other-model") and [json.loads(c.content)["model"] for c in calls] == ["my-model", "other-model"],
   "groq: GROQ_MODEL / GROQ_FALLBACK_MODEL overrides are used")
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE, GROQ_MODEL="openai/gpt-oss-20b")
run_script((429, TPD, {}))
ok(llm.generate_with_model("q") == (None, None) and len(calls) == 1, "groq: primary already equals the fallback model -> no pointless second request")
set_env(GROQ_API_KEY=SECRET, GROQ_BASE_URL=MOCK_BASE)

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
ok(">AI summary<" in report.build_html(7) and "Template summary" not in report.build_html(7), "weekly report labels the panel 'AI summary' when the provider answered")
report._AI_CACHE.clear()
run_script((429, {}, {"retry-after": "0"}))
s = report.summary(facts, 1)
ok("competitor price change(s)" in s and len(calls) == 2 * (llm.MAX_RETRIES + 1), "report.summary falls back to the template when Groq keeps failing (429: retries on both models)")
report._AI_CACHE.clear()
run_script((500, {}, {}))
s = report.summary(facts, 1)
ok("competitor price change(s)" in s and len(calls) == llm.MAX_RETRIES + 1, "report.summary: persistent 500 -> template, the fallback model is not tried")
report._AI_CACHE.clear()
run_script((429, TPD, {}), reply("- F1\nF2\nF3\nF4\nF5"))
r1 = report.summary_with_source(facts, 1)
ok(r1 == ("F1\nF2\nF3\nF4\nF5", True, "openai/gpt-oss-20b") and len(calls) == 2
   and json.loads(calls[1].content)["model"] == "openai/gpt-oss-20b",
   f"report.summary_with_source after a TPD 429: clean AI text, is_ai, reports the fallback model ({r1[1:]})")
ok(report.summary_with_source(facts, 1) == r1 and len(calls) == 2, "report.summary_with_source: the cached answer keeps the model that wrote it")
report._AI_CACHE.clear()
run_script(reply("P1\nP2\nP3\nP4\nP5"))
ok(report.summary_with_source(facts, 1)[1:] == (True, "openai/gpt-oss-120b"), "report.summary_with_source: healthy primary reports the primary model")
report._AI_CACHE.clear()
run_script((429, TPD, {}), (429, TPD, {}))
r2 = report.summary_with_source(facts, 1)
ok(r2[1:] == (False, None) and "competitor price change(s)" in r2[0] and len(calls) == 2, "report.summary_with_source: both models capped -> template, is_ai False, model None")
report._AI_CACHE.clear()
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
