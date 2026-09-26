"""Opt-in access control: user accounts, a break-glass admin password, and
signed expiring tokens.

Off until someone registers or ADMIN_PASSWORD is set, and until then
everything behaves exactly as it did before — a local console is not made
harder to use to protect a public one. Once on, every /api/* route except
health and the auth routes needs a token, and so do the live WebSockets.
Twilio's webhooks are never locked: Twilio cannot log in, and a locked
webhook drops every call in flight.

The first person to register becomes the owner, which is what switches
access control on. ADMIN_PASSWORD stays as a break-glass sign-in (and, while
nobody has registered, as the setup code that stops a stranger claiming a
public deploy). Its tokens act as the owner.

A token is `base64url(json {"exp", "sub", "role"}) "." base64url(HMAC-SHA256)`
— stateless, so there is no session table, and a restart logs nobody out.
`sub` is a user id, or "admin" for the admin password. It is signed with
AUTH_SECRET, else a key derived from the password, else a random key kept
in the database; changing the one in use signs everyone out. Disabling or
deleting a user revokes their tokens at once (see `authenticate`). Settings
are read when used, not at import.

    ADMIN_PASSWORD         — break-glass sign-in; also turns access control on
    AUTH_SECRET            — signing key; optional
    AUTH_TOKEN_TTL_HOURS   — token lifetime, default 12
    REGISTRATION_MODE      — after the owner exists: invite (default) | open | closed
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import logging
import os
import secrets
import time
from collections import deque
from collections.abc import Mapping
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs

from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Receive, Scope, Send

from .. import storage

logger = logging.getLogger(__name__)

DEFAULT_TTL_HOURS = 12.0

# Reachable without a token: monitoring, and what the login and register
# pages themselves need.
OPEN_PATHS = frozenset(
    {"/api/health", "/api/auth/login", "/api/auth/status", "/api/auth/register"}
)

# More than this many failed logins from one client in the window is a 429.
MAX_FAILED_LOGINS = 5
FAILED_LOGIN_WINDOW_SECONDS = 300.0

# The subject of an admin-password token. Never a user id (those are UUIDs).
LEGACY_SUBJECT = "admin"
ROLES = ("owner", "admin", "member")

# scrypt at the cost OWASP suggests: 16 MiB and ~50 ms per hash, which makes
# an offline guess expensive without making a login feel slow.
SCRYPT_N, SCRYPT_R, SCRYPT_P = 2**14, 8, 1
SCRYPT_SALT_BYTES = 16
SCRYPT_KEY_BYTES = 64
# scrypt needs 128·n·r bytes; OpenSSL's default ceiling is 32 MiB, so state
# ours rather than sit just under someone else's.
_SCRYPT_MAXMEM = 64 * 1024 * 1024


# Whether anyone has registered. In-process so auth_enabled() stays a cheap
# synchronous check on every request: loaded at startup, set by the first
# registration, and never cleared in practice (the owner can't be removed).
_users_exist = False


def auth_enabled() -> bool:
    return bool(os.getenv("ADMIN_PASSWORD", "")) or _users_exist


def users_exist() -> bool:
    return _users_exist


def set_users_exist(value: bool) -> None:
    """Record whether any user exists. Called at startup and on registration;
    tests call it to reset.

    Also forgets which subjects were seen active, and with no users at all
    there is nobody left to revoke: both are caches over the users table,
    which stays the authority.
    """
    global _users_exist
    _users_exist = bool(value)
    _active.clear()
    if not value:
        _revoked.clear()


def check_password(password: str) -> bool:
    expected = os.getenv("ADMIN_PASSWORD", "")
    # Constant time, so response timing says nothing about how close a guess was.
    return bool(expected) and hmac.compare_digest(password.encode(), expected.encode())


# --------------------------------------------------------------------------
# Password hashing
# --------------------------------------------------------------------------


def hash_password(password: str) -> str:
    """`scrypt$<n>$<r>$<p>$<salt>$<key>`, base64, with a fresh random salt.

    CPU-bound for ~50 ms: callers on the event loop run it in a thread, since
    the same loop is carrying live call audio.
    """
    salt = secrets.token_bytes(SCRYPT_SALT_BYTES)
    key = hashlib.scrypt(
        password.encode(), salt=salt, n=SCRYPT_N, r=SCRYPT_R, p=SCRYPT_P,
        dklen=SCRYPT_KEY_BYTES, maxmem=_SCRYPT_MAXMEM,
    )
    return "$".join(
        ["scrypt", str(SCRYPT_N), str(SCRYPT_R), str(SCRYPT_P),
         base64.b64encode(salt).decode(), base64.b64encode(key).decode()]
    )


def check_password_hash(password: str, stored: str) -> bool:
    """Whether `password` is the one `stored` was made from. False for any
    malformed hash rather than an exception: a bad row must not become a 500
    on the login page."""
    if not isinstance(password, str) or not isinstance(stored, str):
        return False
    try:
        scheme, n, r, p, salt_b64, key_b64 = stored.split("$")
        n, r, p = int(n), int(r), int(p)
        salt = base64.b64decode(salt_b64, validate=True)
        expected = base64.b64decode(key_b64, validate=True)
    except ValueError:  # includes binascii.Error
        return False
    # Parameters come from the row, so bound them: a tampered row must not be
    # able to ask for gigabytes of memory.
    if scheme != "scrypt" or not salt or not expected or not (
        2 <= n <= 2**20 and n & (n - 1) == 0 and 1 <= r <= 32 and 1 <= p <= 16
    ):
        return False
    try:
        actual = hashlib.scrypt(
            password.encode(), salt=salt, n=n, r=r, p=p,
            dklen=len(expected), maxmem=_SCRYPT_MAXMEM,
        )
    except ValueError:
        return False
    return hmac.compare_digest(actual, expected)


# --------------------------------------------------------------------------
# Tokens
# --------------------------------------------------------------------------

# Replaced at startup by the one stored in the database (load_accounts), and
# only used when neither AUTH_SECRET nor ADMIN_PASSWORD is set. Random until
# then, so a process that never loads one still signs with something unguessable.
_workspace_key: bytes = secrets.token_bytes(32)


def issue_token(
    now: datetime | None = None,
    *,
    subject: str = LEGACY_SUBJECT,
    role: str = "owner",
) -> tuple[str, datetime]:
    """A signed token for `subject` (a user id, or "admin") and its expiry."""
    if role not in ROLES:
        raise ValueError(f"Unknown role: {role!r}")
    now = now or datetime.now(timezone.utc)
    exp = int((now + timedelta(hours=_ttl_hours())).timestamp())
    claims = {"exp": exp, "sub": subject, "role": role}
    payload = _b64encode(json.dumps(claims, separators=(",", ":")).encode())
    return f"{payload}.{_sign(payload, _secret())}", datetime.fromtimestamp(exp, timezone.utc)


def token_claims(token: str, now: datetime | None = None) -> dict | None:
    """`{"sub", "role", "exp"}` for an unexpired token signed with the current
    secret, else None.

    Says nothing about whether the subject may still sign in — a disabled
    user's token is still well-formed. `authenticate` answers that.
    """
    if not isinstance(token, str) or token.count(".") != 1:
        return None
    payload, signature = token.split(".")
    if not hmac.compare_digest(signature.encode(), _sign(payload, _secret()).encode()):
        return None
    try:
        claims = json.loads(_b64decode(payload))
    except (ValueError, TypeError):
        return None
    if not isinstance(claims, dict):
        return None
    exp = claims.get("exp")
    if not isinstance(exp, (int, float)) or isinstance(exp, bool):
        return None
    now = now or datetime.now(timezone.utc)
    if now.timestamp() >= exp:
        return None
    # Tokens issued before accounts existed carry only `exp`; the admin
    # password was the only way to get one, so that is what they were.
    subject = claims.get("sub", LEGACY_SUBJECT)
    role = claims.get("role", "owner")
    if not isinstance(subject, str) or not subject or role not in ROLES:
        return None
    return {"sub": subject, "role": role, "exp": exp}


def verify_token(token: str, now: datetime | None = None) -> bool:
    """True only for an unexpired token signed with the current secret, whose
    subject has not been revoked in this process."""
    claims = token_claims(token, now)
    return claims is not None and claims["sub"] not in _revoked


# --------------------------------------------------------------------------
# Revocation
# --------------------------------------------------------------------------

# A signed token stays well-formed until it expires, so a disabled or
# deleted user has to be refused by who they are, not by their token.
#
# `_revoked` is what this process has been told (by the team endpoints): it
# makes a revocation immediate. `_active` remembers subjects the database
# recently confirmed, so a user's requests don't each cost a query; after a
# restart it is empty, and a token whose user is gone or disabled fails its
# first lookup. The expiry bounds how long another worker process, which
# never heard of the revocation, can go on trusting its cache.
_revoked: set[str] = set()
_active: dict[str, float] = {}
ACTIVE_CACHE_SECONDS = 60.0


def revoke_subject(user_id: str) -> None:
    """Refuse this user's tokens from now on (they were disabled or deleted)."""
    _revoked.add(user_id)
    _active.pop(user_id, None)


def restore_subject(user_id: str) -> None:
    """Undo `revoke_subject` (they were re-enabled)."""
    _revoked.discard(user_id)


async def authenticate(token: str | None, now: datetime | None = None) -> dict | None:
    """The claims of a token that may use the API right now, else None.

    Admin-password tokens never touch the database. A user's token is checked
    against the users table on first sight, then trusted from memory for a
    minute unless revoked.
    """
    claims = token_claims(token or "", now)
    if claims is None:
        return None
    subject = claims["sub"]
    if subject == LEGACY_SUBJECT:
        return claims
    if subject in _revoked:
        return None
    seen = _active.get(subject)
    if seen is not None and time.monotonic() - seen < ACTIVE_CACHE_SECONDS:
        return claims
    if not await _user_is_active(subject):
        return None
    # Re-checked after the await: a revocation that landed while the query
    # was in flight must not be overwritten by a stale "active".
    if subject in _revoked:
        return None
    _active[subject] = time.monotonic()
    return claims


async def _user_is_active(user_id: str) -> bool:
    try:
        # Through storage.SessionLocal at call time, not an import of it, so
        # whatever database the app is using right now is the one asked.
        async with storage.SessionLocal() as session:
            disabled = await session.scalar(
                select(storage.User.disabled).where(storage.User.id == user_id)
            )
    except Exception:  # noqa: BLE001
        # Fail closed: an unreachable database can't vouch for anyone.
        logger.exception("Auth: could not look up user %s", user_id)
        return False
    return disabled is not None and not disabled


# --------------------------------------------------------------------------
# Startup
# --------------------------------------------------------------------------

_SIGNING_KEY_SETTING = "auth_signing_key"


async def load_accounts() -> None:
    """At startup: whether anyone has registered, and the workspace signing key.

    The key is created on first start and stored, so that tokens signed with
    it (when neither AUTH_SECRET nor ADMIN_PASSWORD is set) survive a
    restart. Stored in the settings table under a key no endpoint lists.
    """
    global _workspace_key
    async with storage.SessionLocal() as session:
        count = await session.scalar(select(func.count()).select_from(storage.User)) or 0
        set_users_exist(count > 0)

        row = await session.get(storage.Setting, _SIGNING_KEY_SETTING)
        stored = _decode_key(row.value if row else None)
        if stored is not None:
            _workspace_key = stored
            return
        value = {"key": base64.b64encode(_workspace_key).decode()}
        if row is None:
            session.add(storage.Setting(key=_SIGNING_KEY_SETTING, value=value))
        else:
            row.value = value
        try:
            await session.commit()
        except IntegrityError:
            # Another worker stored its key first; use that one.
            await session.rollback()
            row = await session.get(storage.Setting, _SIGNING_KEY_SETTING)
            stored = _decode_key(row.value if row else None)
            if stored is not None:
                _workspace_key = stored


def _decode_key(value) -> bytes | None:
    try:
        key = base64.b64decode(value["key"], validate=True)
    except (TypeError, KeyError, ValueError):
        return None
    return key if len(key) >= 32 else None


def bearer_token(authorization: str | None) -> str | None:
    scheme, _, token = (authorization or "").partition(" ")
    return token.strip() if scheme.lower() == "bearer" and token.strip() else None


def _secret() -> bytes:
    explicit = os.getenv("AUTH_SECRET", "")
    if explicit:
        return explicit.encode()
    password = os.getenv("ADMIN_PASSWORD", "")
    if password:
        # Derived rather than the password itself, so the signing key and
        # the thing people type are never the same bytes.
        return hashlib.sha256(b"samvaad-auth-token:" + password.encode()).digest()
    # Accounts with neither variable set: a random key, kept in the database
    # so a restart logs nobody out (see load_accounts).
    return _workspace_key


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
        if scope["type"] == "http" and await self._locked(scope):
            response = JSONResponse(
                {"detail": "Authentication required"},
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
            await response(scope, receive, send)
            return
        await self.app(scope, receive, send)

    @staticmethod
    async def _locked(scope: Scope) -> bool:
        path = scope.get("path", "")
        if (
            not path.startswith("/api/")
            or path in OPEN_PATHS
            or scope.get("method") == "OPTIONS"
            or not auth_enabled()
        ):
            return False
        return await authenticate(request_token(scope)) is None


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
