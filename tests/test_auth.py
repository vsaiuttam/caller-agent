"""Opt-in access control: one admin password, signed expiring tokens.

With ADMIN_PASSWORD unset nothing changes — the console stays open exactly as
before. With it set, every /api/* route except health and the auth routes
needs a token, the live sockets need one too, and Twilio's webhooks are never
locked out (Twilio can't log in).

Drives the real FastAPI app over ASGI against a throwaway SQLite database.
WebSockets are driven with a raw ASGI harness so a socket that wrongly stays
open fails the test instead of hanging it. Env vars (ADMIN_PASSWORD,
AUTH_SECRET, AUTH_TOKEN_TTL_HOURS) are set per test, so they must be read at
call time. Runs standalone (`python tests/test_auth.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import sys
import tempfile
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)

PASSWORD = "correct horse battery staple"
AUTH_ON = dict(ADMIN_PASSWORD=PASSWORD, AUTH_SECRET=None, AUTH_TOKEN_TTL_HOURS=None)
AUTH_OFF = dict(ADMIN_PASSWORD=None, AUTH_SECRET=None, AUTH_TOKEN_TTL_HOURS=None)
LOCKED = {"detail": "Authentication required"}


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


@asynccontextmanager
async def _api(client_ip: str):
    """The real app on a throwaway database, seen from `client_ip`.

    Each test uses its own address so failed-login throttling in one test
    can't leak into another.
    """
    path = Path(tempfile.mkdtemp()) / "auth.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(storage.Base.metadata.create_all)
    sessions = async_sessionmaker(engine, expire_on_commit=False)

    async def override():
        async with sessions() as session:
            yield session

    app = app_module.app
    saved = storage.SessionLocal, getattr(app_module, "SessionLocal", None)
    app.dependency_overrides[storage.get_session] = override
    storage.SessionLocal = sessions
    if saved[1] is not None:
        app_module.SessionLocal = sessions
    try:
        async with httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app, client=(client_ip, 5000)),
            base_url="http://test",
            headers={"X-Forwarded-For": client_ip},
        ) as http:
            yield http
    finally:
        app.dependency_overrides.pop(storage.get_session, None)
        storage.SessionLocal = saved[0]
        if saved[1] is not None:
            app_module.SessionLocal = saved[1]
        await engine.dispose()


async def _websocket(path: str, query: str = "", *, wait: float = 0.5) -> dict:
    """Open a WebSocket on the app over raw ASGI and report what the server did.

    Returns {"accepted": bool, "close_code": int | None}. `close_code` is None
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
        "client": ("10.0.9.9", 5000),
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


def _b64decode(part: str) -> bytes:
    return base64.urlsafe_b64decode(part + "=" * (-len(part) % 4))


def _b64encode(raw: bytes) -> str:
    return base64.urlsafe_b64encode(raw).rstrip(b"=").decode()


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _login(http: httpx.AsyncClient, password: str = PASSWORD) -> httpx.Response:
    return await http.post("/api/auth/login", json={"password": password})


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


# ---------------------------------------------------------------------------
# Tokens
# ---------------------------------------------------------------------------


def test_auth_is_off_unless_an_admin_password_is_set() -> None:
    from src.voiceagent.api import auth

    with _env(**AUTH_OFF):
        assert auth.auth_enabled() is False
    with _env(ADMIN_PASSWORD=""):
        assert auth.auth_enabled() is False
    with _env(ADMIN_PASSWORD=None, AUTH_SECRET="some-secret"):
        assert auth.auth_enabled() is False, "AUTH_SECRET alone must not lock the console"
    with _env(**AUTH_ON):
        assert auth.auth_enabled() is True


def test_a_fresh_token_verifies_and_carries_its_expiry() -> None:
    from src.voiceagent.api import auth

    with _env(**AUTH_ON):
        before = datetime.now(timezone.utc)
        token, expires_at = auth.issue_token()
        assert auth.verify_token(token) is True

    assert isinstance(token, str) and isinstance(expires_at, datetime)
    lifetime = _utc(expires_at) - before
    assert timedelta(hours=12) - timedelta(seconds=5) <= lifetime <= timedelta(hours=12, seconds=5), lifetime

    parts = token.split(".")
    assert len(parts) == 2, token
    payload = json.loads(_b64decode(parts[0]))
    assert abs(payload["exp"] - _utc(expires_at).timestamp()) <= 1, (payload, expires_at)
    assert len(_b64decode(parts[1])) == 32, "the signature should be an HMAC-SHA256 digest"


def test_the_token_lifetime_follows_the_env_setting() -> None:
    from src.voiceagent.api import auth

    now = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    with _env(AUTH_TOKEN_TTL_HOURS="1", ADMIN_PASSWORD=PASSWORD, AUTH_SECRET=None):
        token, expires_at = auth.issue_token(now=now)
        assert auth.verify_token(token, now=now + timedelta(minutes=59)) is True
        assert auth.verify_token(token, now=now + timedelta(minutes=61)) is False
    assert _utc(expires_at) == now + timedelta(hours=1), expires_at


def test_expired_or_tampered_tokens_are_rejected() -> None:
    from src.voiceagent.api import auth

    now = datetime(2026, 9, 1, 10, 0, tzinfo=timezone.utc)
    with _env(**AUTH_ON):
        token, _ = auth.issue_token(now=now)
        assert auth.verify_token(token, now=now + timedelta(hours=11)) is True
        assert auth.verify_token(token, now=now + timedelta(hours=13)) is False
        assert auth.verify_token(token) is False, "a token from 2026-09-01 must be long expired"

        payload, signature = token.split(".")
        flipped = ("B" if signature[0] == "A" else "A") + signature[1:]
        assert auth.verify_token(f"{payload}.{flipped}", now=now) is False

        # A later expiry under the old signature.
        forged = _b64encode(json.dumps({"exp": int((now + timedelta(days=365)).timestamp())}).encode())
        assert auth.verify_token(f"{forged}.{signature}", now=now) is False

        for garbage in ("", "abc", "a.b", "a.b.c", "!!!.???", "eyJleHAiOjF9."):
            assert auth.verify_token(garbage) is False, garbage


def test_tokens_are_signed_with_the_configured_secret() -> None:
    """Changing AUTH_SECRET (or, without one, the password) logs everyone out."""
    from src.voiceagent.api import auth

    with _env(ADMIN_PASSWORD=PASSWORD, AUTH_SECRET="secret-a", AUTH_TOKEN_TTL_HOURS=None):
        token, _ = auth.issue_token()
    with _env(ADMIN_PASSWORD=PASSWORD, AUTH_SECRET="secret-b", AUTH_TOKEN_TTL_HOURS=None):
        assert auth.verify_token(token) is False
    with _env(ADMIN_PASSWORD=PASSWORD, AUTH_SECRET="secret-a", AUTH_TOKEN_TTL_HOURS=None):
        assert auth.verify_token(token) is True

    with _env(ADMIN_PASSWORD="first password", AUTH_SECRET=None, AUTH_TOKEN_TTL_HOURS=None):
        token, _ = auth.issue_token()
    with _env(ADMIN_PASSWORD="second password", AUTH_SECRET=None, AUTH_TOKEN_TTL_HOURS=None):
        assert auth.verify_token(token) is False
    with _env(ADMIN_PASSWORD="first password", AUTH_SECRET=None, AUTH_TOKEN_TTL_HOURS=None):
        assert auth.verify_token(token) is True


# ---------------------------------------------------------------------------
# HTTP
# ---------------------------------------------------------------------------


def test_with_auth_off_the_api_stays_open() -> None:
    async def scenario() -> None:
        async with _api("10.0.1.1") as http:
            r = await http.get("/api/campaigns")
            assert r.status_code == 200, (r.status_code, r.text)
            r = await http.get("/api/auth/status")
            assert r.status_code == 200, (r.status_code, r.text)
            assert r.json().get("auth_enabled") is False, r.json()
            r = await http.get("/api/health")
            assert r.status_code == 200 and r.json().get("auth_enabled") is False, r.text

    with _env(**AUTH_OFF):
        asyncio.run(scenario())


def test_with_auth_on_api_routes_need_a_token() -> None:
    async def scenario() -> None:
        async with _api("10.0.2.2") as http:
            requests = [
                ("GET", "/api/campaigns", None),
                ("GET", "/api/templates", None),
                ("GET", "/api/stats", None),
                ("GET", "/api/calls/export.csv", None),
                ("POST", "/api/campaigns", {"name": "Smile Dental", "goal": "Confirm."}),
            ]
            for method, url, body in requests:
                r = await http.request(method, url, json=body)
                assert r.status_code == 401, (method, url, r.status_code, r.text)
                assert r.json() == LOCKED, (url, r.json())

    with _env(**AUTH_ON):
        asyncio.run(scenario())


def test_the_right_password_returns_a_token_that_opens_the_api() -> None:
    async def scenario() -> None:
        async with _api("10.0.3.3") as http:
            r = await _login(http)
            assert r.status_code == 200, (r.status_code, r.text)
            body = r.json()
            assert body.get("token") and body.get("expires_at"), body
            datetime.fromisoformat(body["expires_at"].replace("Z", "+00:00"))
            token = body["token"]

            r = await http.get("/api/campaigns", headers=_bearer(token))
            assert r.status_code == 200, ("bearer", r.status_code, r.text)

            # ?token= is for <audio> and download links, which can't send headers.
            r = await http.get(f"/api/calls/export.csv?token={token}")
            assert r.status_code == 200, ("query token", r.status_code, r.text)

            r = await http.get("/api/auth/status", headers=_bearer(token))
            assert {"auth_enabled": True, "authenticated": True}.items() <= r.json().items(), r.json()

    with _env(**AUTH_ON):
        asyncio.run(scenario())


def test_a_wrong_password_is_refused() -> None:
    async def scenario() -> None:
        async with _api("10.0.4.4") as http:
            r = await _login(http, "not the password")
            assert r.status_code == 401, (r.status_code, r.text)
            assert "token" not in r.text

    with _env(**AUTH_ON):
        asyncio.run(scenario())


def test_a_bad_or_expired_token_is_refused() -> None:
    from src.voiceagent.api import auth

    async def scenario() -> None:
        expired, _ = auth.issue_token(now=datetime(2020, 1, 1, tzinfo=timezone.utc))
        async with _api("10.0.5.5") as http:
            for token in ("not-a-token", expired):
                r = await http.get("/api/campaigns", headers=_bearer(token))
                assert r.status_code == 401, (token[:12], r.status_code, r.text)
                r = await http.get(f"/api/campaigns?token={token}")
                assert r.status_code == 401, (token[:12], r.status_code, r.text)
            r = await http.get("/api/auth/status", headers=_bearer(expired))
            assert {"auth_enabled": True, "authenticated": False}.items() <= r.json().items(), r.json()

    with _env(**AUTH_ON):
        asyncio.run(scenario())


def test_health_status_and_login_stay_open() -> None:
    """The login page needs to ask whether to show itself, and health is monitoring."""

    async def scenario() -> None:
        async with _api("10.0.6.6") as http:
            r = await http.get("/api/health")
            assert r.status_code == 200, (r.status_code, r.text)
            assert r.json().get("auth_enabled") is True, r.json()

            r = await http.get("/api/auth/status")
            assert r.status_code == 200, (r.status_code, r.text)
            assert {"auth_enabled": True, "authenticated": False}.items() <= r.json().items(), r.json()

            r = await _login(http, "wrong")
            assert r.status_code == 401, "login itself must be reachable without a token"

    with _env(**AUTH_ON):
        asyncio.run(scenario())


def test_twilio_webhooks_are_never_behind_auth() -> None:
    """Twilio can't log in; locking its webhooks would drop every call."""

    async def scenario() -> None:
        async with _api("10.0.7.7") as http:
            r = await http.post("/twilio/status/no-such-room", data={"CallStatus": "completed"})
            assert r.status_code == 200, (r.status_code, r.text)
            r = await http.post("/twilio/voice/no-such-room", data={"CallSid": "CA1"})
            assert r.status_code == 200 and "<Hangup/>" in r.text, (r.status_code, r.text)

    with _env(**AUTH_ON):
        asyncio.run(scenario())


def test_repeated_failed_logins_are_throttled() -> None:
    """More than 5 failures from one client in 5 minutes gets 429, not more guesses."""

    async def scenario() -> None:
        async with _api("10.0.8.8") as http:
            codes = [(await _login(http, f"guess-{i}")).status_code for i in range(7)]
        assert codes[:5] == [401] * 5, codes
        assert codes[5] in (401, 429) and codes[6] == 429, codes

        # Someone else is not locked out by it.
        async with _api("10.0.8.9") as http:
            r = await _login(http)
            assert r.status_code == 200, (r.status_code, r.text)

    with _env(**AUTH_ON):
        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# WebSockets
# ---------------------------------------------------------------------------


def test_websockets_need_a_token_when_auth_is_on() -> None:
    from src.voiceagent.api import auth

    async def scenario() -> None:
        token, _ = auth.issue_token()
        for path in ("/api/events", "/api/live"):
            for query in ("", "token=not-a-token"):
                result = await _websocket(path, query)
                assert result["close_code"] == 4401, (path, query, result)

            result = await _websocket(path, f"token={token}")
            assert result["accepted"] and result["close_code"] != 4401, (path, "valid token", result)

    with _env(**AUTH_ON):
        asyncio.run(scenario())


def test_websockets_stay_open_when_auth_is_off() -> None:
    async def scenario() -> None:
        result = await _websocket("/api/events")
        assert result == {"accepted": True, "close_code": None}, result

    with _env(**AUTH_OFF):
        asyncio.run(scenario())


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
