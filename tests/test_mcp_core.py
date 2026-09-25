"""MCP core: the URL guard, sealed secrets, the Demo CRM, discovery and the call toolbox.

Samvaad is an MCP client. People connect their own apps by adding MCP servers,
and a call may use those servers' tools. What has to hold underneath
(docs/mcp-spec.md §1.2):

- nothing reaches a private network address unless explicitly allowed;
- server URLs and headers are sealed at rest;
- the built-in Demo CRM works end to end with no account and no network;
- discovery fails with a message a person can act on;
- a call's toolbox never raises, never hangs a call, reports every tool call,
  and holds one connection per server for the whole call.

Runs standalone (`python tests/test_mcp_core.py`) or under pytest. No network:
DNS is faked by patching `socket.getaddrinfo`, MCP round trips go to
in-process servers through `builtin://demo`, and the few "bad endpoint" cases
talk to a stub HTTP server on 127.0.0.1. Env vars are set per test, so they
must be read at call time. Names that don't exist yet are imported inside the
tests, so each test reports its own result.

Two seams these tests rely on:
- server rows are written the way the API writes them: `storage.McpServer`
  with `secrets = seal({"url": ..., "headers": {...}})`;
- `builtin://demo` is served by calling `demo_server()` each time a
  connection opens, so a test can stand in its own `MCPServer` by patching
  that name.
"""

from __future__ import annotations

import asyncio
import base64
import dataclasses
import functools
import importlib
import ipaddress
import json
import logging
import os
import pkgutil
import re
import socket
import sys
import tempfile
import time
import uuid
from contextlib import asynccontextmanager, contextmanager, suppress
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import storage  # noqa: E402

# A root handler first, so the MCP SDK's logging setup (which installs a rich
# handler at INFO when there is none) leaves the level alone.
logging.basicConfig(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)
for _noisy in ("mcp", "httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

TOOL_ID = re.compile(r"^[a-zA-Z0-9_-]{1,64}$")
EVENT_KEYS = {"phase", "server", "tool", "status", "arguments", "duration_ms", "excerpt", "error"}

# The sealing key is pinned so a key in the developer's .env can't change what
# these tests see.
SEALED = dict(SECRETS_KEY="test-secrets-key-1", AUTH_SECRET=None)


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


@contextmanager
def _dns(table: dict[str, list[str]]):
    """Resolve hostnames from `table` instead of the network.

    IP literals resolve to themselves, like the real resolver; anything else
    not in the table fails to resolve. Yields the hosts that were looked up.
    """
    real = socket.getaddrinfo
    asked: list[str] = []

    def fake(host, port, family=0, type=0, proto=0, flags=0):  # noqa: A002
        name = host.decode() if isinstance(host, bytes) else str(host)
        asked.append(name)
        literal = name.strip("[]")
        try:
            ipaddress.ip_address(literal)
            addresses = [literal]
        except ValueError:
            addresses = table.get(name.lower())
            if addresses is None:
                raise socket.gaierror(socket.EAI_NONAME, "Name or service not known") from None
        number = port if isinstance(port, int) else 443
        out = []
        for address in addresses:
            if ipaddress.ip_address(address).version == 4:
                out.append((socket.AF_INET, socket.SOCK_STREAM, 6, "", (address, number)))
            else:
                out.append((socket.AF_INET6, socket.SOCK_STREAM, 6, "", (address, number, 0, 0)))
        return out

    socket.getaddrinfo = fake
    try:
        yield asked
    finally:
        socket.getaddrinfo = real


def _verdict(url: str) -> str:
    """"allowed", "refused" (UnsafeUrl), or the unexpected exception."""
    from src.voiceagent.mcp.guard import UnsafeUrl, check_url

    try:
        check_url(url)
    except UnsafeUrl:
        return "refused"
    except Exception as exc:  # noqa: BLE001 - reported, not hidden
        return f"{type(exc).__name__}: {exc}"
    return "allowed"


async def _temp_db():
    path = Path(tempfile.mkdtemp()) / "mcp_core.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(storage.Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


@asynccontextmanager
async def _db():
    engine, sessions = await _temp_db()
    try:
        yield sessions
    finally:
        await engine.dispose()


async def _add_server(
    sessions,
    slug: str,
    *,
    tools: list[dict],
    url: str = "builtin://demo",
    headers: dict[str, str] | None = None,
    transport: str | None = None,
    status: str = "ok",
    enabled: bool = True,
):
    """Save a server row the way the API does: URL and headers sealed."""
    from src.voiceagent.mcp.secrets import seal

    row = storage.McpServer(
        id=str(uuid.uuid4()),
        name=slug.replace("_", " ").title(),
        slug=slug,
        transport=transport or ("builtin" if url.startswith("builtin://") else "streamable_http"),
        host=url.split("://", 1)[-1].split("/", 1)[0],
        secrets=seal({"url": url, "headers": dict(headers or {})}),
        enabled=enabled,
        status=status,
        last_error=None,
        tools=list(tools),
    )
    async with sessions() as db:
        db.add(row)
        await db.commit()
    return row


async def _toolbox(sessions, tool_ids: list[str], *, phase: str = "in_call", on_event=None):
    from src.voiceagent.mcp.toolbox import CallToolbox

    return await CallToolbox.for_tool_ids(sessions, tool_ids, phase=phase, on_event=on_event)


async def _within(seconds: float, awaitable, what: str):
    """Await with a deadline; a miss is an assertion, not a hang."""
    task = asyncio.ensure_future(awaitable)
    done, _ = await asyncio.wait({task}, timeout=seconds)
    if not done:
        task.cancel()
        with suppress(BaseException):
            await asyncio.wait_for(task, 1)
        raise AssertionError(f"{what} did not finish within {seconds}s")
    return task.result()


# -- MCP servers ------------------------------------------------------------------

_SCHEMA = {"type": "object"}

# The Demo CRM's tools as a server row stores them after discovery (spec §1.2).
DEMO_TOOLS = [
    {
        "name": "lookup_customer",
        "description": "Look up a customer by phone number.",
        "input_schema": {**_SCHEMA, "properties": {"phone": {"type": "string"}}, "required": ["phone"]},
    },
    {
        "name": "check_availability",
        "description": "Free appointment slots on a date (YYYY-MM-DD).",
        "input_schema": {**_SCHEMA, "properties": {"date": {"type": "string"}}, "required": ["date"]},
    },
    {
        "name": "book_appointment",
        "description": "Book an appointment.",
        "input_schema": {
            **_SCHEMA,
            "properties": {
                "name": {"type": "string"},
                "date": {"type": "string"},
                "time": {"type": "string"},
            },
            "required": ["name", "date", "time"],
        },
    },
    {
        "name": "create_ticket",
        "description": "Open a support ticket.",
        "input_schema": {
            **_SCHEMA,
            "properties": {
                "summary": {"type": "string"},
                "priority": {"type": "string", "default": "normal"},
            },
            "required": ["summary"],
        },
    },
]
DEMO_TOOL_NAMES = {t["name"] for t in DEMO_TOOLS}


class _Connections:
    """Counts MCP sessions opened and closed on a test server."""

    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0


def _test_crm(connections: _Connections | None = None):
    """An in-process MCP server whose tools misbehave on purpose.

    Its lifespan runs once per client session, which is what lets a test see
    when the toolbox connects and when it lets go.
    """
    from mcp.server.mcpserver import MCPServer

    @asynccontextmanager
    async def lifespan(_server):
        if connections is not None:
            connections.opened += 1
        try:
            yield {}
        finally:
            if connections is not None:
                connections.closed += 1

    server = MCPServer("Test CRM", lifespan=lifespan)

    @server.tool()
    def ping() -> str:
        """Answer at once."""
        return "pong"

    @server.tool()
    async def stall() -> str:
        """Never answer."""
        await asyncio.Event().wait()
        return "never"

    @server.tool()
    def huge() -> str:
        """Answer with far more text than a model should be fed."""
        return "z" * 10_000

    @server.tool()
    def crash() -> str:
        """Fail the way a broken integration does."""
        raise RuntimeError("the CRM is down")

    return server


TEST_CRM_TOOLS = [
    {"name": name, "description": f"{name} (test)", "input_schema": {**_SCHEMA, "properties": {}}}
    for name in ("ping", "stall", "huge", "crash")
]


@contextmanager
def _serve_builtin_demo(factory):
    """Serve `builtin://demo` from `factory` instead of the Demo CRM.

    The toolbox calls `demo_server()` whenever it connects to builtin://demo,
    so the name is replaced wherever the MCP package bound it (the defining
    module, modules that imported it, and any registry dict holding it).
    """
    package = importlib.import_module("src.voiceagent.mcp")
    original = importlib.import_module("src.voiceagent.mcp.demo_server").demo_server
    modules = [package] + [
        importlib.import_module(f"{package.__name__}.{info.name}")
        for info in pkgutil.iter_modules(package.__path__)
    ]
    patches: list[tuple[object, str, object]] = []
    for module in modules:
        for name, value in list(vars(module).items()):
            if value is original:
                patches.append((module, name, value))
                setattr(module, name, factory)
            elif isinstance(value, dict):
                for key, item in list(value.items()):
                    if item is original:
                        patches.append((value, key, item))
                        value[key] = factory
    try:
        yield
    finally:
        for target, key, old in reversed(patches):
            if isinstance(target, dict):
                target[key] = old
            else:
                setattr(target, key, old)


@asynccontextmanager
async def _http_stub(status: str | None, *, content_type: str = "text/html"):
    """A plain HTTP server on 127.0.0.1 that is not an MCP server.

    Answers every request with `status`; with None it accepts the connection
    and never answers. Yields its base URL.
    """
    body = b"<html><body>Nothing to see here</body></html>"
    handlers: list[asyncio.Task] = []

    async def handle(reader, writer):
        handlers.append(asyncio.current_task())
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                data += chunk
            if status is None:
                await asyncio.Event().wait()
            writer.write(
                f"HTTP/1.1 {status}\r\nContent-Type: {content_type}\r\n"
                f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
            )
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    port = server.sockets[0].getsockname()[1]
    try:
        yield f"http://127.0.0.1:{port}"
    finally:
        server.close()
        for task in handlers:
            task.cancel()


def _readable(message: str) -> bool:
    """A message fit to show a person: present, short, and not a stack dump."""
    return (
        bool(message.strip())
        and len(message) <= 500
        and "Traceback" not in message
        and "TaskGroup" not in message
    )


# ---------------------------------------------------------------------------
# Guard: check_url
# ---------------------------------------------------------------------------

PUBLIC_V4 = "93.184.216.34"
PUBLIC_V6 = "2606:4700::1111"


def test_unsafe_url_is_a_value_error() -> None:
    """Callers that already handle bad input (ValueError) handle unsafe URLs too."""
    from src.voiceagent.mcp.guard import UnsafeUrl, check_url

    assert issubclass(UnsafeUrl, ValueError), UnsafeUrl.__mro__
    with _env(MCP_ALLOW_PRIVATE_HOSTS=None), _dns({}):
        try:
            check_url("http://127.0.0.1/mcp")
        except UnsafeUrl as exc:
            assert str(exc).strip(), "UnsafeUrl carries no message to show the user"
        else:
            raise AssertionError("a plain-http loopback URL was allowed")


def test_https_urls_on_public_hosts_are_allowed() -> None:
    """A hosted MCP server (Zapier, Composio, a CRM) can be connected."""
    table = {
        "mcp.zapier.example": [PUBLIC_V4],
        "crm.example.com": [PUBLIC_V4, PUBLIC_V6],
        "v6only.example.com": [PUBLIC_V6],
    }
    urls = [
        "https://mcp.zapier.example/api/mcp/s/abc123/mcp",
        "https://crm.example.com:8443/mcp?workspace=7",
        "https://v6only.example.com/sse",
    ]
    with _env(MCP_ALLOW_PRIVATE_HOSTS=None), _dns(table):
        verdicts = {url: _verdict(url) for url in urls}
    assert all(v == "allowed" for v in verdicts.values()), verdicts


def test_plain_http_and_other_schemes_are_refused() -> None:
    """Keys never travel in clear text, and nothing but HTTPS is dialled."""
    table = {"mcp.zapier.example": [PUBLIC_V4]}
    urls = [
        "http://mcp.zapier.example/mcp",
        "ftp://mcp.zapier.example/mcp",
        "ws://mcp.zapier.example/mcp",
        "file:///etc/passwd",
        "mcp.zapier.example/mcp",
        "https://",
        "",
    ]
    with _env(MCP_ALLOW_PRIVATE_HOSTS=None), _dns(table):
        verdicts = {url: _verdict(url) for url in urls}
    assert all(v == "refused" for v in verdicts.values()), verdicts


def test_hosts_on_private_ipv4_addresses_are_refused() -> None:
    """A server URL can't be used to reach the office network or the cloud metadata service."""
    table = {
        "localhost": ["127.0.0.1", "::1"],
        "loopback.example.com": ["127.0.0.1"],
        "ten.example.com": ["10.1.2.3"],
        "one-seven-two.example.com": ["172.16.5.4"],
        "home.example.com": ["192.168.0.10"],
        "metadata.example.com": ["169.254.169.254"],
        "unspecified.example.com": ["0.0.0.0"],
        "multicast.example.com": ["224.0.0.251"],
        "reserved.example.com": ["240.0.0.1"],
    }
    urls = [f"https://{host}/mcp" for host in table] + [
        "https://127.0.0.1/mcp",
        "https://10.0.0.8:8443/mcp",
        "https://169.254.169.254/latest/meta-data/",
    ]
    with _env(MCP_ALLOW_PRIVATE_HOSTS=None), _dns(table):
        verdicts = {url: _verdict(url) for url in urls}
    assert all(v == "refused" for v in verdicts.values()), verdicts


def test_hosts_on_private_ipv6_addresses_are_refused() -> None:
    """IPv6 is no way around the guard: loopback, link-local, ULA and IPv4-mapped all refused."""
    table = {
        "v6-loopback.example.com": ["::1"],
        "v6-link-local.example.com": ["fe80::1"],
        "v6-ula.example.com": ["fd12:3456:789a::1"],
        "v6-mapped-loopback.example.com": ["::ffff:127.0.0.1"],
        "v6-mapped-private.example.com": ["::ffff:10.0.0.1"],
        "v6-multicast.example.com": ["ff02::1"],
        "v6-unspecified.example.com": ["::"],
    }
    urls = [f"https://{host}/mcp" for host in table] + [
        "https://[::1]/mcp",
        "https://[fe80::1]:8443/mcp",
        "https://[::ffff:127.0.0.1]/mcp",
    ]
    with _env(MCP_ALLOW_PRIVATE_HOSTS=None), _dns(table):
        verdicts = {url: _verdict(url) for url in urls}
    assert all(v == "refused" for v in verdicts.values()), verdicts


def test_a_host_with_any_private_address_is_refused() -> None:
    """Resolving to one public and one private address is still refused."""
    table = {"split.example.com": [PUBLIC_V4, "10.0.0.1"], "split6.example.com": [PUBLIC_V6, "::1"]}
    with _env(MCP_ALLOW_PRIVATE_HOSTS=None), _dns(table):
        verdicts = {h: _verdict(f"https://{h}/mcp") for h in table}
    assert all(v == "refused" for v in verdicts.values()), verdicts


def test_private_hosts_are_allowed_only_while_the_override_is_on() -> None:
    """MCP_ALLOW_PRIVATE_HOSTS=true lets a developer use a local server; it is read on every check."""
    table = {"localhost": ["127.0.0.1", "::1"]}
    urls = ["http://localhost:8000/mcp", "https://10.0.0.5/mcp", "http://127.0.0.1:3000/sse", "http://[::1]:9000/mcp"]
    with _dns(table):
        with _env(MCP_ALLOW_PRIVATE_HOSTS="true"):
            allowed = {url: _verdict(url) for url in urls}
        with _env(MCP_ALLOW_PRIVATE_HOSTS=None):
            refused = {url: _verdict(url) for url in urls}
    assert all(v == "allowed" for v in allowed.values()), allowed
    assert all(v == "refused" for v in refused.values()), refused


def test_builtin_urls_are_always_allowed() -> None:
    """The Demo CRM needs no override and no DNS."""
    with _env(MCP_ALLOW_PRIVATE_HOSTS=None), _dns({}):
        verdict = _verdict("builtin://demo")
    assert verdict == "allowed", verdict


# ---------------------------------------------------------------------------
# Secrets: seal / unseal
# ---------------------------------------------------------------------------

SECRET_DATA = {
    "url": "https://mcp.zapier.example/api/mcp/s/sk_live_ABC123/mcp",
    "headers": {"Authorization": "Bearer tok_SECRET456", "X-Workspace": "कार्यक्षेत्र-7"},
}


def test_secrets_are_encrypted_with_secrets_key_and_round_trip() -> None:
    """A stored server URL and API key are unreadable in the database, yet usable by the app."""
    from src.voiceagent.mcp.secrets import seal, sealing_enabled, unseal

    with _env(**SEALED):
        assert sealing_enabled() is True
        token = seal(SECRET_DATA)
        restored = unseal(token)
    assert isinstance(token, str), type(token)
    assert not token.startswith("plain:"), token[:20]
    for plaintext in ("sk_live_ABC123", "tok_SECRET456", "zapier", "Authorization"):
        assert plaintext not in token, f"{plaintext!r} is readable in the sealed token"
    assert restored == SECRET_DATA, restored


def test_auth_secret_is_the_fallback_sealing_key() -> None:
    """A deployment with access control on seals secrets even without SECRETS_KEY."""
    from src.voiceagent.mcp.secrets import seal, sealing_enabled, unseal

    with _env(SECRETS_KEY=None, AUTH_SECRET="auth-secret-for-tests"):
        assert sealing_enabled() is True
        token = seal(SECRET_DATA)
        assert unseal(token) == SECRET_DATA
    assert not token.startswith("plain:") and "tok_SECRET456" not in token, token[:40]


def test_secrets_key_wins_over_auth_secret() -> None:
    """Rotating AUTH_SECRET (logging everyone out) must not lose every stored credential."""
    from src.voiceagent.mcp.secrets import SecretsUnavailable, seal, unseal

    with _env(SECRETS_KEY="k-one", AUTH_SECRET="auth-one"):
        token = seal(SECRET_DATA)
    with _env(SECRETS_KEY="k-one", AUTH_SECRET="auth-two"):
        assert unseal(token) == SECRET_DATA
    with _env(SECRETS_KEY=None, AUTH_SECRET="auth-one"):
        try:
            unseal(token)
        except SecretsUnavailable:
            pass
        else:
            raise AssertionError("a token sealed with SECRETS_KEY opened with AUTH_SECRET")


def test_without_a_key_secrets_are_stored_plain_and_flagged() -> None:
    """With no key configured it still works, and health can warn that secrets are unsealed."""
    from src.voiceagent.mcp.secrets import seal, sealing_enabled, unseal

    with _env(SECRETS_KEY=None, AUTH_SECRET=None):
        assert sealing_enabled() is False
        token = seal(SECRET_DATA)
        restored = unseal(token)
    assert token.startswith("plain:"), token[:20]
    encoded = token[len("plain:"):]
    padded = encoded + "=" * (-len(encoded) % 4)
    try:
        decoded = base64.b64decode(padded, validate=True)
    except ValueError:
        decoded = base64.urlsafe_b64decode(padded)
    assert json.loads(decoded) == SECRET_DATA
    assert restored == SECRET_DATA, restored


def test_a_token_that_cannot_be_opened_raises_secrets_unavailable() -> None:
    """A changed key surfaces as "re-enter this server's credentials", not a crash."""
    from src.voiceagent.mcp.secrets import SecretsUnavailable, seal, unseal

    with _env(SECRETS_KEY="k-one", AUTH_SECRET=None):
        token = seal(SECRET_DATA)

    attempts = {
        "different key": (dict(SECRETS_KEY="k-two", AUTH_SECRET=None), token),
        "no key at all": (dict(SECRETS_KEY=None, AUTH_SECRET=None), token),
        "garbage": (dict(SECRETS_KEY="k-one", AUTH_SECRET=None), "not-a-token"),
    }
    outcomes = {}
    for label, (env, value) in attempts.items():
        with _env(**env):
            try:
                unseal(value)
            except SecretsUnavailable:
                outcomes[label] = "SecretsUnavailable"
            except Exception as exc:  # noqa: BLE001
                outcomes[label] = f"{type(exc).__name__}: {exc}"
            else:
                outcomes[label] = "opened"
    assert all(v == "SecretsUnavailable" for v in outcomes.values()), outcomes


# ---------------------------------------------------------------------------
# The Demo CRM
# ---------------------------------------------------------------------------


async def _demo_tools():
    from mcp import Client

    from src.voiceagent.mcp.demo_server import demo_server

    async with Client(demo_server()) as client:
        return (await client.list_tools()).tools


async def _call_demo(name: str, arguments: dict) -> tuple[bool, str]:
    from mcp import Client

    from src.voiceagent.mcp.demo_server import demo_server

    async with Client(demo_server()) as client:
        result = await client.call_tool(name, arguments)
    return result.is_error, "\n".join(getattr(c, "text", "") for c in result.content)


def test_the_demo_crm_offers_its_four_tools() -> None:
    """Anyone can try tools end to end with the built-in Demo CRM, no account needed."""
    from mcp.server.mcpserver import MCPServer

    from src.voiceagent.mcp.demo_server import demo_server

    assert isinstance(demo_server(), MCPServer)
    tools = {t.name: t for t in asyncio.run(_demo_tools())}
    assert set(tools) == DEMO_TOOL_NAMES, sorted(tools)

    params = {
        "lookup_customer": {"phone"},
        "check_availability": {"date"},
        "book_appointment": {"name", "date", "time"},
        "create_ticket": {"summary", "priority"},
    }
    for name, expected in params.items():
        schema = tools[name].input_schema
        assert set(schema.get("properties", {})) == expected, (name, schema)
        assert (tools[name].description or "").strip(), f"{name} has no description for the model"
    assert set(tools["book_appointment"].input_schema.get("required", [])) == {"name", "date", "time"}
    assert "priority" not in tools["create_ticket"].input_schema.get("required", []), "priority must default"


def test_the_demo_crm_answers_every_tool_with_deterministic_data() -> None:
    """The same question gets the same answer, so a demo and its tests are repeatable."""
    calls = [
        ("lookup_customer", {"phone": "+15555550123"}),
        ("check_availability", {"date": "2026-09-29"}),
        ("book_appointment", {"name": "Asha Rao", "date": "2026-09-29", "time": "10:00"}),
        ("create_ticket", {"summary": "Asha wants a callback about her bill."}),
        ("create_ticket", {"summary": "Billing error on the last invoice.", "priority": "high"}),
    ]

    async def scenario():
        first = [await _call_demo(name, args) for name, args in calls]
        again = [await _call_demo(name, args) for name, args in calls[:2]]
        return first, again

    first, again = asyncio.run(scenario())
    for (name, args), (is_error, text) in zip(calls, first):
        assert not is_error, (name, args, text)
        assert text.strip(), f"{name} answered with no text"
    assert again == first[:2], f"reads are not deterministic: {again} vs {first[:2]}"
    slots = first[1][1]
    assert re.search(r"\d{1,2}:\d{2}|\d{1,2}\s*(am|pm)", slots, re.I), f"no time slots in: {slots!r}"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


def test_discovery_lists_the_demo_crm_tools() -> None:
    """Connecting an app shows exactly the tools it offers, ready to pick per campaign."""

    async def scenario():
        from src.voiceagent.mcp.client import discover

        async with _db() as sessions:
            row = await _add_server(sessions, "demo", tools=[])
            return await _within(5, discover(row), "discovering the Demo CRM")

    with _env(**SEALED, MCP_ALLOW_PRIVATE_HOSTS=None):
        tools = asyncio.run(scenario())
    assert isinstance(tools, list), type(tools)
    assert {t["name"] for t in tools} == DEMO_TOOL_NAMES, tools
    for tool in tools:
        assert {"name", "description", "input_schema"} <= set(tool), tool
        assert isinstance(tool["input_schema"], dict) and "properties" in tool["input_schema"], tool
    availability = next(t for t in tools if t["name"] == "check_availability")
    assert "date" in availability["input_schema"]["properties"], availability


async def _discovery_error(url: str, *, limit: float = 6.0) -> tuple[str, float]:
    """(message, seconds) of the McpUnavailable that discovering `url` raises."""
    from src.voiceagent.mcp.client import McpUnavailable, discover

    async with _db() as sessions:
        row = await _add_server(sessions, "broken", tools=[], url=url, transport="streamable_http")
        started = time.perf_counter()
        try:
            await _within(limit, discover(row), f"discovery against {url}")
        except McpUnavailable as exc:
            return str(exc), time.perf_counter() - started
    raise AssertionError(f"discovery against {url} succeeded; expected McpUnavailable")


LOCAL_DEV = dict(**SEALED, MCP_ALLOW_PRIVATE_HOSTS="true", MCP_CONNECT_TIMEOUT_SECONDS="2")


def test_discovery_of_something_that_is_not_an_mcp_server_fails_readably() -> None:
    """A wrong URL gets a message the person can act on, not a stack dump."""

    async def scenario():
        messages = {}
        for status in ("404 Not Found", "200 OK"):
            async with _http_stub(status) as base:
                messages[status], _ = await _discovery_error(f"{base}/mcp")
        return messages

    with _env(**LOCAL_DEV):
        messages = asyncio.run(scenario())
    unreadable = {k: m for k, m in messages.items() if not _readable(m)}
    assert not unreadable, unreadable


def test_discovery_says_when_the_server_rejects_the_credentials() -> None:
    """A 401 tells the person to check their key — the most common setup mistake."""

    async def scenario():
        async with _http_stub("401 Unauthorized") as base:
            return await _discovery_error(f"{base}/mcp")

    with _env(**LOCAL_DEV):
        message, _ = asyncio.run(scenario())
    assert _readable(message), message
    hint = re.compile(r"401|auth|credential|api key|\bkey\b|token|unauthori[sz]ed|forbidden|denied|rejected", re.I)
    assert hint.search(message), f"nothing in the message points at the credentials: {message!r}"


def test_discovery_gives_up_at_the_connect_timeout() -> None:
    """A server that never answers costs MCP_CONNECT_TIMEOUT_SECONDS, not a hung request."""

    async def scenario():
        async with _http_stub(None) as base:
            return await _discovery_error(f"{base}/mcp", limit=4.0)

    with _env(**{**LOCAL_DEV, "MCP_CONNECT_TIMEOUT_SECONDS": "0.5"}):
        message, seconds = asyncio.run(scenario())
    assert seconds < 3.0, f"discovery took {seconds:.1f}s with a 0.5s connect timeout"
    assert _readable(message), message


def test_discovery_of_an_unknown_builtin_fails_cleanly() -> None:
    """Only builtin://demo exists; anything else is "not an MCP endpoint", not a crash."""

    async def scenario():
        return await _discovery_error("builtin://no-such-server")

    with _env(**SEALED):
        message, _ = asyncio.run(scenario())
    assert _readable(message), message


# ---------------------------------------------------------------------------
# The call toolbox
# ---------------------------------------------------------------------------


def test_tool_specs_and_results_are_immutable() -> None:
    from src.voiceagent.mcp.toolbox import ToolResult, ToolSpec

    spec = ToolSpec(id="demo__ping", description="Ping.", input_schema={"type": "object"})
    result = ToolResult(ok=True, text="pong")
    for value, field in ((spec, "id"), (result, "text")):
        try:
            setattr(value, field, "changed")
        except dataclasses.FrozenInstanceError:
            pass
        else:
            raise AssertionError(f"{type(value).__name__} must be a frozen dataclass")


def test_the_toolbox_offers_only_requested_tools_of_healthy_enabled_servers() -> None:
    """The model sees the campaign's tools; a paused, failing or removed one never reaches it."""

    async def scenario():
        async with _db() as sessions:
            await _add_server(sessions, "demo", tools=DEMO_TOOLS)
            await _add_server(sessions, "paused", tools=DEMO_TOOLS, enabled=False)
            await _add_server(sessions, "broken", tools=DEMO_TOOLS, status="error")
            box = await _toolbox(
                sessions,
                [
                    "demo__check_availability",
                    "demo__create_ticket",
                    "paused__lookup_customer",
                    "broken__lookup_customer",
                    "demo__no_such_tool",
                    "gone__check_availability",
                ],
            )
            try:
                return box.specs()
            finally:
                await box.aclose()

    with _env(**SEALED):
        specs = asyncio.run(scenario())

    from src.voiceagent.mcp.toolbox import ToolSpec

    assert all(isinstance(s, ToolSpec) for s in specs), specs
    by_id = {s.id: s for s in specs}
    assert set(by_id) == {"demo__check_availability", "demo__create_ticket"}, sorted(by_id)
    assert all(TOOL_ID.match(tool_id) for tool_id in by_id), sorted(by_id)
    stored = {t["name"]: t for t in DEMO_TOOLS}
    for tool_id, spec in by_id.items():
        name = tool_id.split("__", 1)[1]
        assert stored[name]["description"] in spec.description, spec
        assert spec.input_schema.get("properties") == stored[name]["input_schema"]["properties"], spec


def test_a_tool_call_reaches_the_demo_crm() -> None:
    """In a call, "is Tuesday free?" is answered from the connected app, the same way every time."""

    async def scenario():
        async with _db() as sessions:
            await _add_server(sessions, "demo", tools=DEMO_TOOLS)
            box = await _toolbox(sessions, ["demo__check_availability", "demo__lookup_customer"])
            try:
                args = {"date": "2026-09-29"}
                first = await _within(5, box.call("demo__check_availability", args), "a demo tool call")
                again = await _within(5, box.call("demo__check_availability", args), "a second demo call")
                customer = await _within(
                    5, box.call("demo__lookup_customer", {"phone": "+15555550123"}), "a lookup"
                )
            finally:
                await box.aclose()
        return first, again, customer

    with _env(**SEALED):
        first, again, customer = asyncio.run(scenario())

    from src.voiceagent.mcp.toolbox import ToolResult

    assert isinstance(first, ToolResult), type(first)
    assert first.ok is True and first.text.strip(), first
    assert again == first, (first, again)
    assert customer.ok is True and customer.text.strip(), customer


def test_an_error_result_from_a_tool_is_a_failed_result() -> None:
    """Bad arguments from the model come back as a failure it can recover from, not a crash."""

    async def scenario():
        async with _db() as sessions:
            await _add_server(sessions, "demo", tools=DEMO_TOOLS)
            box = await _toolbox(sessions, ["demo__book_appointment"])
            try:
                return await _within(5, box.call("demo__book_appointment", {}), "a bad tool call")
            finally:
                await box.aclose()

    with _env(**SEALED):
        result = asyncio.run(scenario())
    assert result.ok is False, result
    assert result.text.strip() and len(result.text) <= 4000, result


def test_only_the_tools_the_campaign_allowed_can_run() -> None:
    """A tool id the model makes up, or one the campaign didn't allow, never runs."""

    async def scenario():
        async with _db() as sessions:
            await _add_server(sessions, "demo", tools=DEMO_TOOLS)
            box = await _toolbox(sessions, ["demo__check_availability"])
            try:
                return [
                    await _within(5, box.call(tool_id, args), f"calling {tool_id}")
                    for tool_id, args in (
                        ("demo__create_ticket", {"summary": "Not allowed in this call."}),
                        ("demo__drop_everything", {}),
                        ("gone__check_availability", {"date": "2026-09-29"}),
                    )
                ]
            finally:
                await box.aclose()

    with _env(**SEALED):
        results = asyncio.run(scenario())
    assert [r.ok for r in results] == [False, False, False], results
    assert all(r.text.strip() for r in results), results


def test_a_tool_that_hangs_times_out_and_the_other_tools_keep_working() -> None:
    """A stuck integration costs the caller MCP_TOOL_TIMEOUT_SECONDS at most, and the call goes on."""

    async def scenario():
        with _serve_builtin_demo(_test_crm):
            async with _db() as sessions:
                await _add_server(sessions, "test_crm", tools=TEST_CRM_TOOLS)
                box = await _toolbox(sessions, ["test_crm__stall", "test_crm__ping"])
                try:
                    started = time.perf_counter()
                    stalled = await _within(
                        4, box.call("test_crm__stall", {}), "a hung tool with MCP_TOOL_TIMEOUT_SECONDS=0.3"
                    )
                    seconds = time.perf_counter() - started
                    after = await _within(3, box.call("test_crm__ping", {}), "the next tool call")
                finally:
                    await _within(3, box.aclose(), "closing the toolbox")
        return stalled, seconds, after

    with _env(**SEALED, MCP_TOOL_TIMEOUT_SECONDS="0.3"):
        stalled, seconds, after = asyncio.run(scenario())
    assert stalled.ok is False and stalled.text.strip(), stalled
    assert seconds < 2.0, f"the timed-out call took {seconds:.1f}s"
    assert after.ok is True and "pong" in after.text, after


def test_a_failing_tool_or_unreachable_server_never_raises() -> None:
    """A broken tool must never break a call: every failure is a result, not an exception."""

    async def scenario():
        with _serve_builtin_demo(_test_crm):
            async with _db() as sessions:
                await _add_server(sessions, "test_crm", tools=TEST_CRM_TOOLS)
                await _add_server(sessions, "nowhere", tools=TEST_CRM_TOOLS, url="builtin://no-such-server")
                box = await _toolbox(sessions, ["test_crm__crash", "nowhere__ping"])
                try:
                    crashed = await _within(5, box.call("test_crm__crash", {}), "a crashing tool")
                    unreachable = await _within(5, box.call("nowhere__ping", {}), "an unreachable server")
                finally:
                    await _within(3, box.aclose(), "closing the toolbox")
        return crashed, unreachable

    with _env(**SEALED):
        crashed, unreachable = asyncio.run(scenario())
    assert crashed.ok is False and crashed.text.strip(), crashed
    assert unreachable.ok is False and unreachable.text.strip(), unreachable


def test_a_long_result_is_cut_down_before_the_model_sees_it() -> None:
    """A tool that dumps a huge record can't blow up the call's prompt."""

    async def scenario():
        with _serve_builtin_demo(_test_crm):
            async with _db() as sessions:
                await _add_server(sessions, "test_crm", tools=TEST_CRM_TOOLS)
                box = await _toolbox(sessions, ["test_crm__huge"])
                try:
                    return await _within(5, box.call("test_crm__huge", {}), "a huge result")
                finally:
                    await box.aclose()

    with _env(**SEALED):
        result = asyncio.run(scenario())
    assert result.ok is True, result
    # 4000 characters; a trailing ellipsis is tolerated.
    assert len(result.text) <= 4003, len(result.text)
    assert result.text.startswith("z" * 1000), result.text[:40]


def test_every_tool_call_is_reported_as_it_starts_and_finishes() -> None:
    """The live console shows each tool call starting, then how it went and how long it took."""

    async def scenario():
        events: list[dict] = []
        post_call: list[dict] = []

        async def on_event(event: dict) -> None:
            events.append(dict(event))

        async def on_post_call(event: dict) -> None:
            post_call.append(dict(event))

        async with _db() as sessions:
            await _add_server(sessions, "demo", tools=DEMO_TOOLS)
            box = await _toolbox(
                sessions, ["demo__check_availability", "demo__book_appointment"], on_event=on_event
            )
            try:
                good = await _within(
                    5, box.call("demo__check_availability", {"date": "2026-09-29"}), "a good call"
                )
                await _within(5, box.call("demo__book_appointment", {}), "a bad call")
            finally:
                await box.aclose()

            after = await _toolbox(
                sessions, ["demo__create_ticket"], phase="post_call", on_event=on_post_call
            )
            try:
                await _within(5, after.call("demo__create_ticket", {"summary": "Booked."}), "a post-call tool")
            finally:
                await after.aclose()
        return events, post_call, good

    with _env(**SEALED):
        events, post_call, good = asyncio.run(scenario())

    assert [e.get("status") for e in events] == ["started", "ok", "started", "error"], events
    for event in events:
        assert EVENT_KEYS <= set(event), f"missing {EVENT_KEYS - set(event)} in {event}"
        assert event["phase"] == "in_call", event
        assert event["server"], event
        assert event["tool"] in ("check_availability", "demo__check_availability",
                                 "book_appointment", "demo__book_appointment"), event

    started, finished = events[0], events[1]
    assert started["arguments"] == {"date": "2026-09-29"}, started
    assert finished["arguments"] == {"date": "2026-09-29"}, finished
    assert isinstance(finished["duration_ms"], int) and finished["duration_ms"] >= 0, finished
    excerpt = finished["excerpt"]
    assert isinstance(excerpt, str) and excerpt.strip() and len(excerpt) <= 300, finished
    assert excerpt.strip() in good.text, (excerpt, good.text)
    assert not finished["error"], finished

    failed = events[3]
    assert isinstance(failed["error"], str) and failed["error"].strip(), failed
    assert isinstance(failed["duration_ms"], int), failed

    assert [e.get("status") for e in post_call] == ["started", "ok"], post_call
    assert all(e["phase"] == "post_call" for e in post_call), post_call


def test_a_broken_observer_never_breaks_a_tool_call() -> None:
    """If the live feed fails, the tool still runs and its answer still reaches the model."""

    async def scenario():
        async def on_event(event: dict) -> None:
            raise RuntimeError("the console went away")

        async with _db() as sessions:
            await _add_server(sessions, "demo", tools=DEMO_TOOLS)
            box = await _toolbox(sessions, ["demo__check_availability"], on_event=on_event)
            try:
                return await _within(
                    5, box.call("demo__check_availability", {"date": "2026-09-29"}), "a call with a broken observer"
                )
            finally:
                await box.aclose()

    with _env(**SEALED):
        result = asyncio.run(scenario())
    assert result.ok is True and result.text.strip(), result


def test_one_connection_per_server_opened_on_first_use_and_closed_at_the_end() -> None:
    """No handshake per tool call, and nothing left open after the call ends."""
    connections = _Connections()

    async def scenario():
        with _serve_builtin_demo(functools.partial(_test_crm, connections)):
            async with _db() as sessions:
                await _add_server(sessions, "test_crm", tools=TEST_CRM_TOOLS)
                box = await _toolbox(sessions, ["test_crm__ping", "test_crm__huge"])
                built = connections.opened
                for tool_id in ("test_crm__ping", "test_crm__huge", "test_crm__ping"):
                    await _within(5, box.call(tool_id, {}), f"calling {tool_id}")
                during = connections.opened
                await _within(3, box.aclose(), "closing the toolbox")
        return built, during

    with _env(**SEALED):
        built, during = asyncio.run(scenario())
    assert built == 0, f"{built} connection(s) opened before any tool was used"
    assert during == 1, f"{during} connections for three calls to one server"
    assert connections.closed == connections.opened == 1, vars(connections)


def test_warm_connects_every_needed_server_before_the_first_tool_call() -> None:
    """Connections are made while the phone rings, so the first "let me check" costs no handshake."""
    connections = _Connections()

    async def scenario():
        with _serve_builtin_demo(functools.partial(_test_crm, connections)):
            async with _db() as sessions:
                await _add_server(sessions, "crm_a", tools=TEST_CRM_TOOLS)
                await _add_server(sessions, "crm_b", tools=TEST_CRM_TOOLS)
                await _add_server(sessions, "crm_unused", tools=TEST_CRM_TOOLS)
                await _add_server(sessions, "nowhere", tools=TEST_CRM_TOOLS, url="builtin://no-such-server")
                box = await _toolbox(sessions, ["crm_a__ping", "crm_b__huge", "crm_b__ping", "nowhere__ping"])
                # An unreachable server must not make warming fail the call.
                await _within(5, box.warm(), "warming the toolbox")
                warmed = connections.opened
                result = await _within(5, box.call("crm_a__ping", {}), "the first tool call")
                after_call = connections.opened
                await _within(3, box.aclose(), "closing the toolbox")
        return warmed, after_call, result

    with _env(**SEALED):
        warmed, after_call, result = asyncio.run(scenario())
    assert warmed == 2, f"warm() opened {warmed} connections; expected one each for crm_a and crm_b"
    assert after_call == 2, "the first tool call opened a new connection after warm()"
    assert result.ok is True, result
    assert connections.closed == 2, vars(connections)


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
