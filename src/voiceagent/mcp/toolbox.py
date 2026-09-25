"""The tools one call may use, and the rules for using them on a live line.

A `Toolbox` is what the conversation sees: tool specs to offer the model, and
`call()`. `CallToolbox` is the real one — a campaign's chosen tools, resolved
against the connected servers, with one MCP session per server for the
length of the call.

The rules come from the phone line, not from MCP:

  * `call()` never raises. A tool that is slow, broken, refuses its
    arguments or reports an error comes back as `ToolResult(ok=False)` with
    a short reason, which the model hears and apologises for. A broken
    integration must never be what ends a call.
  * Every call is bounded by MCP_TOOL_TIMEOUT_SECONDS (default 8), counted
    from the moment the model asked, connecting included — the caller is on
    the line for all of it.
  * Sessions are opened by `warm()` while the phone rings, so the first
    tool of the call does not also pay for a TLS handshake and an MCP
    handshake. A server that could not be reached then is tried again on
    its next use.
  * Every call is reported through `on_event` as it starts and as it ends,
    which is what puts it on the live console and on the call record.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from collections.abc import AsyncIterator, Awaitable, Callable, Iterable
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Protocol

from sqlalchemy import select

from ..storage import McpServer
from .client import Connection, Endpoint, McpUnavailable, redact
from .ids import tool_id

logger = logging.getLogger(__name__)

# What the model is given back from one tool, at most. Tool results go into
# every later request of the call, so a CRM record dumped whole would be
# paid for on every turn that follows.
RESULT_MAX_CHARS = 4000
# What the call record and the live console keep of a result.
EXCERPT_CHARS = 300

ToolEventCallback = Callable[[dict[str, Any]], Awaitable[None]]


@dataclass(frozen=True)
class ToolSpec:
    id: str
    description: str
    input_schema: dict


@dataclass(frozen=True)
class ToolResult:
    ok: bool
    text: str


class Toolbox(Protocol):
    def specs(self) -> list[ToolSpec]: ...

    async def call(self, tool_id: str, arguments: dict) -> ToolResult: ...


def tool_timeout() -> float:
    try:
        value = float(os.getenv("MCP_TOOL_TIMEOUT_SECONDS", "") or 8.0)
    except ValueError:
        return 8.0
    return value if value > 0 else 8.0


@dataclass(frozen=True)
class _Tool:
    """Where one tool id leads: which server, and the tool's own name there."""

    spec: ToolSpec
    endpoint: Endpoint
    name: str


class CallToolbox:
    """The tools one call may use. Implements `Toolbox`."""

    def __init__(
        self,
        tools: Iterable[_Tool] = (),
        *,
        phase: str,
        on_event: ToolEventCallback | None = None,
    ) -> None:
        self._tools = {tool.spec.id: tool for tool in tools}
        self._phase = phase
        self._on_event = on_event
        self._connections: dict[str, Connection] = {}
        self._closed = False

    @classmethod
    async def for_tool_ids(
        cls,
        session_factory,
        tool_ids: list[str],
        *,
        phase: str,
        on_event: ToolEventCallback | None = None,
    ) -> CallToolbox:
        """The campaign's chosen tools that can actually be used right now.

        Only enabled servers whose last check was ok are used; ids for tools
        that no longer exist, or whose server is off, broken or removed, are
        skipped. If the servers cannot even be read, the call goes ahead
        with no tools rather than not at all.
        """
        wanted = list(dict.fromkeys(tid for tid in tool_ids or [] if isinstance(tid, str)))
        if not wanted:
            return cls(phase=phase, on_event=on_event)

        try:
            async with session_factory() as db:
                servers = (
                    await db.execute(
                        select(McpServer).where(
                            McpServer.enabled.is_(True), McpServer.status == "ok"
                        )
                    )
                ).scalars().all()
        except Exception:  # noqa: BLE001 - tools are an extra, never a reason not to call
            logger.exception("Could not load MCP servers; the call goes ahead without tools")
            return cls(phase=phase, on_event=on_event)

        available = {tool.spec.id: tool for server in servers for tool in _tools_of(server)}
        return cls(
            (available[tid] for tid in wanted if tid in available),
            phase=phase,
            on_event=on_event,
        )

    @classmethod
    def for_server(
        cls, server: McpServer, *, phase: str, on_event: ToolEventCallback | None = None
    ) -> CallToolbox:
        """Every tool of one server, whatever its state — for trying a tool out."""
        return cls(_tools_of(server), phase=phase, on_event=on_event)

    # -- what the model sees ------------------------------------------------

    def specs(self) -> list[ToolSpec]:
        return [tool.spec for tool in self._tools.values()]

    def label(self, tool_id: str) -> tuple[str, str] | None:
        """(server name, tool name) for a tool id, for the call record."""
        tool = self._tools.get(tool_id)
        return (tool.endpoint.name, tool.name) if tool else None

    # -- connections ----------------------------------------------------------

    async def warm(self) -> None:
        """Connect to every server this call may use. Never raises."""
        endpoints = {tool.endpoint.slug: tool.endpoint for tool in self._tools.values()}
        await asyncio.gather(*(self._warm(endpoint) for endpoint in endpoints.values()))

    async def _warm(self, endpoint: Endpoint) -> None:
        try:
            await self._connection(endpoint).open()
        except McpUnavailable as exc:
            logger.warning("Could not connect to %s ahead of the call: %s", endpoint.name, exc)

    def _connection(self, endpoint: Endpoint) -> Connection:
        if self._closed:
            raise McpUnavailable("The call is over; its tools are closed.")
        connection = self._connections.get(endpoint.slug)
        if connection is None or connection.failed:
            connection = self._connections[endpoint.slug] = Connection(endpoint)
        return connection

    async def aclose(self) -> None:
        self._closed = True
        connections, self._connections = list(self._connections.values()), {}
        await asyncio.gather(*(connection.close() for connection in connections))

    # -- calling --------------------------------------------------------------

    async def call(self, tool_id: str, arguments: dict) -> ToolResult:
        tool = self._tools.get(tool_id)
        if tool is None:
            return ToolResult(False, f"There is no tool called {tool_id} on this call.")

        event = {
            "phase": self._phase,
            "server": tool.endpoint.name,
            "tool": tool.name,
            "arguments": arguments,
        }
        await self._emit(
            {**event, "status": "started", "duration_ms": None, "excerpt": None, "error": None}
        )
        started = time.perf_counter()
        result = await self._run(tool, arguments)
        await self._emit(
            {
                **event,
                "status": "ok" if result.ok else "error",
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "excerpt": result.text[:EXCERPT_CHARS],
                "error": None if result.ok else result.text[:EXCERPT_CHARS],
            }
        )
        return result

    async def _run(self, tool: _Tool, arguments: dict) -> ToolResult:
        seconds = tool_timeout()
        try:
            async with asyncio.timeout(seconds):
                result = await self._connection(tool.endpoint).call_tool(tool.name, arguments)
        except TimeoutError:
            return ToolResult(False, f"{tool.endpoint.name} did not answer within {seconds:g} seconds.")
        except McpUnavailable as exc:
            return ToolResult(False, str(exc))
        except Exception as exc:  # noqa: BLE001 - a broken tool must not break the call
            logger.warning("Tool %s on %s failed", tool.name, tool.endpoint.name, exc_info=True)
            reason = str(exc).strip() or type(exc).__name__
            return ToolResult(False, redact(f"The tool failed: {reason}", tool.endpoint))

        text = result_text(result)
        if result.is_error:
            return ToolResult(False, text or "The tool reported an error.")
        return ToolResult(True, text)

    async def _emit(self, event: dict[str, Any]) -> None:
        if self._on_event is None:
            return
        try:
            await self._on_event(event)
        except Exception:  # noqa: BLE001 - a broken observer must not break a call
            logger.exception("Tool event observer failed; the call continues")


@asynccontextmanager
async def call_tools(
    session_factory, tool_ids: list[str] | None, *, on_event: ToolEventCallback | None = None
) -> AsyncIterator[CallToolbox]:
    """A call's in-call toolbox for the length of the block.

    Entering costs one lookup of the servers; connecting runs in the
    background from then on, so it happens while the phone rings rather
    than while the caller waits on the first tool. Leaving closes every
    session the call opened.
    """
    toolbox = await CallToolbox.for_tool_ids(
        session_factory, tool_ids or [], phase="in_call", on_event=on_event
    )
    warming = asyncio.create_task(toolbox.warm())
    try:
        yield toolbox
    finally:
        warming.cancel()
        await toolbox.aclose()


def _tools_of(server: McpServer) -> list[_Tool]:
    """A server row's discovered tools, keyed for a call. Empty if unusable."""
    try:
        endpoint = Endpoint.of(server)
    except McpUnavailable as exc:
        logger.warning("Skipping the tools of %s: %s", server.name, exc)
        return []
    return [
        _Tool(
            spec=ToolSpec(
                id=tool_id(server.slug, tool["name"]),
                description=tool.get("description") or tool["name"],
                input_schema=tool.get("input_schema") or {"type": "object", "properties": {}},
            ),
            endpoint=endpoint,
            name=tool["name"],
        )
        for tool in server.tools or []
        if isinstance(tool, dict) and tool.get("name")
    ]


def result_text(result) -> str:
    """A tool result as the model will read it: its text, bounded."""
    parts = [block.text for block in result.content or [] if getattr(block, "text", None)]
    structured = getattr(result, "structured_content", None)
    if not parts and structured is not None:
        parts = [json.dumps(structured, ensure_ascii=False)]
    return "\n".join(parts)[:RESULT_MAX_CHARS]


# --------------------------------------------------------------------------
# The call record
# --------------------------------------------------------------------------


def log_entry(event: dict[str, Any]) -> dict[str, Any]:
    """A finished tool event in the shape stored on `Call.tool_calls`."""
    return {
        "at": datetime.now(timezone.utc).isoformat(),
        "phase": event["phase"],
        "server": event["server"],
        "tool": event["tool"],
        "arguments": event["arguments"],
        "ok": event["status"] == "ok",
        "duration_ms": event["duration_ms"],
        "excerpt": event["excerpt"],
        "error": event["error"],
    }


class ToolLog:
    """A call's record of the tools it used, built from toolbox events."""

    def __init__(self) -> None:
        self.entries: list[dict[str, Any]] = []

    def add(self, event: dict[str, Any]) -> bool:
        """Keep a finished tool call. True if the event was one."""
        if event.get("status") == "started":
            return False
        self.entries.append(log_entry(event))
        return True
