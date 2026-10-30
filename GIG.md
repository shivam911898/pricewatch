# PriceWatch - Fiverr gig copy + Upwork blurb

Suggested category: Programming & Tech -> Data Scraping (or Scripting & Automation). Use the screenshots in `docs/` as gig
images and the Loom from `DEMO_SCRIPT.md` as the gig video. Put the live demo URL in the description's last line and in the portfolio.

## Title (77 characters)

```
I will build a web scraping price monitoring bot and competitor price tracker
```

## Packages

| | **Basic - $120** | **Standard - $350** | **Premium - $800** |
|---|---|---|---|
| Package name | Price Check | Watcher | Command Center |
| Competitor sites | 1 | up to 3 | up to 10 |
| Products tracked | up to 10 | up to 50 | up to 200 |
| JavaScript-heavy sites | no (normal HTML pages or JSON APIs) | 1 JavaScript site (Playwright) | up to 3 JavaScript sites, with AI browser-agent fallback for hard pages |
| Alert rules | undercut + out-of-stock | + price-drop %, per-product thresholds | + custom rules (e.g. margin floor, MAP breach) |
| Alert channels | 1 (Telegram **or** Google Sheet) | 2 (Telegram + Google Sheets) | Telegram + Google Sheets + 1 custom (email / Slack / Discord) |
| Dashboard | no (Google Sheet log + alerts) | yes, deployed on your free host (Render free tier or similar) | yes, password-protected, deployed on your VPS or paid host |
| Scheduling | hourly via cron / Task Scheduler (instructions) | built-in scheduler, hourly or slower | custom schedules per site |
| Weekly report | - | HTML report with price charts | HTML report + AI summary (Groq or Gemini, your key) |
| Source code + setup guide | yes | yes | yes + 15-min handover call |
| Revisions | 1 | 2 | 3 |
| Delivery | 3 days | 6 days | 12 days |
| Post-delivery support | 3 days | 7 days | 30 days (selector fixes if a site redesigns) |

Suggested gig extras: +1 competitor site ($40), +25 products ($30), extra alert channel ($25), 24-hour delivery ($60).

## Description (about 800 characters)

```
Stop checking competitor prices by hand. I build a monitoring bot that visits your competitors' product pages on a schedule, records every price and stock change, and alerts you on Telegram or Google Sheets the moment someone undercuts you, cuts their price or sells out.

You get:
- A clean live dashboard: your price vs each competitor, % difference, stock, alert log and price-history charts
- A weekly report with a short AI summary (Groq or Gemini - your key)
- Support for normal and JavaScript-heavy websites
- Polite scraping: robots.txt respected, sensible delays, hourly checks
- Full source code, a setup guide and a short video walkthrough

Not sure your competitors' sites can be monitored? Send me 2-3 product links and I will tell you before you order. Live demo: https://pricewatch-x0x8.onrender.com
```

## FAQ

1. **Can you monitor Amazon, eBay or other big marketplaces?**
   Usually not reliably: they block bots and their terms forbid scraping. For those I suggest the official APIs. Most independent shops and brand sites work fine. Send me the links and I will check first.
2. **Is this legal, and will I get blocked?**
   It only reads public product pages, checks robots.txt, identifies itself and waits between requests, which keeps load and block risk low. Always check each site's terms; I flag anything risky before building. This is not legal advice.
3. **What do I need to give you?**
   Your product list (name + your current price), the competitor product URLs, and a Telegram bot or Google account for alerts. I set up the rest and show you how to add products yourself from the dashboard.
4. **Where does it run and what does it cost?**
   On your PC, a small VPS or a free host such as Render's free tier. Typical running cost is $0-5 per month. The AI summary is optional and uses your own Groq or Gemini key (both have a free tier); without a key you get a built-in template summary.
5. **What happens when a competitor redesigns their page?**
   The selector for that page needs a small update. Standard includes 7 days of support and Premium 30 days; afterwards I offer quick fixes or a small monthly maintenance plan.

## Tags (5)

`web scraping`, `price monitoring`, `price tracker`, `scraping bot`, `competitor analysis`

## Upwork portfolio blurb

PriceWatch is a competitor price and stock monitoring bot with a live dashboard: it scrapes competitor product pages on a schedule (httpx + BeautifulSoup, with Playwright or an AI browser agent for JavaScript-heavy sites), stores the history in SQLite and sends Telegram / Google Sheets alerts when a rival undercuts a price, drops it or sells out. It ships as a FastAPI app with a Docker image, a weekly report with an optional AI summary (Groq or Gemini) and polite-scraping safeguards (robots.txt, per-site delays, hourly default). The live demo runs a simulated competitor shop so you can watch prices change and alerts fire in real time.
