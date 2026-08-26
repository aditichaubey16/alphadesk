"""Manual data refresh for the tracked company set (Nifty 50 + extras).

AlphaDesk doesn't hit Yahoo Finance live from the running app anymore —
Render's shared IP gets rate-limited too unreliably for that to be usable.
Instead, all company data (snapshot, raw parameters, news, price history)
lives in backend/data/manual_quotes.json, committed to the repo, and is only
ever refreshed by running this script and redeploying.

Usage:
    venv\\Scripts\\python.exe -m backend.tools.refresh_manual_quotes

Run this from wherever Yahoo isn't currently rate-limiting you (this repo's
dev machine has been fine) — never from Render itself. Commit and push
backend/data/manual_quotes.json afterwards to ship the refreshed data.

Coverage = Nifty 50 (backend/data/nifty50_list.csv, also what the Daily
Screen ranks) + a curated list of other prominent Indian-listed companies
that come up often in the news (backend/data/extra_tracked_list.csv) —
banks, defense, recent big IPOs, etc. Edit that CSV to add/remove names,
then re-run this script.
"""
from __future__ import annotations

import csv
import datetime as _dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import market_data, screener  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "manual_quotes.json"
EXTRA_LIST_PATH = Path(__file__).resolve().parents[1] / "data" / "extra_tracked_list.csv"
HISTORY_PERIOD = "2y"  # covers every period option the UI offers up to 2y; 5y requests fall back to whatever's stored


def _load_extra_symbols() -> list[str]:
    if not EXTRA_LIST_PATH.exists():
        return []
    with open(EXTRA_LIST_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        return [f"{(r.get('Symbol') or '').strip()}.NS" for r in reader if r.get("Symbol")]


def refresh() -> None:
    nifty_symbols = [entry["symbol"] for entry in screener._load_nifty50()]
    extra_symbols = _load_extra_symbols()
    symbols = list(dict.fromkeys(nifty_symbols + extra_symbols))  # de-dupe, preserve order
    print(f"Refreshing {len(nifty_symbols)} Nifty 50 + {len(extra_symbols)} extra symbols ({len(symbols)} total)...")

    quotes: dict[str, dict] = {}
    failures: list[str] = []

    for i, symbol in enumerate(symbols, 1):
        try:
            snapshot = market_data.fetch_snapshot(symbol)
            raw = market_data.fetch_raw_parameters(symbol)
            try:
                news = market_data.fetch_recent_news(symbol)
            except Exception:
                news = []
            try:
                history = market_data.fetch_price_history(symbol, HISTORY_PERIOD)
            except Exception:
                history = []
            quotes[symbol] = {"snapshot": snapshot, "raw": raw, "news": news, "history": history}
            price = snapshot.get("price")
            print(f"[{i}/{len(symbols)}] {symbol}: OK (price={price})")
        except Exception as e:
            failures.append(symbol)
            print(f"[{i}/{len(symbols)}] {symbol}: FAILED ({e})")
        time.sleep(0.3)  # be polite even to a non-rate-limited IP

    if failures:
        print(f"\n{len(failures)} symbol(s) failed and are NOT in the output: {', '.join(failures)}")
        print("This script writes a fresh file each run, so a failed symbol just won't be in it. Re-run to retry before shipping.")

    data = {"as_of": _dt.date.today().isoformat(), "quotes": quotes}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nWrote {len(quotes)} symbols to {OUTPUT_PATH}")


if __name__ == "__main__":
    refresh()
