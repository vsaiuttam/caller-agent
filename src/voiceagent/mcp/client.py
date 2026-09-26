"""Talking to one MCP server: connecting, discovering its tools, staying open.

Three transports. Streamable HTTP is the current one and what hosted servers
(Zapier, Composio, most others) speak; SSE is the older one some still do;
`builtin://…` servers run in this process. When a server is added the
transport can be left to us ("auto"): streamable HTTP is tried first and SSE
only if the URL answered but not as streamable HTTP — a server that is down
or refuses the key would fail SSE the same way, and trying it would only
double the wait.

Every connection is checked by `guard.check_url` as it is opened, and bounded
by MCP_CONNECT_TIMEOUT_SECONDS (default 10). Failures come back as
`McpUnavailable`, worded for the person who typed the URL: the key was
refused, the host could not be reached, the URL is not an MCP endpoint.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator, Callable
from contextlib import AsyncExitStack, asynccontextmanager
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

import httpx2
from mcp import Client, MCPError
from mcp.client.sse import sse_client
from mcp.client.streamable_http import streamable_http_client
from mcp.shared._httpx_utils import create_mcp_http_client

from .demo_server import DEMO_URL, demo_server
from .guard import BUILTIN_SCHEME, UnsafeUrl, check_url
from .secrets import REENTER_MESSAGE, SecretsUnavailable, unseal

if TYPE_CHECKING:
    from mcp.server.mcpserver import MCPServer

    from ..storage import McpServer

logger = logging.getLogger(__name__)

STREAMABLE_HTTP = "streamable_http"
SSE = "sse"
BUILTIN = "builtin"
AUTO = "auto"

# A server's SSE stream is held open for as long as the session is; this is
# how long it may go quiet before the session counts as dropped.
_SSE_READ_TIMEOUT = 300.0
# A server with more pages of tools than this is paginating in a loop.
_MAX_TOOL_PAGES = 20
# How long closing a session may take before it is abandoned.
_CLOSE_TIMEOUT = 5.0

_BUILTINS: dict[str, Callable[[], MCPServer]] = {DEMO_URL: demo_server}


class McpUnavailable(Exception):
    """A server could not be reached or used. The message says why, plainly.

    `kind` is what went wrong in a word — auth, unreachable, timeout,
    protocol, unsafe, secrets or error — for code that must decide what to
    try next; people read the message.
    """

    def __init__(self, message: str, kind: str = "error") -> None:
        super().__init__(message)
        self.kind = kind


def connect_timeout() -> float:
    return _seconds_from_env("MCP_CONNECT_TIMEOUT_SECONDS", 10.0)


def _seconds_from_env(name: str, default: float) -> float:
    try:
        value = float(os.getenv(name, "") or default)
    except ValueError:
        return default
    return value if value > 0 else default


def is_builtin(url: str) -> bool:
    return urlsplit(url).scheme == BUILTIN_SCHEME


def host_of(url: str) -> str:
    """The part of a server's address that is safe to show: its host."""
    if is_builtin(url):
        return "built in"
    return urlsplit(url).hostname or ""


@dataclass(frozen=True)
class Endpoint:
    """What it takes to connect to a server, with its secrets unsealed.

    Lives only in memory for the length of a call or a request.
    """

    name: str
    slug: str
    transport: str
    url: str
    headers: dict[str, str] = field(default_factory=dict)

    @classmethod
    def of(cls, server: McpServer) -> Endpoint:
        """Unseal a server row. Raises `McpUnavailable` if its secrets can't be read."""
        try:
            secrets = unseal(server.secrets or "")
        except SecretsUnavailable as exc:
            raise McpUnavailable(REENTER_MESSAGE, "secrets") from exc
        return cls(
            name=server.name,
            slug=server.slug,
            transport=server.transport,
            url=str(secrets.get("url", "")),
            headers={str(k): str(v) for k, v in (secrets.get("headers") or {}).items()},
        )


# --------------------------------------------------------------------------
# Opening a session
# --------------------------------------------------------------------------


@dataclass
class _HttpTrace:
    """HTTP statuses seen while connecting.

    The streamable-HTTP transport turns a 401 into a generic JSON-RPC error
    and the status is lost, but "your key was refused" and "that is not an
    MCP URL" need different fixes, so the statuses are watched on the way in.
    """

    statuses: list[int] = field(default_factory=list)

    async def record(self, response: httpx2.Response) -> None:
        self.statuses.append(response.status_code)

    def rejection(self) -> int | None:
        """The status that best explains a failure: a refused key first."""
        failed = [status for status in self.statuses if status >= 400]
        auth = [status for status in failed if status in (401, 403)]
        return (auth or failed or [None])[-1]

    def http_client(
        self,
        headers: dict[str, str] | None = None,
        timeout: httpx2.Timeout | None = None,
        auth: httpx2.Auth | None = None,
    ) -> httpx2.AsyncClient:
        client = create_mcp_http_client(headers=headers, timeout=timeout, auth=auth)
        client.event_hooks["response"].append(self.record)
        return client


def _client(endpoint: Endpoint, transport: str, trace: _HttpTrace) -> Client:
    """An unentered SDK client for `endpoint` over `transport`."""
    if is_builtin(endpoint.url):
        make = _BUILTINS.get(endpoint.url)
        if make is None:
            raise McpUnavailable(f"There is no built-in server at {endpoint.url}.", "protocol")
        return Client(make())

    check_url(endpoint.url)
    timeout = httpx2.Timeout(connect_timeout(), read=_SSE_READ_TIMEOUT)
    if transport == SSE:
        return Client(
            sse_client(
                endpoint.url,
                headers=endpoint.headers,
                timeout=connect_timeout(),
                sse_read_timeout=_SSE_READ_TIMEOUT,
                httpx_client_factory=trace.http_client,
            )
        )
    return Client(_streamable_http(endpoint.url, trace.http_client(endpoint.headers, timeout)))


@asynccontextmanager
async def _streamable_http(url: str, http: httpx2.AsyncClient) -> AsyncIterator[Any]:
    # The transport leaves a client it was handed open, so it is closed here.
    async with http, streamable_http_client(url, http_client=http) as streams:
        yield streams


async def _open(stack: AsyncExitStack, endpoint: Endpoint, transport: str, trace: _HttpTrace) -> Client:
    """Connect and handshake within the connect timeout, onto `stack`."""
    async with asyncio.timeout(connect_timeout()):
        return await stack.enter_async_context(_client(endpoint, transport, trace))


# --------------------------------------------------------------------------
# Discovery
# --------------------------------------------------------------------------


async def discover(server: McpServer) -> list[dict[str, Any]]:
    """Connect to `server` and list its tools as `{name, description, input_schema}`.

    Raises `McpUnavailable` with a readable reason on any failure.
    """
    endpoint = Endpoint.of(server)
    trace = _HttpTrace()
    try:
        async with AsyncExitStack() as stack:
            client = await _open(stack, endpoint, server.transport, trace)
            async with asyncio.timeout(connect_timeout()):
                return await _list_tools(client)
    except McpUnavailable:
        raise
    except Exception as exc:  # noqa: BLE001 - every failure becomes a reason
        raise unavailable(exc, trace, endpoint) from exc


async def discover_transport(server: McpServer) -> list[dict[str, Any]]:
    """`discover`, trying each transport in turn; leaves the one that worked on `server`.

    When none works the error is streamable HTTP's, which is the one that
    describes the likelier mistake.
    """
    url = Endpoint.of(server).url
    if is_builtin(url):
        server.transport = BUILTIN
        return await discover(server)

    server.transport = STREAMABLE_HTTP
    try:
        return await discover(server)
    except McpUnavailable as first:
        if first.kind != "protocol":
            raise
        server.transport = SSE
        try:
            return await discover(server)
        except McpUnavailable:
            server.transport = STREAMABLE_HTTP
            raise first from None


async def _list_tools(client: Client) -> list[dict[str, Any]]:
    tools: list[dict[str, Any]] = []
    cursor: str | None = None
    for _ in range(_MAX_TOOL_PAGES):
        page = await client.list_tools(cursor=cursor)
        tools.extend(
            {
                "name": tool.name,
                "description": (tool.description or "").strip(),
                "input_schema": tool.input_schema or {"type": "object", "properties": {}},
            }
            for tool in page.tools
        )
        cursor = page.next_cursor
        if not cursor:
            break
    return tools


# --------------------------------------------------------------------------
# A session held open for a call
# --------------------------------------------------------------------------


class Connection:
    """One MCP session, held open for the length of a call.

    Owned by a task of its own. The SDK runs on anyio, which requires every
    cancel scope to be exited by the task that entered it — and a call opens
    its sessions in one task (warming them while the phone rings), uses them
    from another (the conversation), and closes them from a third. Here the
    owner task enters the session and is the one that leaves it; everyone
    else only sends it requests.
    """

    def __init__(self, endpoint: Endpoint) -> None:
        self.endpoint = endpoint
        self._client: Client | None = None
        self._error: McpUnavailable | None = None
        self._ready = asyncio.Event()
        self._closing = asyncio.Event()
        self._owner: asyncio.Task | None = None

    @property
    def failed(self) -> bool:
        """Settled without a usable session: never connected, dropped, or closed."""
        return self._ready.is_set() and self._client is None

    async def open(self) -> Client:
        """The connected client, connecting first if nobody has yet."""
        if self._owner is None:
            self._owner = asyncio.create_task(self._own())
        await self._ready.wait()
        if self._client is None:
            raise self._error or McpUnavailable(f"{self.endpoint.name} is not connected.")
        return self._client

    async def call_tool(self, name: str, arguments: dict[str, Any]):
        client = await self.open()
        return await client.call_tool(name, arguments)

    async def close(self) -> None:
        self._closing.set()
        owner = self._owner
        if owner is None:
            return
        if not self._ready.is_set():
            owner.cancel()  # still connecting; nobody is waiting for it now
        await asyncio.wait({owner}, timeout=_CLOSE_TIMEOUT)
        if not owner.done():
            owner.cancel()

    async def _own(self) -> None:
        trace = _HttpTrace()
        try:
            async with AsyncExitStack() as stack:
                self._client = await _open(stack, self.endpoint, self.endpoint.transport, trace)
                self._ready.set()
                await self._closing.wait()
                self._client = None  # closing: no new requests from here on
        except McpUnavailable as exc:
            self._error = exc
        except Exception as exc:  # noqa: BLE001 - kept for whoever calls next
            self._error = unavailable(exc, trace, self.endpoint)
            logger.warning("MCP session with %s ended: %s", self.endpoint.name, self._error)
        finally:
            self._client = None
            self._ready.set()


# --------------------------------------------------------------------------
# Saying what went wrong
# --------------------------------------------------------------------------


def redact(text: str, endpoint: Endpoint) -> str:
    """`text` without the endpoint's URL or header values in it.

    Error text is stored and shown — `last_error`, the call record, the
    model's context — and an SDK message can quote the URL it failed on,
    which is often where the key is.
    """
    url = endpoint.url
    secrets = {url, url.split("?", 1)[0], url.split("#", 1)[0]}
    for value in endpoint.headers.values():
        # The whole value, and its token alone ("Bearer <token>").
        secrets.update({value, *(part for part in value.split() if len(part) >= 8)})
    for secret in sorted(filter(None, secrets), key=len, reverse=True):
        if not is_builtin(secret):
            text = text.replace(secret, "[hidden]")
    return text


def unavailable(exc: BaseException, trace: _HttpTrace, endpoint: Endpoint) -> McpUnavailable:
    """Turn whatever the SDK raised into a reason a person can act on."""
    reason = _reason(exc, trace, endpoint)
    return McpUnavailable(redact(str(reason), endpoint), reason.kind)


def _reason(exc: BaseException, trace: _HttpTrace, endpoint: Endpoint) -> McpUnavailable:
    leaves = list(_leaves(exc))
    host = host_of(endpoint.url) or "the server"

    unsafe = _first(leaves, UnsafeUrl)
    if unsafe is not None:
        return McpUnavailable(str(unsafe), "unsafe")
    known = _first(leaves, McpUnavailable)
    if known is not None:
        return known

    status = trace.rejection() or _status_of(leaves)
    if status in (401, 403):
        return McpUnavailable(
            f"{host} refused the credentials (HTTP {status}). Check the API key or token "
            "in the headers, or in the URL if the app puts it there.",
            "auth",
        )
    if _first(leaves, TimeoutError, httpx2.TimeoutException) is not None:
        return McpUnavailable(
            f"{host} did not answer within {connect_timeout():g} seconds.", "timeout"
        )
    if status is not None and status >= 500:
        return McpUnavailable(
            f"{host} had an internal error (HTTP {status}). Try again in a minute.", "error"
        )
    if status is not None:
        return McpUnavailable(
            f"{host} answered, but not as an MCP server (HTTP {status}). Check the URL's "
            "path — hosted servers usually end in /mcp or /sse.",
            "protocol",
        )
    network = _first(leaves, httpx2.TransportError, OSError)
    if network is not None:
        return McpUnavailable(f"Could not reach {host}: {_describe(network)}", "unreachable")
    protocol = _first(leaves, MCPError)
    if protocol is not None:
        return McpUnavailable(
            f"{host} did not complete the MCP handshake: {_describe(protocol)}", "protocol"
        )
    return McpUnavailable(f"Could not connect to {host}: {_describe(leaves[0])}", "error")


def _leaves(exc: BaseException):
    """The individual exceptions inside anyio's exception groups."""
    if isinstance(exc, BaseExceptionGroup):
        for inner in exc.exceptions:
            yield from _leaves(inner)
    else:
        yield exc


def _first(leaves: list[BaseException], *types: type[BaseException]) -> BaseException | None:
    return next((leaf for leaf in leaves if isinstance(leaf, types)), None)


def _status_of(leaves: list[BaseException]) -> int | None:
    error = _first(leaves, httpx2.HTTPStatusError)
    return error.response.status_code if error is not None else None


def _describe(exc: BaseException) -> str:
    return str(exc).strip() or type(exc).__name__
