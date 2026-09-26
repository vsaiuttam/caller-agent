"""User accounts and registration, on top of the opt-in admin password.

Covers docs/accounts-spec.md §0–§1 from the outside: salted scrypt password
hashes, tokens that carry a subject and a role, when access control switches
on, owner bootstrap with and without a setup code, the three registration
modes, invites (single use, expiry, revocation, email binding, role),
password and email rules, one generic answer for a failed sign-in, disabled
and deleted users locked out at once and after a restart, the legacy admin
password as a break-glass owner, throttling, password hashes never leaving the
API, and the accounts block in /api/health.

Drives the real FastAPI app over ASGI against a throwaway SQLite database.
Env vars (ADMIN_PASSWORD, AUTH_SECRET, REGISTRATION_MODE) are set per test and
must be read at call time; the in-process "a user exists" flag is reset around
every test with `auth.set_users_exist(False)`. Register and login calls come
from a fresh X-Forwarded-For address each unless a test pins one, so failed
attempts in one check can never throttle another. Runs standalone
(`python tests/test_accounts.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import base64
import hashlib
import itertools
import json
import logging
import os
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import insert, update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402
from src.voiceagent.api import auth  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)

SECRET = "accounts-test-signing-secret"
ADMIN_PASSWORD = "break glass in an emergency"

OWNER_NAME = "Asha Rao"
OWNER_EMAIL = "asha@example.com"
OWNER_PASSWORD = "owner pass phrase 1"
MEMBER_PASSWORD = "member pass phrase 2"

# Pinned so nothing in a developer's .env changes what these tests see. A
# signing secret is set so tokens can be issued without ADMIN_PASSWORD; the
# one test that needs neither unsets it.
BASE_ENV = dict(
    ADMIN_PASSWORD=None,
    AUTH_SECRET=SECRET,
    REGISTRATION_MODE=None,
    AUTH_TOKEN_TTL_HOURS=None,
    REQUIRE_LOGIN=None,
)


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@contextmanager
def _env(**values: str | None):
    """Set (or, with None, unset) environment variables for the block."""
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


def _forget_users() -> None:
    """Teardown: the in-process "a user exists" flag must not leak into other tests.

    Looked up rather than called directly so that, before the feature exists,
    a test fails on what it checks rather than in its teardown; the tests
    that exercise the flag call it directly.
    """
    setter = getattr(auth, "set_users_exist", None)
    if setter is not None:
        setter(False)


@asynccontextmanager
async def _api(client_ip: str):
    """The real app on a throwaway database, seen from `client_ip`.

    Every loaded module of the package that holds the real `SessionLocal` is
    pointed at the throwaway database too, since account checks may run
    outside a request's `get_session` (in the auth gate, for one).
    """
    path = Path(tempfile.mkdtemp()) / "accounts.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(storage.Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with sessions() as session:
            yield session

    app = app_module.app
    original = storage.SessionLocal
    patched = [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("src.voiceagent") and getattr(module, "SessionLocal", None) is original
    ]
    app.dependency_overrides[storage.get_session] = override
    for module in patched:
        module.SessionLocal = sessions
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(client_ip, 5000)),
            base_url="http://test",
            headers={"X-Forwarded-For": client_ip},
        ) as http:
            yield http, sessions
    finally:
        app.dependency_overrides.pop(storage.get_session, None)
        for module in patched:
            module.SessionLocal = original
        await engine.dispose()


def _run(scenario, client_ip: str, **env: str | None):
    """Run `scenario(http, sessions)` on a fresh database with BASE_ENV plus `env`."""

    async def main():
        async with _api(client_ip) as (http, sessions):
            return await scenario(http, sessions)

    _forget_users()
    try:
        with _env(**{**BASE_ENV, **env}):
            return asyncio.run(main())
    finally:
        _forget_users()


_addresses = itertools.count(1)


def _fresh_ip() -> str:
    n = next(_addresses)
    return f"10.39.{n // 250}.{n % 250 + 1}"


async def _websocket(path: str, query: str = "", *, wait: float = 0.4) -> dict:
    """Open a WebSocket on the app over raw ASGI and report what the server did.

    Returns {"accepted": bool, "close_code": int | None}; `close_code` is None
    when the server left the socket open for `wait` seconds.
    """
    inbound: asyncio.Queue = asyncio.Queue()
    outbound: asyncio.Queue = asyncio.Queue()
    inbound.put_nowait({"type": "websocket.connect"})
    scope = {
        "type": "websocket",
        "asgi": {"version": "3.0", "spec_version": "2.3"},
        "http_version": "1.1",
        "scheme": "ws",
        "server": ("test", 80),
        "client": ("10.39.255.1", 5000),
        "root_path": "",
        "path": path,
        "raw_path": path.encode(),
        "query_string": query.encode(),
        "headers": [(b"host", b"test")],
        "subprotocols": [],
        "state": {},
    }
    task = asyncio.create_task(app_module.app(scope, inbound.get, outbound.put))
    loop = asyncio.get_running_loop()
    deadline = loop.time() + wait
    accepted, close_code = False, None
    try:
        while close_code is None:
            remaining = deadline - loop.time()
            if remaining <= 0:
                break
            try:
                message = await asyncio.wait_for(outbound.get(), remaining)
            except asyncio.TimeoutError:
                break
            if message["type"] == "websocket.accept":
                accepted = True
            elif message["type"] == "websocket.close":
                close_code = message.get("code", 1000)
    finally:
        inbound.put_nowait({"type": "websocket.disconnect", "code": 1000})
        task.cancel()
        with suppress(BaseException):
            await task
    return {"accepted": accepted, "close_code": close_code}


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _b64any(text: str) -> bytes:
    """Decode base64 in either alphabet, padded or not."""
    padded = text + "=" * (-len(text) % 4)
    if "-" in text or "_" in text:
        return base64.urlsafe_b64decode(padded)
    return base64.b64decode(padded)


def _b64url(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _reason(r: httpx.Response) -> str:
    """The whole error body, lower-cased, for checking that it names the rule."""
    try:
        return json.dumps(r.json(), ensure_ascii=False).lower()
    except ValueError:
        return r.text.lower()


def _show(r: httpx.Response) -> str:
    return f"{r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:300]}"


async def _register(
    http: httpx.AsyncClient,
    *,
    email: str,
    password: str,
    name: str = "Test Person",
    invite_code: str | None = None,
    setup_code: str | None = None,
    extra: dict | None = None,
    ip: str | None = None,
) -> httpx.Response:
    body: dict = {"name": name, "email": email, "password": password}
    if invite_code is not None:
        body["invite_code"] = invite_code
    if setup_code is not None:
        body["setup_code"] = setup_code
    if extra:
        body.update(extra)
    return await http.post("/api/auth/register", json=body, headers={"X-Forwarded-For": ip or _fresh_ip()})


async def _register_ok(http: httpx.AsyncClient, **kwargs) -> dict:
    r = await _register(http, **kwargs)
    assert r.status_code == 201, f"expected 201 from register: {_show(r)}"
    return r.json()


async def _owner(http: httpx.AsyncClient, **codes) -> dict:
    """Register the owner; returns {token, expires_at, user}."""
    return await _register_ok(http, name=OWNER_NAME, email=OWNER_EMAIL, password=OWNER_PASSWORD, **codes)


async def _login(
    http: httpx.AsyncClient, email: str | None, password: str, *, ip: str | None = None
) -> httpx.Response:
    body = {"password": password} if email is None else {"email": email, "password": password}
    return await http.post("/api/auth/login", json=body, headers={"X-Forwarded-For": ip or _fresh_ip()})


async def _invite(http: httpx.AsyncClient, token: str, **body) -> dict:
    r = await http.post("/api/team/invites", json=body, headers=_bearer(token))
    assert r.status_code == 201, f"expected 201 from invite: {_show(r)}"
    return r.json()


async def _member(http: httpx.AsyncClient, owner_token: str, email: str, role: str = "member") -> dict:
    """Invite and register a teammate; returns {token, expires_at, user}."""
    invite = await _invite(http, owner_token, role=role)
    return await _register_ok(
        http, name=email.split("@")[0].title(), email=email, password=MEMBER_PASSWORD, invite_code=invite["code"]
    )


async def _team_users(http: httpx.AsyncClient, token: str) -> dict[str, dict]:
    r = await http.get("/api/team/users", headers=_bearer(token))
    assert r.status_code == 200, _show(r)
    assert isinstance(r.json(), list), r.json()
    return {user["email"]: user for user in r.json()}


async def _patch_user(http: httpx.AsyncClient, token: str, user_id: str, **body) -> httpx.Response:
    return await http.patch(f"/api/team/users/{user_id}", json=body, headers=_bearer(token))


async def _set_row(sessions, table: str, row_id: str, **values) -> None:
    """Change a row behind the API's back, the way time or a restart would."""
    t = storage.Base.metadata.tables[table]
    async with sessions() as db:
        result = await db.execute(update(t).where(t.c.id == row_id).values(**values))
        await db.commit()
    assert result.rowcount == 1, (table, row_id, result.rowcount)


async def _status(http: httpx.AsyncClient, token: str | None = None) -> dict:
    r = await http.get("/api/auth/status", headers=_bearer(token) if token else {})
    assert r.status_code == 200, _show(r)
    return r.json()


# ---------------------------------------------------------------------------
# Password hashing
# ---------------------------------------------------------------------------


def test_password_hashes_are_salted_scrypt_in_the_documented_format() -> None:
    """Stored passwords are salted scrypt hashes that a stolen database can't reverse."""
    from src.voiceagent.api.auth import check_password_hash, hash_password

    password = "a long enough passphrase"
    stored = hash_password(password)
    assert isinstance(stored, str) and password not in stored, stored
    assert len(stored) <= 255, "must fit users.password_hash String(255)"

    parts = stored.split("$")
    assert len(parts) == 6 and parts[0] == "scrypt", stored
    assert parts[1:4] == ["16384", "8", "1"], f"n, r, p should be 2**14, 8, 1: {parts[1:4]}"
    salt, key = _b64any(parts[4]), _b64any(parts[5])
    assert len(salt) == 16, f"salt should be 16 random bytes, got {len(salt)}"
    assert len(key) == 64, f"key should be 64 bytes, got {len(key)}"
    assert key == hashlib.scrypt(password.encode(), salt=salt, n=2**14, r=8, p=1, dklen=64), (
        "the stored key should be hashlib.scrypt of the password with the stored salt"
    )

    again = hash_password(password)
    assert again != stored, "two hashes of one password must differ (random salt)"
    assert check_password_hash(password, stored) is True
    assert check_password_hash(password, again) is True
    assert check_password_hash("a long enough passphrasE", stored) is False
    assert check_password_hash("", stored) is False


def test_malformed_stored_hashes_never_match() -> None:
    """A corrupt or foreign hash in the database denies the sign-in instead of crashing it."""
    from src.voiceagent.api.auth import check_password_hash

    for stored in (
        "",
        "the password itself",
        "scrypt$",
        "scrypt$16384$8$1$!!!$???",
        "scrypt$1$8$1$AAAAAAAAAAAAAAAAAAAAAA$AAAA",
        "scrypt$abc$8$1$AAAA$AAAA",
        "bcrypt$2b$12$abcdefghijklmnopqrstuv",
    ):
        assert check_password_hash("the password itself", stored) is False, stored


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def test_tokens_carry_the_user_and_role() -> None:
    """A token says who signed in and as what, can't be re-signed to a higher role, and old callers still get an admin token."""
    from src.voiceagent.api.auth import token_claims

    now = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    with _env(**BASE_ENV):
        token, expires_at = auth.issue_token(now=now, subject="user-123", role="member")
        later = now + timedelta(hours=1)
        claims = token_claims(token, now=later)
        assert claims is not None, "a fresh token must have claims"
        assert claims["sub"] == "user-123" and claims["role"] == "member", claims
        assert abs(claims["exp"] - _utc(expires_at).timestamp()) <= 1, (claims, expires_at)
        assert auth.verify_token(token, now=later) is True

        assert token_claims(token, now=now + timedelta(hours=13)) is None, "expired tokens have no claims"

        legacy, _ = auth.issue_token(now=now)
        claims = token_claims(legacy, now=later)
        assert claims is not None and claims["sub"] == "admin" and claims["role"] == "owner", claims
        assert auth.verify_token(legacy, now=later) is True

        payload, signature = token.split(".")
        promoted = _b64url(
            json.dumps({"sub": "user-123", "role": "owner", "exp": int(_utc(expires_at).timestamp())}).encode()
        )
        assert token_claims(f"{promoted}.{signature}", now=later) is None, "a re-written role must not verify"
        assert auth.verify_token(f"{promoted}.{signature}", now=later) is False

        for garbage in ("", "abc", "a.b", "a.b.c", "!!!.???"):
            assert token_claims(garbage) is None, garbage

    with _env(**{**BASE_ENV, "AUTH_SECRET": "a-different-secret"}):
        assert token_claims(token, now=later) is None, "a token signed with another secret has no claims"


def test_access_control_turns_on_with_an_admin_password_or_any_user() -> None:
    """The console locks once an admin password is set or anyone has an account, and stays open otherwise."""
    try:
        with _env(**{**BASE_ENV, "AUTH_SECRET": None}):
            auth.set_users_exist(False)
            assert auth.auth_enabled() is False, "no password, no users: open"
            auth.set_users_exist(True)
            assert auth.auth_enabled() is True, "a user exists: locked"
        with _env(**BASE_ENV):
            auth.set_users_exist(False)
            assert auth.auth_enabled() is False, "AUTH_SECRET alone must not lock the console"
        with _env(**{**BASE_ENV, "ADMIN_PASSWORD": ADMIN_PASSWORD}):
            auth.set_users_exist(False)
            assert auth.auth_enabled() is True, "admin password: locked"
            auth.set_users_exist(True)
            assert auth.auth_enabled() is True, "both: locked"
    finally:
        _forget_users()


# ---------------------------------------------------------------------------
# Owner bootstrap
# ---------------------------------------------------------------------------


def test_status_offers_owner_registration_while_nobody_has_an_account() -> None:
    """A fresh deploy tells the console to create the owner, and whether a setup code is needed."""

    async def open_console(http, _sessions):
        body = await _status(http)
        assert body["auth_enabled"] is False and body["authenticated"] is True, body
        assert body["user"] is None, body
        assert body["registration"]["mode"] == "owner", body
        assert body["registration"]["setup_code_required"] is False, body

    async def with_admin_password(http, _sessions):
        body = await _status(http)
        assert body["auth_enabled"] is True and body["authenticated"] is False, body
        assert body["user"] is None, body
        assert body["registration"]["mode"] == "owner", "no user yet, whatever REGISTRATION_MODE says"
        assert body["registration"]["setup_code_required"] is True, body

    _run(open_console, "10.31.1.1")
    _run(with_admin_password, "10.31.1.2", ADMIN_PASSWORD=ADMIN_PASSWORD, REGISTRATION_MODE="closed")


def test_first_registration_creates_the_owner_and_locks_the_console() -> None:
    """Whoever registers first on a fresh deploy becomes the owner, and the console then needs sign-in."""
    from src.voiceagent.api.auth import token_claims

    async def scenario(http, _sessions):
        r = await http.get("/api/campaigns")
        assert r.status_code == 200, f"open before anyone registers: {_show(r)}"

        body = await _register_ok(http, name=OWNER_NAME, email="  Asha@Example.COM ", password=OWNER_PASSWORD)
        assert body.get("token") and body.get("expires_at"), body
        assert _iso(body["expires_at"]) > datetime.now(timezone.utc), body
        user = body["user"]
        assert user.get("id"), user
        assert user["email"] == OWNER_EMAIL, f"emails are stored trimmed and lower-case: {user}"
        assert user["name"] == OWNER_NAME and user["role"] == "owner", user

        claims = token_claims(body["token"])
        assert claims and claims["sub"] == user["id"] and claims["role"] == "owner", claims
        assert auth.auth_enabled() is True, "the first registration must switch access control on"

        r = await http.get("/api/campaigns")
        assert r.status_code == 401, f"locked once an owner exists: {_show(r)}"
        r = await http.get("/api/campaigns", headers=_bearer(body["token"]))
        assert r.status_code == 200, _show(r)

        status = await _status(http, body["token"])
        assert status["auth_enabled"] is True and status["authenticated"] is True, status
        assert {k: status["user"][k] for k in ("id", "email", "name", "role")} == {
            "id": user["id"], "email": OWNER_EMAIL, "name": OWNER_NAME, "role": "owner",
        }, status
        assert status["registration"]["mode"] == "invite", "invite is the default once the owner exists"

        anonymous = await _status(http)
        assert anonymous["authenticated"] is False and anonymous["user"] is None, anonymous

        r = await _register(http, name="Mallory", email="mallory@example.com", password="another fine pass 9")
        assert r.status_code == 403, f"a second person can't register without an invite: {_show(r)}"

    _run(scenario, "10.31.2.1")


def test_owner_registration_works_with_no_secret_configured() -> None:
    """A deploy with neither ADMIN_PASSWORD nor AUTH_SECRET can still create its owner and sign them in."""

    async def scenario(http, _sessions):
        body = await _owner(http)
        r = await http.get("/api/campaigns", headers=_bearer(body["token"]))
        assert r.status_code == 200, _show(r)
        r = await http.get("/api/campaigns")
        assert r.status_code == 401, _show(r)
        r = await _login(http, OWNER_EMAIL, OWNER_PASSWORD)
        assert r.status_code == 200, _show(r)
        r = await http.get("/api/campaigns", headers=_bearer(r.json()["token"]))
        assert r.status_code == 200, _show(r)

    _run(scenario, "10.31.3.1", AUTH_SECRET=None)


def test_with_an_admin_password_the_owner_must_present_it_as_the_setup_code() -> None:
    """A public deploy can't be claimed by a stranger who reaches the register page first."""

    async def scenario(http, _sessions):
        r = await _register(http, name=OWNER_NAME, email=OWNER_EMAIL, password=OWNER_PASSWORD)
        assert r.status_code == 403, f"no setup code: {_show(r)}"
        r = await _register(
            http, name=OWNER_NAME, email=OWNER_EMAIL, password=OWNER_PASSWORD, setup_code="not the password"
        )
        assert r.status_code == 403, f"wrong setup code: {_show(r)}"
        assert "token" not in r.text

        status = await _status(http)
        assert status["registration"]["mode"] == "owner", f"refused attempts create nobody: {status}"

        body = await _owner(http, setup_code=ADMIN_PASSWORD)
        assert body["user"]["role"] == "owner", body
        status = await _status(http, body["token"])
        assert status["authenticated"] is True and status["user"]["role"] == "owner", status
        assert status["registration"]["mode"] == "invite", status

    _run(scenario, "10.31.4.1", ADMIN_PASSWORD=ADMIN_PASSWORD)


# ---------------------------------------------------------------------------
# Registration modes
# ---------------------------------------------------------------------------


def test_after_the_owner_registration_needs_an_invite_by_default() -> None:
    """With REGISTRATION_MODE unset, a stranger can't join without a valid invite code."""

    async def scenario(http, _sessions):
        owner = await _owner(http)
        assert (await _status(http))["registration"]["mode"] == "invite"

        r = await _register(http, email="stranger@example.com", password="stranger pass 42")
        assert r.status_code == 403, f"no invite code: {_show(r)}"
        r = await _register(
            http, email="stranger@example.com", password="stranger pass 42", invite_code="not-a-real-code"
        )
        assert r.status_code == 403, f"unknown invite code: {_show(r)}"

        users = await _team_users(http, owner["token"])
        assert list(users) == [OWNER_EMAIL], f"refused registrations create nobody: {list(users)}"

    _run(scenario, "10.31.5.1")


def test_open_mode_lets_anyone_register_but_only_as_a_member() -> None:
    """With REGISTRATION_MODE=open anyone can join without a code, and never above member."""

    async def scenario(http, _sessions):
        await _owner(http)
        assert (await _status(http))["registration"]["mode"] == "open"

        body = await _register_ok(http, name="Ravi", email="ravi@example.com", password=MEMBER_PASSWORD)
        assert body["user"]["role"] == "member", body
        r = await http.get("/api/campaigns", headers=_bearer(body["token"]))
        assert r.status_code == 200, f"members use the whole console: {_show(r)}"

        for role in ("owner", "admin"):
            r = await _register(
                http, email=f"sneaky-{role}@example.com", password=MEMBER_PASSWORD, extra={"role": role}
            )
            if r.status_code == 201:
                assert r.json()["user"]["role"] == "member", f"asked for {role}: {r.json()}"
            else:
                assert r.status_code in (400, 422), f"asked for {role}: {_show(r)}"

    _run(scenario, "10.31.6.1", REGISTRATION_MODE="open")


def test_closed_mode_refuses_registration_even_with_an_invite() -> None:
    """With REGISTRATION_MODE=closed nobody new gets in, the owner can still bootstrap, and the mode is read on every call."""

    async def scenario(http, _sessions):
        assert (await _status(http))["registration"]["mode"] == "owner"
        owner = await _owner(http)
        assert (await _status(http))["registration"]["mode"] == "closed"

        invite = await _invite(http, owner["token"])
        r = await _register(http, email="ravi@example.com", password=MEMBER_PASSWORD, invite_code=invite["code"])
        assert r.status_code == 403, f"closed, even with an invite: {_show(r)}"
        r = await _register(http, email="meera@example.com", password=MEMBER_PASSWORD)
        assert r.status_code == 403, f"closed, no code: {_show(r)}"

        with _env(REGISTRATION_MODE="invite"):
            assert (await _status(http))["registration"]["mode"] == "invite"
            body = await _register_ok(
                http, email="ravi@example.com", password=MEMBER_PASSWORD, invite_code=invite["code"]
            )
            assert body["user"]["role"] == "member", "the refused attempt must not have used up the invite"

    _run(scenario, "10.31.7.1", REGISTRATION_MODE="closed")


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


def test_an_invite_admits_one_person_only() -> None:
    """An invite code stops working once someone has used it."""

    async def scenario(http, _sessions):
        owner = await _owner(http)
        invite = await _invite(http, owner["token"])
        body = await _register_ok(http, email="ravi@example.com", password=MEMBER_PASSWORD, invite_code=invite["code"])
        assert body["user"]["role"] == "member", body

        r = await _register(http, email="meera@example.com", password=MEMBER_PASSWORD, invite_code=invite["code"])
        assert r.status_code == 403, f"second use of one invite: {_show(r)}"
        assert "used" in _reason(r), f"the reason should say it was used: {r.text}"

    _run(scenario, "10.31.8.1")


def test_an_expired_invite_is_refused() -> None:
    """An invite past its expiry no longer admits anyone."""

    async def scenario(http, sessions):
        owner = await _owner(http)
        invite = await _invite(http, owner["token"], expires_in_days=1)
        await _set_row(sessions, "invites", invite["id"], expires_at=datetime.now(timezone.utc) - timedelta(hours=1))

        r = await _register(http, email="ravi@example.com", password=MEMBER_PASSWORD, invite_code=invite["code"])
        assert r.status_code == 403, f"expired invite: {_show(r)}"
        assert "expire" in _reason(r), f"the reason should say it expired: {r.text}"

    _run(scenario, "10.31.9.1")


def test_a_revoked_invite_is_refused() -> None:
    """Revoking an invite stops its code from working."""

    async def scenario(http, _sessions):
        owner = await _owner(http)
        invite = await _invite(http, owner["token"])
        r = await http.delete(f"/api/team/invites/{invite['id']}", headers=_bearer(owner["token"]))
        assert r.status_code == 204, _show(r)

        r = await _register(http, email="ravi@example.com", password=MEMBER_PASSWORD, invite_code=invite["code"])
        assert r.status_code == 403, f"revoked invite: {_show(r)}"
        assert "revoke" in _reason(r), f"the reason should say it was revoked: {r.text}"

    _run(scenario, "10.31.10.1")


def test_an_email_bound_invite_admits_only_that_address() -> None:
    """An invite made out to one email can't be used by anyone else, and a refused try doesn't use it up."""

    async def scenario(http, _sessions):
        owner = await _owner(http)
        invite = await _invite(http, owner["token"], email="ravi@example.com")
        assert invite["email"] == "ravi@example.com", invite

        r = await _register(http, email="meera@example.com", password=MEMBER_PASSWORD, invite_code=invite["code"])
        assert r.status_code == 403, f"someone else's invite: {_show(r)}"
        assert "email" in _reason(r), f"the reason should mention the email: {r.text}"

        body = await _register_ok(http, email="Ravi@Example.com", password=MEMBER_PASSWORD, invite_code=invite["code"])
        assert body["user"]["email"] == "ravi@example.com" and body["user"]["role"] == "member", body

    _run(scenario, "10.31.11.1")


def test_an_invite_grants_the_role_it_was_created_with() -> None:
    """Accepting an admin invite makes an admin, and a member invite a member."""
    from src.voiceagent.api.auth import token_claims

    async def scenario(http, _sessions):
        owner = await _owner(http)
        admin = await _member(http, owner["token"], "neha@example.com", role="admin")
        member = await _member(http, owner["token"], "ravi@example.com", role="member")

        assert admin["user"]["role"] == "admin", admin
        assert member["user"]["role"] == "member", member
        assert token_claims(admin["token"])["role"] == "admin"
        assert token_claims(member["token"])["role"] == "member"

        r = await http.get("/api/team/users", headers=_bearer(admin["token"]))
        assert r.status_code == 200, f"admins manage the team: {_show(r)}"
        r = await http.get("/api/team/users", headers=_bearer(member["token"]))
        assert r.status_code == 403, f"members don't: {_show(r)}"

    _run(scenario, "10.31.12.1")


# ---------------------------------------------------------------------------
# Password and email rules
# ---------------------------------------------------------------------------


def test_passwords_must_follow_the_rules() -> None:
    """Weak passwords are refused with a message naming the rule, and the limits themselves are allowed."""
    email = "vikram.rules@example.com"
    cases = [
        ("9 characters", "abc12345x", ("10", "short", "at least", "character")),
        ("129 characters", "x" * 129, ("128", "long", "at most", "character")),
        ("all digits", "12345678901234", ("digit", "number")),
        ("same as the email", email, ("email",)),
    ]

    async def scenario(http, _sessions):
        for label, password, words in cases:
            r = await _register(http, name="Vikram", email=email, password=password)
            assert r.status_code == 400, f"{label}: {_show(r)}"
            reason = _reason(r)
            assert any(word in reason for word in words), f"{label}: the message should name the rule: {r.text}"
            assert "token" not in r.text, label

        assert (await _status(http))["registration"]["mode"] == "owner", "refused registrations create nobody"
        await _register_ok(http, name="Vikram", email=email, password="abcdefghi1")  # exactly 10

        with _env(REGISTRATION_MODE="open"):
            longest = "p" * 127 + "!"
            await _register_ok(http, name="Meera", email="meera@example.com", password=longest)
            r = await _login(http, "meera@example.com", longest)
            assert r.status_code == 200, f"a 128-character password signs in: {_show(r)}"

    _run(scenario, "10.31.13.1")


def test_emails_must_look_like_emails_and_be_unique() -> None:
    """Malformed, overlong or already-registered emails are refused before any account is made."""
    malformed = [
        "plainaddress",
        "@example.com",
        "user@",
        "user name@example.com",
        "a" * 245 + "@example.com",  # 257 characters
    ]

    async def scenario(http, _sessions):
        for email in malformed:
            r = await _register(http, email=email, password=OWNER_PASSWORD)
            assert r.status_code == 400, f"{email[:40]!r}: {_show(r)}"
            assert "email" in _reason(r), f"{email[:40]!r}: the message should name the email: {r.text}"
        assert (await _status(http))["registration"]["mode"] == "owner", "refused registrations create nobody"

        await _owner(http)
        with _env(REGISTRATION_MODE="open"):
            for taken in ("ASHA@EXAMPLE.COM", " asha@example.com "):
                r = await _register(http, email=taken, password=MEMBER_PASSWORD)
                assert r.status_code == 409, f"{taken!r} is already registered: {_show(r)}"

    _run(scenario, "10.31.14.1")


# ---------------------------------------------------------------------------
# Signing in
# ---------------------------------------------------------------------------


def test_users_sign_in_with_email_and_password() -> None:
    """A registered user signs in with email and password, gets a working token, and their last sign-in is recorded."""
    from src.voiceagent.api.auth import token_claims

    async def scenario(http, _sessions):
        owner = await _owner(http)
        before = datetime.now(timezone.utc) - timedelta(seconds=2)

        r = await _login(http, "Asha@Example.COM", OWNER_PASSWORD)
        assert r.status_code == 200, _show(r)
        body = r.json()
        assert body.get("token") and body.get("expires_at"), body
        claims = token_claims(body["token"])
        assert claims and claims["sub"] == owner["user"]["id"] and claims["role"] == "owner", claims

        r = await http.get("/api/campaigns", headers=_bearer(body["token"]))
        assert r.status_code == 200, _show(r)

        me = (await _team_users(http, body["token"]))[OWNER_EMAIL]
        assert me.get("last_login_at"), f"a sign-in updates last_login_at: {me}"
        assert _iso(me["last_login_at"]) >= before, me

    _run(scenario, "10.31.15.1")


def test_wrong_credentials_get_one_generic_answer() -> None:
    """A failed sign-in never reveals whether the email has an account."""

    async def scenario(http, _sessions):
        await _owner(http)
        wrong_password = await _login(http, OWNER_EMAIL, "not the right password")
        unknown_email = await _login(http, "nobody@example.com", "not the right password")

        assert wrong_password.status_code == 401, _show(wrong_password)
        assert unknown_email.status_code == 401, _show(unknown_email)
        assert wrong_password.json() == unknown_email.json(), (wrong_password.text, unknown_email.text)
        assert "token" not in wrong_password.text and "token" not in unknown_email.text

    _run(scenario, "10.31.16.1")


def test_a_disabled_user_cannot_sign_in() -> None:
    """A disabled teammate is told their account is disabled, and can sign in again once re-enabled."""

    async def scenario(http, _sessions):
        owner = await _owner(http)
        member = await _member(http, owner["token"], "ravi@example.com")

        r = await _patch_user(http, owner["token"], member["user"]["id"], disabled=True)
        assert r.status_code in (200, 204), _show(r)
        r = await _login(http, "ravi@example.com", MEMBER_PASSWORD)
        assert r.status_code == 403, f"disabled: {_show(r)}"
        assert "this account is disabled" in _reason(r), r.text
        assert "token" not in r.text

        r = await _patch_user(http, owner["token"], member["user"]["id"], disabled=False)
        assert r.status_code in (200, 204), _show(r)
        r = await _login(http, "ravi@example.com", MEMBER_PASSWORD)
        assert r.status_code == 200, f"re-enabled: {_show(r)}"
        r = await http.get("/api/campaigns", headers=_bearer(r.json()["token"]))
        assert r.status_code == 200, _show(r)

    _run(scenario, "10.31.17.1")


def test_disabling_or_removing_a_user_locks_their_token_out_at_once() -> None:
    """A disabled or removed teammate's open sessions stop working immediately, live sockets included."""

    async def scenario(http, _sessions):
        owner = await _owner(http)
        disabled = await _member(http, owner["token"], "ravi@example.com")
        removed = await _member(http, owner["token"], "meera@example.com")

        for who in (disabled, removed):
            r = await http.get("/api/campaigns", headers=_bearer(who["token"]))
            assert r.status_code == 200, _show(r)
        socket = await _websocket("/api/events", f"token={disabled['token']}")
        assert socket["accepted"] and socket["close_code"] != 4401, f"valid before disabling: {socket}"

        r = await _patch_user(http, owner["token"], disabled["user"]["id"], disabled=True)
        assert r.status_code in (200, 204), _show(r)
        r = await http.delete(f"/api/team/users/{removed['user']['id']}", headers=_bearer(owner["token"]))
        assert r.status_code == 204, _show(r)

        for label, who in (("disabled", disabled), ("removed", removed)):
            r = await http.get("/api/campaigns", headers=_bearer(who["token"]))
            assert r.status_code == 401, f"{label} user's token: {_show(r)}"
            r = await http.get(f"/api/calls/export.csv?token={who['token']}")
            assert r.status_code == 401, f"{label} user's ?token=: {_show(r)}"
            status = await _status(http, who["token"])
            assert status["authenticated"] is False and status["user"] is None, (label, status)
            socket = await _websocket("/api/events", f"token={who['token']}")
            assert socket["close_code"] == 4401, f"{label} user's socket: {socket}"

        r = await _login(http, "meera@example.com", MEMBER_PASSWORD)
        assert r.status_code == 401, f"a removed user can't sign in: {_show(r)}"
        r = await http.get("/api/campaigns", headers=_bearer(owner["token"]))
        assert r.status_code == 200, f"everyone else is unaffected: {_show(r)}"

    _run(scenario, "10.31.18.1")


def test_after_a_restart_tokens_of_missing_or_disabled_users_are_refused() -> None:
    """Tokens outlive the process, so after a restart a user who is gone or disabled is still refused."""
    from src.voiceagent.api.auth import hash_password

    async def scenario(http, sessions):
        await _owner(http)

        # Rows this process has never seen, as after a restart that forgot
        # every in-memory revocation.
        users = storage.Base.metadata.tables["users"]
        ids = {}
        async with sessions() as db:
            for email, disabled in (("kept@example.com", False), ("benched@example.com", True)):
                ids[email] = str(uuid.uuid4())
                await db.execute(
                    insert(users).values(
                        id=ids[email],
                        email=email,
                        name=email.split("@")[0].title(),
                        password_hash=hash_password(MEMBER_PASSWORD),
                        role="member",
                        disabled=disabled,
                        created_at=datetime.now(timezone.utc),
                        last_login_at=None,
                    )
                )
            await db.commit()

        ghost, _ = auth.issue_token(subject=str(uuid.uuid4()), role="admin")
        r = await http.get("/api/campaigns", headers=_bearer(ghost))
        assert r.status_code == 401, f"a user that no longer exists: {_show(r)}"

        benched, _ = auth.issue_token(subject=ids["benched@example.com"], role="member")
        r = await http.get("/api/campaigns", headers=_bearer(benched))
        assert r.status_code == 401, f"a user disabled while the process was down: {_show(r)}"

        kept, _ = auth.issue_token(subject=ids["kept@example.com"], role="member")
        r = await http.get("/api/campaigns", headers=_bearer(kept))
        assert r.status_code == 200, f"an enabled user from the database still works: {_show(r)}"

        r = await _login(http, "kept@example.com", MEMBER_PASSWORD)
        assert r.status_code == 200, f"hash_password output is what sign-in checks: {_show(r)}"
        r = await _login(http, "benched@example.com", MEMBER_PASSWORD)
        assert r.status_code == 403, _show(r)

    _run(scenario, "10.31.19.1")


def test_the_admin_password_still_signs_in_as_a_break_glass_owner() -> None:
    """The legacy admin password keeps working next to accounts and acts as the owner."""

    async def scenario(http, _sessions):
        await _owner(http, setup_code=ADMIN_PASSWORD)

        r = await _login(http, None, ADMIN_PASSWORD)
        assert r.status_code == 200, _show(r)
        token = r.json()["token"]
        status = await _status(http, token)
        assert status["authenticated"] is True, status
        assert status["user"] == {"id": "admin", "email": "", "name": "Admin", "role": "owner"}, status

        r = await http.get("/api/campaigns", headers=_bearer(token))
        assert r.status_code == 200, _show(r)
        r = await http.get("/api/team/users", headers=_bearer(token))
        assert r.status_code == 200, f"break-glass sign-in has owner rights: {_show(r)}"

        r = await _login(http, None, "not the admin password")
        assert r.status_code == 401, _show(r)

    async def without_admin_password(http, _sessions):
        await _owner(http)
        r = await _login(http, None, "any old password guess")
        assert r.status_code == 401, f"no ADMIN_PASSWORD means no break-glass sign-in: {_show(r)}"
        assert "token" not in r.text

    _run(scenario, "10.31.20.1", ADMIN_PASSWORD=ADMIN_PASSWORD)
    _run(without_admin_password, "10.31.20.2")


# ---------------------------------------------------------------------------
# Throttling, leaks, health
# ---------------------------------------------------------------------------


def test_repeated_failed_sign_ins_and_registrations_are_throttled() -> None:
    """Guessing passwords or invite codes from one address is cut off with 429, and other addresses are unaffected."""

    async def scenario(http, _sessions):
        await _owner(http)

        ip = "10.31.21.1"
        codes = [(await _login(http, OWNER_EMAIL, f"wrong guess {i}", ip=ip)).status_code for i in range(7)]
        assert codes[:5] == [401] * 5, codes
        assert codes[5] in (401, 429) and codes[6] == 429, codes
        r = await _login(http, OWNER_EMAIL, OWNER_PASSWORD, ip=ip)
        assert r.status_code == 429, f"throttled even with the right password: {_show(r)}"
        r = await _login(http, OWNER_EMAIL, OWNER_PASSWORD, ip="10.31.21.2")
        assert r.status_code == 200, f"another address is not locked out: {_show(r)}"

        ip = "10.31.21.3"
        codes = [
            (
                await _register(
                    http, email=f"guess{i}@example.com", password=MEMBER_PASSWORD, invite_code=f"guess-{i}", ip=ip
                )
            ).status_code
            for i in range(7)
        ]
        assert codes[:5] == [403] * 5, codes
        assert codes[5] in (403, 429) and codes[6] == 429, codes

    _run(scenario, "10.31.21.9")


def test_password_hashes_never_appear_in_any_response() -> None:
    """No endpoint ever sends back a password hash or a password."""

    async def scenario(http, _sessions):
        seen: list[httpx.Response] = []
        owner = await _register(http, name=OWNER_NAME, email=OWNER_EMAIL, password=OWNER_PASSWORD)
        assert owner.status_code == 201, _show(owner)
        seen.append(owner)
        token = owner.json()["token"]
        member = await _register(http, name="Ravi", email="ravi@example.com", password=MEMBER_PASSWORD)
        assert member.status_code == 201, _show(member)
        seen.append(member)
        seen.append(await _login(http, OWNER_EMAIL, OWNER_PASSWORD))
        seen.append(await _login(http, OWNER_EMAIL, "not the right password"))
        seen.append(await http.get("/api/auth/status", headers=_bearer(token)))
        seen.append(await http.get("/api/team/users", headers=_bearer(token)))
        seen.append(await _patch_user(http, token, member.json()["user"]["id"], role="admin"))
        seen.append(await http.post("/api/team/invites", json={"role": "member"}, headers=_bearer(token)))
        seen.append(await http.get("/api/team/invites", headers=_bearer(token)))
        seen.append(await http.get("/api/health"))

        for r in seen:
            assert r.status_code < 500, _show(r)
            text = r.text
            assert "password_hash" not in text, _show(r)
            assert "scrypt$" not in text, _show(r)
            assert OWNER_PASSWORD not in text and MEMBER_PASSWORD not in text, _show(r)

    _run(scenario, "10.31.22.1", REGISTRATION_MODE="open")


def test_health_reports_how_many_accounts_exist_and_the_registration_mode() -> None:
    """Monitoring sees the account count and registration mode without signing in."""

    async def scenario(http, _sessions):
        r = await http.get("/api/health")
        assert r.status_code == 200, _show(r)
        accounts = r.json()["accounts"]
        assert accounts["users"] == 0, accounts
        assert isinstance(accounts["registration_mode"], str), accounts
        assert r.json()["auth_enabled"] is False, r.json()

        owner = await _owner(http)
        r = await http.get("/api/health")
        assert r.status_code == 200, f"health stays open once accounts lock the console: {_show(r)}"
        assert r.json()["auth_enabled"] is True, r.json()
        assert r.json()["accounts"] == {"users": 1, "registration_mode": "invite"}, r.json()["accounts"]

        await _member(http, owner["token"], "ravi@example.com")
        with _env(REGISTRATION_MODE="open"):
            await _register_ok(http, email="meera@example.com", password=MEMBER_PASSWORD)
            r = await http.get("/api/health")
            assert r.json()["accounts"] == {"users": 3, "registration_mode": "open"}, r.json()["accounts"]

    _run(scenario, "10.31.23.1")


# ---------------------------------------------------------------------------


def _run_all() -> int:
    # Failure messages can hold Devanagari; a cp1252 console must not crash the run.
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"pass  {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
