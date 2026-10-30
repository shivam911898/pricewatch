# PriceWatch - Fiverr gig copy + Upwork blurb

Suggested category: Programming & Tech -> Data Scraping (or Scripting & Automation). Use the screenshots in `docs/` as gig
images and the Loom from `DEMO_SCRIPT.md` as the gig video. Put the live demo URL in the first lines of the description and in the portfolio.

Pricing basis: `freelance_biz/research/competitors-pricewatch.md` (section 4.2). The numbers below are launch prices for a seller with
zero reviews. Raise them on the schedule in "Raise to".

## Title (73 characters)

```
I will build a competitor price tracker with dashboard and instant alerts
```

Other titles to test (swap after about 2 weeks if impressions are low):

- `I will build a price monitoring bot with Telegram and Google Sheets alerts` (74) - best keyword match
- `I will track competitor prices and stock and alert you on every price drop` (74)

## Packages (launch prices)

| | **Basic - $59** | **Standard - $199** | **Premium - $449** |
|---|---|---|---|
| Package name | Price Check | Watcher | Command Center |
| Competitor websites | 1 | up to 3 | up to 5 |
| Products tracked | up to 25 | up to 100 | up to 300 |
| Check schedule | daily | daily or hourly (built-in scheduler) | daily or hourly (built-in scheduler) |
| Price + stock history | price + stock status to Google Sheets or CSV | stored history with charts + Google Sheets sync | stored history with charts + Google Sheets sync |
| Alert rules | price drop | all three: undercut vs your price, price drop %, out of stock | all three + custom rules (margin floor, MAP breach) |
| Alert channel | 1 (Telegram **or** email) | Telegram or email, plus Google Sheets | Telegram or email, plus Google Sheets |
| Dashboard | no | yes, with price-history charts, deployed on a free host | yes, password-protected, deployed on your server or Docker |
| Weekly report | - | HTML report (save as PDF from the browser) | HTML report + AI summary (your Groq or Gemini key) |
| Source code + setup guide | yes | yes | yes |
| Revisions | 1 | 2 | 3 |
| Delivery | 4 days | 7 days | 10 days |
| Post-delivery support | 3 days | 7 days | 30 days of selector fixes if a site changes |

Built into the app today: dashboard, Telegram, Google Sheets alert rows, weekly HTML report, robots.txt check. Email alerts, CSV
output, a per-check price log in Sheets and the custom Premium rules are small additions I write for the order.

## Raise to

| | Basic | Standard | Premium | When |
|---|---|---|---|---|
| Fiverr launch | $59 | $199 | $449 | 0 reviews |
| Fiverr step 2 | $79 | $249 | $549 | after 3-5 five-star reviews |
| Fiverr target | $120 | $350 | $800 | after about 10-15 reviews at 4.9+ (or Level 1-2); this was the first draft |
| Upwork project catalog | $99 | $349 | $799 | list at launch; about 1.5-2x the Fiverr launch prices |
| Contra | from $400 | | | single service, "from" price |

## Extras

- Extra website: $60
- +25 products: $30
- Extra alert channel: $25
- Monthly monitoring and maintenance plan: $49-99 per month (selector fixes, checks that the bot still runs)
- Amazon via Keepa or the Product Advertising API, with your own keys: $120
- 24-hour delivery: $60

## Description (about 800 characters)

```
Live demo, open it now: https://pricewatch-x0x8.onrender.com
Free pre-check: send me 2-3 competitor links and I tell you the same day whether they can be monitored.
When a competitor undercuts you, drops their price or sells out, you get an alert on the next scheduled check, not days later.

I build a tracker that visits competitor product pages on a schedule and records every price and stock change.

- Dashboard: your price vs each competitor, % difference, stock, alert log, price-history charts
- Weekly report you can save as PDF, optional AI summary on your own key
- Alerts to Telegram or email, plus Google Sheets
- Polite scraping: robots.txt respected, delays between requests, no logins or captcha bypass
- Full source code and setup guide handed over

Best on Shopify, WooCommerce and independent shops. Amazon and eBay are not scraped (see FAQ). Dashboard and report are in Standard and Premium.
```

## FAQ

1. **Which websites can you monitor?**
   Shopify, WooCommerce and independent shops or brand sites with public product pages are the sweet spot, because the price and stock sit in the page or in a JSON feed. Pages that only show a price after JavaScript runs need an extra browser backend (Playwright); I confirm that in the free pre-check, before you order.
2. **Is this legal, and will I get blocked?**
   It only reads public product pages, checks robots.txt, identifies itself and waits between requests, which keeps load and block risk low. Always check each site's terms; I flag anything risky before building. This is not legal advice.
3. **What do I need to give you?**
   Your product list (name + your current price), the competitor product URLs, and a Telegram bot or Google account for alerts. I set up the rest and show you how to add products yourself from the dashboard.
4. **Where does it run?**
   On your PC, a small VPS, Docker on your own server, or a free host such as Render's free tier. Basic is a script on a schedule; Standard and Premium include the dashboard.
5. **What happens when a competitor redesigns their page?**
   The selector for that page needs a small update. Standard includes 7 days of support and Premium 30 days of selector fixes; afterwards I offer quick fixes or the monthly maintenance plan.
6. **Can you monitor Amazon or eBay?**
   Not by scraping: they block bots and their terms forbid it, so I do not scrape them. For Amazon I can use Keepa or the Amazon Product Advertising API with your own keys, as a $120 add-on; both have their own access rules and fees, paid by you. For eBay, send me what you need and I will tell you if an official route fits. Shopify, WooCommerce and independent shops are where this works best.
7. **What will you not scrape?**
   Pages behind logins, pages with captchas or paywalls, and pages that robots.txt disallows. The app skips those and shows "Check failed: blocked by robots.txt". I do not bypass bot protection.
8. **What does it cost to run?**
   About $0-5 per month on free tiers or a small VPS. Free hosts sleep when idle and can lose the database on a restart, so for a shop that depends on it a $5 VPS or a persistent disk is better. The AI summary is optional and uses your own Groq or Gemini key (both have a free tier); without a key you get a built-in template summary.

## Tags (5)

`price monitoring`, `price tracker`, `competitor price tracking`, `web scraping`, `price alert bot`

## Upwork portfolio blurb

PriceWatch is a competitor price and stock monitor with a live dashboard. It checks competitor product pages on a schedule (httpx and BeautifulSoup, Playwright for JavaScript pages), keeps price history in SQLite and sends Telegram or Google Sheets alerts when a rival undercuts you, drops a price or sells out. A weekly HTML report has an optional AI summary on your own Groq or Gemini key. Scraping is polite: robots.txt, per-site delays. FastAPI app with a Docker image; MIT source handed over. Live demo with a simulated competitor shop: https://pricewatch-x0x8.onrender.com. Send 2-3 competitor links for a free same-day check.

## Launch checklist

- [ ] Title, category and the 5 tags above entered; the pricing table matches "Launch prices", not "Raise to"
- [ ] Description first three lines show the demo link, the free pre-check offer and the alert promise
- [ ] Gallery: dashboard screenshot, alert example, tier table, "what works / what I will not scrape" slide, FAQ
- [ ] Video: 45-60 s from `DEMO_SCRIPT.md` (paste 3 URLs, first price table, test alert, weekly report)
- [ ] Thumbnail has no "Amazon" wording unless the Keepa / Product Advertising API add-on has been built and tested
- [ ] Render demo wakes within about a minute (free instance sleeps after about 15 minutes idle); open it before each outreach
- [ ] Upwork catalog entry at $99 / $349 / $799 and Contra service "from $400" published
- [ ] Review the "Raise to" table after the 3rd, 5th and 10th five-star review
