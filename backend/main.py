"""AlphaDesk FastAPI app: JSON API + static frontend."""
from __future__ import annotations

import time
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, HTMLResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import db, market_data, screener, universe

FRONTEND_DIR = Path(__file__).parent.parent / "frontend" / "static"
_ASSET_VERSION = str(int(time.time()))  # busts browser cache for static assets on each restart

app = FastAPI(title="AlphaDesk")


@app.on_event("startup")
def _startup():
    db.init_db()
    universe.refresh_if_stale()


def _company_or_404(symbol: str) -> dict:
    company = db.get_company(symbol.upper())
    if not company:
        raise HTTPException(status_code=404, detail=f"{symbol} is not on the watchlist")
    return company


# ---- search ----

@app.get("/api/search")
def search(q: str):
    return market_data.search_companies(q)


# ---- NSE universe (local directory, no live data) ----

@app.get("/api/universe")
def get_universe(q: str = "", limit: int = 60):
    return {"total": universe.universe_count(), "results": universe.search_universe(q, limit)}


# ---- daily screen (Nifty 50 Top Buys / Top Sells) ----

@app.get("/api/daily-screen")
def get_daily_screen(refresh: bool = False):
    return screener.get_daily_screen(force_refresh=refresh)


# ---- watchlist ----

@app.get("/api/watchlist")
def get_watchlist():
    return db.list_companies()


class AddWatchlistItem(BaseModel):
    symbol: str
    name: str | None = None
    sector: str | None = None


@app.post("/api/watchlist")
def add_to_watchlist(item: AddWatchlistItem):
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
    return db.add_company(symbol, name, sector)


@app.delete("/api/watchlist/{symbol}")
def delete_from_watchlist(symbol: str):
    db.remove_company(symbol.upper())
    return {"ok": True}


# ---- company workspace ----

class EnsureCompanyIn(BaseModel):
    name: str | None = None


@app.post("/api/company/{symbol}/ensure")
def ensure_company(symbol: str, body: EnsureCompanyIn):
    """Makes sure `symbol` has a row in the companies table (without adding it
    to the watchlist) so its research view can be opened — used when jumping
    into a company from somewhere that isn't the watchlist, e.g. the Daily
    Screen or NSE Universe search."""
    return _get_or_create_company(symbol, body.name)


@app.get("/api/company/{symbol}")
def get_company_snapshot(symbol: str):
    company = _company_or_404(symbol)
    try:
        snapshot = market_data.fetch_snapshot(company["symbol"])
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch live data: {e}")
    concerns = market_data.flag_concerns(snapshot)
    raw = market_data.fetch_raw_parameters(company["symbol"])
    recommendation = market_data.build_recommendation(snapshot, concerns)
    return {"company": company, "snapshot": snapshot, "concerns": concerns, "raw": raw, "recommendation": recommendation}


@app.get("/api/company/{symbol}/history")
def get_company_history(symbol: str, period: str = "6mo"):
    company = _company_or_404(symbol)
    try:
        return market_data.fetch_price_history(company["symbol"], period)
    except Exception as e:
        raise HTTPException(status_code=502, detail=f"Could not fetch price history: {e}")


class NoteIn(BaseModel):
    body: str


@app.get("/api/company/{symbol}/notes")
def get_notes(symbol: str):
    company = _company_or_404(symbol)
    return db.list_notes(company["id"])


@app.post("/api/company/{symbol}/notes")
def post_note(symbol: str, note: NoteIn):
    company = _company_or_404(symbol)
    return db.add_note(company["id"], note.body)


class ThesisIn(BaseModel):
    thesis_text: str = ""
    risks: str = ""
    catalysts: str = ""


@app.get("/api/company/{symbol}/thesis")
def get_thesis(symbol: str):
    company = _company_or_404(symbol)
    thesis = db.get_thesis(company["id"])
    return thesis or {"thesis_text": "", "risks": "", "catalysts": ""}


@app.put("/api/company/{symbol}/thesis")
def put_thesis(symbol: str, thesis: ThesisIn):
    company = _company_or_404(symbol)
    return db.upsert_thesis(company["id"], thesis.thesis_text, thesis.risks, thesis.catalysts)


class EstimateIn(BaseModel):
    period_label: str
    est_eps: float | None = None
    est_revenue: float | None = None


@app.get("/api/company/{symbol}/estimates")
def get_estimates(symbol: str):
    company = _company_or_404(symbol)
    return db.list_estimates(company["id"])


@app.post("/api/company/{symbol}/estimates")
def post_estimate(symbol: str, estimate: EstimateIn):
    company = _company_or_404(symbol)
    return db.add_estimate(company["id"], estimate.period_label, estimate.est_eps, estimate.est_revenue)


class ActualsIn(BaseModel):
    actual_eps: float | None = None
    actual_revenue: float | None = None


@app.put("/api/estimates/{estimate_id}/actuals")
def put_actuals(estimate_id: int, actuals: ActualsIn):
    result = db.update_estimate_actuals(estimate_id, actuals.actual_eps, actuals.actual_revenue)
    if not result:
        raise HTTPException(status_code=404, detail="Estimate not found")
    return result


# ---- calendar / events ----

@app.get("/api/events")
def get_events():
    return db.list_events()


class EventIn(BaseModel):
    company_symbol: str | None = None
    event_type: str
    event_date: str
    description: str | None = None


@app.post("/api/events")
def post_event(event: EventIn):
    company_id = None
    if event.company_symbol:
        company = _company_or_404(event.company_symbol)
        company_id = company["id"]
    return db.add_event(company_id, event.event_type, event.event_date, event.description)


# ---- portfolio holdings ----

def _get_or_create_company(symbol: str, name: str | None) -> dict:
    symbol = symbol.upper()
    existing = db.get_company(symbol)
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
    return db.add_company(symbol, resolved_name, sector)


def _enrich_holding(h: dict) -> dict:
    symbol = h["company_symbol"]
    try:
        snapshot = market_data.fetch_snapshot(symbol)
        concerns = market_data.flag_concerns(snapshot)
        financial_rec = market_data.build_recommendation(snapshot, concerns)
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
    }


@app.get("/api/holdings")
def get_holdings():
    return [_enrich_holding(h) for h in db.list_holdings()]


class HoldingIn(BaseModel):
    symbol: str
    name: str | None = None
    quantity: float
    buy_price: float
    buy_date: str | None = None


@app.post("/api/holdings")
def post_holding(holding: HoldingIn):
    company = _get_or_create_company(holding.symbol, holding.name)
    h = db.add_holding(company["id"], holding.quantity, holding.buy_price, holding.buy_date)
    return _enrich_holding({**h, "company_symbol": company["symbol"], "company_name": company["name"], "company_sector": company["sector"]})


class HoldingUpdateIn(BaseModel):
    quantity: float
    buy_price: float
    buy_date: str | None = None


@app.put("/api/holdings/{holding_id}")
def put_holding(holding_id: int, holding: HoldingUpdateIn):
    updated = db.update_holding(holding_id, holding.quantity, holding.buy_price, holding.buy_date)
    if not updated:
        raise HTTPException(status_code=404, detail="Holding not found")
    matching = next((h for h in db.list_holdings() if h["id"] == holding_id), None)
    return _enrich_holding(matching) if matching else updated


@app.delete("/api/holdings/{holding_id}")
def delete_holding(holding_id: int):
    db.delete_holding(holding_id)
    return {"ok": True}


class QualitativeIn(BaseModel):
    management_quality: str | None = None
    governance_risk: str | None = None
    regulatory_risk: str | None = None
    competitive_moat: str | None = None
    future_prospects: str = ""
    notes: str = ""


@app.put("/api/company/{symbol}/qualitative")
def put_qualitative(symbol: str, q: QualitativeIn):
    company = _company_or_404(symbol)
    return db.upsert_qualitative(
        company["id"], q.management_quality, q.governance_risk,
        q.regulatory_risk, q.competitive_moat, q.future_prospects, q.notes,
    )


# ---- frontend ----

app.mount("/static", StaticFiles(directory=FRONTEND_DIR), name="static")


@app.get("/")
def index():
    html = (FRONTEND_DIR / "index.html").read_text(encoding="utf-8")
    html = html.replace("style.css", f"style.css?v={_ASSET_VERSION}")
    html = html.replace("app.js", f"app.js?v={_ASSET_VERSION}")
    return HTMLResponse(html, headers={"Cache-Control": "no-store"})
