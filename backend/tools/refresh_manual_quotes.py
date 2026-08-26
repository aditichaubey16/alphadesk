"""Manual data refresh for the Nifty 50 tracked set.

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
"""
from __future__ import annotations

import datetime as _dt
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend import market_data, screener  # noqa: E402

OUTPUT_PATH = Path(__file__).resolve().parents[1] / "data" / "manual_quotes.json"
HISTORY_PERIOD = "2y"  # covers every period option the UI offers up to 2y; 5y requests fall back to whatever's stored


def refresh() -> None:
    symbols = [entry["symbol"] for entry in screener._load_nifty50()]
    print(f"Refreshing {len(symbols)} symbols...")

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
        print("Re-run the script to retry — a partial file only overwrites symbols that succeeded this run is NOT how this works, it writes a fresh file each time. Fix failures before shipping.")

    data = {"as_of": _dt.date.today().isoformat(), "quotes": quotes}
    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")
    print(f"\nWrote {len(quotes)} symbols to {OUTPUT_PATH}")


if __name__ == "__main__":
    refresh()
