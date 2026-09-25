"""The MCP API: connecting apps, choosing tools per campaign, and never leaking a secret.

Covers docs/mcp-spec.md §1.5: server CRUD with discovery, refresh and the
"Try it" endpoint; the tool catalog; tool ids that every provider accepts;
campaign tool fields (unknown ids refused, removed with their server);
`CallDetail.tool_calls`; the health flags; and the rule that a server's URL
and header values never come back out of the API once entered.

Drives the real FastAPI app over ASGI on a throwaway SQLite database. No
network: the Demo CRM is `builtin://demo` (in-process), unsafe hosts are
resolved by a patched `socket.getaddrinfo`, and servers that fail discovery
point at a stub HTTP server on 127.0.0.1. Runs standalone
(`python tests/test_mcp_api.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import ipaddress
import logging
import os
import re
import socket
import sys
import tempfile
import uuid
from contextlib import asynccontextmanager, contextmanager
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)
for _noisy in ("mcp", "httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

TOOL_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
SLUG = re.compile(r"^[a-z0-9_]{1,32}$")
DEMO_TOOL_NAMES = {"lookup_customer", "check_availability", "book_appointment", "create_ticket"}
SERVER_KEYS = {
    "id", "name", "slug", "transport", "host", "header_names",
    "enabled", "status", "last_error", "checked_at", "tools",
}
CATALOG_KEYS = {"id", "server_id", "server_name", "name", "description", "input_schema"}

# Pinned so nothing in the developer's .env changes what these tests see.
BASE_ENV = dict(
    MODEL_PROVIDER="anthropic",
    ANTHROPIC_API_KEY="sk-ant-test-key",
    SECRETS_KEY="test-secrets-key-1",
    AUTH_SECRET=None,
    ADMIN_PASSWORD=None,
    MCP_ALLOW_PRIVATE_HOSTS=None,
    MCP_CONNECT_TIMEOUT_SECONDS="2",
)
LOCAL_DEV = dict(BASE_ENV, MCP_ALLOW_PRIVATE_HOSTS="true")


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


async def _temp_db():
    path = Path(tempfile.mkdtemp()) / "mcp_api.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(storage.Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _api():
    """The real FastAPI app on a throwaway SQLite database, auth off."""
    engine, sessions = await _temp_db()

    async def override():
        async with sessions() as session:
            yield session

    app = app_module.app
    saved = storage.SessionLocal, getattr(app_module, "SessionLocal", None)
    app.dependency_overrides[storage.get_session] = override
    storage.SessionLocal = sessions
    if saved[1] is not None:
        app_module.SessionLocal = sessions  # app.py imports the name directly
    try:
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
            yield http, sessions
    finally:
        app.dependency_overrides.pop(storage.get_session, None)
        storage.SessionLocal = saved[0]
        if saved[1] is not None:
            app_module.SessionLocal = saved[1]
        await engine.dispose()


def _run(scenario, **env):
    """Run an async scenario against the API with the base env (plus overrides)."""

    async def main():
        async with _api() as (http, sessions):
            return await scenario(http, sessions)

    with _env(**{**BASE_ENV, **env}):
        return asyncio.run(main())


@contextmanager
def _dns(table: dict[str, list[str]]):
    """Resolve hostnames from `table`; IP literals resolve to themselves."""
    real = socket.getaddrinfo

    def fake(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        name = host.decode() if isinstance(host, bytes) else str(host)
        literal = name.strip("[]")
        try:
            ipaddress.ip_address(literal)
            addresses = [literal]
        except ValueError:
            addresses = table.get(name.lower())
            if addresses is None:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None
        number = port if isinstance(port, int) else 443
        return [
            (socket.AF_INET, socket.SOCK_STREAM, 6, "", (a, number))
            if ipaddress.ip_address(a).version == 4
            else (socket.AF_INET6, socket.SOCK_STREAM, 6, "", (a, number, 0, 0))
            for a in addresses
        ]

    socket.getaddrinfo = fake
    try:
        yield
    finally:
        socket.getaddrinfo = real


@asynccontextmanager
async def _not_mcp():
    """A plain HTTP server on 127.0.0.1 that answers everything with 404."""

    async def handle(reader, writer):
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                data += chunk
            body = b"Not found"
            writer.write(
                b"HTTP/1.1 404 Not Found\r\nContent-Type: text/plain\r\n"
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode()
                + body
            )
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}"
    finally:
        server.close()


async def _add_demo(http, name: str = "Demo CRM", **extra) -> dict:
    r = await http.post("/api/mcp/servers", json={"name": name, "url": "builtin://demo", **extra})
    assert r.status_code == 201, (r.status_code, r.text)
    return r.json()


def _ids(server: dict) -> dict[str, str]:
    """Tool name -> tool id, for one server."""
    return {tool["name"]: tool["id"] for tool in server["tools"]}


def _parse_time(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)


async def _seed_campaign(sessions, campaign_id: str = "camp-1", **fields) -> None:
    async with sessions() as db:
        db.add(storage.Campaign(id=campaign_id, name="Smile Dental", goal="Book cleanings.", **fields))
        await db.commit()


# ---------------------------------------------------------------------------
# Servers
# ---------------------------------------------------------------------------


def test_adding_the_demo_crm_discovers_its_tools() -> None:
    """One click adds the built-in Demo CRM, healthy, with its four tools ready to choose."""

    async def scenario(http, sessions):
        created = await _add_demo(http)
        listed = (await http.get("/api/mcp/servers")).json()
        return created, listed

    created, listed = _run(scenario)
    assert SERVER_KEYS <= set(created), f"missing {SERVER_KEYS - set(created)}"
    assert created["name"] == "Demo CRM", created
    assert created["status"] == "ok" and not created["last_error"], created
    assert created["enabled"] is True and created["transport"] == "builtin", created
    assert created["header_names"] == [] and created["checked_at"], created
    slug = created["slug"]
    assert SLUG.match(slug) and slug.startswith("demo"), slug

    tools = {t["name"]: t for t in created["tools"]}
    assert set(tools) == DEMO_TOOL_NAMES, sorted(tools)
    for name, tool in tools.items():
        assert {"id", "name", "description", "input_schema"} <= set(tool), tool
        assert tool["id"] == f"{slug}__{name}", tool["id"]
        assert isinstance(tool["input_schema"], dict) and tool["input_schema"].get("properties"), tool
    assert [s["id"] for s in listed] == [created["id"]], listed


def test_server_slugs_come_from_the_name_and_never_collide() -> None:
    """Two apps with the same name get distinct tool ids, so a campaign's choice is never ambiguous."""

    async def scenario(http, sessions):
        first = await _add_demo(http)
        second = await _add_demo(http)
        odd = await _add_demo(http, name="Zapier (Prod) – CRM!")
        long = await _add_demo(http, name="A very long integration name " * 3)
        return first["slug"], second["slug"], odd["slug"], long["slug"]

    first, second, odd, long = _run(scenario)
    assert first != second, (first, second)
    assert second.startswith(first) and second[len(first):].strip("_").isdigit(), (first, second)
    for slug in (first, second, odd, long):
        assert SLUG.match(slug), slug


def test_unsafe_urls_are_refused_and_nothing_is_saved() -> None:
    """A server URL can't be used to reach the local network or the cloud metadata service."""
    table = {"crm.example.com": ["93.184.216.34"], "intranet.example.com": ["10.0.0.7"], "localhost": ["127.0.0.1"]}
    unsafe = [
        "http://crm.example.com/mcp",
        "https://intranet.example.com/mcp",
        "https://localhost/mcp",
        "https://169.254.169.254/latest/meta-data/",
        "https://[::1]/mcp",
    ]

    async def scenario(http, sessions):
        statuses = {}
        details = {}
        for url in unsafe:
            r = await http.post("/api/mcp/servers", json={"name": "Office CRM", "url": url})
            statuses[url] = r.status_code
            details[url] = r.json().get("detail") if r.headers.get("content-type", "").startswith("application/json") else r.text
        listed = (await http.get("/api/mcp/servers")).json()

        demo = await _add_demo(http)
        patched = await http.patch(f"/api/mcp/servers/{demo['id']}", json={"url": "https://intranet.example.com/mcp"})
        after = (await http.get("/api/mcp/servers")).json()
        return statuses, details, listed, patched.status_code, after

    with _dns(table):
        statuses, details, listed, patch_status, after = _run(scenario)
    assert all(code == 400 for code in statuses.values()), statuses
    assert all(isinstance(d, str) and d.strip() for d in details.values()), details
    assert listed == [], f"an unsafe server was saved: {listed}"
    assert patch_status == 400, patch_status
    assert after[0]["status"] == "ok" and len(after[0]["tools"]) == 4, after


def test_only_the_documented_transports_are_accepted() -> None:
    async def scenario(http, sessions):
        r = await http.post(
            "/api/mcp/servers", json={"name": "Local", "url": "builtin://demo", "transport": "stdio"}
        )
        return r.status_code, (await http.get("/api/mcp/servers")).json()

    status, listed = _run(scenario)
    assert 400 <= status < 500, status
    assert listed == [], listed


def test_a_server_that_fails_discovery_is_kept_so_it_can_be_fixed() -> None:
    """A wrong URL is saved with its error; fixing the URL re-discovers and it turns healthy."""

    async def scenario(http, sessions):
        async with _not_mcp() as base:
            r = await http.post(
                "/api/mcp/servers",
                json={"name": "Office CRM", "url": f"{base}/mcp", "transport": "streamable_http"},
            )
            assert r.status_code == 201, (r.status_code, r.text)
            broken = r.json()
            listed = (await http.get("/api/mcp/servers")).json()
        fixed = await http.patch(f"/api/mcp/servers/{broken['id']}", json={"url": "builtin://demo"})
        return broken, listed, fixed

    broken, listed, fixed = _run(scenario, **LOCAL_DEV)
    assert broken["status"] == "error", broken
    assert isinstance(broken["last_error"], str) and broken["last_error"].strip(), broken
    assert "Traceback" not in broken["last_error"], broken["last_error"]
    assert broken["tools"] == [], broken
    assert [s["id"] for s in listed] == [broken["id"]], listed
    assert fixed.status_code == 200, (fixed.status_code, fixed.text)
    assert fixed.json()["status"] == "ok" and len(fixed.json()["tools"]) == 4, fixed.json()


def test_a_servers_url_and_header_values_never_leave_the_server() -> None:
    """Once entered, an API key or a secret URL is never shown again — not in any response, not in the database."""
    secrets = ["sk_live_PATHSECRET", "QUERYSECRET", "tok_HEADERSECRET", "key_HEADERSECRET2", "key_DEMOSECRET"]

    async def scenario(http, sessions):
        texts = []
        async with _not_mcp() as base:
            r = await http.post(
                "/api/mcp/servers",
                json={
                    "name": "Office CRM",
                    "url": f"{base}/mcp/sk_live_PATHSECRET?token=QUERYSECRET",
                    "transport": "streamable_http",
                    "headers": {"Authorization": "Bearer tok_HEADERSECRET", "X-Api-Key": "key_HEADERSECRET2"},
                },
            )
            assert r.status_code == 201, (r.status_code, r.text)
            office = r.json()
            texts.append(r.text)
            texts.append((await http.post(f"/api/mcp/servers/{office['id']}/refresh")).text)
            texts.append((await http.patch(f"/api/mcp/servers/{office['id']}", json={"name": "Office"})).text)

            demo_response = await http.post(
                "/api/mcp/servers",
                json={"name": "Demo CRM", "url": "builtin://demo", "headers": {"X-Api-Key": "key_DEMOSECRET"}},
            )
            demo = demo_response.json()
            texts.append(demo_response.text)
            texts.append((await http.post(f"/api/mcp/servers/{demo['id']}/refresh")).text)
            texts.append((await http.get("/api/mcp/servers")).text)
            texts.append((await http.get("/api/mcp/tools")).text)
            texts.append((await http.get("/api/health")).text)
        async with sessions() as db:
            stored = [row.secrets for row in (await db.execute(select(storage.McpServer))).scalars()]
        return office, demo, texts, stored

    office, demo, texts, stored = _run(scenario, **LOCAL_DEV)
    leaks = [(secret, text[:200]) for text in texts for secret in secrets if secret in text]
    assert not leaks, f"secrets in API responses: {leaks}"
    for body in (office, demo):
        assert not {"url", "headers", "secrets"} & set(body), sorted(body)
    assert sorted(office["header_names"]) == ["Authorization", "X-Api-Key"], office["header_names"]
    assert demo["header_names"] == ["X-Api-Key"], demo["header_names"]
    assert all(not any(secret in value for secret in secrets) for value in stored), "secrets stored in plain text"


def test_editing_a_server() -> None:
    """Rename, replace or clear headers, and pause a server; its tools leave the catalog while paused."""

    async def scenario(http, sessions):
        demo = await _add_demo(http, headers={"X-Api-Key": "key-1"})
        url = f"/api/mcp/servers/{demo['id']}"
        renamed = (await http.patch(url, json={"name": "Demo CRM (sandbox)"})).json()
        replaced = (await http.patch(url, json={"headers": {"Authorization": "Bearer b", "X-Team": "7"}})).json()
        cleared = (await http.patch(url, json={"headers": {}})).json()
        paused = (await http.patch(url, json={"enabled": False})).json()
        catalog_paused = (await http.get("/api/mcp/tools")).json()
        resumed = (await http.patch(url, json={"enabled": True})).json()
        catalog_resumed = (await http.get("/api/mcp/tools")).json()
        missing = await http.patch(f"/api/mcp/servers/{uuid.uuid4()}", json={"name": "Ghost"})
        return renamed, replaced, cleared, paused, catalog_paused, resumed, catalog_resumed, missing.status_code

    renamed, replaced, cleared, paused, catalog_paused, resumed, catalog_resumed, missing = _run(scenario)
    assert renamed["name"] == "Demo CRM (sandbox)", renamed
    assert renamed["header_names"] == ["X-Api-Key"], f"omitting headers dropped them: {renamed['header_names']}"
    assert sorted(replaced["header_names"]) == ["Authorization", "X-Team"], replaced["header_names"]
    assert cleared["header_names"] == [], cleared["header_names"]
    assert paused["enabled"] is False and catalog_paused == [], catalog_paused
    assert resumed["enabled"] is True and len(catalog_resumed) == 4, catalog_resumed
    assert missing == 404, missing


def test_refresh_rediscovers_a_servers_tools() -> None:
    """"Refresh" re-reads what the app offers and stamps when it was checked."""

    async def scenario(http, sessions):
        demo = await _add_demo(http)
        await asyncio.sleep(0.02)
        r = await http.post(f"/api/mcp/servers/{demo['id']}/refresh")
        missing = await http.post(f"/api/mcp/servers/{uuid.uuid4()}/refresh")
        return demo, r, missing.status_code

    demo, r, missing = _run(scenario)
    assert r.status_code == 200, (r.status_code, r.text)
    refreshed = r.json()
    assert refreshed["id"] == demo["id"] and refreshed["status"] == "ok", refreshed
    assert {t["name"] for t in refreshed["tools"]} == DEMO_TOOL_NAMES, refreshed["tools"]
    assert _parse_time(refreshed["checked_at"]) >= _parse_time(demo["checked_at"]), (refreshed, demo)
    assert missing == 404, missing


def test_a_server_whose_secrets_cannot_be_opened_asks_for_them_again() -> None:
    """After SECRETS_KEY changes, the server shows an error telling the user to re-enter its URL and credentials."""

    async def scenario(http, sessions):
        demo = await _add_demo(http)
        with _env(SECRETS_KEY="a-different-key"):
            r = await http.post(f"/api/mcp/servers/{demo['id']}/refresh")
            catalog = (await http.get("/api/mcp/tools")).json()
        return r, catalog

    r, catalog = _run(scenario)
    assert r.status_code == 200, (r.status_code, r.text)
    server = r.json()
    assert server["status"] == "error", server
    assert "Re-enter" in (server["last_error"] or ""), server["last_error"]
    assert catalog == [], "a server that can't be reached still offers tools"


def test_trying_a_tool_from_the_console() -> None:
    """The "Try it" panel runs a tool once and shows the answer and how long it took."""

    async def scenario(http, sessions):
        demo = await _add_demo(http)
        base = f"/api/mcp/servers/{demo['id']}/tools"
        good = await http.post(f"{base}/check_availability/test", json={"arguments": {"date": "2026-09-29"}})
        bad = await http.post(f"{base}/book_appointment/test", json={"arguments": {}})
        unknown = await http.post(f"{base}/no_such_tool/test", json={"arguments": {}})
        no_server = await http.post(f"/api/mcp/servers/{uuid.uuid4()}/tools/check_availability/test",
                                    json={"arguments": {}})
        return good, bad, unknown, no_server

    good, bad, unknown, no_server = _run(scenario)
    assert good.status_code == 200, (good.status_code, good.text)
    body = good.json()
    assert body["ok"] is True and body["text"].strip(), body
    assert isinstance(body["duration_ms"], int) and body["duration_ms"] >= 0, body
    assert bad.status_code == 200 and bad.json()["ok"] is False and bad.json()["text"].strip(), bad.text
    assert unknown.status_code == 404 or (unknown.status_code == 200 and unknown.json()["ok"] is False), (
        unknown.status_code, unknown.text,
    )
    assert no_server.status_code == 404, no_server.status_code


def test_the_tool_catalog_lists_tools_of_enabled_healthy_servers_only() -> None:
    """The campaign's tool picker offers only tools that can actually run."""

    async def scenario(http, sessions):
        demo = await _add_demo(http)
        paused = await _add_demo(http, name="Paused CRM")
        await http.patch(f"/api/mcp/servers/{paused['id']}", json={"enabled": False})
        async with _not_mcp() as base:
            await http.post("/api/mcp/servers", json={"name": "Broken", "url": f"{base}/mcp",
                                                      "transport": "streamable_http"})
        return demo, (await http.get("/api/mcp/tools")).json()

    demo, catalog = _run(scenario, **LOCAL_DEV)
    assert len(catalog) == 4, catalog
    for tool in catalog:
        assert CATALOG_KEYS <= set(tool), f"missing {CATALOG_KEYS - set(tool)} in {tool}"
        assert tool["server_id"] == demo["id"] and tool["server_name"] == "Demo CRM", tool
    assert {t["id"] for t in catalog} == set(_ids(demo).values()), catalog


def test_tool_ids_are_safe_for_every_model_provider() -> None:
    """Odd tool names still become ids Anthropic and OpenAI accept, and the toolbox resolves them."""
    names = ["x" * 90, "lookup.customer v2", "get-weather", "créer_ticket", "a/b:c"]

    async def scenario(http, sessions):
        from src.voiceagent.mcp.secrets import seal
        from src.voiceagent.mcp.toolbox import CallToolbox

        async with sessions() as db:
            db.add(
                storage.McpServer(
                    id=str(uuid.uuid4()), name="CRM", slug="crm", transport="builtin", host="builtin",
                    secrets=seal({"url": "builtin://demo", "headers": {}}), enabled=True, status="ok",
                    last_error=None,
                    tools=[{"name": n, "description": f"{n} tool", "input_schema": {"type": "object"}} for n in names],
                )
            )
            await db.commit()
        catalog = (await http.get("/api/mcp/tools")).json()
        ids = [t["id"] for t in catalog]
        box = await CallToolbox.for_tool_ids(sessions, ids, phase="in_call")
        try:
            resolved = [s.id for s in box.specs()]
        finally:
            await box.aclose()
        return catalog, ids, resolved

    catalog, ids, resolved = _run(scenario)
    assert len(ids) == len(names), catalog
    assert all(TOOL_ID.match(i) for i in ids), ids
    assert len(set(ids)) == len(ids), f"two tools share an id: {ids}"
    assert "crm__get-weather" in ids, ids
    assert sorted(resolved) == sorted(ids), (resolved, ids)


def test_removing_a_server_removes_its_tools_from_campaigns() -> None:
    """Deleting an app never leaves campaigns pointing at tools that no longer exist."""

    async def scenario(http, sessions):
        a = await _add_demo(http)
        b = await _add_demo(http)
        a_ids, b_ids = _ids(a), _ids(b)
        r = await http.post(
            "/api/campaigns",
            json={
                "name": "Smile Dental",
                "goal": "Book cleanings.",
                "mcp_tools": [a_ids["check_availability"], b_ids["check_availability"]],
                "mcp_post_call_tools": [a_ids["create_ticket"]],
            },
        )
        assert r.status_code == 201, (r.status_code, r.text)
        campaign_id = r.json()["id"]
        deleted = await http.delete(f"/api/mcp/servers/{a['id']}")
        again = await http.delete(f"/api/mcp/servers/{a['id']}")
        campaign = (await http.get(f"/api/campaigns/{campaign_id}")).json()
        servers = (await http.get("/api/mcp/servers")).json()
        catalog = (await http.get("/api/mcp/tools")).json()
        return deleted.status_code, again.status_code, campaign, servers, catalog, a, b_ids

    deleted, again, campaign, servers, catalog, a, b_ids = _run(scenario)
    assert deleted == 204, deleted
    assert again == 404, again
    assert campaign["mcp_tools"] == [b_ids["check_availability"]], campaign["mcp_tools"]
    assert campaign["mcp_post_call_tools"] == [], campaign["mcp_post_call_tools"]
    assert a["id"] not in {s["id"] for s in servers}, servers
    assert all(t["server_id"] != a["id"] for t in catalog), catalog


# ---------------------------------------------------------------------------
# Campaigns
# ---------------------------------------------------------------------------


def test_campaigns_carry_their_tool_choices() -> None:
    """In-call tools, after-call tools and the after-call instruction are saved per campaign."""

    async def scenario(http, sessions):
        ids = _ids(await _add_demo(http))
        created = await http.post(
            "/api/campaigns",
            json={
                "name": "Smile Dental",
                "goal": "Book cleanings.",
                "mcp_tools": [ids["check_availability"]],
                "mcp_post_call_tools": [ids["create_ticket"]],
                "mcp_post_call_instructions": "Open a ticket for every booking.",
            },
        )
        assert created.status_code == 201, (created.status_code, created.text)
        campaign_id = created.json()["id"]
        fetched = (await http.get(f"/api/campaigns/{campaign_id}")).json()
        patched = await http.patch(
            f"/api/campaigns/{campaign_id}",
            json={"mcp_tools": [ids["check_availability"], ids["lookup_customer"]], "mcp_post_call_instructions": ""},
        )
        plain = await http.post("/api/campaigns", json={"name": "Plain", "goal": "Say hello."})
        return ids, created.json(), fetched, patched, plain.json()

    ids, created, fetched, patched, plain = _run(scenario)
    for body in (created, fetched):
        assert body["mcp_tools"] == [ids["check_availability"]], body.get("mcp_tools")
        assert body["mcp_post_call_tools"] == [ids["create_ticket"]], body.get("mcp_post_call_tools")
        assert body["mcp_post_call_instructions"] == "Open a ticket for every booking.", body
    assert patched.status_code == 200, (patched.status_code, patched.text)
    assert patched.json()["mcp_tools"] == [ids["check_availability"], ids["lookup_customer"]], patched.json()
    assert patched.json()["mcp_post_call_tools"] == [ids["create_ticket"]], "PATCH dropped an omitted field"
    assert patched.json()["mcp_post_call_instructions"] == "", patched.json()
    assert (plain.get("mcp_tools"), plain.get("mcp_post_call_tools"), plain.get("mcp_post_call_instructions")) == (
        [], [], "",
    ), plain


def test_unknown_tool_ids_are_refused_on_campaigns() -> None:
    """A typo'd or stale tool id is caught when the campaign is saved, not mid-call."""

    async def scenario(http, sessions):
        ids = _ids(await _add_demo(http))
        created = await http.post(
            "/api/campaigns", json={"name": "Smile Dental", "goal": "Book.", "mcp_tools": ["ghost__nothing"]}
        )
        ok = await http.post(
            "/api/campaigns", json={"name": "Smile Dental", "goal": "Book.", "mcp_tools": [ids["lookup_customer"]]}
        )
        campaign_id = ok.json()["id"]
        patched = await http.patch(
            f"/api/campaigns/{campaign_id}", json={"mcp_post_call_tools": [ids["create_ticket"], "demo_crm__nope"]}
        )
        after = (await http.get(f"/api/campaigns/{campaign_id}")).json()
        listed = (await http.get("/api/campaigns")).json()
        return created.status_code, patched.status_code, after, listed

    created, patched, after, listed = _run(scenario)
    assert created == 400, created
    assert patched == 400, patched
    assert after["mcp_post_call_tools"] == [], after
    assert len(listed) == 1, "the refused campaign was saved anyway"


def test_campaigns_saved_before_tools_existed_read_as_having_none() -> None:
    """Old rows with null tool lists show empty lists, never null."""

    async def scenario(http, sessions):
        await _seed_campaign(sessions, mcp_tools=None, mcp_post_call_tools=None)
        return (await http.get("/api/campaigns/camp-1")).json()

    body = _run(scenario)
    assert body["mcp_tools"] == [] and body["mcp_post_call_tools"] == [], body


# ---------------------------------------------------------------------------
# Calls and health
# ---------------------------------------------------------------------------


def test_call_detail_includes_its_tool_calls() -> None:
    """The Calls page shows which tools a call used, and an empty list when it used none."""
    entry = {
        "at": "2026-09-29T10:00:05+00:00", "phase": "in_call", "server": "Demo CRM",
        "tool": "check_availability", "arguments": {"date": "2026-09-29"}, "ok": True,
        "duration_ms": 42, "excerpt": "Free slots on 2026-09-29: 10:00, 14:00", "error": None,
    }

    async def scenario(http, sessions):
        await _seed_campaign(sessions)
        async with sessions() as db:
            db.add(storage.Contact(id="ct-1", campaign_id="camp-1", full_name="Asha Rao", phone_e164="+15555550100"))
            db.add(storage.Call(id="call-tools", contact_id="ct-1", campaign_id="camp-1",
                                status=storage.CallStatus.COMPLETED, tool_calls=[entry]))
            db.add(storage.Call(id="call-plain", contact_id="ct-1", campaign_id="camp-1",
                                status=storage.CallStatus.COMPLETED))
            await db.commit()
        with_tools = (await http.get("/api/calls/call-tools")).json()
        without = (await http.get("/api/calls/call-plain")).json()
        return with_tools, without

    with_tools, without = _run(scenario)
    assert with_tools.get("tool_calls") == [entry], with_tools.get("tool_calls")
    assert without.get("tool_calls") == [], without.get("tool_calls")


def test_health_reports_mcp_readiness() -> None:
    """The console can warn when the provider can't use tools or secrets are stored unsealed."""

    async def scenario(http, sessions):
        demo = await _add_demo(http)
        paused = await _add_demo(http, name="Paused CRM")
        await http.patch(f"/api/mcp/servers/{paused['id']}", json={"enabled": False})
        readings = {"anthropic, sealed": (await http.get("/api/health")).json()}
        with _env(MODEL_PROVIDER="sarvam", SARVAM_API_KEY="test-sarvam-key", SECRETS_KEY=None, AUTH_SECRET=None):
            readings["sarvam, unsealed"] = (await http.get("/api/health")).json()
        with _env(MODEL_PROVIDER="nvidia", NVIDIA_API_KEY=None):
            readings["no provider"] = (await http.get("/api/health")).json()
        return demo, readings

    _demo, readings = _run(scenario)
    flags = {
        label: (h.get("mcp_servers"), h.get("provider_supports_tools"), h.get("secrets_sealed"))
        for label, h in readings.items()
    }
    assert flags["anthropic, sealed"] == (1, True, True), flags
    assert flags["sarvam, unsealed"] == (1, False, False), flags
    assert flags["no provider"][1] is False, flags


def test_mcp_routes_need_a_login_when_access_control_is_on() -> None:
    """With ADMIN_PASSWORD set, nobody can list, add or run tools without logging in."""

    async def scenario(http, sessions):
        with _env(ADMIN_PASSWORD="test-admin-password"):
            return [
                (await http.get("/api/mcp/servers")).status_code,
                (await http.get("/api/mcp/tools")).status_code,
                (await http.post("/api/mcp/servers", json={"name": "Demo", "url": "builtin://demo"})).status_code,
            ]

    assert _run(scenario) == [401, 401, 401]


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
