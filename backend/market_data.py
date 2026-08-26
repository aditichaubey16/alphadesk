"""Live market data via yfinance. Adapted from ../clientresearch/analysis.py.

No LLM step — every number comes straight from Yahoo Finance, and every
concern flag is a named threshold rule, so results are traceable.
"""
from __future__ import annotations

import datetime as _dt
import json
import time

import yfinance as yf

_FX_CACHE: dict[str, tuple[float, float]] = {}  # currency -> (rate_to_inr, fetched_at)
_FX_TTL_SECONDS = 900

# Shared, short-TTL cache for yfinance's `.info` dict, keyed by symbol.
# fetch_snapshot / fetch_raw_parameters / fetch_price_history each used to
# call `yf.Ticker(symbol).info` independently — 2-3 redundant Yahoo requests
# per single page view. On a shared cloud IP (Render, etc.) that adds up fast
# and is exactly what trips Yahoo's rate limiting, so everything routes
# through this cache instead. A short TTL keeps prices reasonably live while
# cutting request volume drastically, especially for popular symbols multiple
# users are looking at.
_INFO_CACHE: dict[str, tuple[dict, float]] = {}
_INFO_TTL_SECONDS = 90


def _fetch_info_with_retry(t: "yf.Ticker", attempts: int = 2, delay_seconds: float = 2.5) -> dict:
    """Yahoo's rate-limit errors are often transient (a burst, not a hard
    ban) — one short retry recovers a meaningful fraction of them."""
    last_err = None
    for attempt in range(attempts):
        try:
            info = t.info
            if info:
                return info
        except Exception as e:
            last_err = e
        if attempt < attempts - 1:
            time.sleep(delay_seconds)
    if last_err:
        raise last_err
    return {}


def _get_info(symbol: str) -> tuple[dict, "yf.Ticker"]:
    now = time.time()
    cached = _INFO_CACHE.get(symbol)
    if cached and now - cached[1] < _INFO_TTL_SECONDS:
        return cached[0], yf.Ticker(symbol)
    t = yf.Ticker(symbol)
    info = _fetch_info_with_retry(t)
    _INFO_CACHE[symbol] = (info, now)
    return info, t


def get_fx_to_inr(currency: str | None) -> float | None:
    """1 unit of `currency` in INR, via yfinance's `{CCY}INR=X` pair. Cached
    in-process for 15 minutes since every snapshot/raw-data fetch calls this."""
    if not currency:
        return None
    currency = currency.upper()
    if currency == "INR":
        return 1.0
    now = time.time()
    cached = _FX_CACHE.get(currency)
    if cached and now - cached[1] < _FX_TTL_SECONDS:
        return cached[0]
    try:
        pair = yf.Ticker(f"{currency}INR=X")
        rate = None
        try:
            rate = pair.fast_info.get("last_price")
        except Exception:
            rate = None
        if not rate:
            info = pair.info or {}
            rate = info.get("regularMarketPrice") or info.get("currentPrice")
        if rate:
            _FX_CACHE[currency] = (float(rate), now)
            return float(rate)
    except Exception:
        pass
    return None


def search_companies(query: str, limit: int = 8) -> list[dict]:
    if not query or not query.strip():
        return []
    results = yf.Search(query, max_results=limit).quotes
    out = []
    for r in results:
        if r.get("quoteType") != "EQUITY":
            continue
        out.append(
            {
                "symbol": r.get("symbol"),
                "name": r.get("longname") or r.get("shortname") or r.get("symbol"),
                "exchange": r.get("exchDisp"),
                "sector": r.get("sectorDisp"),
            }
        )
    return out


def _pct(x):
    return None if x is None else round(x * 100, 2)


def _logo_url(info: dict) -> str | None:
    """Real company logo via Clearbit's free logo API, keyed off the domain
    from yfinance's `website` field — no API key, no scraping. Falls back to
    None (frontend shows a generated initials badge instead) when Yahoo
    doesn't have a website on file, which is common for small/illiquid names."""
    website = info.get("website")
    if not website:
        return None
    domain = website.replace("https://", "").replace("http://", "").split("/")[0]
    domain = domain[4:] if domain.startswith("www.") else domain
    if not domain or "." not in domain:
        return None
    return f"https://logo.clearbit.com/{domain}"


# Snapshot fields that are currency-denominated amounts (as opposed to
# ratios/percentages/counts), so these are the ones converted to INR.
_SNAPSHOT_MONETARY_FIELDS = {"price", "prev_close", "market_cap", "52w_high", "52w_low", "target_mean_price"}


def fetch_snapshot(symbol: str) -> dict:
    info, t = _get_info(symbol)
    orig_currency = info.get("currency")
    snapshot = {
        "symbol": symbol,
        "name": info.get("longName") or info.get("shortName") or symbol,
        "sector": info.get("sector"),
        "industry": info.get("industry"),
        "currency": orig_currency,
        "price": info.get("currentPrice") or info.get("regularMarketPrice"),
        "prev_close": info.get("previousClose"),
        "market_cap": info.get("marketCap"),
        "52w_high": info.get("fiftyTwoWeekHigh"),
        "52w_low": info.get("fiftyTwoWeekLow"),
        "pe_trailing": info.get("trailingPE"),
        "pe_forward": info.get("forwardPE"),
        "price_to_book": info.get("priceToBook"),
        "debt_to_equity": info.get("debtToEquity"),
        "current_ratio": info.get("currentRatio"),
        "quick_ratio": info.get("quickRatio"),
        "profit_margin_pct": _pct(info.get("profitMargins")),
        "roe_pct": _pct(info.get("returnOnEquity")),
        "revenue_growth_pct": _pct(info.get("revenueGrowth")),
        "earnings_growth_pct": _pct(info.get("earningsGrowth")),
        "dividend_yield_pct": info.get("dividendYield"),
        "target_mean_price": info.get("targetMeanPrice"),
        "analyst_recommendation": info.get("recommendationKey"),
        "next_earnings_date": _next_earnings_date(t),
        "logo_url": _logo_url(info),
    }

    fx_rate = get_fx_to_inr(orig_currency)
    if orig_currency and orig_currency.upper() != "INR" and fx_rate:
        for key in _SNAPSHOT_MONETARY_FIELDS:
            if snapshot.get(key) is not None:
                snapshot[key] = round(snapshot[key] * fx_rate, 2)
        snapshot["currency"] = "INR"
        snapshot["orig_currency"] = orig_currency
        snapshot["fx_rate"] = round(fx_rate, 4)
    else:
        snapshot["orig_currency"] = orig_currency
        snapshot["fx_rate"] = 1.0

    return snapshot


_VALID_HISTORY_PERIODS = {"1mo", "3mo", "6mo", "1y", "2y", "5y"}


def fetch_price_history(symbol: str, period: str = "6mo") -> list[dict]:
    """Daily close price series for the trailing `period`, converted to INR
    like everything else in the app. Used for the price-trend line chart —
    a separate live call from `fetch_snapshot` since most views never need it."""
    if period not in _VALID_HISTORY_PERIODS:
        period = "6mo"
    info, t = _get_info(symbol)
    hist = t.history(period=period)
    if hist.empty:
        return []
    currency = info.get("currency")
    fx_rate = get_fx_to_inr(currency)
    convert = bool(currency and currency.upper() != "INR" and fx_rate)

    points = []
    for date, row in hist.iterrows():
        close = float(row["Close"])
        if convert:
            close = close * fx_rate
        points.append({"date": date.strftime("%Y-%m-%d"), "close": round(close, 2)})
    return points


def _parse_quote_row(row: dict) -> dict:
    return {
        "snapshot": json.loads(row["snapshot_json"]),
        "raw": json.loads(row["raw_json"]) if row.get("raw_json") else [],
        "news": json.loads(row["news_json"]) if row.get("news_json") else [],
        "quote_date": row["quote_date"],
    }


def get_daily_quote(symbol: str) -> dict:
    """The one place that actually hits Yahoo for a symbol's snapshot/raw
    data/news. Fetches live at most once per calendar day — every request
    for that symbol that day (from any user) reads the same cached row
    instead of triggering its own Yahoo call, which is what was tripping
    rate limits on a shared cloud IP. If today's live fetch fails, falls
    back to the most recent successfully cached quote (however old) and
    marks the result `is_stale=True` instead of erroring — a rate-limited
    server shows yesterday's numbers, not a blank page.

    Returns {snapshot, raw, news, quote_date, is_stale}.
    """
    from . import db  # local import: db.py has no reverse dependency on this module

    today = _dt.date.today().isoformat()

    cached = db.get_daily_quote(symbol, today)
    if cached:
        result = _parse_quote_row(cached)
        result["is_stale"] = False
        return result

    try:
        snapshot = fetch_snapshot(symbol)
        raw = fetch_raw_parameters(symbol)
        try:
            news = fetch_recent_news(symbol)
        except Exception:
            news = []
        db.save_daily_quote(symbol, today, json.dumps(snapshot), json.dumps(raw), json.dumps(news))
        return {"snapshot": snapshot, "raw": raw, "news": news, "quote_date": today, "is_stale": False}
    except Exception:
        latest = db.get_latest_daily_quote(symbol)
        if latest:
            result = _parse_quote_row(latest)
            result["is_stale"] = True
            return result
        raise


def _next_earnings_date(t: "yf.Ticker") -> str | None:
    try:
        cal = t.calendar
        if isinstance(cal, dict):
            dates = cal.get("Earnings Date")
            if dates:
                d = dates[0] if isinstance(dates, list) else dates
                return str(d)
    except Exception:
        pass
    return None


# Full parameter set an equity research analyst typically checks, grouped the
# way a research note would group them. Pulled straight from yfinance's `info`
# dict — nothing computed or inferred. Indian NSE/BSE listings (symbol suffix
# `.NS` / `.BO`) commonly leave several of these `None` (Yahoo's coverage of
# Indian fundamentals is thinner than US) — each field just shows blank rather
# than being guessed.
_RAW_FIELD_GROUPS: list[tuple[str, list[tuple[str, str]]]] = [
    (
        "Company",
        [
            ("longName", "Name"),
            ("sector", "Sector"),
            ("industry", "Industry"),
            ("country", "Country"),
            ("exchange", "Exchange"),
            ("currency", "Currency"),
            ("fullTimeEmployees", "Employees"),
            ("longBusinessSummary", "Business Summary"),
        ],
    ),
    (
        "Price & Trading",
        [
            ("currentPrice", "Current Price"),
            ("previousClose", "Previous Close"),
            ("open", "Open"),
            ("dayLow", "Day Low"),
            ("dayHigh", "Day High"),
            ("fiftyTwoWeekLow", "52-Week Low"),
            ("fiftyTwoWeekHigh", "52-Week High"),
            ("fiftyDayAverage", "50-Day Avg"),
            ("twoHundredDayAverage", "200-Day Avg"),
            ("volume", "Volume"),
            ("averageVolume", "Avg Volume (10d)"),
            ("beta", "Beta"),
        ],
    ),
    (
        "Valuation",
        [
            ("marketCap", "Market Cap"),
            ("enterpriseValue", "Enterprise Value"),
            ("trailingPE", "P/E (Trailing)"),
            ("forwardPE", "P/E (Forward)"),
            ("pegRatio", "PEG Ratio"),
            ("priceToBook", "Price/Book"),
            ("priceToSalesTrailing12Months", "Price/Sales (TTM)"),
            ("enterpriseToRevenue", "EV/Revenue"),
            ("enterpriseToEbitda", "EV/EBITDA"),
        ],
    ),
    (
        "Per-Share Data",
        [
            ("trailingEps", "EPS (Trailing)"),
            ("forwardEps", "EPS (Forward)"),
            ("bookValue", "Book Value/Share"),
            ("revenuePerShare", "Revenue/Share"),
        ],
    ),
    (
        "Profitability",
        [
            ("grossMargins", "Gross Margin"),
            ("operatingMargins", "Operating Margin"),
            ("profitMargins", "Net Margin"),
            ("ebitdaMargins", "EBITDA Margin"),
            ("returnOnAssets", "Return on Assets"),
            ("returnOnEquity", "Return on Equity"),
        ],
    ),
    (
        "Growth",
        [
            ("revenueGrowth", "Revenue Growth (YoY)"),
            ("earningsGrowth", "Earnings Growth (YoY)"),
            ("earningsQuarterlyGrowth", "Earnings Growth (QoQ)"),
        ],
    ),
    (
        "Balance Sheet & Cash Flow",
        [
            ("totalCash", "Total Cash"),
            ("totalDebt", "Total Debt"),
            ("debtToEquity", "Debt/Equity"),
            ("currentRatio", "Current Ratio"),
            ("quickRatio", "Quick Ratio"),
            ("totalRevenue", "Total Revenue"),
            ("ebitda", "EBITDA"),
            ("operatingCashflow", "Operating Cash Flow"),
            ("freeCashflow", "Free Cash Flow"),
        ],
    ),
    (
        "Dividend",
        [
            ("dividendRate", "Dividend Rate"),
            ("dividendYield", "Dividend Yield"),
            ("payoutRatio", "Payout Ratio"),
            ("exDividendDate", "Ex-Dividend Date"),
            ("fiveYearAvgDividendYield", "5Y Avg Div Yield"),
        ],
    ),
    (
        "Ownership & Shares",
        [
            ("sharesOutstanding", "Shares Outstanding"),
            ("floatShares", "Float Shares"),
            ("heldPercentInsiders", "Held by Insiders"),
            ("heldPercentInstitutions", "Held by Institutions"),
            ("sharesShort", "Shares Short"),
        ],
    ),
    (
        "Analyst Coverage",
        [
            ("numberOfAnalystOpinions", "# Analysts"),
            ("recommendationKey", "Consensus Rating"),
            ("targetLowPrice", "Target Low"),
            ("targetMeanPrice", "Target Mean"),
            ("targetHighPrice", "Target High"),
        ],
    ),
]

_PCT_FIELDS = {
    "grossMargins", "operatingMargins", "profitMargins", "ebitdaMargins",
    "returnOnAssets", "returnOnEquity", "revenueGrowth", "earningsGrowth",
    "earningsQuarterlyGrowth", "payoutRatio",
    "heldPercentInsiders", "heldPercentInstitutions",
}

# yfinance returns these already scaled as percentage points (e.g. 0.46 = 0.46%),
# unlike the fraction-of-1 fields above (e.g. profitMargins 0.0661 = 6.61%) —
# a Yahoo API quirk. Leave them as-is, don't multiply by 100.
_ALREADY_PCT_FIELDS = {"dividendYield", "fiveYearAvgDividendYield"}

_UNIX_DATE_FIELDS = {"exDividendDate"}

# Raw-data fields that are currency-denominated amounts (prices, per-share
# figures, balance-sheet/cash-flow totals) — converted to INR. Ratios,
# margins, multiples (P/E, P/B, EV/EBITDA...), share counts, and dates are
# currency-independent and left as-is.
_RAW_MONETARY_FIELDS = {
    "currentPrice", "previousClose", "open", "dayLow", "dayHigh",
    "fiftyTwoWeekLow", "fiftyTwoWeekHigh", "fiftyDayAverage", "twoHundredDayAverage",
    "marketCap", "enterpriseValue",
    "trailingEps", "forwardEps", "bookValue", "revenuePerShare",
    "totalCash", "totalDebt", "totalRevenue", "ebitda", "operatingCashflow", "freeCashflow",
    "dividendRate",
    "targetLowPrice", "targetMeanPrice", "targetHighPrice",
}


def fetch_raw_parameters(symbol: str) -> list[dict]:
    """All equity-research-relevant fields yfinance exposes for this ticker,
    grouped for display. Every value is the raw field straight from Yahoo's
    `info` payload — `None` means Yahoo doesn't have it for this listing.
    Monetary fields are converted to INR when the listing trades in another
    currency; ratios/percentages/counts are left as reported."""
    import datetime as _dt

    info, t = _get_info(symbol)
    orig_currency = info.get("currency")
    fx_rate = get_fx_to_inr(orig_currency)
    convert = bool(orig_currency and orig_currency.upper() != "INR" and fx_rate)

    groups = []
    for group_name, fields in _RAW_FIELD_GROUPS:
        rows = []
        for key, label in fields:
            value = info.get(key)
            if key == "currency" and convert:
                value = "INR"
            elif key in _RAW_MONETARY_FIELDS and convert and isinstance(value, (int, float)):
                value = round(value * fx_rate, 2)
            elif key in _PCT_FIELDS and isinstance(value, (int, float)):
                value = round(value * 100, 2)
            elif key in _ALREADY_PCT_FIELDS and isinstance(value, (int, float)):
                value = round(value, 2)
            elif key in _UNIX_DATE_FIELDS and isinstance(value, (int, float)):
                try:
                    value = _dt.datetime.fromtimestamp(value, tz=_dt.timezone.utc).strftime("%Y-%m-%d")
                except (OSError, OverflowError, ValueError):
                    pass
            rows.append({"key": key, "label": label, "value": value})
        groups.append({"group": group_name, "fields": rows})
    return groups


def _rules():
    return [
        (
            "high_leverage",
            lambda s: s["debt_to_equity"] is not None and s["debt_to_equity"] > 100,
            "high",
            lambda s: f"Debt/Equity is elevated at {s['debt_to_equity']:.1f}.",
        ),
        (
            "thin_liquidity",
            lambda s: s["current_ratio"] is not None and s["current_ratio"] < 1,
            "high",
            lambda s: f"Current ratio is {s['current_ratio']:.2f}, below 1.0.",
        ),
        (
            "earnings_decline",
            lambda s: s["earnings_growth_pct"] is not None and s["earnings_growth_pct"] < 0,
            "medium",
            lambda s: f"Earnings growth is negative ({s['earnings_growth_pct']:.1f}%).",
        ),
        (
            "revenue_decline",
            lambda s: s["revenue_growth_pct"] is not None and s["revenue_growth_pct"] < 0,
            "medium",
            lambda s: f"Revenue growth is negative ({s['revenue_growth_pct']:.1f}%).",
        ),
        (
            "rich_valuation",
            lambda s: s["pe_trailing"] is not None and s["pe_trailing"] > 40,
            "low",
            lambda s: f"Trailing P/E of {s['pe_trailing']:.1f} is rich.",
        ),
        (
            "near_52w_low",
            lambda s: (
                s["price"] and s["52w_low"] and s["52w_high"]
                and (s["price"] - s["52w_low"]) / max(s["52w_high"] - s["52w_low"], 1e-9) < 0.1
            ),
            "medium",
            lambda s: f"Price is near its 52-week low ({s['52w_low']}).",
        ),
    ]


def flag_concerns(snapshot: dict) -> list[dict]:
    concerns = []
    for rule_id, cond, severity, msg in _rules():
        try:
            if cond(snapshot):
                concerns.append({"id": rule_id, "severity": severity, "message": msg(snapshot)})
        except Exception:
            continue
    order = {"high": 0, "medium": 1, "low": 2}
    concerns.sort(key=lambda c: order.get(c["severity"], 3))
    return concerns


# ---- recent news (real headlines, keyword-scanned — no LLM/sentiment model) ----

def fetch_recent_news(symbol: str, limit: int = 6) -> list[dict]:
    """Recent headlines for this ticker via yfinance. Same source
    `clientresearch` uses for its news panel."""
    t = yf.Ticker(symbol)
    try:
        raw = t.news or []
    except Exception:
        raw = []
    items = []
    for n in raw[:limit]:
        c = n.get("content", n)
        title = c.get("title")
        if not title:
            continue
        items.append(
            {
                "title": title,
                "publisher": (c.get("provider") or {}).get("displayName"),
                "published": c.get("pubDate"),
                "url": (c.get("canonicalUrl") or {}).get("url") or (c.get("clickThroughUrl") or {}).get("url"),
            }
        )
    return items


# Deliberately simple, transparent keyword matching — not sentiment analysis.
# Every flag names the exact headline and keyword that triggered it, so it's
# just as auditable as the numeric rules, even though headline keyword-matching
# is a blunt instrument that can misfire (e.g. "avoids lawsuit" would still
# match "lawsuit"). Treat these as prompts to go read the actual article, not
# as a verdict.
_NEWS_HIGH_SEVERITY_KEYWORDS = [
    "fraud", "scam", "investigation", "probe", "raid", "default", "bankruptcy",
    "insolvency", "delisting", "delisted", "banned", "arrested", "arrest",
    "resigns", "resignation", "resigned",
]
_NEWS_MEDIUM_SEVERITY_KEYWORDS = [
    "downgrade", "downgraded", "lawsuit", "penalty", "fined", "fine", "loss",
    "layoffs", "layoff", "recall", "recalls", "suspended", "suspends", "halt",
    "halted", "scrutiny", "strike", "resignation",
]
_NEWS_POSITIVE_KEYWORDS = [
    "upgrade", "upgraded", "record profit", "record revenue", "wins order",
    "order win", "bags order", "expansion", "acquisition", "acquires",
    "partnership", "buyback", "dividend hike", "outperform", "beats estimate",
    "strong growth", "raises guidance", "new contract", "approval", "clears",
]


def flag_news_concerns(news_items: list[dict]) -> list[dict]:
    """Scans headline titles for high/medium-severity negative keywords and
    returns them shaped exactly like `flag_concerns` output, so they merge
    into the same severity-ordered list and drive the same recommendation
    ladder — news-derived concerns aren't a separate, weaker signal."""
    concerns = []
    for item in news_items:
        title = item.get("title") or ""
        low = title.lower()
        matched, severity = None, None
        for kw in _NEWS_HIGH_SEVERITY_KEYWORDS:
            if kw in low:
                matched, severity = kw, "high"
                break
        if not matched:
            for kw in _NEWS_MEDIUM_SEVERITY_KEYWORDS:
                if kw in low:
                    matched, severity = kw, "medium"
                    break
        if matched:
            concerns.append(
                {
                    "id": f"news_{matched.replace(' ', '_')}",
                    "severity": severity,
                    "message": f'Recent headline flagged for "{matched}": {title}',
                    "source": "news",
                    "url": item.get("url"),
                    "published": item.get("published"),
                }
            )
    return concerns


def flag_news_positives(news_items: list[dict]) -> list[dict]:
    positives = []
    for item in news_items:
        title = item.get("title") or ""
        low = title.lower()
        for kw in _NEWS_POSITIVE_KEYWORDS:
            if kw in low:
                positives.append({"keyword": kw, "headline": title, "url": item.get("url"), "published": item.get("published")})
                break
    return positives


def build_recommendation(snapshot: dict, concerns: list[dict], news_positives: list[dict] | None = None) -> dict:
    """Transparent, rule-based Buy/Hold/Sell screen — combines concern-flag
    severity with analyst-target upside. Every input is named so the call is
    auditable; nothing is inferred by a model. Explicitly not personalized
    investment advice."""
    news_positives = news_positives or []
    high = sum(1 for c in concerns if c["severity"] == "high")
    medium = sum(1 for c in concerns if c["severity"] == "medium")
    news_flag_count = sum(1 for c in concerns if c.get("source") == "news")

    price = snapshot.get("price")
    target = snapshot.get("target_mean_price")
    upside_pct = round((target - price) / price * 100, 1) if price and target else None

    reasoning = []
    reasoning.append(f"{high} high-severity and {medium} medium-severity concern flag(s) from the rule scan.")
    if news_flag_count:
        reasoning.append(f"{news_flag_count} of those came from recent headlines flagged by keyword scan (see Concern Flags for which ones).")
    if upside_pct is not None:
        reasoning.append(f"Analyst target implies {upside_pct:+.1f}% vs. current price.")
    if snapshot.get("analyst_recommendation"):
        reasoning.append(f"Street consensus: {snapshot['analyst_recommendation'].replace('_', ' ')}.")

    if high >= 2:
        label = "Sell"
        reasoning.append("Two or more high-severity flags — balance sheet or earnings trend is a material concern.")
    elif high == 1:
        if upside_pct is not None and upside_pct > 10:
            label = "Hold"
            reasoning.append("One high-severity flag, but analyst target still implies meaningful upside — worth monitoring rather than exiting.")
        else:
            label = "Sell"
            reasoning.append("One high-severity flag with no offsetting upside case.")
    elif medium >= 3:
        label = "Hold"
        reasoning.append("Several medium-severity flags stacking up — mixed picture.")
    elif upside_pct is not None and upside_pct > 15 and medium <= 1:
        label = "Buy"
        reasoning.append("Clean flag profile and double-digit implied upside to analyst target.")
    elif high == 0 and medium == 0:
        label = "Buy"
        reasoning.append("No concern flags raised by the rule scan.")
    else:
        label = "Hold"
        reasoning.append("No strong signal either way from flags or valuation upside.")

    # Positive news can tip a clean-but-unremarkable Hold into a Buy — it
    # never overrides a Sell or a high-severity flag, it just breaks ties.
    if label == "Hold" and high == 0 and len(news_positives) >= 2:
        label = "Buy"
        example = news_positives[0]["keyword"]
        reasoning.append(f'{len(news_positives)} recent headline(s) matched positive-catalyst keywords (e.g. "{example}") — tipped this from Hold to Buy.')
    elif news_positives:
        reasoning.append(f"{len(news_positives)} recent headline(s) matched positive-catalyst keywords, noted but not enough alone to change the call.")

    return {
        "label": label,
        "upside_pct": upside_pct,
        "reasoning": reasoning,
        "disclaimer": (
            "Includes a keyword scan of recent headlines (both concerns and positive catalysts), "
            "on top of concern-flag severity and analyst-target upside — but keyword matching is a "
            "blunt instrument (e.g. \"avoids lawsuit\" would still match \"lawsuit\"), not real "
            "comprehension of the article. Always open the actual headline before relying on a "
            "news-driven flag. A personal, rule-based view, not personalized investment advice — "
            "verify against your own thesis and primary filings before acting."
        ),
    }


# Ladder used to downgrade the financial Buy/Hold/Sell call when qualitative
# (analyst-judged, non-financial) red flags are present. "Sell" starts at the
# floor already, so qualitative factors can't make it worse — they just add
# to the caution list.
_HOLDING_LADDER = ["Exit", "Trim", "Hold", "Buy More"]
_HOLDING_BASE_INDEX = {"Sell": 0, "Hold": 2, "Buy": 3}


def build_holistic_recommendation(financial_rec: dict, qualitative: dict | None) -> dict:
    """Combines the financial rule-based recommendation with analyst-entered
    non-financial factors (management quality, governance risk, regulatory/
    policy risk, competitive moat) into one portfolio-level call. The
    qualitative inputs are the analyst's own judgment, not inferred by the
    app — this just makes their effect on the position transparent and
    consistent rather than left to gut feel."""
    qualitative = qualitative or {}
    mq = (qualitative.get("management_quality") or "").lower()
    gr = (qualitative.get("governance_risk") or "").lower()
    rr = (qualitative.get("regulatory_risk") or "").lower()
    moat = (qualitative.get("competitive_moat") or "").lower()

    cautions = []
    red_flags = 0
    if mq == "poor":
        red_flags += 1
        cautions.append("Management quality flagged as poor (analyst-assessed).")
    if gr == "high":
        red_flags += 1
        cautions.append("Governance risk flagged as high (analyst-assessed).")
    if rr == "high":
        red_flags += 1
        cautions.append("Regulatory/policy risk flagged as high (analyst-assessed).")
    if moat == "weak":
        red_flags += 1
        cautions.append("Competitive moat flagged as weak (analyst-assessed).")

    positives = []
    if mq == "good":
        positives.append("Management quality assessed as good.")
    if gr == "low":
        positives.append("Governance risk assessed as low.")
    if rr == "low":
        positives.append("Regulatory/policy risk assessed as low.")
    if moat == "strong":
        positives.append("Competitive moat assessed as strong.")

    base_index = _HOLDING_BASE_INDEX.get(financial_rec.get("label"), 2)
    downgrade_steps = min(red_flags, 2)  # cap so one bad factor doesn't jump straight to Exit
    new_index = max(0, base_index - downgrade_steps)
    label = _HOLDING_LADDER[new_index]

    return {
        "label": label,
        "financial_label": financial_rec.get("label"),
        "downgraded": new_index < base_index,
        "cautions": cautions,
        "positives": positives,
        "disclaimer": (
            "Combines the numbers-only financial screen with whatever qualitative inputs you've "
            "entered (management, governance, regulatory risk, moat) — those are your own manual "
            "judgment calls, not automatically updated, and neither this nor the financial screen "
            "knows about recent news or events unless you've factored it into those inputs "
            "yourself. Still a personal view, not independent research or investment advice — "
            "check current news before relying on it."
        ),
    }


def _big_number(x) -> str:
    if x is None:
        return "n/a"
    if abs(x) >= 1e9:
        return f"₹{x / 1e9:,.1f}B"
    if abs(x) >= 1e7:
        return f"₹{x / 1e7:,.1f}Cr"
    return f"₹{x:,.0f}"


def build_summary(snapshot: dict, concerns: list[dict], recommendation: dict) -> str:
    """A short, templated research-note paragraph — every clause is filled
    straight from the same snapshot/concerns/recommendation data shown
    elsewhere on the page. No model, no inference beyond simple sentence
    assembly, so it's exactly as trustworthy (and exactly as limited) as the
    numbers behind it."""
    name = snapshot.get("name") or snapshot.get("symbol")
    sector = snapshot.get("sector")
    price = snapshot.get("price")
    pe = snapshot.get("pe_trailing")
    pe_fwd = snapshot.get("pe_forward")
    mcap = snapshot.get("market_cap")
    rev_growth = snapshot.get("revenue_growth_pct")
    earnings_growth = snapshot.get("earnings_growth_pct")
    roe = snapshot.get("roe_pct")
    de = snapshot.get("debt_to_equity")

    sentences = []

    # Valuation
    s1 = f"{name}"
    if sector:
        s1 += f" ({sector})"
    if price is not None:
        s1 += f" trades at ₹{price:,.2f}"
        if mcap is not None:
            s1 += f", a market cap of {_big_number(mcap)}"
        if pe is not None:
            s1 += f", valued at {pe:.1f}x trailing earnings"
            if pe_fwd is not None:
                s1 += f" ({pe_fwd:.1f}x forward)"
    s1 += "."
    sentences.append(s1)

    # Growth / profitability / leverage — only the facts that are actually available
    growth_bits = []
    if rev_growth is not None:
        growth_bits.append(f"revenue grew {rev_growth:+.1f}% year-on-year")
    if earnings_growth is not None:
        growth_bits.append(f"earnings {'grew' if earnings_growth >= 0 else 'declined'} {abs(earnings_growth):.1f}%")
    if roe is not None:
        growth_bits.append(f"ROE stands at {roe:.1f}%")
    if de is not None:
        growth_bits.append(f"debt/equity is {de:.1f}")
    if growth_bits:
        sentences.append(", ".join(growth_bits).capitalize() + ".")

    # Rule-based call
    label = recommendation.get("label")
    upside = recommendation.get("upside_pct")
    s3 = f"The rule-based screen calls this a {label}"
    if upside is not None:
        direction = "upside" if upside >= 0 else "downside"
        s3 += f", with the analyst target implying {abs(upside):.1f}% {direction}"
    s3 += "."
    sentences.append(s3)

    # Concerns (numeric rules + any keyword-flagged headlines, already merged)
    news_flag_count = sum(1 for c in concerns if c.get("source") == "news")
    if not concerns:
        sentences.append("No concerns were raised by the rule scan, and no negative-keyword headlines were flagged.")
    else:
        top = concerns[0]
        n = len(concerns)
        news_note = f" ({news_flag_count} from recent headlines)" if news_flag_count else ""
        sentences.append(
            f"{n} concern{'s' if n != 1 else ''} flagged{news_note}, most notably ({top['severity']}): {top['message']}"
        )

    sentences.append(
        "Generated purely from the numbers and headline keywords above — not a substitute for "
        "actually reading recent news, management commentary, or other qualitative context. A "
        "personal, rule-based view, not independent research."
    )

    return " ".join(sentences)
