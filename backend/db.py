"""SQLite persistence for AlphaDesk. Plain stdlib sqlite3, no ORM — schema is
portable to Postgres later if this ever needs to scale beyond a small group.

Multi-user model: every `companies` row belongs to exactly one user
(`user_id`), and everything else (notes, thesis, estimates, holdings,
qualitative_factors) hangs off `company_id` — so it's automatically
user-scoped for free as long as callers always resolve companies through a
user-filtered lookup. `events` gets its own `user_id` since a calendar entry
can stand alone with no company attached."""
from __future__ import annotations

import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(os.environ.get("ALPHADESK_DB_PATH", str(Path(__file__).parent.parent / "alphadesk.sqlite3")))

SCHEMA = """
CREATE TABLE IF NOT EXISTS users (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    email TEXT UNIQUE NOT NULL,
    password_hash TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS sessions (
    token TEXT PRIMARY KEY,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS companies (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    symbol TEXT NOT NULL,
    name TEXT,
    sector TEXT,
    added_at TEXT NOT NULL,
    UNIQUE(user_id, symbol)
);

CREATE TABLE IF NOT EXISTS notes (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    body TEXT NOT NULL,
    created_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS thesis (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER UNIQUE NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    thesis_text TEXT,
    risks TEXT,
    catalysts TEXT,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS estimates (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    period_label TEXT NOT NULL,
    est_eps REAL,
    actual_eps REAL,
    est_revenue REAL,
    actual_revenue REAL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
    company_id INTEGER REFERENCES companies(id) ON DELETE CASCADE,
    event_type TEXT NOT NULL,
    event_date TEXT NOT NULL,
    description TEXT
);

CREATE TABLE IF NOT EXISTS holdings (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    quantity REAL NOT NULL,
    buy_price REAL NOT NULL,
    buy_date TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS qualitative_factors (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    company_id INTEGER UNIQUE NOT NULL REFERENCES companies(id) ON DELETE CASCADE,
    management_quality TEXT,
    governance_risk TEXT,
    regulatory_risk TEXT,
    competitive_moat TEXT,
    future_prospects TEXT,
    notes TEXT,
    updated_at TEXT NOT NULL
);
"""


def now() -> str:
    return datetime.now(timezone.utc).isoformat()


def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db() -> None:
    conn = get_conn()
    try:
        conn.executescript(SCHEMA)
        conn.commit()
    finally:
        conn.close()


def _row_to_dict(row: sqlite3.Row) -> dict:
    return dict(row)


# ---- users ----

def create_user(name: str, email: str, password_hash: str) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO users (name, email, password_hash, created_at) VALUES (?, ?, ?, ?)",
            (name, email.lower(), password_hash, now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM users WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def get_user_by_email(email: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE email = ?", (email.lower(),)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def get_user_by_id(user_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM users WHERE id = ?", (user_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


# ---- sessions ----

def create_session(token: str, user_id: int, expires_at: str) -> None:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT INTO sessions (token, user_id, created_at, expires_at) VALUES (?, ?, ?, ?)",
            (token, user_id, now(), expires_at),
        )
        conn.commit()
    finally:
        conn.close()


def get_session(token: str) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM sessions WHERE token = ?", (token,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def delete_session(token: str) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM sessions WHERE token = ?", (token,))
        conn.commit()
    finally:
        conn.close()


# ---- companies / watchlist (user-scoped) ----

def list_companies(user_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM companies WHERE user_id = ? ORDER BY symbol", (user_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_company(symbol: str, user_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM companies WHERE symbol = ? AND user_id = ?", (symbol, user_id)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def add_company(user_id: int, symbol: str, name: str, sector: str | None) -> dict:
    conn = get_conn()
    try:
        conn.execute(
            "INSERT OR IGNORE INTO companies (user_id, symbol, name, sector, added_at) VALUES (?, ?, ?, ?, ?)",
            (user_id, symbol, name, sector, now()),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM companies WHERE symbol = ? AND user_id = ?", (symbol, user_id)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def remove_company(symbol: str, user_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute("DELETE FROM companies WHERE symbol = ? AND user_id = ?", (symbol, user_id))
        conn.commit()
    finally:
        conn.close()


# ---- notes ----

def list_notes(company_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM notes WHERE company_id = ? ORDER BY created_at DESC", (company_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def add_note(company_id: int, body: str) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO notes (company_id, body, created_at) VALUES (?, ?, ?)",
            (company_id, body, now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM notes WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


# ---- thesis ----

def get_thesis(company_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute("SELECT * FROM thesis WHERE company_id = ?", (company_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def upsert_thesis(company_id: int, thesis_text: str, risks: str, catalysts: str) -> dict:
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO thesis (company_id, thesis_text, risks, catalysts, updated_at)
            VALUES (?, ?, ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                thesis_text = excluded.thesis_text,
                risks = excluded.risks,
                catalysts = excluded.catalysts,
                updated_at = excluded.updated_at
            """,
            (company_id, thesis_text, risks, catalysts, now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM thesis WHERE company_id = ?", (company_id,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


# ---- estimates ----

def list_estimates(company_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            "SELECT * FROM estimates WHERE company_id = ? ORDER BY period_label", (company_id,)
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def add_estimate(company_id: int, period_label: str, est_eps, est_revenue) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            """INSERT INTO estimates (company_id, period_label, est_eps, est_revenue, updated_at)
               VALUES (?, ?, ?, ?, ?)""",
            (company_id, period_label, est_eps, est_revenue, now()),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM estimates WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def update_estimate_actuals(estimate_id: int, user_id: int, actual_eps, actual_revenue) -> dict | None:
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE estimates SET actual_eps = ?, actual_revenue = ?, updated_at = ?
            WHERE id = ? AND company_id IN (SELECT id FROM companies WHERE user_id = ?)
            """,
            (actual_eps, actual_revenue, now(), estimate_id, user_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM estimates WHERE id = ?", (estimate_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


# ---- events (user-scoped) ----

def list_events(user_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT events.*, companies.symbol AS company_symbol
            FROM events LEFT JOIN companies ON companies.id = events.company_id
            WHERE events.user_id = ?
            ORDER BY event_date
            """,
            (user_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def add_event(user_id: int, company_id: int | None, event_type: str, event_date: str, description: str | None) -> dict:
    conn = get_conn()
    try:
        cur = conn.execute(
            "INSERT INTO events (user_id, company_id, event_type, event_date, description) VALUES (?, ?, ?, ?, ?)",
            (user_id, company_id, event_type, event_date, description),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM events WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


# ---- holdings (user-scoped via companies.user_id) ----

def list_holdings(user_id: int) -> list[dict]:
    conn = get_conn()
    try:
        rows = conn.execute(
            """
            SELECT holdings.*, companies.symbol AS company_symbol, companies.name AS company_name,
                   companies.sector AS company_sector
            FROM holdings JOIN companies ON companies.id = holdings.company_id
            WHERE companies.user_id = ?
            ORDER BY companies.symbol
            """,
            (user_id,),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]
    finally:
        conn.close()


def get_holding(holding_id: int, user_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            """
            SELECT holdings.*, companies.symbol AS company_symbol, companies.name AS company_name,
                   companies.sector AS company_sector
            FROM holdings JOIN companies ON companies.id = holdings.company_id
            WHERE holdings.id = ? AND companies.user_id = ?
            """,
            (holding_id, user_id),
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def add_holding(company_id: int, quantity: float, buy_price: float, buy_date: str | None) -> dict:
    conn = get_conn()
    try:
        ts = now()
        cur = conn.execute(
            """INSERT INTO holdings (company_id, quantity, buy_price, buy_date, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (company_id, quantity, buy_price, buy_date, ts, ts),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM holdings WHERE id = ?", (cur.lastrowid,)).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


def update_holding(holding_id: int, user_id: int, quantity: float, buy_price: float, buy_date: str | None) -> dict | None:
    conn = get_conn()
    try:
        conn.execute(
            """
            UPDATE holdings SET quantity = ?, buy_price = ?, buy_date = ?, updated_at = ?
            WHERE id = ? AND company_id IN (SELECT id FROM companies WHERE user_id = ?)
            """,
            (quantity, buy_price, buy_date, now(), holding_id, user_id),
        )
        conn.commit()
        row = conn.execute("SELECT * FROM holdings WHERE id = ?", (holding_id,)).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def delete_holding(holding_id: int, user_id: int) -> None:
    conn = get_conn()
    try:
        conn.execute(
            """
            DELETE FROM holdings WHERE id = ? AND company_id IN (
                SELECT id FROM companies WHERE user_id = ?
            )
            """,
            (holding_id, user_id),
        )
        conn.commit()
    finally:
        conn.close()


# ---- qualitative factors ----

def get_qualitative(company_id: int) -> dict | None:
    conn = get_conn()
    try:
        row = conn.execute(
            "SELECT * FROM qualitative_factors WHERE company_id = ?", (company_id,)
        ).fetchone()
        return _row_to_dict(row) if row else None
    finally:
        conn.close()


def upsert_qualitative(
    company_id: int,
    management_quality: str | None,
    governance_risk: str | None,
    regulatory_risk: str | None,
    competitive_moat: str | None,
    future_prospects: str,
    notes: str,
) -> dict:
    conn = get_conn()
    try:
        conn.execute(
            """
            INSERT INTO qualitative_factors
                (company_id, management_quality, governance_risk, regulatory_risk,
                 competitive_moat, future_prospects, notes, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(company_id) DO UPDATE SET
                management_quality = excluded.management_quality,
                governance_risk = excluded.governance_risk,
                regulatory_risk = excluded.regulatory_risk,
                competitive_moat = excluded.competitive_moat,
                future_prospects = excluded.future_prospects,
                notes = excluded.notes,
                updated_at = excluded.updated_at
            """,
            (
                company_id, management_quality, governance_risk, regulatory_risk,
                competitive_moat, future_prospects, notes, now(),
            ),
        )
        conn.commit()
        row = conn.execute(
            "SELECT * FROM qualitative_factors WHERE company_id = ?", (company_id,)
        ).fetchone()
        return _row_to_dict(row)
    finally:
        conn.close()


# ---- full export (backup, user-scoped) ----

def export_all(user_id: int) -> dict:
    """Dumps everything belonging to this user — a plain JSON snapshot for
    backup/export, keyed by table name."""
    conn = get_conn()
    try:
        companies = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM companies WHERE user_id = ?", (user_id,)
        ).fetchall()]
        company_ids = [c["id"] for c in companies]
        placeholders = ",".join("?" * len(company_ids)) if company_ids else "NULL"

        def _scoped(table: str) -> list[dict]:
            if not company_ids:
                return []
            return [_row_to_dict(r) for r in conn.execute(
                f"SELECT * FROM {table} WHERE company_id IN ({placeholders})", company_ids
            ).fetchall()]

        events = [_row_to_dict(r) for r in conn.execute(
            "SELECT * FROM events WHERE user_id = ?", (user_id,)
        ).fetchall()]

        return {
            "exported_at": now(),
            "companies": companies,
            "notes": _scoped("notes"),
            "thesis": _scoped("thesis"),
            "estimates": _scoped("estimates"),
            "events": events,
            "holdings": _scoped("holdings"),
            "qualitative_factors": _scoped("qualitative_factors"),
        }
    finally:
        conn.close()
