# Deploying PriceWatch

The same `Dockerfile` serves every target. It runs `uvicorn app:app` on `$PORT` (default **7860** when `PORT` is not set;
Render injects its own) and sets `DEMO_MODE=1`, so a fresh container is a self-contained public demo:
dashboard + simulated competitor shop + scheduler, no keys, no external scraping.

**Render blueprint:** `render.yaml` in the project root describes the same service (New -> Blueprint), as a shortcut for steps 2-5 of Option A.

> **SQLite is ephemeral on free hosts.** Free Render instances lose their disk on every restart, spin-down or
> redeploy. For the demo that is fine: on each start the app re-runs three real checks against the embedded
> demo store, so the dashboard is never empty. For a real client, use a persistent volume (last section).

## Option A - Render (free, recommended for the demo)

Free-tier facts: the instance spins down after about 15 minutes without traffic and cold-starts in about a minute;
512 MB RAM (enough for this app); the scheduler only runs while the instance is awake, which is fine for a demo.

1. Push the project to GitHub as `shivam911898/pricewatch`, with the `Dockerfile` in the repo root (`.env`, `.venv` and `*.db`
   are git-ignored).
2. Sign in at <https://dashboard.render.com> (signing in with GitHub is the simplest) -> **New -> Web Service**.
3. Source: connect the GitHub repo `shivam911898/pricewatch`, **or** use the **Public Git Repository** tab and paste
   `https://github.com/shivam911898/pricewatch` (no GitHub connection needed for a public repo).
4. Name `pricewatch`, branch `main`, leave Root Directory blank. **Runtime: Docker** (Render finds the `Dockerfile`),
   **Instance Type: Free**.
5. **Environment Variables**:

   | Name | Value |
   |------|-------|
   | `DEMO_MODE` | `1` (already the Dockerfile default, set it explicitly anyway) |
   | `GROQ_API_KEY` (optional) | key from <https://console.groq.com>; turns on the AI summary in `/report`. Treat it as a secret: enter it only here (or at the blueprint prompt), never in the repo |

   Render injects `PORT`; the container honours it. Under **Advanced** set **Health Check Path** to `/healthz`.
6. **Create Web Service**. The build takes about 3-5 minutes the first time (watch the **Logs** tab). When it says
   `Application startup complete`, open `https://pricewatch.onrender.com` (the exact URL is shown at the top of the service page;
   if the name was taken Render adds a suffix, e.g. `pricewatch-ab12.onrender.com`). `/healthz` returns `{"ok": true}`.
7. Put that URL in `README.md`, the Fiverr gig and your Upwork portfolio.

Notes
- The first visit after an idle period waits about a minute for the cold start. Open the URL a few minutes before
  recording the Loom or sending it to a buyer. The warm-up checks repopulate the dashboard on wake-up.
- To update: `git push` to `main`; Render rebuilds and redeploys automatically.

Optional: AI summary on the demo (Groq)
- The demo works with no keys; the weekly report then shows the built-in template summary. To get an AI-written summary
  in `/report`, open the service -> **Environment** -> **Add Environment Variable**, name `GROQ_API_KEY`, value your key from
  <https://console.groq.com>; Render redeploys. Never put the key in the repo.
  Gemini works too: set `GEMINI_API_KEY` instead (or `LLM_PROVIDER=gemini` if both are present).
- The dashboard footer then reads "AI summary on (groq)". `/report` is public on the demo, so the summary is cached for
  10 minutes and any Groq error or rate limit silently falls back to the template.
- Default model is `openai/gpt-oss-120b`; override with a `GROQ_MODEL` variable (for example `openai/gpt-oss-20b`).
  Check which model ids your account can use with `GET https://api.groq.com/openai/v1/models`.
- Do not enable `browser_agent` on the demo service: the default image has no browser.

## Option B - Hugging Face Spaces (PRO only now)

Hugging Face Spaces is no longer a free host for server apps (checked 2026-10-30): the Space SDK choices are only
`gradio`, `docker` and `static`, and creating a Docker or Gradio Space returns HTTP 402 ("requires a PRO subscription").
That is why the demo moved to Render. With a PRO account the old route still works: create a **Docker -> Blank** Space,
copy the project into the Space repo (without `.venv`, `.git`, `docs`, `.env`, `*.db`, `README.md`), copy
`deploy/HF_SPACE_README.md` over as the Space's `README.md` (it holds the required YAML header, `app_port: 7860`), and push.
The Dockerfile already runs as uid 1000 and listens on 7860, which is what Spaces expects.

## Run the container locally (needs Docker)

```bash
docker build -t pricewatch .
docker run --rm -p 7860:7860 pricewatch              # open http://localhost:7860
```

## Real client deployment (not demo)

On any VPS / container host with a persistent volume:

```bash
docker run -d --name pricewatch --restart unless-stopped -p 80:7860 \
  -e DEMO_MODE=0 \
  -e DASHBOARD_PASSWORD='choose-a-long-password' \
  -e CHECK_INTERVAL_SECONDS=3600 \
  -e PM_DB=/data/prices.db -e PM_CONFIG=/data/products.yaml \
  -e TELEGRAM_BOT_TOKEN=... -e TELEGRAM_CHAT_ID=... \
  -e GROQ_API_KEY=... \
  -v pricewatch-data:/data pricewatch
```

- `PM_DB` / `PM_CONFIG` on the volume keep history and the product list across restarts (the first products
  are added through the dashboard form, or copy a `products.yaml` into the volume).
- Always set `DASHBOARD_PASSWORD` (HTTP Basic, user `admin`) and put the app behind HTTPS (Caddy, Nginx, Cloudflare).
- Prefer cron over the in-app scheduler? Set `SCHEDULER=0` and run `python monitor.py --once` hourly.
- JavaScript-only competitor sites: build a custom image that also installs `requirements-browser.txt`
  plus Chromium (`playwright install --with-deps chromium`) and set `backend: playwright` or `browser_agent`
  on those competitors. The default image deliberately does not include a browser.
  `browser_agent` on Groq reads the page as text (no screenshots); use `LLM_PROVIDER=gemini` + `GEMINI_API_KEY` for
  pages where the price is only visible in an image.
- `-e GROQ_API_KEY=...` is optional (AI summary in the weekly report); omit it and the report uses the template.
