"""Daily Nifty 50 Buy/Sell screen. Scans a fixed, curated index (not the full
NSE universe — 2,500+ live lookups isn't feasible to run synchronously) and
ranks it by the same transparent rule-based `build_recommendation` used
everywhere else in the app: concern-flag severity + analyst-target upside.

Computed once per calendar day and cached to disk (`data/daily_screen_cache.json`)
so opening the tab doesn't re-run ~50 live yfinance lookups every time — only
the first request of the day (or an explicit refresh) pays that cost.
"""
from __future__ import annotations

import csv
import json
import time
from datetime import date, datetime, timezone
from pathlib import Path

from . import market_data

_NIFTY50_CSV = Path(__file__).parent / "data" / "nifty50_list.csv"
_CACHE_PATH = Path(__file__).parent / "data" / "daily_screen_cache.json"

_SYMBOLS_CACHE: list[dict] | None = None


def _load_nifty50() -> list[dict]:
    global _SYMBOLS_CACHE
    if _SYMBOLS_CACHE is not None:
        return _SYMBOLS_CACHE
    rows = []
    with open(_NIFTY50_CSV, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for r in reader:
            symbol = (r.get("Symbol") or "").strip()
            name = (r.get("Company Name") or "").strip()
            if not symbol:
                continue
            rows.append({"symbol": f"{symbol}.NS", "name": name, "industry": (r.get("Industry") or "").strip()})
    _SYMBOLS_CACHE = rows
    return rows


def _today() -> str:
    return date.today().isoformat()


def _read_cache() -> dict | None:
    if not _CACHE_PATH.exists():
        return None
    try:
        return json.loads(_CACHE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return None


def _write_cache(data: dict) -> None:
    _CACHE_PATH.parent.mkdir(parents=True, exist_ok=True)
    _CACHE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def get_daily_screen(force_refresh: bool = False) -> dict:
    """Returns today's cached Top-10-Buys / Top-10-Sells screen, computing it
    first if today's cache doesn't exist yet or `force_refresh` is set."""
    cached = _read_cache()
    if cached and cached.get("date") == _today() and not force_refresh:
        return cached
    return _compute_and_cache()


def _compute_and_cache() -> dict:
    candidates = []
    errors = []
    for entry in _load_nifty50():
        symbol = entry["symbol"]
        try:
            snapshot = market_data.fetch_snapshot(symbol)
            concerns = market_data.flag_concerns(snapshot)
            rec = market_data.build_recommendation(snapshot, concerns)
            candidates.append(
                {
                    "symbol": symbol,
                    "name": entry["name"] or snapshot.get("name") or symbol,
                    "industry": entry["industry"],
                    "price": snapshot.get("price"),
                    "logo_url": snapshot.get("logo_url"),
                    "upside_pct": rec.get("upside_pct"),
                    "label": rec.get("label"),
                    "reasoning": rec.get("reasoning"),
                    "concerns": concerns,
                    "high_flags": sum(1 for c in concerns if c["severity"] == "high"),
                    "medium_flags": sum(1 for c in concerns if c["severity"] == "medium"),
                }
            )
        except Exception as e:
            errors.append({"symbol": symbol, "error": str(e)})

    # Rank within label buckets, not by raw upside alone — otherwise a stock
    # the rule scan calls "Buy" (clean flags, even with slim/negative upside)
    # could land in the Sells list purely because its upside number is low,
    # which reads as the app contradicting its own call.
    with_upside = [c for c in candidates if c["upside_pct"] is not None]
    buy_pool = sorted((c for c in with_upside if c["label"] == "Buy"), key=lambda c: -c["upside_pct"])
    sell_pool = sorted((c for c in with_upside if c["label"] == "Sell"), key=lambda c: c["upside_pct"])
    hold_pool_desc = sorted((c for c in with_upside if c["label"] == "Hold"), key=lambda c: -c["upside_pct"])
    hold_pool_asc = sorted((c for c in with_upside if c["label"] == "Hold"), key=lambda c: c["upside_pct"])

    # Fill remaining slots from Hold (never Sell in Top Buys, never Buy in Top
    # Sells) so a stock never contradicts its own label — and never let the
    # same stock fill both lists' overflow.
    top_buys = (buy_pool + hold_pool_desc)[:10]
    used_symbols = {c["symbol"] for c in top_buys}
    top_sells = (sell_pool + [c for c in hold_pool_asc if c["symbol"] not in used_symbols])[:10]

    label_counts = {"Buy": 0, "Hold": 0, "Sell": 0}
    for c in candidates:
        if c["label"] in label_counts:
            label_counts[c["label"]] += 1

    result = {
        "date": _today(),
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "universe": "Nifty 50",
        "universe_size": len(_load_nifty50()),
        "label_counts": label_counts,
        "top_buys": top_buys,
        "top_sells": top_sells,
        "errors": errors,
        "caution": (
            "Ranked within each stock's own rule-based Buy/Hold/Sell call (concern-flag severity "
            "and analyst-target upside), not by raw upside alone — so a stock never appears under "
            "Sells while still labeled Buy. Nifty 50 names rarely trigger an outright Sell under "
            "this rule scan, so the Sells list may run short and lean on Hold-labeled names with "
            "the weakest upside instead of true Sells; check each label before acting. Not "
            "personalized investment advice, not a real-time feed, and not based on trading volume "
            "or actual order flow. Refreshed once per day (or on manual refresh). Verify "
            "independently before acting."
        ),
    }
    _write_cache(result)
    return result
