"""Admin auth: env password, signed session cookie, rate-limited login.

The password lives ONLY in the DASHBOARD_ADMIN_PASSWORD environment variable —
never in code, logs, or the database. Session tokens are HMAC-signed with a
random per-boot secret, so restarting the dashboard invalidates all sessions.
"""
from __future__ import annotations

import hashlib
import hmac
import os
import secrets
import time

from fastapi import HTTPException, Request, Response

_BOOT_SECRET = secrets.token_bytes(32)
SESSION_COOKIE = "dash_session"
SESSION_TTL = 12 * 3600
_attempts: dict[str, list[float]] = {}
MAX_ATTEMPTS = 5
WINDOW = 60.0


def admin_password() -> str | None:
    return os.environ.get("DASHBOARD_ADMIN_PASSWORD") or None


def _sign(payload: str) -> str:
    return hmac.new(_BOOT_SECRET, payload.encode(), hashlib.sha256).hexdigest()


def make_session() -> str:
    exp = str(int(time.time()) + SESSION_TTL)
    return f"{exp}.{_sign(exp)}"


def session_valid(token: str | None) -> bool:
    if not token or "." not in token:
        return False
    exp, sig = token.rsplit(".", 1)
    if not hmac.compare_digest(sig, _sign(exp)):
        return False
    return int(exp) > time.time()


def rate_limited(ip: str) -> bool:
    now = time.time()
    window = [t for t in _attempts.get(ip, []) if now - t < WINDOW]
    _attempts[ip] = window
    return len(window) >= MAX_ATTEMPTS


def record_attempt(ip: str) -> None:
    _attempts.setdefault(ip, []).append(time.time())


def login(request: Request, response: Response, password: str) -> None:
    ip = request.client.host if request.client else "?"
    if rate_limited(ip):
        raise HTTPException(429, "too many attempts — wait a minute")
    configured = admin_password()
    if configured is None:
        raise HTTPException(503, "admin disabled: DASHBOARD_ADMIN_PASSWORD not set")
    record_attempt(ip)
    if not hmac.compare_digest(password.encode(), configured.encode()):
        raise HTTPException(401, "wrong password")
    response.set_cookie(SESSION_COOKIE, make_session(), httponly=True,
                        samesite="strict", max_age=SESSION_TTL)


def require_admin(request: Request) -> None:
    if not session_valid(request.cookies.get(SESSION_COOKIE)):
        raise HTTPException(401, "admin login required")
