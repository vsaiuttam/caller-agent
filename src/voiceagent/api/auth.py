"""Opt-in access control: one admin password, signed expiring tokens.

Off unless ADMIN_PASSWORD is set, and then everything behaves exactly as it
did before — a local console is not made harder to use to protect a public
one. Set it, and every /api/* route except health and the auth routes needs
a token, and so do the live WebSockets. Twilio's webhooks are never locked:
Twilio cannot log in, and a locked webhook drops every call in flight.

A token is `base64url(json {"exp": unix_seconds}) "." base64url(HMAC-SHA256)`
— stateless, so there is no session table, and a restart logs nobody out.
It is signed with AUTH_SECRET, or failing that a key derived from the
password, so changing either one signs everyone out. Settings are read when
used, not at import.

    ADMIN_PASSWORD         — turns access control on
    AUTH_SECRET            — signing key; optional, derived from the password
    AUTH_TOKEN_TTL_HOURS   — token lifetime, default 12
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

DEFAULT_TTL_HOURS = 12.0

# Reachable without a token: monitoring, and what the login page itself needs.
OPEN_PATHS = frozenset({"/api/health", "/api/auth/login", "/api/auth/status"})

# More than this many failed logins from one client in the window is a 429.
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW_SECONDS = 300.0


def auth_enabled() -> bool:
    return bool(os.getenv("ADMIN_PASSWORD", ""))


def check_password(password: str) -> bool:
    expected = os.getenv("ADMIN_PASSWORD", "")
    # Constant time, so response timing says nothing about how close a guess was.
    return bool(expected) and hmac.compare_digest(password.encode(), expected.encode())


def issue_token(now: datetime | None = None) -> tuple[str, datetime]:
    """A signed token and the moment it expires."""
    secret = _secret()
    if secret is None:
        raise RuntimeError("Access control is off: set ADMIN_PASSWORD to issue tokens.")
    now = now or datetime.now(timezone.utc)
    exp = int((now + timedelta(hours=_ttl_hours())).timestamp())
    payload = _b64encode(json.dumps({"exp": exp}, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload, secret)}", datetime.fromtimestamp(exp, timezone.utc)


def verify_token(token: str, now: datetime | None = None) -> bool:
    """True only for an unexpired token signed with the current secret."""
    secret = _secret()
    if secret is None or not token or token.count(".") != 1:
        return False
    payload, signature = token.split(".")
    if not hmac.compare_digest(signature.encode(), _sign(payload, secret).encode()):
        return False
    try:
        exp = json.loads(_b64decode(payload))["exp"]
    except (ValueError, KeyError, TypeError):
        return False
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return False
    now = now or datetime.now(timezone.utc)
    return now.timestamp() < exp


def bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _secret() -> bytes | None:
    explicit = os.getenv("AUTH_SECRET", "")
    if explicit:
        return explicit.encode()
    password = os.getenv("ADMIN_PASSWORD", "")
    if not password:
        return None
    # Derived rather than the password itself, so the signing key and the
    # thing people type are never the same bytes.
    return hashlib.sha256(b"samvaad-auth-token:" + password.encode()).digest()


def _ttl_hours() -> float:
    try:
        hours = float(os.getenv("AUTH_TOKEN_TTL_HOURS", "") or DEFAULT_TTL_HOURS)
    except ValueError:
        return DEFAULT_TTL_HOURS
    return hours if hours > 0 else DEFAULT_TTL_HOURS


def _sign(payload: str, secret: bytes) -> str:
    return _b64encode(hmac.new(secret, payload.encode(), hashlib.sha256).digest())


def _b64encode(raw: bytes) -> str:
    # Unpadded, so a token rides in a query string without escaping.
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _b64decode(text: str) -> bytes:
    return base64.urlsafe_b64decode(text + "=" * (-len(text) % 4))


# --------------------------------------------------------------------------
# Failed-login throttle
# --------------------------------------------------------------------------


class LoginThrottle:
    """Counts failed logins per client, in memory, over a sliding window.

    In-process like the event bus: enough to make guessing a password from
    one address slow, which is the threat a single shared password faces.
    """

    def __init__(
        self,
        max_failures: int = MAX_FAILED_LOGINS,
        window_seconds: float = FAILED_LOGIN_WINDOW_SECONDS,
    ) -> None:
        self._max = max_failures
        self._window = window_seconds
        self._failures: dict[str, deque[float]] = {}

    def blocked(self, client: str) -> bool:
        failures = self._failures.get(client)
        if not failures:
            return False
        cutoff = time.monotonic() - self._window
        while failures and failures[0] < cutoff:
            failures.popleft()
        return len(failures) > self._max

    def failed(self, client: str) -> None:
        now = time.monotonic()
        self._failures.setdefault(client, deque()).append(now)
        # Forget clients whose failures have all aged out, so the table
        # cannot grow without bound.
        cutoff = now - self._window
        for key in [k for k, v in self._failures.items() if not v or v[-1] < cutoff]:
            del self._failures[key]

    def succeeded(self, client: str) -> None:
        self._failures.pop(client, None)


def client_address(headers: Mapping[str, str], peer: str | None) -> str:
    """Who is logging in, as far as throttling is concerned.

    Behind a proxy (Render) every request arrives from the proxy's address,
    so that alone would throttle everyone together. The last X-Forwarded-For
    hop is the one the proxy itself added; earlier hops are whatever the
    client chose to send.
    """
    forwarded = headers.get("x-forwarded-for", "")
    hops = [hop.strip() for hop in forwarded.split(",") if hop.strip()]
    return hops[-1] if hops else (peer or "unknown")


# --------------------------------------------------------------------------
# HTTP gate
# --------------------------------------------------------------------------


class AuthMiddleware:
    """Refuses /api/* requests without a valid token while auth is on.

    Plain ASGI, and HTTP only: WebSockets check their own `?token=`, since a
    browser can't set headers on a socket and a refused one must close with
    4401 rather than answer with a status code. Preflight OPTIONS requests
    pass, since a browser never attaches credentials to one.
    """

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] == "http" and self._locked(scope):
            response = JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    def _locked(scope: Scope) -> bool:
        path = scope.get("path", "")
        if (
            not path.startswith("/api/")
            or path in OPEN_PATHS
            or scope.get("method") == "OPTIONS"
            or not auth_enabled()
        ):
            return False
        return not verify_token(request_token(scope) or "")


def request_token(scope: Scope) -> str | None:
    """The token on a request: `Authorization: Bearer`, else `?token=`.

    The query form exists for what can't send headers — <audio> sources,
    download links, and WebSockets.
    """
    headers = {k.decode("latin-1").lower(): v.decode("latin-1") for k, v in scope.get("headers", [])}
    token = bearer_token(headers.get("authorization"))
    if token:
        return token
    query = parse_qs(scope.get("query_string", b"").decode("latin-1"))
    values = query.get("token")
    return values[0] if values else None
