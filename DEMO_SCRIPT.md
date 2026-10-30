# Loom demo script (60-90 seconds)

**Before recording:** open the live demo on Render a few minutes early (the free instance sleeps after about 15 minutes idle and needs about a minute to wake), or run `DEMO_MODE=1 uvicorn app:app`. Browser at 1440x900, zoom 100%, close other tabs.
Click **Reset demo** once so the dashboard is in its starting state, then wait about 10 seconds for the first alerts.
Speak slowly; every pause below is a place to let the screen do the talking.

| Time | On screen | Say |
|---|---|---|
| 0:00-0:10 | Dashboard top: logo, summary cards | "If you sell online, a competitor can quietly undercut you and you might not notice for days. This is PriceWatch: it watches your competitors' prices and stock for you and tells you the moment something changes." |
| 0:10-0:25 | Move over the competitor price table; point at a red row, an amber row, a green row | "Every row is one competitor page. My price on the left, their price, the percentage gap and their stock. Red means they undercut me, amber means they are out of stock, green means I'm the cheaper one." |
| 0:25-0:42 | Click **Run check now**; toast appears; the alert log gains lines | "I can run a check on demand, or it runs on a schedule, hourly by default. Prices just moved, so here is the alert log: one undercut, one price drop, one out-of-stock. These also go to Telegram or a Google Sheet." |
| 0:42-0:55 | Click a table row; the chart updates; hover a point | "Click any product to see its price history. The dashed line is my price, each colour is a competitor, and a cross marks a check where they were out of stock." |
| 0:55-1:12 | Click **Fill with demo values**, then **Add & check now**; the new row appears in the table | "Adding a product takes a minute: name, my price, the competitor's page link, and where the price is on the page. It runs a first check straight away, so I know it works before anything is saved." |
| 1:12-1:22 | Scroll to the footer, then the Weekly report button | "There's a weekly report with charts and a plain-English AI summary, written with your own Groq or Gemini key, JavaScript-heavy shops are supported, and it scrapes politely: robots.txt, delays, and hourly checks." |
| 1:22-1:30 | Back to the top of the dashboard | "If you'd like this set up for your shop, send me two or three competitor links and I'll tell you what's possible. Thanks for watching." |

Note: on the public demo the AI summary is only live if `GROQ_API_KEY` is set as an environment variable on the Render service (see DEPLOY.md); without it the report shows the built-in template summary, so do not promise AI wording on camera unless the footer says "AI summary on".

Tips: keep the cursor still while you talk; if a check fails on camera, click **Reset demo** and re-record that part.
