"""The team API: who may manage accounts, what they may change, and invites.

Covers docs/accounts-spec.md §1 "Team" from the outside: only the owner and
admins reach /api/team/*, members get 403 and anonymous callers 401; the
owner can't be changed or removed; admins can't change other admins; nobody
can disable or remove themselves; only the owner invites admins; an invite
code is returned once and never listed; invite statuses (pending, used,
expired, revoked); and revoking an invite.

Drives the real FastAPI app over ASGI against a throwaway SQLite database.
Env vars (ADMIN_PASSWORD, AUTH_SECRET, REGISTRATION_MODE) are set per test and
must be read at call time; the in-process "a user exists" flag is reset around
every test with `auth.set_users_exist(False)`. Register and login calls come
from a fresh X-Forwarded-For address each, so no check can throttle another.
Runs standalone (`python tests/test_team_api.py`) or under pytest.

Where the spec names a refusal but not its status code (the owner and
self-protection guards), any of 400/403/409 is accepted and the test checks
that nothing changed.
"""

from __future__ import annotations

import asyncio
import itertools
import logging
import os
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import update  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402
from src.voiceagent.api import auth  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)

SECRET = "team-test-signing-secret"
ADMIN_PASSWORD = "break glass in an emergency"
PASSWORD = "team pass phrase 77"

OWNER_EMAIL = "asha@example.com"
ADMIN_EMAIL = "neha@example.com"
MEMBER_EMAIL = "ravi@example.com"

USER_FIELDS = {"id", "email", "name", "role", "disabled", "created_at", "last_login_at"}
INVITE_CREATED_FIELDS = {"id", "code", "email", "role", "expires_at"}
INVITE_LISTED_FIELDS = {"id", "email", "role", "created_at", "expires_at", "used_at", "revoked", "status"}
# A guard with no status code in the spec: refused, one way or another.
REFUSED = (400, 403, 409)
INVALID = (400, 422)

BASE_ENV = dict(
    ADMIN_PASSWORD=None,
    AUTH_SECRET=SECRET,
    REGISTRATION_MODE=None,
    AUTH_TOKEN_TTL_HOURS=None,
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
    a test fails on what it checks rather than in its teardown.
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
    path = Path(tempfile.mkdtemp()) / "team.db"
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
    return f"10.49.{n // 250}.{n % 250 + 1}"


def _bearer(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


def _show(r: httpx.Response) -> str:
    return f"{r.request.method} {r.request.url.path} -> {r.status_code} {r.text[:300]}"


async def _register(http: httpx.AsyncClient, email: str, **extra) -> httpx.Response:
    body = {"name": email.split("@")[0].title(), "email": email, "password": PASSWORD, **extra}
    return await http.post("/api/auth/register", json=body, headers={"X-Forwarded-For": _fresh_ip()})


async def _register_ok(http: httpx.AsyncClient, email: str, **extra) -> dict:
    r = await _register(http, email, **extra)
    assert r.status_code == 201, f"expected 201 from register: {_show(r)}"
    return r.json()


async def _login(http: httpx.AsyncClient, email: str | None, password: str = PASSWORD) -> httpx.Response:
    body = {"password": password} if email is None else {"email": email, "password": password}
    return await http.post("/api/auth/login", json=body, headers={"X-Forwarded-For": _fresh_ip()})


async def _create_invite(http: httpx.AsyncClient, token: str, **body) -> httpx.Response:
    return await http.post("/api/team/invites", json=body, headers=_bearer(token))


async def _invite(http: httpx.AsyncClient, token: str, **body) -> dict:
    r = await _create_invite(http, token, **body)
    assert r.status_code == 201, f"expected 201 from invite: {_show(r)}"
    return r.json()


async def _join(http: httpx.AsyncClient, inviter_token: str, email: str, role: str = "member") -> dict:
    """Invite and register a teammate; returns {token, expires_at, user}."""
    invite = await _invite(http, inviter_token, role=role)
    return await _register_ok(http, email, invite_code=invite["code"])


async def _team(http: httpx.AsyncClient) -> dict[str, dict]:
    """An owner, an admin and a member, each as {token, expires_at, user}."""
    owner = await _register_ok(http, OWNER_EMAIL)
    assert owner["user"]["role"] == "owner", owner
    admin = await _join(http, owner["token"], ADMIN_EMAIL, role="admin")
    member = await _join(http, owner["token"], MEMBER_EMAIL)
    return {"owner": owner, "admin": admin, "member": member}


async def _users(http: httpx.AsyncClient, token: str) -> dict[str, dict]:
    r = await http.get("/api/team/users", headers=_bearer(token))
    assert r.status_code == 200, _show(r)
    assert isinstance(r.json(), list), r.json()
    return {user["email"]: user for user in r.json()}


async def _invites(http: httpx.AsyncClient, token: str) -> tuple[httpx.Response, dict[str, dict]]:
    r = await http.get("/api/team/invites", headers=_bearer(token))
    assert r.status_code == 200, _show(r)
    assert isinstance(r.json(), list), r.json()
    return r, {invite["id"]: invite for invite in r.json()}


async def _patch(http: httpx.AsyncClient, token: str, user_id: str, **body) -> httpx.Response:
    return await http.patch(f"/api/team/users/{user_id}", json=body, headers=_bearer(token))


async def _delete_user(http: httpx.AsyncClient, token: str, user_id: str) -> httpx.Response:
    return await http.delete(f"/api/team/users/{user_id}", headers=_bearer(token))


async def _set_row(sessions, table: str, row_id: str, **values) -> None:
    """Change a row behind the API's back, the way time would."""
    t = storage.Base.metadata.tables[table]
    async with sessions() as db:
        result = await db.execute(update(t).where(t.c.id == row_id).values(**values))
        await db.commit()
    assert result.rowcount == 1, (table, row_id, result.rowcount)


def _requests(user_id: str, invite_id: str) -> list[tuple[str, str, dict | None]]:
    """Every team endpoint, as (method, path, body)."""
    return [
        ("GET", "/api/team/users", None),
        ("PATCH", f"/api/team/users/{user_id}", {"role": "admin"}),
        ("DELETE", f"/api/team/users/{user_id}", None),
        ("POST", "/api/team/invites", {"role": "member"}),
        ("GET", "/api/team/invites", None),
        ("DELETE", f"/api/team/invites/{invite_id}", None),
    ]


# ---------------------------------------------------------------------------
# Role guards
# ---------------------------------------------------------------------------


def test_team_endpoints_need_a_signed_in_user() -> None:
    """Nobody reaches the team endpoints without signing in."""

    async def scenario(http, _sessions):
        team = await _team(http)
        invite = await _invite(http, team["owner"]["token"])
        for method, path, body in _requests(team["member"]["user"]["id"], invite["id"]):
            r = await http.request(method, path, json=body)
            assert r.status_code == 401, f"anonymous: {_show(r)}"

        users = await _users(http, team["owner"]["token"])
        assert users[MEMBER_EMAIL]["role"] == "member", "anonymous calls changed nothing"

    _run(scenario, "10.32.1.1")


def test_members_cannot_manage_the_team() -> None:
    """A member uses the console but gets 403 from every team endpoint."""

    async def scenario(http, _sessions):
        team = await _team(http)
        member = team["member"]
        invite = await _invite(http, team["owner"]["token"])
        for target in (team["admin"]["user"]["id"], member["user"]["id"]):
            for method, path, body in _requests(target, invite["id"]):
                r = await http.request(method, path, json=body, headers=_bearer(member["token"]))
                assert r.status_code == 403, f"member: {_show(r)}"

        r = await http.get("/api/campaigns", headers=_bearer(member["token"]))
        assert r.status_code == 200, f"members still use the whole console: {_show(r)}"
        users = await _users(http, team["owner"]["token"])
        assert users[MEMBER_EMAIL]["role"] == "member" and users[ADMIN_EMAIL]["role"] == "admin", users
        _, invites = await _invites(http, team["owner"]["token"])
        assert invites[invite["id"]]["status"] == "pending", "a member can't revoke an invite"

    _run(scenario, "10.32.2.1")


def test_owner_and_admins_see_the_team_without_password_hashes() -> None:
    """The owner and admins list every teammate with their role and status, never a password hash."""

    async def scenario(http, _sessions):
        team = await _team(http)
        for who in ("owner", "admin"):
            r = await http.get("/api/team/users", headers=_bearer(team[who]["token"]))
            assert r.status_code == 200, f"{who}: {_show(r)}"
            assert "password_hash" not in r.text and "scrypt$" not in r.text and PASSWORD not in r.text, r.text
            users = {user["email"]: user for user in r.json()}
            assert set(users) == {OWNER_EMAIL, ADMIN_EMAIL, MEMBER_EMAIL}, list(users)
            for email, user in users.items():
                assert USER_FIELDS <= set(user), f"{email} is missing {USER_FIELDS - set(user)}"
                assert user["disabled"] is False, user
                _iso(user["created_at"])
            assert {e: u["role"] for e, u in users.items()} == {
                OWNER_EMAIL: "owner", ADMIN_EMAIL: "admin", MEMBER_EMAIL: "member",
            }
            assert users[MEMBER_EMAIL]["id"] == team["member"]["user"]["id"], users[MEMBER_EMAIL]

    _run(scenario, "10.32.3.1")


def test_the_break_glass_admin_password_manages_the_team_as_owner() -> None:
    """Signing in with the legacy admin password gives full owner rights over the team."""

    async def scenario(http, _sessions):
        await _register_ok(http, OWNER_EMAIL, setup_code=ADMIN_PASSWORD)
        r = await _login(http, None, ADMIN_PASSWORD)
        assert r.status_code == 200, _show(r)
        token = r.json()["token"]

        assert set(await _users(http, token)) == {OWNER_EMAIL}
        invite = await _invite(http, token, role="admin")
        assert invite["role"] == "admin", invite
        admin = await _register_ok(http, ADMIN_EMAIL, invite_code=invite["code"])
        assert admin["user"]["role"] == "admin", admin

    _run(scenario, "10.32.4.1", ADMIN_PASSWORD=ADMIN_PASSWORD)


# ---------------------------------------------------------------------------
# Changing and removing users
# ---------------------------------------------------------------------------


def test_the_owner_changes_roles_and_access() -> None:
    """The owner can promote, demote, disable and re-enable teammates, and a promotion takes effect at next sign-in."""

    async def scenario(http, _sessions):
        team = await _team(http)
        owner, member_id = team["owner"]["token"], team["member"]["user"]["id"]

        r = await _patch(http, owner, member_id, role="admin")
        assert r.status_code in (200, 204), _show(r)
        assert (await _users(http, owner))[MEMBER_EMAIL]["role"] == "admin"
        r = await _login(http, MEMBER_EMAIL)
        assert r.status_code == 200, _show(r)
        r = await http.get("/api/team/users", headers=_bearer(r.json()["token"]))
        assert r.status_code == 200, f"promoted to admin, then signed in again: {_show(r)}"

        r = await _patch(http, owner, member_id, role="member")
        assert r.status_code in (200, 204), _show(r)
        assert (await _users(http, owner))[MEMBER_EMAIL]["role"] == "member"

        r = await _patch(http, owner, team["admin"]["user"]["id"], disabled=True)
        assert r.status_code in (200, 204), _show(r)
        assert (await _users(http, owner))[ADMIN_EMAIL]["disabled"] is True
        r = await _patch(http, owner, team["admin"]["user"]["id"], disabled=False)
        assert r.status_code in (200, 204), _show(r)
        assert (await _users(http, owner))[ADMIN_EMAIL]["disabled"] is False

    _run(scenario, "10.32.5.1")


def test_roles_can_only_be_set_to_admin_or_member() -> None:
    """There is only ever one owner: nobody can be made owner, or given a made-up role."""

    async def scenario(http, _sessions):
        team = await _team(http)
        owner = team["owner"]["token"]
        for role in ("owner", "superuser", ""):
            r = await _patch(http, owner, team["member"]["user"]["id"], role=role)
            assert r.status_code in INVALID, f"role {role!r}: {_show(r)}"

        users = await _users(http, owner)
        assert [u["email"] for u in users.values() if u["role"] == "owner"] == [OWNER_EMAIL], users
        assert users[MEMBER_EMAIL]["role"] == "member", users[MEMBER_EMAIL]

    _run(scenario, "10.32.6.1")


def test_the_owner_cannot_be_changed_or_removed() -> None:
    """Nobody, the owner included, can demote, disable or remove the owner."""

    async def scenario(http, _sessions):
        team = await _team(http)
        owner_id = team["owner"]["user"]["id"]
        attempts = [
            ("admin demotes owner", team["admin"]["token"], "PATCH", {"role": "member"}),
            ("admin disables owner", team["admin"]["token"], "PATCH", {"disabled": True}),
            ("admin removes owner", team["admin"]["token"], "DELETE", None),
            ("owner demotes self", team["owner"]["token"], "PATCH", {"role": "admin"}),
            ("owner disables self", team["owner"]["token"], "PATCH", {"disabled": True}),
            ("owner removes self", team["owner"]["token"], "DELETE", None),
        ]
        for label, token, method, body in attempts:
            r = await http.request(method, f"/api/team/users/{owner_id}", json=body, headers=_bearer(token))
            assert r.status_code in REFUSED, f"{label}: {_show(r)}"

        me = (await _users(http, team["owner"]["token"]))[OWNER_EMAIL]
        assert me["role"] == "owner" and me["disabled"] is False, me
        r = await http.get("/api/campaigns", headers=_bearer(team["owner"]["token"]))
        assert r.status_code == 200, f"the owner's session is untouched: {_show(r)}"

    _run(scenario, "10.32.7.1")


def test_admins_cannot_change_other_admins_but_can_manage_members() -> None:
    """An admin can't demote, disable or remove another admin, but can manage members; the owner can manage admins."""

    async def scenario(http, _sessions):
        team = await _team(http)
        other = await _join(http, team["owner"]["token"], "kiran@example.com", role="admin")
        admin, other_id = team["admin"]["token"], other["user"]["id"]

        for label, method, body in (
            ("demote", "PATCH", {"role": "member"}),
            ("disable", "PATCH", {"disabled": True}),
            ("remove", "DELETE", None),
        ):
            r = await http.request(method, f"/api/team/users/{other_id}", json=body, headers=_bearer(admin))
            assert r.status_code in REFUSED, f"admin {label}s another admin: {_show(r)}"
        other_now = (await _users(http, admin))["kiran@example.com"]
        assert other_now["role"] == "admin" and other_now["disabled"] is False, other_now

        member_id = team["member"]["user"]["id"]
        r = await _patch(http, admin, member_id, disabled=True)
        assert r.status_code in (200, 204), f"admin disables a member: {_show(r)}"
        assert (await _users(http, admin))[MEMBER_EMAIL]["disabled"] is True
        r = await _delete_user(http, admin, member_id)
        assert r.status_code == 204, f"admin removes a member: {_show(r)}"
        assert MEMBER_EMAIL not in await _users(http, admin)

        r = await _patch(http, team["owner"]["token"], other_id, role="member")
        assert r.status_code in (200, 204), f"the owner can demote an admin: {_show(r)}"
        assert (await _users(http, admin))["kiran@example.com"]["role"] == "member"

    _run(scenario, "10.32.8.1")


def test_nobody_can_disable_or_remove_themselves() -> None:
    """An admin can't lock themselves out by disabling or removing their own account."""

    async def scenario(http, _sessions):
        team = await _team(http)
        admin, admin_id = team["admin"]["token"], team["admin"]["user"]["id"]

        r = await _patch(http, admin, admin_id, disabled=True)
        assert r.status_code in REFUSED, f"admin disables self: {_show(r)}"
        r = await _delete_user(http, admin, admin_id)
        assert r.status_code in REFUSED, f"admin removes self: {_show(r)}"

        me = (await _users(http, admin))[ADMIN_EMAIL]
        assert me["disabled"] is False, me
        r = await http.get("/api/campaigns", headers=_bearer(admin))
        assert r.status_code == 200, _show(r)

    _run(scenario, "10.32.9.1")


def test_removing_a_user_takes_them_off_the_team() -> None:
    """A removed teammate disappears from the list and can no longer sign in."""

    async def scenario(http, _sessions):
        team = await _team(http)
        r = await _delete_user(http, team["owner"]["token"], team["member"]["user"]["id"])
        assert r.status_code == 204, _show(r)
        assert not r.content, f"204 has no body: {r.text!r}"

        assert set(await _users(http, team["owner"]["token"])) == {OWNER_EMAIL, ADMIN_EMAIL}
        r = await _login(http, MEMBER_EMAIL)
        assert r.status_code == 401, _show(r)

    _run(scenario, "10.32.10.1")


def test_unknown_users_and_invites_are_not_found() -> None:
    """Acting on a user or invite that doesn't exist says so with 404."""

    async def scenario(http, _sessions):
        team = await _team(http)
        owner, nobody = team["owner"]["token"], str(uuid.uuid4())
        r = await _patch(http, owner, nobody, role="admin")
        assert r.status_code == 404, _show(r)
        r = await _delete_user(http, owner, nobody)
        assert r.status_code == 404, _show(r)
        r = await http.delete(f"/api/team/invites/{nobody}", headers=_bearer(owner))
        assert r.status_code == 404, _show(r)

    _run(scenario, "10.32.11.1")


# ---------------------------------------------------------------------------
# Invites
# ---------------------------------------------------------------------------


def test_only_the_owner_can_invite_admins() -> None:
    """Admins can invite members but not other admins; the owner can invite either."""

    async def scenario(http, _sessions):
        team = await _team(http)
        r = await _create_invite(http, team["admin"]["token"], role="admin")
        assert r.status_code == 403, f"admin invites an admin: {_show(r)}"
        r = await _create_invite(http, team["admin"]["token"], role="member")
        assert r.status_code == 201 and r.json()["role"] == "member", f"admin invites a member: {_show(r)}"
        r = await _create_invite(http, team["owner"]["token"], role="admin")
        assert r.status_code == 201 and r.json()["role"] == "admin", f"owner invites an admin: {_show(r)}"

    _run(scenario, "10.32.12.1")


def test_an_invite_code_is_shown_once_and_never_listed() -> None:
    """Creating an invite returns its code that one time; the invite list never contains a code."""

    async def scenario(http, _sessions):
        team = await _team(http)
        owner = team["owner"]["token"]
        now = datetime.now(timezone.utc)

        default = await _invite(http, owner)
        assert INVITE_CREATED_FIELDS <= set(default), f"missing {INVITE_CREATED_FIELDS - set(default)}"
        assert isinstance(default["code"], str) and len(default["code"]) >= 8, default
        assert default["role"] == "member" and default["email"] is None, default
        expires = _iso(default["expires_at"])
        assert abs(expires - (now + timedelta(days=7))) < timedelta(minutes=5), f"default expiry is 7 days: {expires}"

        bound = await _invite(http, owner, email="kiran@example.com", role="admin", expires_in_days=30)
        assert bound["email"] == "kiran@example.com" and bound["role"] == "admin", bound
        assert abs(_iso(bound["expires_at"]) - (now + timedelta(days=30))) < timedelta(minutes=5), bound

        short = await _invite(http, owner, expires_in_days=1)
        assert abs(_iso(short["expires_at"]) - (now + timedelta(days=1))) < timedelta(minutes=5), short
        assert len({default["code"], bound["code"], short["code"]}) == 3, "every invite gets its own code"

        r, listed = await _invites(http, owner)
        for invite in (default, bound, short):
            assert invite["code"] not in r.text, "a code must never be listed"
            item = listed[invite["id"]]
            assert INVITE_LISTED_FIELDS <= set(item), f"missing {INVITE_LISTED_FIELDS - set(item)}"
            assert "code" not in item and "code_hash" not in item, item
            assert item["status"] == "pending", item
        assert listed[bound["id"]]["email"] == "kiran@example.com" and listed[bound["id"]]["role"] == "admin"

    _run(scenario, "10.32.13.1")


def test_invite_options_are_validated() -> None:
    """An invite must expire in 1 to 30 days and grant member or admin, nothing else."""

    async def scenario(http, _sessions):
        team = await _team(http)
        owner = team["owner"]["token"]
        for body in (
            {"expires_in_days": 0},
            {"expires_in_days": 31},
            {"expires_in_days": -5},
            {"role": "owner"},
            {"role": "superuser"},
        ):
            r = await _create_invite(http, owner, **body)
            assert r.status_code in INVALID, f"{body}: {_show(r)}"
        _, listed = await _invites(http, owner)
        assert all(item["status"] != "pending" for item in listed.values()), "refused invites were not created"

    _run(scenario, "10.32.14.1")


def test_the_invite_list_reports_each_invite_status() -> None:
    """The console sees which invites are pending, used, expired or revoked, and when."""

    async def scenario(http, sessions):
        team = await _team(http)
        owner = team["owner"]["token"]

        pending = await _invite(http, owner)
        used = await _invite(http, owner)
        expired = await _invite(http, owner)
        revoked = await _invite(http, owner)

        await _register_ok(http, "kiran@example.com", invite_code=used["code"])
        await _set_row(sessions, "invites", expired["id"], expires_at=datetime.now(timezone.utc) - timedelta(hours=1))
        r = await http.delete(f"/api/team/invites/{revoked['id']}", headers=_bearer(owner))
        assert r.status_code == 204, _show(r)

        r, listed = await _invites(http, owner)
        for invite in (pending, used, expired, revoked):
            assert invite["code"] not in r.text, "a code must never be listed"
        assert "code_hash" not in r.text, r.text

        assert listed[pending["id"]]["status"] == "pending", listed[pending["id"]]
        assert listed[pending["id"]]["used_at"] is None and listed[pending["id"]]["revoked"] is False

        assert listed[used["id"]]["status"] == "used", listed[used["id"]]
        assert listed[used["id"]]["used_at"], listed[used["id"]]
        _iso(listed[used["id"]]["used_at"])

        assert listed[expired["id"]]["status"] == "expired", listed[expired["id"]]

        assert listed[revoked["id"]]["status"] == "revoked", listed[revoked["id"]]
        assert listed[revoked["id"]]["revoked"] is True, listed[revoked["id"]]

        r = await http.get("/api/team/invites", headers=_bearer(team["admin"]["token"]))
        assert r.status_code == 200, f"admins see invites too: {_show(r)}"

    _run(scenario, "10.32.15.1")


def test_revoking_an_invite_stops_its_code() -> None:
    """An admin can revoke an invite they sent, and the code then admits nobody."""

    async def scenario(http, _sessions):
        team = await _team(http)
        admin = team["admin"]["token"]
        invite = await _invite(http, admin, email="kiran@example.com")

        r = await http.delete(f"/api/team/invites/{invite['id']}", headers=_bearer(admin))
        assert r.status_code == 204, _show(r)
        assert not r.content, f"204 has no body: {r.text!r}"

        r = await _register(http, "kiran@example.com", invite_code=invite["code"])
        assert r.status_code == 403, f"revoked code: {_show(r)}"
        assert "kiran@example.com" not in await _users(http, admin)

        _, listed = await _invites(http, admin)
        assert listed[invite["id"]]["status"] == "revoked" and listed[invite["id"]]["revoked"] is True

    _run(scenario, "10.32.16.1")


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
