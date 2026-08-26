# AlphaDesk

A multi-user equity research workspace for Indian (NSE) markets: watchlist,
portfolio tracking with P&L, a rule-based Buy/Hold/Sell screen, a Nifty 50
Top Buys/Sells scan, and a full per-company research page — backed by a real
SQLite database.

Sibling to `../findash` (offline financial-statement analysis) and
`../clientresearch` (single-ticker live report). AlphaDesk reuses
`clientresearch`'s `yfinance`-based fetch/concern-flag logic
(`backend/market_data.py`) and adds the workflow layer neither of those apps has.

`../alphadesk-solo` is a preserved standalone snapshot of the original
single-user version (own venv, own database), kept as a backup from before
multi-user accounts were added.

## Accounts

No login screen at all. The app opens straight to the Watchlist — a session
cookie is minted silently on the first request, so each browser still gets
its own private watchlist/portfolio/notes/thesis/estimates/calendar under
the hood, it's just never surfaced as a sign-in step. The Daily Screen
(Nifty 50 scan) and Sectors tab are the shared, non-personal views everyone
sees the same data for.

There's no accounts table anyone fills in and nothing to persist across a
redeploy wipe by design — a fresh visit just gets a fresh anonymous session,
same as before.

The one owner/admin identity is claimed via a hidden URL parameter
(`?admin=<key>`, matched against `ALPHADESK_OWNER_EMAIL`, default
`adit.shiv@1805`) instead of a login form — visiting that URL once quietly
upgrades the current session and strips the parameter from the address bar.
No one else ever sees a way to attempt this.

## Run it

```bash
cd alphadesk
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app.py
```

Opens `http://127.0.0.1:8010` in your browser automatically, straight into
the app — nothing to sign in with.

## What's here

- **Watchlist** — type-ahead search over the tracked set (see "Data model"
  below), each row showing price, concern-flag count, and the rule-based
  Buy/Hold/Sell call.
- **Company research page** — full snapshot (price, valuation, profitability,
  growth), a 52-week range chart, a margins bar chart, an ownership donut
  (insiders/institutions/public), the full raw-data table (60+ fields, every
  one with a hover tooltip explaining what it means), concern flags, a
  transparent recommendation banner, notes (append-only log), thesis/risks/
  catalysts, and an estimates-vs-actuals tracker.
- **Portfolio** — log quantity and buy price per holding, see P&L (with a
  diverging bar chart) and portfolio allocation (bar + donut chart) update
  automatically. Layer in your own qualitative judgment — management
  quality, governance risk, regulatory risk, competitive moat — and the app
  combines that with the financial signal into a holistic Buy More / Hold /
  Trim / Exit consensus, complete with the reasoning behind it.
- **Daily Screen** — the full Nifty 50 ranked into Top 10 Buys / Top 10 Sells
  *within* each stock's own rule-based label (so a "Buy" never shows up
  under Sells), plus a Buy/Hold/Sell distribution bar across all 50. Click
  any row to jump straight into its research page.
- **Compare** — pick up to 4 companies and see valuation, profitability, and
  rule-based call side by side.
- **Sectors** — every tracked company grouped by sector (Financial Services,
  Healthcare, Technology, etc. — Yahoo's own sector taxonomy, the closest
  thing to a BFSI/Pharma/IT-style breakdown), each with price and call, for
  browsing by sector instead of searching one name at a time.
- **Calendar** — cross-company event list (earnings, investor days, etc.),
  add manually.
- All monetary figures convert to ₹ automatically for non-Indian listings,
  using an FX rate captured at the same time as the rest of the data.

**Data model**: only the tracked set — the Nifty 50 plus a curated list of
other prominent Indian-listed names often in the news (PSU banks, defense,
big recent IPOs like Swiggy/Ola Electric/Hyundai India, etc.; ~89 companies
total as of the last refresh) — is covered with real numbers (price,
valuation, raw data, news, price history). See "Data refresh" below for why
and how that data gets updated, and `backend/data/extra_tracked_list.csv` to
add or remove names from the non-Nifty-50 part of the list. Search
(Watchlist, Portfolio, Compare) only surfaces tracked companies, so there's
nothing to add that would show up without real data.

Data lives in `alphadesk.sqlite3` in this folder — nothing leaves your
machine except the NSE company-directory refresh (static list, not prices).

## Known limitations

- Coverage is limited to the Nifty 50 — deliberate tradeoff, see "Data
  refresh" below. Search only surfaces those 50, so this isn't usually
  visible day to day.
- Data quality depends on what Yahoo Finance returned at the time of the
  last refresh; some fields are `None` for certain exchanges (e.g. Indian
  NSE tickers often lack `currentRatio`/`quickRatio`/`returnOnEquity`).
- Calendar events must be added manually — `next_earnings_date` on the
  company snapshot is whatever `yfinance` returned at refresh time, not
  guaranteed to still be accurate.
- Notes are an append-only log rather than true diff-based version history —
  simplest way to preserve "what did I think and when" without building a full
  versioning system.
- Real company logos (via Yahoo's on-file website → Clearbit) depend on that
  external service being reachable and having a match — falls back to a
  generated initials badge automatically when it isn't.
- Runs locally over plain HTTP — session cookies aren't marked `Secure`. Fine
  on `localhost` or a trusted local network; if you ever expose this beyond
  that (a tunnel, a real deployment), put HTTPS in front of it first.
- No account deletion/data-purge endpoint yet.
- Schema is plain SQLite via stdlib `sqlite3`, no ORM — a straightforward
  port to Postgres later if this ever needs to scale past a small group on
  one machine.

## Phase 2 ideas (not built yet)

- Task/pipeline board (models to update, notes due, calls to schedule)
- Filings/news aggregator filtered to your coverage list

## Data refresh

**Company data (prices, valuation, news, history) is never fetched live by
the running app.** Render's shared IP gets rate-limited by Yahoo Finance too
unreliably for live per-request fetches to be usable — so instead, every
tracked company's full snapshot/raw-data/news/price-history lives in
`backend/data/manual_quotes.json`, committed to the repo, and is only ever
updated by running one script and redeploying:

```bash
venv\Scripts\python.exe -m backend.tools.refresh_manual_quotes
```

Run it from a machine Yahoo isn't currently rate-limiting (never from Render
itself), then commit and push `backend/data/manual_quotes.json` to ship the
refresh. The whole app — Watchlist, Company page, Portfolio, Daily Screen,
Compare — reads from this one file; nothing about it happens automatically.

Separately, the NSE company directory (`backend/data/nse_equity_list.csv`,
used only for watchlist/portfolio search, not for pricing) auto-refreshes
from NSE's archive on server startup if older than 7 days (silently keeps
the cached copy if NSE is unreachable). The Nifty 50 constituent list
(`backend/data/nifty50_list.csv`) is a static snapshot — re-download it
manually from NSE's index archive if constituents change.

---

Built by **Aditi Chaubey** — CA, 5+ years across Forex Trading, Accounting,
Finance, Equity Research, and Automation.
