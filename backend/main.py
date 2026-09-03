"""AlphaDesk FastAPI app: JSON API + static frontend. No login screen — a
session cookie is issued silently on a visitor's first request, so every
data route is still scoped to a "user" under the hood, but nobody ever
types a name or email to get one."""
from __future__ import annotations

import os
import secrets
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, market_data, screener, universe

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "static"
_ASSET_VERSION = str(int(time.time()))  # busts browser cache for static assets on each restart
# Owner's account sees the admin/signups view; everyone else gets a 403.
# Claimed via a hidden URL parameter (?admin=<this value>), not a login
# form — see /api/auth/claim-admin. Must be set via the ALPHADESK_OWNER_EMAIL
# env var (Render dashboard -> this service -> Environment) — deliberately
# NOT hardcoded here, since this file is public. The placeholder below never
# matches anything real, so admin claiming just fails closed if the env var
# isn't set, rather than falling back to a value anyone can read in the repo.
_OWNER_EMAIL = os.environ.get("ALPHADESK_OWNER_EMAIL", "unset-owner-email-placeholder").lower()

app = FastAPI(title="AlphaDesk")


@app.on_event("startup")
def _startup():
    db.init_db()
    universe.refresh_if_stale()


# ---- auth dependency ----
#
# No login screen — every request either carries a valid session cookie, or
# doesn't, in which case one is silently minted right here: a brand-new
# anonymous user + session, cookie set on the response, seeded with the
# starter watchlist, and the request continues as if it always had one.
# The first request of a new visit pays for this; every request after
# reuses the same cookie like a normal session.

def get_current_user(request: Request, response: Response) -> dict:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    session = db.get_session(token) if token else None
    if session and not auth.is_expired(session["expires_at"]):
        user = db.get_user_by_id(session["user_id"])
        if user:
            return user

    placeholder_email = f"guest-{secrets.token_hex(10)}@local"
    user = db.create_anonymous_user("Guest", placeholder_email)
    _seed_default_watchlist(user["id"])
    new_token = auth.new_session_token()
    db.create_session(new_token, user["id"], auth.session_expiry())
    _set_session_cookie(response, new_token)
    return user


def _public_user(user: dict) -> dict:
    return {"id": user["id"], "name": user["name"], "email": user["email"]}


def _set_session_cookie(response: Response, token: str) -> None:
    # Render (and most PaaS hosts) set RENDER/PORT-style env vars in production;
    # only mark the cookie Secure there so plain-http local dev keeps working.
    is_deployed = bool(os.environ.get("RENDER") or os.environ.get("ALPHADESK_ENV") == "production")
    response.set_cookie(
        auth.SESSION_COOKIE_NAME,
        token,
        max_age=auth.SESSION_TTL_DAYS * 86400,
        httponly=True,
        samesite="lax",
        secure=is_deployed,
    )


def _company_or_404(symbol: str, user_id: int) -> dict:
    company = db.get_company(symbol.upper(), user_id)
    if not company:
        raise HTTPException(status_code=404, detail=f"{symbol} is not on your watchlist")
    return company


def _get_or_create_company(symbol: str, name: str | None, user_id: int) -> dict:
    symbol = symbol.upper()
    existing = db.get_company(symbol, user_id)
    if existing:
        return existing
    resolved_name = name
    sector = None
    if not resolved_name:
        try:
            snapshot = market_data.get_daily_quote(symbol)["snapshot"]
            resolved_name = snapshot.get("name") or symbol
            sector = snapshot.get("sector")
        except Exception:
            resolved_name = symbol
    return db.add_company(user_id, symbol, resolved_name, sector)


# ---- admin claim (hidden — no login form) ----
#
# Visiting the site with ?admin=<key> in the URL quietly upgrades the
# current anonymous session to the owner account, keeping whatever
# watchlist/portfolio it already had. No visible form anywhere; the key
# only needs to be known to the one person who should have it.

class ClaimAdminIn(BaseModel):
    key: str


@app.post("/api/auth/claim-admin")
def claim_admin(body: ClaimAdminIn, request: Request, response: Response, user: dict = Depends(get_current_user)):
    client_ip = request.client.host if request.client else "unknown"
    if not auth.check_rate_limit(f"claim-admin:{client_ip}", max_attempts=10, window_seconds=3600):
        raise HTTPException(status_code=429, detail="Too many attempts — try again later.")

    if body.key.strip().lower() != _OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="Not authorized")

    existing = db.get_user_by_email(_OWNER_EMAIL)
    if existing and existing["id"] != user["id"]:
        # owner identity already belongs to another session (e.g. claimed on a
        # different device) — switch this session to point at that account
        # rather than fail on the email's UNIQUE constraint
        token = request.cookies.get(auth.SESSION_COOKIE_NAME)
        if token:
            db.delete_session(token)
        new_token = auth.new_session_token()
        db.create_session(new_token, existing["id"], auth.session_expiry())
        _set_session_cookie(response, new_token)
        return _public_user(existing)

    updated = db.update_email(user["id"], _OWNER_EMAIL)
    return _public_user(updated)


# A starter watchlist so new accounts don't land on an empty screen. Names/
# sectors are hardcoded rather than fetched live, so this stays fast and
# doesn't depend on yfinance being reachable at that exact moment.
_DEFAULT_WATCHLIST = [
    ("RELIANCE.NS", "Reliance Industries Limited", "Energy"),
    ("TCS.NS", "Tata Consultancy Services Limited", "Information Technology"),
    ("INFY.NS", "Infosys Limited", "Information Technology"),
]


def _seed_default_watchlist(user_id: int) -> None:
    for symbol, name, sector in _DEFAULT_WATCHLIST:
        try:
            db.add_company(user_id, symbol, name, sector)
        except Exception:
            pass  # never let a seeding hiccup break account creation


@app.post("/api/auth/logout")
def logout(request: Request, response: Response):
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    if token:
        db.delete_session(token)
    response.delete_cookie(auth.SESSION_COOKIE_NAME)
    return {"ok": True}


@app.get("/api/auth/me")
def me(user: dict = Depends(get_current_user)):
    return _public_user(user)


class UpdateNameIn(BaseModel):
    name: str


@app.post("/api/auth/update-name")
def update_name(body: UpdateNameIn, user: dict = Depends(get_current_user)):
    name = body.name.strip()
    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    updated = db.update_name(user["id"], name)
    return _public_user(updated)


@app.get("/api/admin/users")
def admin_list_users(user: dict = Depends(get_current_user)):
    if user["email"].lower() != _OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="Not authorized")
    users = db.list_users()
    return {"total": len(users), "users": users, "owner_email": _OWNER_EMAIL}


# ---- search ----

@app.get("/api/search")
def search(q: str, user: dict = Depends(get_current_user)):
    return market_data.search_companies(q)


# ---- NSE universe (local directory, no live data) ----

@app.get("/api/universe")
def get_universe(q: str = "", limit: int = 60, user: dict = Depends(get_current_user)):
    return {"total": universe.universe_count(), "results": universe.search_universe(q, limit)}


# ---- daily screen (Nifty 50 Top Buys / Top Sells — shared market data, not per-user) ----

@app.get("/api/daily-screen")
def get_daily_screen(refresh: bool = False, user: dict = Depends(get_current_user)):
    return screener.get_daily_screen(force_refresh=refresh)


# ---- sectors (every tracked company grouped by sector — shared, not per-user) ----

@app.get("/api/sectors")
def get_sectors(user: dict = Depends(get_current_user)):
    return market_data.list_tracked_by_sector()


# ---- data freshness (shown in the topbar so the manual-refresh date is always visible) ----

@app.get("/api/data-status")
def get_data_status(user: dict = Depends(get_current_user)):
    return {"as_of": market_data._load_manual_quotes().get("as_of"), "tracked_count": len(market_data.get_tracked_symbols())}


# ---- peer comparison (doesn't touch the watchlist - just looks symbols up) ----

class CompareIn(BaseModel):
    symbols: list[str]


@app.post("/api/compare")
def compare_companies(body: CompareIn, user: dict = Depends(get_current_user)):
    results = []
    for raw_symbol in body.symbols[:4]:
        symbol = raw_symbol.strip().upper()
        if not symbol:
            continue
        try:
            quote = market_data.get_daily_quote(symbol)
            snapshot = quote["snapshot"]
            concerns = market_data.flag_concerns(snapshot) + market_data.flag_news_concerns(quote["news"])
            news_positives = market_data.flag_news_positives(quote["news"])
            recommendation = market_data.build_recommendation(snapshot, concerns, news_positives)
            results.append(
                {
                    "symbol": symbol,
                    "snapshot": snapshot,
                    "concerns": concerns,
                    "recommendation": recommendation,
                    "quote_date": quote["quote_date"],
                    "is_stale": quote["is_stale"],
                }
            )
        except Exception as e:
            results.append({"symbol": symbol, "error": str(e)})
    return {"companies": results}


# ---- data export (backup) ----

@app.get("/api/export")
def export_data(user: dict = Depends(get_current_user)):
    data = db.export_all(user["id"])
    filename = f"alphadesk-backup-{db.now()[:10]}.json"
    return JSONResponse(content=data, headers={"Content-Disposition": f'attachment; filename="{filename}"'})


# ---- watchlist ----

@app.get("/api/watchlist")
def get_watchlist(user: dict = Depends(get_current_user)):
    return db.list_companies(user["id"])


class AddWatchlistItem(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None


@app.post("/api/watchlist")
def add_to_watchlist(item: AddWatchlistItem, user: dict = Depends(get_current_user)):
    symbol = item.symbol.upper()
    name = item.name
    sector = item.sector
    if not name:
        try:
            snapshot = market_data.get_daily_quote(symbol)["snapshot"]
            name = snapshot.get("name") or symbol
            sector = sector or snapshot.get("sector")
        except Exception:
            name = symbol
    return db.add_company(user["id"], symbol, name, sector)


@app.delete("/api/watchlist/{symbol}")
def delete_from_watchlist(symbol: str, user: dict = Depends(get_current_user)):
    db.remove_company(symbol.upper(), user["id"])
    return {"ok": True}


# ---- company workspace ----

class EnsureCompanyIn(BaseModel):
    name: str | None = None


@app.post("/api/company/{symbol}/ensure")
def ensure_company(symbol: str, body: EnsureCompanyIn, user: dict = Depends(get_current_user)):
    """Makes sure `symbol` has a row in the companies table (without adding it
    to the watchlist) so its research view can be opened — used when jumping
    into a company from somewhere that isn't the watchlist, e.g. the Daily
    Screen or NSE Universe search."""
    return _get_or_create_company(symbol, body.name, user["id"])


@app.get("/api/company/{symbol}")
def get_company_snapshot(symbol: str, user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    try:
        quote = market_data.get_daily_quote(company["symbol"])
    except market_data.QuoteNotAvailable as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not load data: {e}")

    snapshot, raw, news = quote["snapshot"], quote["raw"], quote["news"]
    news_concerns = market_data.flag_news_concerns(news)
    news_positives = market_data.flag_news_positives(news)

    concerns = market_data.flag_concerns(snapshot) + news_concerns
    recommendation = market_data.build_recommendation(snapshot, concerns, news_positives)
    summary = market_data.build_summary(snapshot, concerns, recommendation)
    return {
        "company": company,
        "snapshot": snapshot,
        "concerns": concerns,
        "raw": raw,
        "recommendation": recommendation,
        "summary": summary,
        "news": news,
        "news_positives": news_positives,
        "quote_date": quote["quote_date"],
        "is_stale": quote["is_stale"],
    }


@app.get("/api/company/{symbol}/history")
def get_company_history(symbol: str, period: str = "6mo", user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    try:
        return market_data.get_price_history(company["symbol"], period)
    except market_data.QuoteNotAvailable as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not load price history: {e}")


class NoteIn(BaseModel):
    body: str


@app.get("/api/company/{symbol}/notes")
def get_notes(symbol: str, user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    return db.list_notes(company["id"])


@app.post("/api/company/{symbol}/notes")
def post_note(symbol: str, note: NoteIn, user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    return db.add_note(company["id"], note.body)


@app.delete("/api/notes/{note_id}")
def delete_note(note_id: int, user: dict = Depends(get_current_user)):
    db.delete_note(note_id, user["id"])
    return {"ok": True}


class ThesisIn(BaseModel):
    thesis_text: str = ""
    risks: str = ""
    catalysts: str = ""


@app.get("/api/company/{symbol}/thesis")
def get_thesis(symbol: str, user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    thesis = db.get_thesis(company["id"])
    return thesis or {"thesis_text": "", "risks": "", "catalysts": ""}


@app.put("/api/company/{symbol}/thesis")
def put_thesis(symbol: str, thesis: ThesisIn, user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    return db.upsert_thesis(company["id"], thesis.thesis_text, thesis.risks, thesis.catalysts)


class EstimateIn(BaseModel):
    period_label: str
    est_eps: float | None = None
    est_revenue: float | None = None


@app.get("/api/company/{symbol}/estimates")
def get_estimates(symbol: str, user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    return db.list_estimates(company["id"])


@app.post("/api/company/{symbol}/estimates")
def post_estimate(symbol: str, estimate: EstimateIn, user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    return db.add_estimate(company["id"], estimate.period_label, estimate.est_eps, estimate.est_revenue)


class ActualsIn(BaseModel):
    actual_eps: float | None = None
    actual_revenue: float | None = None


@app.put("/api/estimates/{estimate_id}/actuals")
def put_actuals(estimate_id: int, actuals: ActualsIn, user: dict = Depends(get_current_user)):
    result = db.update_estimate_actuals(estimate_id, user["id"], actuals.actual_eps, actuals.actual_revenue)
    if not result:
        raise HTTPException(status_code=404, detail="Estimate not found")
    return result


# ---- calendar / events ----

@app.get("/api/events")
def get_events(user: dict = Depends(get_current_user)):
    return db.list_events(user["id"])


class EventIn(BaseModel):
    company_symbol: str | None = None
    event_type: str
    event_date: str
    description: str | None = None


@app.post("/api/events")
def post_event(event: EventIn, user: dict = Depends(get_current_user)):
    company_id = None
    if event.company_symbol:
        company = _company_or_404(event.company_symbol, user["id"])
        company_id = company["id"]
    return db.add_event(user["id"], company_id, event.event_type, event.event_date, event.description)


# ---- portfolio holdings ----

def _enrich_holding(h: dict) -> dict:
    symbol = h["company_symbol"]
    try:
        quote = market_data.get_daily_quote(symbol)
        snapshot, news = quote["snapshot"], quote["news"]
        news_concerns = market_data.flag_news_concerns(news)
        news_positives = market_data.flag_news_positives(news)
        concerns = market_data.flag_concerns(snapshot) + news_concerns
        financial_rec = market_data.build_recommendation(snapshot, concerns, news_positives)
    except Exception as e:
        return {**h, "error": str(e)}

    qualitative = db.get_qualitative(h["company_id"])
    holistic = market_data.build_holistic_recommendation(financial_rec, qualitative)

    current_price = snapshot.get("price")
    invested_value = h["quantity"] * h["buy_price"]
    current_value = h["quantity"] * current_price if current_price is not None else None
    pnl = (current_value - invested_value) if current_value is not None else None
    pnl_pct = (pnl / invested_value * 100) if pnl is not None and invested_value else None

    return {
        **h,
        "current_price": current_price,
        "logo_url": snapshot.get("logo_url"),
        "invested_value": round(invested_value, 2),
        "current_value": round(current_value, 2) if current_value is not None else None,
        "pnl": round(pnl, 2) if pnl is not None else None,
        "pnl_pct": round(pnl_pct, 2) if pnl_pct is not None else None,
        "concerns": concerns,
        "financial_recommendation": financial_rec,
        "qualitative": qualitative,
        "holistic_recommendation": holistic,
        "summary": market_data.build_summary(snapshot, concerns, financial_rec),
        "news": news,
        "news_positives": news_positives,
        "quote_date": quote["quote_date"],
        "is_stale": quote["is_stale"],
    }


@app.get("/api/holdings")
def get_holdings(user: dict = Depends(get_current_user)):
    return [_enrich_holding(h) for h in db.list_holdings(user["id"])]


class HoldingIn(BaseModel):
    symbol: str
    name: str | None = None
    quantity: float
    buy_price: float
    buy_date: str | None = None


@app.post("/api/holdings")
def post_holding(holding: HoldingIn, user: dict = Depends(get_current_user)):
    company = _get_or_create_company(holding.symbol, holding.name, user["id"])
    h = db.add_holding(company["id"], holding.quantity, holding.buy_price, holding.buy_date)
    return _enrich_holding({**h, "company_symbol": company["symbol"], "company_name": company["name"], "company_sector": company["sector"]})


class HoldingUpdateIn(BaseModel):
    quantity: float
    buy_price: float
    buy_date: str | None = None


@app.put("/api/holdings/{holding_id}")
def put_holding(holding_id: int, holding: HoldingUpdateIn, user: dict = Depends(get_current_user)):
    updated = db.update_holding(holding_id, user["id"], holding.quantity, holding.buy_price, holding.buy_date)
    if not updated:
        raise HTTPException(status_code=404, detail="Holding not found")
    matching = next((h for h in db.list_holdings(user["id"]) if h["id"] == holding_id), None)
    return _enrich_holding(matching) if matching else updated


@app.delete("/api/holdings/{holding_id}")
def delete_holding(holding_id: int, user: dict = Depends(get_current_user)):
    db.delete_holding(holding_id, user["id"])
    return {"ok": True}


class QualitativeIn(BaseModel):
    management_quality: str | None = None
    governance_risk: str | None = None
    regulatory_risk: str | None = None
    competitive_moat: str | None = None
    future_prospects: str = ""
    notes: str = ""


@app.put("/api/company/{symbol}/qualitative")
def put_qualitative(symbol: str, q: QualitativeIn, user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    return db.upsert_qualitative(
        company["id"], q.management_quality, q.governance_risk,
        q.regulatory_risk, q.competitive_moat, q.future_prospects, q.notes,
    )


# ---- frontend ----

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index(request: Request):
    # Render (and most PaaS hosts) terminate TLS at a proxy in front of
    # uvicorn, so the raw request scope often still says "http" — trust
    # X-Forwarded-Proto when present so the Open Graph image/url are https.
    proto = request.headers.get("x-forwarded-proto", request.url.scheme)
    host = request.headers.get("host", request.url.netloc)
    base_url = f"{proto}://{host}/"

    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("{{BASE_URL}}", base_url)
    html = html.replace("style.css", f"style.css?v={_ASSET_VERSION}")
    html = html.replace("app.js", f"app.js?v={_ASSET_VERSION}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
