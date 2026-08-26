"""Password hashing and session tokens. Stdlib only (no bcrypt/passlib
dependency) — salted PBKDF2-HMAC-SHA256, which is a solid, well-reviewed
choice for this without adding a new package."""
from __future__ import annotations

import hashlib
import secrets
from datetime import datetime, timedelta, timezone

_PBKDF2_ITERATIONS = 260_000
SESSION_COOKIE_NAME = "alphadesk_session"
SESSION_TTL_DAYS = 30


def hash_password(password: str) -> str:
    salt = secrets.token_hex(16)
    digest = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS).hex()
    return f"{salt}${digest}"


def verify_password(password: str, stored: str) -> bool:
    try:
        salt, digest = stored.split("$", 1)
    except ValueError:
        return False
    check = hashlib.pbkdf2_hmac("sha256", password.encode("utf-8"), salt.encode("utf-8"), _PBKDF2_ITERATIONS).hex()
    return secrets.compare_digest(check, digest)


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()


def is_expired(expires_at: str) -> bool:
    return datetime.fromisoformat(expires_at) < datetime.now(timezone.utc)
