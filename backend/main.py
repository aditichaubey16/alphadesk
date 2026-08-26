"""AlphaDesk FastAPI app: JSON API + static frontend. Multi-user: every
request past the auth routes requires a valid session cookie, and all data
routes are scoped to the logged-in user."""
from __future__ import annotations

import os
import re
import time
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Request, Response
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import auth, db, market_data, screener, universe

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "static"
_ASSET_VERSION = str(int(time.time()))  # busts browser cache for static assets on each restart
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
# Owner's account sees the admin/signups view; everyone else gets a 403.
# Override via env var if you ever change the account you sign up with.
_OWNER_EMAIL = os.environ.get("ALPHADESK_OWNER_EMAIL", "aditichaubey1805@gmail.com").lower()

app = FastAPI(title="AlphaDesk")


@app.on_event("startup")
def _startup():
    db.init_db()
    universe.refresh_if_stale()


# ---- auth dependency ----

def get_current_user(request: Request) -> dict:
    token = request.cookies.get(auth.SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(status_code=401, detail="Not signed in")
    session = db.get_session(token)
    if not session or auth.is_expired(session["expires_at"]):
        raise HTTPException(status_code=401, detail="Session expired")
    user = db.get_user_by_id(session["user_id"])
    if not user:
        raise HTTPException(status_code=401, detail="Not signed in")
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
            snap = market_data.fetch_snapshot(symbol)
            resolved_name = snap.get("name") or symbol
            sector = snap.get("sector")
        except Exception:
            resolved_name = symbol
    return db.add_company(user_id, symbol, resolved_name, sector)


# ---- auth routes ----

class SignupIn(BaseModel):
    name: str
    email: str
    password: str


@app.post("/api/auth/signup")
def signup(body: SignupIn, response: Response):
    name = body.name.strip()
    email = body.email.strip().lower()
    password = body.password

    if not name:
        raise HTTPException(status_code=400, detail="Name is required")
    if not _EMAIL_RE.match(email):
        raise HTTPException(status_code=400, detail="Enter a valid email address")
    if len(password) < 6:
        raise HTTPException(status_code=400, detail="Password must be at least 6 characters")
    if db.get_user_by_email(email):
        raise HTTPException(status_code=409, detail="An account with this email already exists — log in instead")

    user = db.create_user(name, email, auth.hash_password(password))
    _seed_default_watchlist(user["id"])
    token = auth.new_session_token()
    db.create_session(token, user["id"], auth.session_expiry())
    _set_session_cookie(response, token)
    return _public_user(user)


# A starter watchlist so new signups don't land on an empty screen. Names/
# sectors are hardcoded rather than fetched live, so signup stays fast and
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
            pass  # never let a seeding hiccup break signup


class LoginIn(BaseModel):
    email: str
    password: str


@app.post("/api/auth/login")
def login(body: LoginIn, response: Response):
    email = body.email.strip().lower()
    user = db.get_user_by_email(email)
    if not user or not auth.verify_password(body.password, user["password_hash"]):
        raise HTTPException(status_code=401, detail="Incorrect email or password")

    token = auth.new_session_token()
    db.create_session(token, user["id"], auth.session_expiry())
    _set_session_cookie(response, token)
    return _public_user(user)


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


@app.get("/api/admin/users")
def admin_list_users(user: dict = Depends(get_current_user)):
    if user["email"].lower() != _OWNER_EMAIL:
        raise HTTPException(status_code=403, detail="Not authorized")
    users = db.list_users()
    return {"total": len(users), "users": users}


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
            snap = market_data.fetch_snapshot(symbol)
            name = snap.get("name") or symbol
            sector = sector or snap.get("sector")
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
        snapshot = market_data.fetch_snapshot(company["symbol"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch live data: {e}")
    try:
        news = market_data.fetch_recent_news(company["symbol"])
    except Exception:
        news = []
    news_concerns = market_data.flag_news_concerns(news)
    news_positives = market_data.flag_news_positives(news)

    concerns = market_data.flag_concerns(snapshot) + news_concerns
    raw = market_data.fetch_raw_parameters(company["symbol"])
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
    }


@app.get("/api/company/{symbol}/history")
def get_company_history(symbol: str, period: str = "6mo", user: dict = Depends(get_current_user)):
    company = _company_or_404(symbol, user["id"])
    try:
        return market_data.fetch_price_history(company["symbol"], period)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch price history: {e}")


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
        snapshot = market_data.fetch_snapshot(symbol)
        try:
            news = market_data.fetch_recent_news(symbol)
        except Exception:
            news = []
        news_concerns = market_data.flag_news_concerns(news)
        news_positives = market_data.flag_news_positives(news)
        concerns = market_data.flag_concerns(snapshot) + news_concerns
        financial_rec = market_data.build_recommendation(snapshot, concerns, news_positives)
    except Exception as e:
        return {**h, "error": f"Could not fetch live data: {e}"}

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
