"""The full NSE main-board equity list, loaded from a local CSV snapshot
(`data/nse_equity_list.csv`, NSE's own published `EQUITY_L.csv`) so browsing
and searching it never touches yfinance or the network on every request —
only adding a company to the watchlist triggers a live lookup.

The snapshot drifts (new listings, delistings) so `refresh_if_stale()` is
called once at server startup: if the cached file is older than
`_MAX_AGE_DAYS`, it re-downloads from NSE's archive. If NSE is unreachable
(offline, blocked, etc.) it silently keeps using the existing cached file —
staleness never breaks the app, it just means the list lags reality a bit.
"""
from __future__ import annotations

import csv
import time
from pathlib import Path

_CSV_PATH = Path(__file__).parent / "data" / "nse_equity_list.csv"
_CSV_URL = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
_MAX_AGE_DAYS = 7
_CACHE: list[dict] | None = None


def refresh_if_stale(max_age_days: float = _MAX_AGE_DAYS) -> None:
    """Re-download the NSE list if the cached copy is older than
    `max_age_days` (or missing). Never raises — a failed refresh just means
    the existing (or absent) cache is used as-is."""
    global _CACHE
    try:
        if _CSV_PATH.exists():
            age_days = (time.time() - _CSV_PATH.stat().st_mtime) / 86400
            if age_days < max_age_days:
                return
        import requests

        headers = {
            "User-Agent": (
                "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
            ),
            "Referer": "https://www.nseindia.com/",
        }
        resp = requests.get(_CSV_URL, headers=headers, timeout=20)
        resp.raise_for_status()
        if len(resp.content) < 1000:  # sanity check — a real listing is hundreds of KB
            return
        tmp_path = _CSV_PATH.with_suffix(".csv.tmp")
        _CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        tmp_path.write_bytes(resp.content)
        tmp_path.replace(_CSV_PATH)
        _CACHE = None  # force reload from the freshly written file
        print(f"[universe] Refreshed NSE equity list from {_CSV_URL}")
    except Exception as e:
        print(f"[universe] Could not refresh NSE equity list, using cached copy: {e}")


def _load() -> list[dict]:
    global _CACHE
    if _CACHE is not None:
        return _CACHE
    rows = []
    with open(_CSV_PATH, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        reader.fieldnames = [fn.strip() for fn in reader.fieldnames]
        for r in reader:
            nse_symbol = (r.get("SYMBOL") or "").strip()
            name = (r.get("NAME OF COMPANY") or "").strip()
            if not nse_symbol or not name:
                continue
            rows.append(
                {
                    "symbol": f"{nse_symbol}.NS",
                    "nse_symbol": nse_symbol,
                    "name": name,
                    "isin": (r.get("ISIN NUMBER") or "").strip(),
                    "listed_on": (r.get("DATE OF LISTING") or "").strip(),
                }
            )
    rows.sort(key=lambda x: x["name"])
    _CACHE = rows
    return rows


def universe_count() -> int:
    return len(_load())


def search_universe(query: str, limit: int = 60) -> list[dict]:
    rows = _load()
    if not query or not query.strip():
        return rows[:limit]
    q = query.strip().lower()
    matches = [r for r in rows if q in r["name"].lower() or q in r["nse_symbol"].lower()]
    return matches[:limit]
