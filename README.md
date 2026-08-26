# AlphaDesk

A multi-user equity research workspace for Indian (NSE) markets: watchlist,
portfolio tracking with live P&L, a rule-based Buy/Hold/Sell screen, a daily
Nifty 50 Top Buys/Sells scan, and a full per-company research page — backed by
a real SQLite database.

Sibling to `../findash` (offline financial-statement analysis) and
`../clientresearch` (single-ticker live report). AlphaDesk reuses
`clientresearch`'s `yfinance`-based fetch/concern-flag logic
(`backend/market_data.py`) and adds the workflow layer neither of those apps has.

`../alphadesk-solo` is a preserved standalone snapshot of the original
single-user version (own venv, own database), kept as a backup from before
multi-user accounts were added.

## Accounts

Each person gets their own account — name, email, and a password they set at
signup (no OTP or email verification). Email is the login ID. Everything —
watchlist, portfolio, notes, thesis, estimates, calendar — is private to the
account that created it; the Daily Screen (Nifty 50 scan) is the one shared,
non-personal view everyone sees the same data for.

## Run it

```bash
cd alphadesk
python -m venv venv
venv\Scripts\pip install -r requirements.txt
venv\Scripts\python app.py
```

Opens `http://127.0.0.1:8010` in your browser automatically — sign up with a
name, email, and password to get started.

## What's here

- **Watchlist** — type-ahead search over the full local NSE company directory
  (2,500+ names, no live lookup until you add one), each row showing live
  price, concern-flag count, and the rule-based Buy/Hold/Sell call.
- **Company research page** — live snapshot (price, valuation, profitability,
  growth), a 52-week range chart, a margins bar chart, an ownership donut
  (insiders/institutions/public), the full raw-data table (60+ fields, every
  one with a hover tooltip explaining what it means), concern flags, a
  transparent recommendation banner, notes (append-only log), thesis/risks/
  catalysts, and an estimates-vs-actuals tracker.
- **Portfolio** — log quantity and buy price per holding, see live P&L
  (with a diverging bar chart) and portfolio allocation (bar + donut chart)
  update automatically. Layer in your own qualitative judgment — management
  quality, governance risk, regulatory risk, competitive moat — and the app
  combines that with the financial signal into a holistic Buy More / Hold /
  Trim / Exit consensus, complete with the reasoning behind it.
- **Daily Screen** — Nifty 50 scanned once a day (cached, with a manual
  Refresh Now), ranked into Top 10 Buys / Top 10 Sells *within* each stock's
  own rule-based label (so a "Buy" never shows up under Sells), plus a
  Buy/Hold/Sell distribution bar across the full 50-stock scan. Click any row
  to jump straight into its research page.
- **Calendar** — cross-company event list (earnings, investor days, etc.),
  add manually.
- All monetary figures convert to ₹ automatically for non-Indian listings,
  using a live FX rate (shown on the company page when conversion applies).

Data lives in `alphadesk.sqlite3` in this folder — nothing leaves your machine
except live `yfinance` lookups and the NSE/Nifty 50 list refresh.

## Known limitations

- Live data depends entirely on what Yahoo Finance returns for a given ticker;
  some fields are `None` for certain exchanges (e.g. Indian NSE tickers often
  lack `currentRatio`/`quickRatio`/`returnOnEquity` from this endpoint).
- Calendar events must be added manually — `next_earnings_date` on the company
  snapshot is best-effort from `yfinance`'s calendar data, not guaranteed.
- Notes are an append-only log rather than true diff-based version history —
  simplest way to preserve "what did I think and when" without building a full
  versioning system.
- The Daily Screen scans all 50 Nifty stocks synchronously — the first
  request of the day (or a manual refresh) blocks the server for a few
  seconds. Fine for single-user local use; would need to move to a background
  job if this were ever shared with concurrent users.
- Real company logos (via Yahoo's on-file website → Clearbit) depend on that
  external service being reachable and having a match — falls back to a
  generated initials badge automatically when it isn't.
- Runs locally over plain HTTP — session cookies aren't marked `Secure`. Fine
  on `localhost` or a trusted local network; if you ever expose this beyond
  that (a tunnel, a real deployment), put HTTPS in front of it first.
- No password reset flow yet — losing a password currently means a new
  account. No account deletion/data-purge endpoint either.
- Schema is plain SQLite via stdlib `sqlite3`, no ORM — a straightforward
  port to Postgres later if this ever needs to scale past a small group on
  one machine.

## Phase 2 ideas (not built yet)

- Peer comparison / valuation screener across a sector
- Task/pipeline board (models to update, notes due, calls to schedule)
- Filings/news aggregator filtered to your coverage list
- Multi-user accounts and sharing
- In-app data export (JSON dump of watchlist/portfolio/notes) for backup
  peace of mind beyond the OneDrive-synced `.sqlite3` file

## Data refresh

- The NSE company directory (`backend/data/nse_equity_list.csv`) and Nifty 50
  list (`backend/data/nifty50_list.csv`) are static snapshots. The NSE list
  auto-refreshes from NSE's archive on server startup if older than 7 days
  (silently keeps the cached copy if NSE is unreachable). Re-download the
  Nifty 50 list manually from NSE's index archive if constituents change.

---

Built by **Aditi Chaubey** — CA, 5+ years across Forex Trading, Accounting,
Finance, Equity Research, and Automation.
