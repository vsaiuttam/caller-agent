"""REQUIRE_LOGIN: a deployed console asks for a sign-in from its first visit.

Without it, a server with no accounts and no ADMIN_PASSWORD is open, which
suits local development but put a public deploy's console one click away from
anyone. With it, the console is locked from the start, and the only thing a
visitor can do is create the owner account.

Reuses the harness from test_accounts.py. Runs standalone
(`python tests/test_require_login.py`) or under pytest.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_accounts import _bearer, _fresh_ip, _owner, _run, _show  # noqa: E402

from src.voiceagent.api import auth  # noqa: E402


def test_require_login_locks_a_server_with_no_accounts() -> None:
    """With REQUIRE_LOGIN on, a fresh server is locked but still invites the owner."""

    async def scenario(http, sessions):
        status = (await http.get("/api/auth/status")).json()
        assert status["auth_enabled"] is True, status
        assert status["authenticated"] is False, status
        assert status["registration"] == {"mode": "owner", "setup_code_required": False}, status

        r = await http.get("/api/campaigns")
        assert r.status_code == 401, _show(r)
        r = await http.get("/api/health")
        assert r.status_code == 200, _show(r)

    _run(scenario, _fresh_ip(), REQUIRE_LOGIN="true")


def test_the_owner_can_still_be_created_and_then_gets_in() -> None:
    """The owner account can be created on a locked server, and its token opens the console."""

    async def scenario(http, sessions):
        owner = await _owner(http)
        r = await http.get("/api/campaigns", headers=_bearer(owner["token"]))
        assert r.status_code == 200, _show(r)
        status = (await http.get("/api/auth/status", headers=_bearer(owner["token"]))).json()
        assert status["authenticated"] is True and status["user"]["role"] == "owner", status
        assert status["registration"]["mode"] == "invite", status

    _run(scenario, _fresh_ip(), REQUIRE_LOGIN="true")


def test_without_require_login_a_fresh_server_stays_open() -> None:
    """Unset, nothing changes: no accounts and no admin password means an open console."""

    async def scenario(http, sessions):
        status = (await http.get("/api/auth/status")).json()
        assert status["auth_enabled"] is False, status
        r = await http.get("/api/campaigns")
        assert r.status_code == 200, _show(r)

    _run(scenario, _fresh_ip(), REQUIRE_LOGIN=None)


def test_require_login_reads_the_usual_ways_of_saying_yes() -> None:
    """true/1/yes/on (any case) turn it on; anything else leaves it off."""
    import os

    saved = os.environ.get("REQUIRE_LOGIN")
    try:
        for value in ("true", "TRUE", "1", "yes", "on"):
            os.environ["REQUIRE_LOGIN"] = value
            assert auth.login_required() is True, value
        for value in ("false", "0", "", "no", "off", "maybe"):
            os.environ["REQUIRE_LOGIN"] = value
            assert auth.login_required() is False, value
    finally:
        if saved is None:
            os.environ.pop("REQUIRE_LOGIN", None)
        else:
            os.environ["REQUIRE_LOGIN"] = saved


def _run_all() -> int:
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
