"""Tools on a live call and after it: no dead air, every tool call on the record.

While a tool runs the caller must hear something — what the agent already
said, or a short "let me check" in the call's language — and the console must
show the agent working. Every tool call lands on the call record and on the
live feed as it happens. After the call, the campaign's post-call tools write
the outcome back into the user's systems, unless the call is held for review
or never reached anyone (docs/mcp-spec.md §1.3, §1.4).

Covers the session's handling of `ToolPause`, the Twilio interim reply, the
pipeline's tool log and `call.tool` events (campaign calls and test calls),
and `run_post_call_actions`. MCP round trips go to the in-process Demo CRM
through `builtin://demo`; models, telephony and Twilio's REST client are
fakes. Runs standalone (`python tests/test_mcp_call.py`) or under pytest. No
API key, no network. Names that don't exist yet are imported inside the
tests.

Seams relied on, beyond the spec's names: server rows are written with
`secrets = seal({"url": ..., "headers": {...}})`, and `builtin://demo` calls
`demo_server()` whenever a connection opens (so a test can stand in its own
`MCPServer`).
"""

from __future__ import annotations

import asyncio
import functools
import importlib
import logging
import os
import pkgutil
import sys
import tempfile
import time
import unicodedata
import uuid
from contextlib import asynccontextmanager, contextmanager, suppress
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import providers, storage  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402
from src.voiceagent.catalog import TokenUsage  # noqa: E402
from src.voiceagent.integrations.mocks import MockCalendar, MockControl, MockRecords, MockSpeaker  # noqa: E402
from src.voiceagent.models import CallOutcome, Disposition  # noqa: E402
from src.voiceagent.models import Contact as ContactModel  # noqa: E402
from src.voiceagent.orchestrator.events import bus  # noqa: E402
from src.voiceagent.voice import twilio_adapter as tw  # noqa: E402
from src.voiceagent.voice.session import CallSession  # noqa: E402

# Imported up front: a test call may import these lazily inside the request.
import src.voiceagent.postcall.extract  # noqa: E402, F401
import src.voiceagent.scoring  # noqa: E402, F401

logging.basicConfig(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)
for _noisy in ("mcp", "httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

GREETING = "Hi Asha, it's Smile Dental calling."
ANTHROPIC_ENV = dict(MODEL_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant-test-key")
OPENAI_SHAPE_ENV = dict(MODEL_PROVIDER="gemini", GEMINI_API_KEY="test-gemini-key")
SEALED = dict(SECRETS_KEY="test-secrets-key-1", AUTH_SECRET=None)
NO_LANGUAGE_PINS = dict(SARVAM_STT_LANGUAGE=None, SARVAM_TTS_LANGUAGE=None)
# The extraction model under ANTHROPIC_ENV; post-call actions run on it.
EXTRACTION_MODEL = "claude-opus-5"

AVAILABILITY = "demo__check_availability"
TICKET = "demo__create_ticket"
LOG_KEYS = {"at", "phase", "server", "tool", "arguments", "ok", "duration_ms", "excerpt", "error"}
INSTRUCTIONS = "Open a ticket summarising every booked appointment."

EXPECTED_CHECKING = {
    "en": "One moment, let me check that.",
    "hi": "एक सेकंड, ज़रा देख लेते हैं।",
    "ur": "एक लम्हा, ज़रा देख लेते हैं।",
    "hi-en": "Ek second, check kar lete hain.",
}

BOOKED = CallOutcome(
    disposition=Disposition.COMPLETED,
    summary="Asha booked a cleaning for Tuesday 29 September at 10:00.",
    needs_human_review=False,
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


_MISSING = object()


@contextmanager
def _patched(target, name: str, value):
    """Set an attribute for the block; restore (or remove) it afterwards."""
    saved = getattr(target, name, _MISSING)
    setattr(target, name, value)
    try:
        yield
    finally:
        if saved is _MISSING:
            with suppress(AttributeError):
                delattr(target, name)
        else:
            setattr(target, name, saved)


def _nfc(text: str) -> str:
    return unicodedata.normalize("NFC", text)


async def _until(predicate, timeout: float = 2.0, what: str = "condition") -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


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


@asynccontextmanager
async def _events():
    """Everything published on the bus while the block runs."""
    seen = []

    async def collect() -> None:
        async for event in bus.subscribe():
            seen.append(event)

    task = asyncio.create_task(collect())
    await asyncio.sleep(0)  # let it subscribe
    try:
        yield seen
    finally:
        await asyncio.sleep(0.05)  # let the last events arrive
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


async def _temp_db():
    path = Path(tempfile.mkdtemp()) / "mcp_call.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(storage.Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


# -- MCP servers ------------------------------------------------------------------

_SCHEMA = {"type": "object"}
DEMO_TOOLS = [
    {"name": "lookup_customer", "description": "Look up a customer by phone number.",
     "input_schema": {**_SCHEMA, "properties": {"phone": {"type": "string"}}, "required": ["phone"]}},
    {"name": "check_availability", "description": "Free appointment slots on a date (YYYY-MM-DD).",
     "input_schema": {**_SCHEMA, "properties": {"date": {"type": "string"}}, "required": ["date"]}},
    {"name": "book_appointment", "description": "Book an appointment.",
     "input_schema": {**_SCHEMA, "properties": {"name": {"type": "string"}, "date": {"type": "string"},
                                                "time": {"type": "string"}},
                      "required": ["name", "date", "time"]}},
    {"name": "create_ticket", "description": "Open a support ticket.",
     "input_schema": {**_SCHEMA, "properties": {"summary": {"type": "string"},
                                                "priority": {"type": "string", "default": "normal"}},
                      "required": ["summary"]}},
]


async def _add_server(sessions, slug: str, *, tools: list[dict], url: str = "builtin://demo"):
    """Save a healthy server row the way the API does: URL and headers sealed."""
    from src.voiceagent.mcp.secrets import seal

    async with sessions() as db:
        db.add(
            storage.McpServer(
                id=str(uuid.uuid4()),
                name=slug.replace("_", " ").title(),
                slug=slug,
                transport="builtin",
                host="builtin",
                secrets=seal({"url": url, "headers": {}}),
                enabled=True,
                status="ok",
                last_error=None,
                tools=list(tools),
            )
        )
        await db.commit()


class _Connections:
    def __init__(self) -> None:
        self.opened = 0
        self.closed = 0


def _test_crm(connections: _Connections):
    """An in-process MCP server that counts the sessions opened against it."""
    from mcp.server.mcpserver import MCPServer

    @asynccontextmanager
    async def lifespan(_server):
        connections.opened += 1
        try:
            yield {}
        finally:
            connections.closed += 1

    server = MCPServer("Test CRM", lifespan=lifespan)

    @server.tool()
    def ping() -> str:
        """Answer at once."""
        return "pong"

    return server


@contextmanager
def _serve_builtin_demo(factory):
    """Serve `builtin://demo` from `factory` instead of the Demo CRM (see core tests)."""
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


# -- model clients ------------------------------------------------------------------


class _Obj(SimpleNamespace):
    """An SDK response object: attribute access, plus pydantic's `model_dump()`."""

    def model_dump(self, **_):
        return {k: (v.model_dump() if isinstance(v, _Obj) else v) for k, v in vars(self).items()}


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _text_of(content) -> str:
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return " ".join(p if isinstance(p, str) else _text_of(_get(p, "text", "")) for p in content)
    return str(content)


class Say:
    """One scripted Anthropic response: streamed text, then optional tool calls."""

    def __init__(self, *deltas: str, tools=()) -> None:
        self.deltas = list(deltas)
        content = []
        if deltas:
            content.append(_Obj(type="text", text="".join(deltas), citations=None))
        for tool_use_id, name, arguments in tools:
            content.append(_Obj(type="tool_use", id=tool_use_id, name=name, input=arguments))
        self.final = _Obj(
            id="msg_test",
            type="message",
            role="assistant",
            content=content,
            stop_reason="tool_use" if tools else "end_turn",
            usage=_Obj(input_tokens=100, output_tokens=20, cache_read_input_tokens=0, cache_creation_input_tokens=0),
        )


class _AnthropicStream:
    def __init__(self, reply: Say) -> None:
        self._reply = reply

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    @property
    def text_stream(self):
        async def deltas():
            for delta in self._reply.deltas:
                await asyncio.sleep(0)
                yield delta

        return deltas()

    async def get_final_message(self):
        return self._reply.final


class FakeAnthropic:
    """Anthropic-shaped, with one script per role.

    The conversation streams (`messages.stream`); extraction uses
    `messages.parse`; post-call actions run on the extraction model, through
    `messages.create` or `messages.stream`. `script` entries are replies, or
    a function (request, number) -> reply.
    """

    def __init__(self, conversation=(), *, outcome: CallOutcome = BOOKED, post_call=(), fail=False) -> None:
        self._scripts = {"conversation": list(conversation), "post_call": post_call if callable(post_call) else list(post_call)}
        self.outcome = outcome
        self.fail = fail
        self.requests = {"conversation": [], "post_call": []}
        self.messages = _Obj(stream=self._stream, create=self._create, parse=self._parse)

    def _reply(self, role: str, kwargs: dict) -> Say:
        if self.fail:
            raise RuntimeError("the model provider is down")
        snapshot = dict(kwargs)
        snapshot["messages"] = list(kwargs.get("messages") or [])
        self.requests[role].append(snapshot)
        script = self._scripts[role]
        if callable(script):
            return script(snapshot, len(self.requests[role]))
        return script.pop(0) if script else Say("Okay.")

    def _role(self, kwargs: dict) -> str:
        return "post_call" if kwargs.get("model") == EXTRACTION_MODEL else "conversation"

    def _stream(self, **kwargs):
        return _AnthropicStream(self._reply(self._role(kwargs), kwargs))

    async def _create(self, **kwargs):
        return self._reply("post_call", kwargs).final

    async def _parse(self, **kwargs):
        return _Obj(parsed_output=self.outcome, stop_reason="end_turn", usage=None)

    async def close(self) -> None:
        pass


class Reply:
    """One scripted chat/completions response; `tool_calls` are (id, name, arguments_json)."""

    def __init__(self, *deltas: str, tool_calls=()) -> None:
        self.deltas = list(deltas)
        self.tool_calls = list(tool_calls)

    def completion(self):
        calls = [
            _Obj(id=call_id, type="function", function=_Obj(name=name, arguments=args))
            for call_id, name, args in self.tool_calls
        ]
        message = _Obj(role="assistant", content="".join(self.deltas) or None, tool_calls=calls or None, refusal=None)
        return _Obj(
            id="completion",
            choices=[_Obj(index=0, message=message, finish_reason="tool_calls" if calls else "stop")],
            usage=_Obj(prompt_tokens=100, completion_tokens=20, total_tokens=120),
        )

    def events(self):
        def chunk(content=None, tool_calls=None, finish_reason=None):
            delta = _Obj(role=None, content=content, tool_calls=tool_calls)
            return _Obj(id="c", choices=[_Obj(index=0, delta=delta, finish_reason=finish_reason)], usage=None)

        for delta in self.deltas:
            yield chunk(content=delta)
        for index, (call_id, name, args) in enumerate(self.tool_calls):
            fragment = _Obj(index=index, id=call_id, type="function", function=_Obj(name=name, arguments=args))
            yield chunk(tool_calls=[fragment])
        yield chunk(finish_reason="tool_calls" if self.tool_calls else "stop")
        yield _Obj(id="c", choices=[], usage=_Obj(prompt_tokens=100, completion_tokens=20, total_tokens=120))


class FakeChat:
    """chat/completions-shaped; streams when asked to, else returns a completion."""

    def __init__(self, script) -> None:
        self._script = list(script)
        self.requests: list[dict] = []
        self.chat = _Obj(completions=_Obj(create=self._create))

    async def _create(self, **kwargs):
        snapshot = dict(kwargs)
        snapshot["messages"] = list(kwargs.get("messages") or [])
        self.requests.append(snapshot)
        reply = self._script.pop(0) if self._script else Reply("Okay.")
        if not kwargs.get("stream"):
            return reply.completion()

        async def events():
            for event in reply.events():
                await asyncio.sleep(0)
                yield event

        return events()

    async def close(self) -> None:
        pass


class FakeToolbox:
    """The Toolbox protocol, recording every call. `fail` makes call() raise."""

    def __init__(self, tool_ids=(TICKET,), *, fail: bool = False) -> None:
        from src.voiceagent.mcp.toolbox import ToolSpec

        described = {f"demo__{t['name']}": t for t in DEMO_TOOLS}
        self._specs = [
            ToolSpec(id=t, description=described[t]["description"], input_schema=described[t]["input_schema"])
            for t in tool_ids
        ]
        self.fail = fail
        self.calls: list[tuple[str, dict]] = []

    def specs(self):
        return list(self._specs)

    async def call(self, tool_id: str, arguments: dict):
        from src.voiceagent.mcp.toolbox import ToolResult

        self.calls.append((tool_id, arguments))
        if self.fail:
            raise RuntimeError("a toolbox that breaks its promise")
        await asyncio.sleep(0)
        return ToolResult(ok=True, text="Ticket T-00017 opened.")


# -- session parts ----------------------------------------------------------------

PAUSE = object()  # stands for a ToolPause in a scripted reply


class ToolLLM:
    """Stands in for ConversationLLM: replies mix text chunks and tool pauses.

    After a pause is handed over, the "tool" runs for `tool_seconds` — and
    only once the session asks for more, which is when a real wrapper would
    run it. `log` records "tool ran" at that moment.
    """

    def __init__(self, replies, *, tool_seconds: float = 0.0, log: list | None = None) -> None:
        self._replies = list(replies)
        self._tool_seconds = tool_seconds
        self.log = log if log is not None else []
        self.end_requested = False
        self.recorded = []

    def record(self, turn) -> None:
        self.recorded.append(turn)

    async def generate(self):
        from src.voiceagent.llm import ToolPause

        self.end_requested = False
        items, end = self._replies.pop(0) if self._replies else (["Okay."], False)
        self.end_requested = end
        for item in items:
            await asyncio.sleep(0)
            if item is PAUSE:
                yield ToolPause(tools=(AVAILABILITY,))
                self.log.append("tool ran")
                await asyncio.sleep(self._tool_seconds)
            else:
                yield item


class FastSpeaker(MockSpeaker):
    """A streaming speaker: plays each chunk as it arrives. No flush()."""

    async def say(self, text: str) -> None:
        await asyncio.sleep(0)
        self.spoken.append(text)


class BufferedSpeaker:
    """A webhook-style speaker (like Twilio's): say() buffers, flush() plays a turn."""

    def __init__(self, log: list) -> None:
        self._buffer: list[str] = []
        self.played: list[tuple[str, str]] = []
        self.log = log

    async def say(self, text: str) -> None:
        self._buffer.append(text)

    async def flush(self) -> None:
        if self._buffer:
            self.played.append(("turn", " ".join(self._buffer)))
            self._buffer.clear()

    async def flush_interim(self) -> None:
        self.log.append("interim")
        self.played.append(("interim", " ".join(self._buffer)))
        self._buffer.clear()

    async def stop(self) -> str:
        self._buffer.clear()
        return ""


class LineListener:
    """Says each line in turn; then hangs up, or stays silent on the line."""

    def __init__(self, lines, *, hang_up_after: bool = True, gap: float = 0.01) -> None:
        self._lines = list(lines)
        self._hang_up_after = hang_up_after
        self._gap = gap

    async def utterances(self):
        for line in self._lines:
            await asyncio.sleep(self._gap)
            yield line
        if not self._hang_up_after:
            await asyncio.Event().wait()

    async def wait_for_speech_start(self) -> None:
        await asyncio.Event().wait()


async def _run_session(llm, speaker, *, on_event=None, lines=("Is Tuesday free?",)):
    session = CallSession(
        llm=llm,  # type: ignore[arg-type]
        listener=LineListener(lines),
        speaker=speaker,
        control=MockControl(),
        greeting=GREETING,
        max_duration_seconds=5,
        silence_timeout_seconds=2,
        on_event=on_event,
    )
    try:
        return await asyncio.wait_for(session.run(), 5)
    except asyncio.TimeoutError:
        raise AssertionError(f"the call did not end; so far: {[t.text for t in session.transcript]}") from None


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_tool_events_have_their_own_type_on_the_feed() -> None:
    from src.voiceagent.orchestrator.events import CALL_TOOL

    assert CALL_TOOL == "call.tool", CALL_TOOL


def test_the_checking_phrase_is_said_in_the_calls_language() -> None:
    """"Let me check" is never English on a Hindi call."""
    from src.voiceagent.voice.phrases import phrases_for

    got = {language: getattr(phrases_for(language), "checking", None) for language in EXPECTED_CHECKING}
    wrong = {k: v for k, v in got.items() if v is None or _nfc(v) != _nfc(EXPECTED_CHECKING[k])}
    assert not wrong, wrong


# ---------------------------------------------------------------------------
# The session during a tool pause
# ---------------------------------------------------------------------------


def test_the_agent_shows_as_working_while_a_tool_runs() -> None:
    """The console switches to "Using a tool" before the tool runs, and names it."""

    async def scenario():
        log: list = []
        states: list[dict] = []

        async def on_event(kind: str, payload: dict) -> None:
            if kind == "state":
                states.append(dict(payload))
                if payload.get("state") == "working":
                    log.append("working")

        llm = ToolLLM([(["One moment, let me check.", PAUSE, "Tuesday at ten is free."], False)], log=log)
        speaker = FastSpeaker()
        transcript = await _run_session(llm, speaker, on_event=on_event)
        return log, states, speaker, transcript, llm

    log, states, speaker, transcript, llm = asyncio.run(scenario())

    working = [s for s in states if s.get("state") == "working"]
    assert len(working) == 1, states
    assert list(working[0].get("tools") or []) == [AVAILABILITY], working[0]
    assert log.index("working") < log.index("tool ran"), log
    assert all(isinstance(s, str) for s in speaker.spoken), f"a pause reached the speaker: {speaker.spoken}"
    assert "One moment, let me check." in speaker.spoken and "Tuesday at ten is free." in speaker.spoken
    texts = [t.text for t in transcript]
    assert texts == [GREETING, "Is Tuesday free?", "One moment, let me check. Tuesday at ten is free."], texts
    agent_turns = [t for t in llm.recorded if t.role == "assistant"]
    assert len(agent_turns) == 2, [t.text for t in agent_turns]  # the greeting, then the one reply


def test_a_buffered_speaker_plays_what_was_said_before_the_tool_runs() -> None:
    """On Twilio the caller hears "let me check" at once, not after the tool; one turn is recorded."""

    async def scenario():
        log: list = []
        llm = ToolLLM(
            [(["One moment, let me check.", PAUSE, "Tuesday at ten is free."], False)],
            tool_seconds=0.5,
            log=log,
        )
        speaker = BufferedSpeaker(log)
        transcript = await _run_session(llm, speaker)
        return log, speaker, transcript

    log, speaker, transcript = asyncio.run(scenario())
    reply = [p for p in speaker.played if p != ("turn", GREETING)]
    assert reply == [("interim", "One moment, let me check."), ("turn", "Tuesday at ten is free.")], speaker.played
    assert log.index("interim") < log.index("tool ran"), log
    last = transcript[-1]
    assert last.text == "One moment, let me check. Tuesday at ten is free.", [t.text for t in transcript]
    assert last.latency_ms is not None and last.latency_ms < 400, (
        f"latency {last.latency_ms} ms: it should be measured to the interim audio, not the answer after the tool"
    )


def test_a_pause_before_anything_was_said_still_plays_an_interim() -> None:
    """Even when the model goes straight to a tool, the speaker is asked to cover the wait."""

    async def scenario():
        log: list = []
        llm = ToolLLM([([PAUSE, "Tuesday at ten is free."], False)], tool_seconds=0.05, log=log)
        speaker = BufferedSpeaker(log)
        transcript = await _run_session(llm, speaker)
        return log, speaker, transcript

    log, speaker, transcript = asyncio.run(scenario())
    assert ("interim", "") in speaker.played, speaker.played
    assert log.index("interim") < log.index("tool ran"), log
    assert transcript[-1].text == "Tuesday at ten is free.", [t.text for t in transcript]


# ---------------------------------------------------------------------------
# Twilio: the interim reply
# ---------------------------------------------------------------------------


@contextmanager
def _voice(provider: str):
    """Pin the voice provider — the package loads .env, which may say sarvam."""
    real = tw.VOICE_PROVIDER
    tw.VOICE_PROVIDER = provider
    try:
        yield
    finally:
        tw.VOICE_PROVIDER = real
        tw._audio_store.clear()
        tw._inflight.clear()


class _FakeCalls:
    def __init__(self) -> None:
        self.created: list[dict] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(sid=f"CA-test-{len(self.created)}")

    def __call__(self, sid: str):
        return SimpleNamespace(update=lambda **_: None)


def _twilio():
    """A real TwilioTelephony whose REST client is a fake. No server is started."""
    tele = tw.TwilioTelephony(
        account_sid="AC-test", auth_token="test-token", from_number="+15550000000",
        webhook_url="https://samvaad.test",
    )
    tele._client = SimpleNamespace(calls=_FakeCalls())
    return tele


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(transport=httpx.ASGITransport(app=tw._build_webhook_app()), base_url="http://test")


@dataclass
class _Call:
    room: str
    session: CallSession
    run: asyncio.Task


async def _start_twilio_call(http, room: str, *, llm, language: str, greeting: str = GREETING) -> _Call:
    """Prepare in `language`, dial, answer, start the session; returns once the greeting is fetched."""
    from src.voiceagent.voice.phrases import phrases_for

    tele = _twilio()
    tele.prepare_call(room, language=language, greeting=greeting)
    dialing = asyncio.create_task(tele.dial(phone_e164="+15550001111", room_name=room))
    await _until(lambda: room in tw._active_calls, what=f"{room} to be dialled")
    answering = asyncio.create_task(http.post(f"/twilio/voice/{room}", data={"CallSid": f"CA-{room}"}))
    listener, speaker, control, _sid = await asyncio.wait_for(dialing, 3)
    session = CallSession(
        llm=llm,  # type: ignore[arg-type]
        listener=listener,
        speaker=speaker,
        control=control,
        greeting=greeting,
        max_duration_seconds=15,
        silence_timeout_seconds=10,
        phrases=phrases_for(language),
    )
    run = asyncio.create_task(session.run())
    await asyncio.wait_for(answering, 5)
    return _Call(room, session, run)


async def _end_twilio_call(http, call: _Call):
    await http.post(f"/twilio/status/{call.room}", data={"CallStatus": "completed"})
    try:
        return await asyncio.wait_for(call.run, 5)
    finally:
        tw._active_calls.pop(call.room, None)


def test_twilio_plays_the_lead_in_then_collects_the_answer_while_the_tool_runs() -> None:
    """The caller hears "let me check" straight away; the answer follows without them saying anything."""
    lead, answer = "One moment, let me check.", "Tuesday at ten is free."

    async def scenario():
        room = "t-mcp-interim"
        async with _http() as http:
            llm = ToolLLM([([lead, PAUSE, answer], False)], tool_seconds=0.3)
            call = await _start_twilio_call(http, room, llm=llm, language="en")
            interim = (await http.post(f"/twilio/gather/{room}", data={"SpeechResult": "Is Tuesday free?"})).text
            final = (await http.post(f"/twilio/wait/{room}")).text
            transcript = await _end_twilio_call(http, call)
        return room, interim, final, transcript

    with _env(TWILIO_FILLER_AFTER_MS="0", **NO_LANGUAGE_PINS), _voice("twilio"):
        room, interim, final, transcript = asyncio.run(scenario())

    assert lead in interim and answer not in interim, interim
    assert "<Gather" not in interim, f"the interim listens for speech: {interim}"
    assert "<Redirect" in interim and f"/twilio/wait/{room}" in interim, interim
    assert "<Hangup" not in interim, interim
    assert answer in final and "<Gather" in final, final
    assert lead not in final, f"the lead-in was played twice: {final}"
    assert transcript[-1].text == f"{lead} {answer}", [t.text for t in transcript]


def test_twilio_says_the_checking_phrase_in_the_calls_language_when_nothing_was_said() -> None:
    """A Hindi caller hears a Hindi "let me check" while the tool runs, never silence."""
    from src.voiceagent.voice.phrases import phrases_for

    checking = phrases_for("hi").checking
    answer = "जी, मंगलवार दस बजे खाली है।"

    async def scenario():
        room = "t-mcp-checking-hi"
        async with _http() as http:
            llm = ToolLLM([([PAUSE, answer], False)], tool_seconds=0.3)
            call = await _start_twilio_call(
                http, room, llm=llm, language="hi", greeting="नमस्ते Asha, Smile Dental से बात कर रहे हैं।"
            )
            interim = (await http.post(f"/twilio/gather/{room}", data={"SpeechResult": "क्या मंगलवार खाली है?"})).text
            final = (await http.post(f"/twilio/wait/{room}")).text
            transcript = await _end_twilio_call(http, call)
        return room, interim, final, transcript

    with _env(TWILIO_FILLER_AFTER_MS="0", **NO_LANGUAGE_PINS), _voice("twilio"):
        room, interim, final, transcript = asyncio.run(scenario())

    assert f">{escape(checking)}</Say>" in interim, interim
    assert "<Gather" not in interim and f"/twilio/wait/{room}" in interim, interim
    assert answer in final and "<Gather" in final, final
    assert transcript[-1].text.endswith(answer), [t.text for t in transcript]


def test_twilio_interim_replies_are_marked_and_fall_back_to_the_checking_phrase() -> None:
    """flush_interim() queues what was said so far, or the call's "let me check" when nothing was."""
    from src.voiceagent.voice.phrases import phrases_for

    async def scenario():
        talking = tw._CallState(language="hi")
        speaker = tw.TwilioSpeaker(talking)
        await speaker.say("जी, एक मिनट।")
        await speaker.flush_interim()
        said = talking.response_queue.get_nowait()

        quiet = tw._CallState(language="hi")
        await tw.TwilioSpeaker(quiet).flush_interim()
        nothing_said = quiet.response_queue.get_nowait()
        return said, nothing_said

    with _voice("twilio"):
        said, nothing_said = asyncio.run(scenario())
    assert getattr(said, "interim", None) is True, said
    assert [text for text, _audio in said.segments] == ["जी, एक मिनट।"], said.segments
    assert getattr(nothing_said, "interim", None) is True, nothing_said
    assert [text for text, _audio in nothing_said.segments] == [phrases_for("hi").checking], nothing_said.segments


# ---------------------------------------------------------------------------
# Campaign calls: the tool log and the live feed
# ---------------------------------------------------------------------------


class _NoSuppression:
    async def suppress(self, *, contact_id: str, reason: str) -> None:
        pass


class _FakeTelephony:
    """Answers at once with the given listener and a fast speaker."""

    def __init__(self, listener) -> None:
        self.listener = listener
        self.speaker = FastSpeaker()
        self.control = MockControl()

    def prepare_call(self, room_name: str, *, language: str, greeting: str) -> None:
        pass

    async def dial(self, *, phone_e164: str, room_name: str):
        return self.listener, self.speaker, self.control, "CA-test"

    def get_call_state(self, room_name: str):
        return None


async def _seed_campaign(sessions, *, tools=(), post_tools=(), instructions: str = ""):
    async with sessions() as db:
        db.add(
            storage.Campaign(
                id="camp-1",
                name="Smile Dental",
                goal="Book Asha's next cleaning.",
                language="en",
                greeting="Hi {first_name}, it's {campaign_name} calling.",
                mcp_tools=list(tools),
                mcp_post_call_tools=list(post_tools),
                mcp_post_call_instructions=instructions,
            )
        )
        db.add(
            storage.Contact(
                id="ct-1", campaign_id="camp-1", full_name="Asha Rao",
                phone_e164="+15555550123", timezone="Asia/Kolkata",
            )
        )
        await db.commit()
    async with sessions() as db:
        return await db.get(storage.Contact, "ct-1"), await db.get(storage.Campaign, "camp-1")


async def _campaign_call(client, *, tools=(), post_tools=(), instructions="", listener=None, servers=None):
    """Place one campaign call through the real pipeline; return the saved row and its events."""
    from src.voiceagent.voice.pipeline import CallPipeline

    engine, sessions = await _temp_db()
    try:
        for slug, server_tools in (servers or [("demo", DEMO_TOOLS)]):
            await _add_server(sessions, slug, tools=server_tools)
        contact, campaign = await _seed_campaign(
            sessions, tools=tools, post_tools=post_tools, instructions=instructions
        )
        telephony = _FakeTelephony(listener or LineListener(["Is Tuesday free?"], hang_up_after=False))
        pipeline = CallPipeline(
            sessions, client, telephony,
            calendar=MockCalendar(), records=MockRecords(), suppression=_NoSuppression(), followups=False,
        )
        async with _events() as seen:
            await _within(8, pipeline.place_call(contact, campaign), "the campaign call")
        async with sessions() as db:
            call = (await db.execute(select(storage.Call))).scalars().one()
        events = [e for e in seen if (e.payload or {}).get("call_id") == call.id]
        return SimpleNamespace(call=call, events=events, telephony=telephony)
    finally:
        await engine.dispose()


def _availability_conversation():
    return [
        Say("Let me check that.", tools=[("toolu_1", AVAILABILITY, {"date": "2026-09-29"})]),
        Say("Tuesday at ten is free. ", "See you then, goodbye! [END_CALL]"),
    ]


def test_a_campaign_call_saves_its_tool_calls_and_streams_them_live() -> None:
    """Every tool call is on the call record and on the live feed, tagged with the call."""

    async def scenario():
        client = FakeAnthropic(_availability_conversation())
        result = await _campaign_call(client, tools=[AVAILABILITY])
        return result, client

    with _env(**ANTHROPIC_ENV, **SEALED):
        result, client = asyncio.run(scenario())

    log = result.call.tool_calls or []
    assert len(log) == 1, log
    entry = log[0]
    assert LOG_KEYS <= set(entry), f"missing {LOG_KEYS - set(entry)} in {entry}"
    assert entry["phase"] == "in_call", entry
    assert entry["tool"] in ("check_availability", AVAILABILITY), entry
    assert entry["server"], entry
    assert entry["arguments"] == {"date": "2026-09-29"}, entry
    assert entry["ok"] is True and not entry["error"], entry
    assert isinstance(entry["duration_ms"], int) and entry["duration_ms"] >= 0, entry
    assert entry["at"], entry
    excerpt = entry["excerpt"]
    assert isinstance(excerpt, str) and excerpt.strip() and len(excerpt) <= 300, entry

    # The model got the Demo CRM's real answer, and the excerpt is its start.
    result_block = client.requests["conversation"][1]["messages"][-1]["content"][0]
    returned = _text_of(_get(result_block, "content"))
    assert returned.startswith(excerpt.strip()[:50]), (excerpt, returned)

    tool_events = [e for e in result.events if e.type == "call.tool"]
    assert [e.payload.get("status") for e in tool_events] == ["started", "ok"], [e.payload for e in tool_events]
    for event in tool_events:
        assert event.payload["call_id"] == result.call.id, event.payload
        assert event.payload.get("phase") == "in_call", event.payload
        assert event.payload.get("tool") in ("check_availability", AVAILABILITY), event.payload

    # The transcript holds speech only.
    texts = [t["text"] for t in result.call.transcript]
    assert texts[-1] == "Let me check that. Tuesday at ten is free. See you then, goodbye!", texts
    assert not any("2026-09-29" in t or "check_availability" in t for t in texts), texts


def test_a_campaign_calls_tool_connections_open_before_it_is_needed_and_close_after() -> None:
    """Warmed while dialling, so the first "let me check" costs no handshake; nothing is left open."""
    connections = _Connections()

    class WaitsForWarmup(LineListener):
        """Speaks once the tool server is connected (or after a second)."""

        warm_when_spoken: int | None = None

        async def utterances(self):
            loop = asyncio.get_running_loop()
            deadline = loop.time() + 1.0
            while connections.opened < 1 and loop.time() < deadline:
                await asyncio.sleep(0.01)
            self.warm_when_spoken = connections.opened
            async for line in super().utterances():
                yield line

    async def scenario():
        listener = WaitsForWarmup(["Can I book Tuesday?"], hang_up_after=False)
        client = FakeAnthropic([Say("Yes, you're booked. ", "Goodbye! [END_CALL]")])
        with _serve_builtin_demo(functools.partial(_test_crm, connections)):
            await _campaign_call(
                client,
                tools=["test_crm__ping"],
                listener=listener,
                servers=[("test_crm", [{"name": "ping", "description": "Answer at once.",
                                        "input_schema": {**_SCHEMA, "properties": {}}}])],
            )
        return listener

    with _env(**ANTHROPIC_ENV, **SEALED):
        listener = asyncio.run(scenario())
    assert listener.warm_when_spoken == 1, (
        f"{listener.warm_when_spoken} connections open when the person first spoke; warm() should have run while dialling"
    )
    assert connections.closed == connections.opened == 1, vars(connections)


# -- test calls from the console -------------------------------------------------


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
        app_module.SessionLocal = sessions
    try:
        with _env(ADMIN_PASSWORD=None):
            async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://test") as http:
                yield http, sessions
    finally:
        app.dependency_overrides.pop(storage.get_session, None)
        storage.SessionLocal = saved[0]
        if saved[1] is not None:
            app_module.SessionLocal = saved[1]
        await engine.dispose()


TEST_CALL_ENV = dict(
    **ANTHROPIC_ENV,
    **SEALED,
    TELEPHONY="twilio",
    TWILIO_ACCOUNT_SID=None,
    TWILIO_AUTH_TOKEN=None,
    TWILIO_PHONE_NUMBER=None,
    TWILIO_WHATSAPP_FROM=None,
    TELNYX_API_KEY=None,
    TELNYX_PHONE_NUMBER=None,
    ADMIN_PASSWORD=None,
)


def test_a_test_call_saves_its_tool_calls_and_streams_them_live() -> None:
    """Trying a campaign from the console shows and saves its tool calls like a real call."""

    async def scenario():
        client = FakeAnthropic(_availability_conversation())
        telephony = _FakeTelephony(LineListener(["Is Tuesday free?"], hang_up_after=False))
        factory = lambda *args, **kwargs: client  # noqa: E731
        async with _api() as (http, sessions), _events() as seen:
            await _add_server(sessions, "demo", tools=DEMO_TOOLS)
            await _seed_campaign(sessions, tools=[AVAILABILITY])
            with _patched(app_module, "_test_call_telephony", lambda: telephony), \
                    _patched(app_module, "make_client", factory), _patched(providers, "make_client", factory):
                response = await asyncio.wait_for(
                    http.post("/api/test-call", json={
                        "campaign_id": "camp-1", "phone_number": "+15555550123", "contact_name": "Asha Rao",
                        "send_sms": False, "send_whatsapp": False,
                    }),
                    5,
                )
                assert response.status_code == 202, (response.status_code, response.text)
                call_id = response.json()["call_id"]
                await _until(
                    lambda: any(e.type == "call.extracted" and e.payload.get("call_id") == call_id for e in seen),
                    8, "the test call to finish",
                )
            async with sessions() as db:
                row = await db.get(storage.Call, call_id)
            events = [e for e in seen if (e.payload or {}).get("call_id") == call_id]
        return row, events

    with _env(**TEST_CALL_ENV):
        row, events = asyncio.run(scenario())

    log = row.tool_calls or []
    assert [(e["phase"], e["ok"]) for e in log] == [("in_call", True)], log
    assert log[0]["arguments"] == {"date": "2026-09-29"}, log
    statuses = [e.payload.get("status") for e in events if e.type == "call.tool"]
    assert statuses == ["started", "ok"], statuses


# ---------------------------------------------------------------------------
# After the call: run_post_call_actions
# ---------------------------------------------------------------------------


class _Contact(ContactModel):
    """A contact that reads like both the ORM row and the prompt model."""

    id: str = "ct-1"


def _campaign(post_tools=(TICKET,), instructions: str = INSTRUCTIONS):
    return storage.Campaign(
        id="camp-1",
        name="Smile Dental",
        goal="Book Asha's next cleaning.",
        language="en",
        greeting="Hi {first_name}, it's {campaign_name} calling.",
        fields_to_collect=[],
        constraints=[],
        scorecard=[],
        extra_instructions="",
        mcp_tools=[],
        mcp_post_call_tools=list(post_tools),
        mcp_post_call_instructions=instructions,
    )


async def _post_call(client, *, outcome=BOOKED, toolbox=None, post_tools=(TICKET,), model=EXTRACTION_MODEL):
    from src.voiceagent.postcall.mcp_actions import run_post_call_actions

    return await _within(
        5,
        run_post_call_actions(
            client,
            model=model,
            effort="high",
            campaign=_campaign(post_tools),
            contact=_Contact(contact_id="ct-1", full_name="Asha Rao", phone_e164="+15555550123",
                             timezone="Asia/Kolkata"),
            outcome=outcome,
            toolbox=toolbox if toolbox is not None else FakeToolbox(),
            usage=TokenUsage(),
        ),
        "post-call actions",
    )


def test_post_call_actions_write_the_outcome_back_with_the_allowed_tools() -> None:
    """After a good call the agent records it in the user's system, following their instruction."""
    arguments = {"summary": "Asha Rao booked a cleaning for Tuesday 29 September, 10:00."}

    async def scenario():
        client = FakeAnthropic(post_call=[Say(tools=[("toolu_p1", TICKET, arguments)]), Say("Recorded.")])
        box = FakeToolbox()
        entries = await _post_call(client, toolbox=box)
        return entries, box, client.requests["post_call"]

    with _env(**ANTHROPIC_ENV):
        entries, box, requests = asyncio.run(scenario())

    assert box.calls == [(TICKET, arguments)], box.calls
    assert isinstance(entries, list) and len(entries) == 1, entries
    entry = entries[0]
    assert LOG_KEYS <= set(entry), f"missing {LOG_KEYS - set(entry)} in {entry}"
    assert entry["phase"] == "post_call" and entry["ok"] is True, entry
    assert entry["tool"] in (TICKET, "create_ticket") and entry["arguments"] == arguments, entry

    first = requests[0]
    assert first.get("model") == EXTRACTION_MODEL, first.get("model")
    assert [t["name"] for t in first.get("tools") or []] == [TICKET], first.get("tools")
    sent = repr(first)
    assert INSTRUCTIONS in sent, "the campaign's post-call instructions never reached the model"
    assert BOOKED.summary in sent, "the call's outcome never reached the model"
    assert len(requests) == 2, f"{len(requests)} requests; the loop should stop once the model answers"


def test_post_call_actions_work_on_chat_completions_too() -> None:
    """Gemini and OpenAI workspaces get post-call actions in their function-calling shape."""
    arguments = '{"summary": "Asha booked Tuesday 10:00."}'

    async def scenario():
        client = FakeChat([Reply(tool_calls=[("call_p1", TICKET, arguments)]), Reply("Recorded.")])
        box = FakeToolbox()
        entries = await _post_call(client, toolbox=box, model="gemini-3-pro")
        return entries, box, client.requests

    with _env(**OPENAI_SHAPE_ENV):
        entries, box, requests = asyncio.run(scenario())

    assert box.calls == [(TICKET, {"summary": "Asha booked Tuesday 10:00."})], box.calls
    assert [(e["phase"], e["ok"]) for e in entries] == [("post_call", True)], entries
    assert [t["function"]["name"] for t in requests[0].get("tools") or []] == [TICKET], requests[0].get("tools")
    tool_messages = [m for m in requests[1]["messages"] if _get(m, "role") == "tool"]
    assert [_get(m, "tool_call_id") for m in tool_messages] == ["call_p1"], requests[1]["messages"]


def test_post_call_actions_are_skipped_when_the_call_is_held_for_review() -> None:
    """Nothing is written back from a call a human still has to check."""
    held = BOOKED.model_copy(update={"needs_human_review": True, "review_reason": "Unclear time."})

    async def scenario():
        client = FakeAnthropic(post_call=[Say(tools=[("toolu_p1", TICKET, {"summary": "x"})]), Say("Done.")])
        box = FakeToolbox()
        entries = await _post_call(client, outcome=held, toolbox=box)
        return entries, box, client.requests["post_call"]

    with _env(**ANTHROPIC_ENV):
        entries, box, requests = asyncio.run(scenario())
    assert entries == [] and box.calls == [] and requests == [], (entries, box.calls, len(requests))


def test_post_call_actions_are_skipped_for_calls_that_reached_nobody_or_failed() -> None:
    """No CRM notes for voicemails, no-answers, wrong numbers or failed calls — but a "no thanks" is recorded."""

    async def scenario(disposition: Disposition):
        outcome = BOOKED.model_copy(update={"disposition": disposition})
        client = FakeAnthropic(post_call=[Say(tools=[("toolu_p1", TICKET, {"summary": "x"})]), Say("Done.")])
        box = FakeToolbox()
        entries = await _post_call(client, outcome=outcome, toolbox=box)
        return len(client.requests["post_call"]), len(box.calls), len(entries)

    skipped = (Disposition.NO_ANSWER, Disposition.VOICEMAIL, Disposition.WRONG_NUMBER, Disposition.FAILED)
    with _env(**ANTHROPIC_ENV):
        runs = {d.value: asyncio.run(scenario(d)) for d in (*skipped, Disposition.DECLINED)}
    assert all(runs[d.value] == (0, 0, 0) for d in skipped), runs
    assert runs["declined"][0] >= 1 and runs["declined"][1] == 1, runs


def test_post_call_actions_need_post_call_tools() -> None:
    """A campaign that chose no after-call tools costs no model call."""

    async def scenario():
        client = FakeAnthropic(post_call=[Say("Nothing to do.")])
        entries = await _post_call(client, post_tools=(), toolbox=FakeToolbox(tool_ids=()))
        return entries, client.requests["post_call"]

    with _env(**ANTHROPIC_ENV):
        entries, requests = asyncio.run(scenario())
    assert entries == [] and requests == [], (entries, requests)


def test_post_call_actions_never_raise() -> None:
    """A provider outage or a broken toolbox after the call never loses the call's outcome."""

    async def scenario():
        down = await _post_call(FakeAnthropic(fail=True))
        broken_box = FakeToolbox(fail=True)
        broken = await _post_call(
            FakeAnthropic(post_call=[Say(tools=[("toolu_p1", TICKET, {"summary": "x"})]), Say("Done.")]),
            toolbox=broken_box,
        )
        return down, broken, broken_box

    with _env(**ANTHROPIC_ENV):
        down, broken, broken_box = asyncio.run(scenario())
    assert isinstance(down, list), down
    assert isinstance(broken, list) and broken_box.calls, (broken, broken_box.calls)


def test_post_call_actions_stop_after_five_tool_calls() -> None:
    """A model stuck in a loop can't spray a CRM with writes."""

    def always(request, number):
        return Say(tools=[(f"toolu_{number}", TICKET, {"summary": f"note {number}"})]) if number <= 12 else Say("Done.")

    async def scenario():
        box = FakeToolbox()
        entries = await _post_call(FakeAnthropic(post_call=always), toolbox=box)
        return entries, box

    with _env(**ANTHROPIC_ENV):
        entries, box = asyncio.run(scenario())
    assert 1 <= len(box.calls) <= 5, f"{len(box.calls)} tool calls after the call"
    assert len(entries) == len(box.calls), (entries, box.calls)


# -- through the pipeline ---------------------------------------------------------


def test_a_campaign_call_runs_its_post_call_actions_and_records_them() -> None:
    """The call record shows what was written back, and dispatch says so."""
    arguments = {"summary": "Asha confirmed her cleaning on Tuesday at ten."}

    async def scenario():
        client = FakeAnthropic(
            [Say("Great, see you Tuesday. ", "Goodbye! [END_CALL]")],
            post_call=[Say(tools=[("toolu_p1", TICKET, arguments)]), Say("Recorded.")],
        )
        result = await _campaign_call(client, post_tools=[TICKET], instructions=INSTRUCTIONS)
        return result, client

    with _env(**ANTHROPIC_ENV, **SEALED):
        result, client = asyncio.run(scenario())

    log = result.call.tool_calls or []
    after = [e for e in log if e.get("phase") == "post_call"]
    assert len(after) == 1, log
    assert after[0]["tool"] in ("create_ticket", TICKET) and after[0]["ok"] is True, after[0]
    assert after[0]["arguments"] == arguments, after[0]
    dispatch = result.call.dispatch_result or {}
    assert dispatch.get("mcp_actions"), dispatch
    assert "mcp_actions_skipped" not in dispatch, dispatch
    assert client.requests["post_call"], "post-call actions did not run on the extraction model"


def test_a_call_held_for_review_skips_post_call_actions_and_says_why() -> None:
    """A reviewer can see that nothing was written back, and why."""
    held = BOOKED.model_copy(update={"needs_human_review": True, "review_reason": "The time was unclear."})

    async def scenario():
        client = FakeAnthropic(
            [Say("Great, see you Tuesday. ", "Goodbye! [END_CALL]")],
            outcome=held,
            post_call=[Say(tools=[("toolu_p1", TICKET, {"summary": "x"})]), Say("Recorded.")],
        )
        result = await _campaign_call(client, post_tools=[TICKET], instructions=INSTRUCTIONS)
        return result, client

    with _env(**ANTHROPIC_ENV, **SEALED):
        result, client = asyncio.run(scenario())

    dispatch = result.call.dispatch_result or {}
    assert dispatch.get("mcp_actions_skipped") == "held for review", dispatch
    assert not [e for e in (result.call.tool_calls or []) if e.get("phase") == "post_call"], result.call.tool_calls
    assert client.requests["post_call"] == [], "the model was asked to write back a held call"


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
