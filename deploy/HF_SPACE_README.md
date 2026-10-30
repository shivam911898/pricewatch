---
title: PriceWatch
colorFrom: blue
colorTo: indigo
sdk: docker
app_port: 7860
pinned: false
short_description: Competitor price and stock monitor with alerts
---

> Hugging Face Spaces requires a PRO subscription as of Oct 2026 (Docker/Gradio Spaces return HTTP 402), so the free public demo lives on Render; see `DEPLOY.md`. This file is only for someone with a PRO account.

# PriceWatch - live demo

A competitor price and stock monitoring bot with a dashboard, alert log and price-history charts.
This Space runs the whole app in one container: the dashboard, a simulated competitor shop and a
scheduler that re-checks prices every minute, so prices move and alerts fire while you watch.

Use **Run check now**, open a row to chart it, or add your own product with the form
(click "Fill with demo values" to see the full flow).

Source code and docs: see the project README.
