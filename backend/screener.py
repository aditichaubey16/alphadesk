"""Nifty 50 Buy/Sell screen. Scans the fixed, curated Nifty 50 index and
ranks it by the same transparent rule-based `build_recommendation` used
everywhere else in the app: concern-flag severity + analyst-target upside.

Built from the manually-refreshed dataset (backend/data/manual_quotes.json,
see tools/refresh_manual_quotes.py) — no live Yahoo calls happen here.
Recomputing the rankings from that data is cheap (pure Python, no network),
so this just runs fresh on every request rather than caching to disk; the
"as of" date shown to users is the manual dataset's refresh date, not
today, unless a refresh happened today.
"""
from __future__ import annotations

import csv
from datetime import date, datetime, timezone
from pathlib import Path

from . import market_data

_NIFTY50_CSV = Path(__file__).parent / "data" / "nifty50_list.csv"

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


def get_daily_screen(force_refresh: bool = False) -> dict:
    """`force_refresh` is accepted for API compatibility with the old
    once-a-day-cache model but is now a no-op — every call already
    recomputes fresh from the manually-refreshed dataset."""
    return _compute()


def _compute() -> dict:
    candidates = []
    errors = []
    for entry in _load_nifty50():
        symbol = entry["symbol"]
        try:
            quote = market_data.get_daily_quote(symbol)
            snapshot = quote["snapshot"]
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

    as_of = market_data._load_manual_quotes().get("as_of")

    result = {
        "date": as_of,
        "computed_at": datetime.now(timezone.utc).isoformat(),
        "universe": "Nifty 50",
        "universe_size": len(_load_nifty50()),
        "label_counts": label_counts,
        "top_buys": top_buys,
        "top_sells": top_sells,
        "errors": errors,
        "caution": (
            "Numbers only, across all 50 names: this scan is purely concern-flag severity and "
            "analyst-target upside from Yahoo Finance's data — it has no idea about news, "
            "management commentary, regulatory developments, or anything else qualitative for any "
            "of these companies. Ranked within each stock's own rule-based Buy/Hold/Sell call, not "
            "by raw upside alone — so a stock never appears under Sells while still labeled Buy. "
            "Nifty 50 names rarely trigger an outright Sell under this rule scan, so the Sells list "
            "may run short and lean on Hold-labeled names with the weakest upside instead of true "
            "Sells; check each label before acting. A personal, rule-based view — not personalized "
            "investment advice, not a real-time feed, and not based on trading volume or actual "
            f"order flow. Data as of {as_of or 'unknown'} — refreshed manually, not automatically. "
            "Check current news and verify independently before relying on any of these calls."
        ),
    }
    return result
