"""Password hashing and session tokens. Stdlib only (no bcrypt/passlib
dependency) — salted PBKDF2-HMAC-SHA256, which is a solid, well-reviewed
choice for this without adding a new package."""
from __future__ import annotations

import hashlib
import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

_PBKDF2_ITERATIONS = 260_000
SESSION_COOKIE_NAME = "alphadesk_session"
SESSION_TTL_DAYS = 30

# In-memory rate limiter — fine for a single-process deployment like this
# one; resets on restart, which is an acceptable tradeoff for its purpose
# (slow down brute-force/spam, not a hard security boundary).
_attempts: dict[str, deque] = defaultdict(deque)


def check_rate_limit(key: str, max_attempts: int, window_seconds: int) -> bool:
    """True if this action is still allowed (and records it); False if the
    caller has hit `max_attempts` within the last `window_seconds`."""
    now = time.time()
    dq = _attempts[key]
    while dq and now - dq[0] > window_seconds:
        dq.popleft()
    if len(dq) >= max_attempts:
        return False
    dq.append(now)
    return True


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
