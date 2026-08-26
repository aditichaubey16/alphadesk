"""Session tokens and rate limiting. No password hashing — accounts are
passwordless (name + email)."""
from __future__ import annotations

import secrets
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

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


def new_session_token() -> str:
    return secrets.token_urlsafe(32)


def session_expiry() -> str:
    return (datetime.now(timezone.utc) + timedelta(days=SESSION_TTL_DAYS)).isoformat()


def is_expired(expires_at: str) -> bool:
    return datetime.fromisoformat(expires_at) < datetime.now(timezone.utc)
