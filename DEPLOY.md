# Deploying PriceWatch

The same `Dockerfile` serves every target. It runs `uvicorn app:app` on `$PORT` (default **7860**, the
Hugging Face Spaces port) and sets `DEMO_MODE=1`, so a fresh container is a self-contained public demo:
dashboard + simulated competitor shop + scheduler, no keys, no external scraping.

> **SQLite is ephemeral on free hosts.** Free Spaces/Render instances lose their disk on every restart or
> redeploy. For the demo that is fine: on each start the app re-runs three real checks against the embedded
> demo store, so the dashboard is never empty. For a real client, use a persistent volume (last section).

## Option A - Hugging Face Spaces (free, recommended for the demo)

1. Create a free account at <https://huggingface.co> and a **write** access token
   (Settings -> Access Tokens -> New token -> role *Write*).
2. Create the Space: <https://huggingface.co/new-space> -> name `pricewatch`, **SDK: Docker -> Blank**,
   hardware **CPU basic (free)**, visibility **Public**.
3. Push the project (PowerShell, from the project folder; replace `<USER>`):

   ```powershell
   cd ..
   git clone https://huggingface.co/spaces/<USER>/pricewatch hf-space    # user: <USER>, password: the write token
   robocopy price-monitor hf-space /E /XD .venv .git __pycache__ docs /XF .env *.db report.html README.md | Out-Null
   copy price-monitor\deploy\HF_SPACE_README.md hf-space\README.md       # Space README with the required YAML header
   cd hf-space
   git add .
   git commit -m "Deploy PriceWatch"
   git push
   ```

   (robocopy exit codes below 8 mean success. Bash equivalent: `rsync -a --exclude .venv --exclude .git --exclude docs --exclude .env --exclude '*.db' --exclude README.md price-monitor/ hf-space/`.
   You can also drag-and-drop the files in the Space's **Files -> Add file -> Upload files** page, and
   paste `deploy/HF_SPACE_README.md` as `README.md`.)
4. The **Logs** tab shows the image build (about 3-5 minutes the first time). When it says
   `Application startup complete`, open `https://<USER>-pricewatch.hf.space`. `/healthz` returns `{"ok": true}`.
5. Put that URL in `README.md`, the Fiverr gig and your Upwork portfolio.

Notes
- Free Spaces sleep after ~48 h without visitors and wake on the next visit (about 30-60 s). The warm-up checks
  repopulate the dashboard on wake-up.
- The Space URL works embedded in an iframe and directly (`*.hf.space`).
- To update: commit and `git push` again from `hf-space`; the Space rebuilds.

Optional: AI summary on the demo (Groq)
- The demo works with no keys; the weekly report then shows the built-in template summary. To get an AI-written summary
  in `/report`, open the Space -> **Settings -> Variables and secrets -> New secret**, name `GROQ_API_KEY`, value your key from
  <https://console.groq.com>, then restart the Space. Add it as a **secret**, never as a plain variable and never in the repo.
  Gemini works too: set `GEMINI_API_KEY` instead (or `LLM_PROVIDER=gemini` if both are present).
- The dashboard footer then reads "AI summary on (groq)". `/report` is public on the demo, so the summary is cached for
  10 minutes and any Groq error or rate limit silently falls back to the template.
- Default model is `openai/gpt-oss-120b`; override with a `GROQ_MODEL` variable (for example `openai/gpt-oss-20b`).
  Check which model ids your account can use with `GET https://api.groq.com/openai/v1/models`.
- Do not enable `browser_agent` on the demo Space: the default image has no browser.

## Option B - Render (fallback)

1. Push the project to a GitHub repo (keep `Dockerfile` in the repo root; `.env`, `.venv` and `*.db` are git-ignored).
2. <https://dashboard.render.com> -> **New -> Web Service** -> connect the repo.
3. **Runtime: Docker** (Render finds the `Dockerfile`), **Instance type: Free**.
4. Environment variable `DEMO_MODE` = `1` (already the Dockerfile default, set it explicitly anyway).
   Render injects `PORT`; the container honours it. Set **Health Check Path** to `/healthz`.
5. Deploy. The URL is `https://<service-name>.onrender.com`.

Notes: Render's free instances spin down after 15 minutes without traffic and cold-start in about a minute;
the scheduler only runs while the instance is awake, which is fine for a demo.

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
