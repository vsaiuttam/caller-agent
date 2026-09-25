"""Real-time call streaming: watching a call happen, and steering it.

The console shows a call as it happens: the agent's state, each turn as it
is said, and an operator can whisper guidance or end the call. This covers
the session's observer hook, the event bus contract, the in-process registry
of live calls, the whisper/hangup endpoints, and a campaign call streaming
its events end to end.

Runs standalone (`python tests/test_live_streaming.py`) or under pytest. No
API key, no network, no real Twilio. Names that don't exist yet are imported
inside the tests, so each test reports its own result.
"""

from __future__ import annotations

import asyncio
import logging
import os
import sys
import tempfile
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402
from src.voiceagent.integrations.mocks import (  # noqa: E402
    MockCalendar,
    MockControl,
    MockRecords,
    MockSpeaker,
)
from src.voiceagent.models import CallContext, CallOutcome, Contact, Disposition  # noqa: E402
from src.voiceagent.orchestrator.events import bus  # noqa: E402
from src.voiceagent.voice.session import CallSession  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)

GREETING = "Hi Asha, it's Smile Dental calling."
STATES = {"speaking", "listening", "thinking", "ended"}


# ---------------------------------------------------------------------------
# Fakes
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


ANTHROPIC_ENV = dict(MODEL_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant-test-key")
OPENAI_SHAPE_ENV = dict(MODEL_PROVIDER="gemini", GEMINI_API_KEY="test-gemini-key")


class FakeLLM:
    """Stands in for ConversationLLM. Each reply is (chunks, end_requested)."""

    def __init__(self, replies: list[tuple[list[str], bool]] | None = None) -> None:
        self._replies = list(replies or [])
        self.end_requested = False
        self.recorded = []
        self.guidance: list[str] = []

    def record(self, turn) -> None:
        self.recorded.append(turn)

    def add_guidance(self, text: str) -> None:
        self.guidance.append(text)

    async def generate(self):
        self.end_requested = False
        chunks, end = self._replies.pop(0) if self._replies else (["Okay."], False)
        self.end_requested = end
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk


class FastSpeaker(MockSpeaker):
    """MockSpeaker's contract without its per-character sleeps (slow on Windows)."""

    async def say(self, text: str) -> None:
        await asyncio.sleep(0)
        self.spoken.append(text)


class LineListener:
    """Says each line in turn; then hangs up, or stays silent on the line."""

    def __init__(self, lines: list[str], *, hang_up_after: bool = True) -> None:
        self._lines = list(lines)
        self._hang_up_after = hang_up_after

    async def utterances(self):
        for line in self._lines:
            await asyncio.sleep(0.01)
            yield line
        if not self._hang_up_after:
            await asyncio.Event().wait()

    async def wait_for_speech_start(self) -> None:
        await asyncio.Event().wait()


def _session(llm=None, listener=None, **kwargs) -> CallSession:
    kwargs.setdefault("max_duration_seconds", 5)
    kwargs.setdefault("silence_timeout_seconds", 0.5)
    return CallSession(
        llm=llm or FakeLLM(),  # type: ignore[arg-type]
        listener=listener or LineListener([]),
        speaker=kwargs.pop("speaker", None) or FastSpeaker(),
        control=kwargs.pop("control", None) or MockControl(),
        greeting=GREETING,
        **kwargs,
    )


async def _run(session: CallSession, timeout: float = 3.0):
    try:
        return await asyncio.wait_for(session.run(), timeout)
    except asyncio.TimeoutError:
        texts = [t.text for t in session.transcript]
        raise AssertionError(f"the call did not end within {timeout}s; so far: {texts}") from None


async def _until(predicate, timeout: float = 2.0, what: str = "condition") -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


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
        task.cancel()
        with suppress(asyncio.CancelledError):
            await task


def _for_call(seen, call_id: str) -> list:
    return [e for e in seen if (e.payload or {}).get("call_id") == call_id]


# -- model clients ------------------------------------------------------------


class _FakeStream:
    def __init__(self, deltas: list[str]) -> None:
        self._deltas = deltas

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    @property
    def text_stream(self):
        async def deltas():
            for delta in self._deltas:
                await asyncio.sleep(0)
                yield delta

        return deltas()

    async def get_final_message(self):
        return SimpleNamespace(usage=None)


class _FakeMessages:
    def __init__(self, owner: "FakeAnthropicClient") -> None:
        self._owner = owner

    def stream(self, **kwargs):
        self._owner.requests.append(kwargs)
        deltas = self._owner.replies.pop(0) if self._owner.replies else ["Okay."]
        return _FakeStream(deltas)

    async def parse(self, **kwargs):
        return SimpleNamespace(parsed_output=self._owner.outcome, stop_reason="end_turn", usage=None)


class FakeAnthropicClient:
    """Anthropic-shaped: `messages.stream` for the call, `messages.parse` for extraction."""

    def __init__(self, replies: list[list[str]], outcome: CallOutcome | None = None) -> None:
        self.replies = [list(r) for r in replies]
        self.outcome = outcome
        self.requests: list[dict] = []
        self.messages = _FakeMessages(self)

    async def close(self) -> None:
        pass


class _FakeCompletions:
    def __init__(self, replies: list[list[str]]) -> None:
        self.replies = [list(r) for r in replies]
        self.requests: list[dict] = []

    async def create(self, **kwargs):
        self.requests.append(kwargs)
        deltas = self.replies.pop(0) if self.replies else ["Okay."]

        async def events():
            for delta in deltas:
                await asyncio.sleep(0)
                yield SimpleNamespace(
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=delta))], usage=None
                )

        return events()


class FakeOpenAIClient:
    def __init__(self, replies: list[list[str]]) -> None:
        self.completions = _FakeCompletions(replies)
        self.chat = SimpleNamespace(completions=self.completions)

    async def close(self) -> None:
        pass


def _llm(client):
    from src.voiceagent.llm import ConversationLLM

    return ConversationLLM(
        client,
        contact=Contact(
            contact_id="c1", full_name="Asha Rao", phone_e164="+919800000000", timezone="Asia/Kolkata"
        ),
        context=CallContext(campaign_id="camp-1", goal="Confirm Tuesday's cleaning appointment."),
    )


async def _drain(llm) -> list[str]:
    return [chunk async for chunk in llm.generate()]


# -- database + API -------------------------------------------------------------


async def _temp_db():
    path = Path(tempfile.mkdtemp()) / "live_streaming.db"
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
        with _env(ADMIN_PASSWORD=None):
            async with httpx.AsyncClient(
                transport=httpx.ASGITransport(app=app), base_url="http://test"
            ) as http:
                yield http, sessions
    finally:
        app.dependency_overrides.pop(storage.get_session, None)
        storage.SessionLocal = saved[0]
        if saved[1] is not None:
            app_module.SessionLocal = saved[1]
        await engine.dispose()


@contextmanager
def _live(call_id: str, session: CallSession, **fields):
    """Register a call in the live registry for the duration of the block."""
    from src.voiceagent.voice import live_registry

    values = dict(
        room_name=f"room-{call_id}", campaign_id="camp-1", contact_name="Asha Rao", is_test=True
    )
    values.update(fields)
    live_registry.register(call_id, session=session, **values)
    try:
        yield live_registry.get(call_id)
    finally:
        live_registry.unregister(call_id)


# ---------------------------------------------------------------------------
# Event bus contract
# ---------------------------------------------------------------------------


def test_new_event_types_have_their_documented_names() -> None:
    """The frontend filters on these strings; a typo is a silent blank screen."""
    from src.voiceagent.orchestrator import events

    assert events.CALL_TURN == "call.turn"
    assert events.CALL_STATE == "call.state"
    assert events.CALL_FAILED == "call.failed"
    assert events.CALL_WHISPER == "call.whisper"
    # The existing ones keep their names.
    assert events.CALL_STARTED == "call.started"
    assert events.CALL_CONNECTED == "call.connected"
    assert events.CALL_ENDED == "call.ended"
    assert events.CALL_EXTRACTED == "call.extracted"


# ---------------------------------------------------------------------------
# Session observer (on_event)
# ---------------------------------------------------------------------------


def _index(events, start: int, predicate) -> int:
    for i in range(start, len(events)):
        if predicate(events[i]):
            return i
    return -1


def test_on_event_reports_states_and_turns_in_order() -> None:
    """The live console animates from these: speaking, listening, thinking, ended."""

    async def scenario():
        seen: list[tuple[str, dict]] = []

        async def on_event(kind: str, payload: dict) -> None:
            seen.append((kind, dict(payload)))

        session = _session(
            FakeLLM([(["Great, see you Tuesday."], False)]),
            LineListener(["Yes, Tuesday works."]),
            on_event=on_event,
        )
        return await _run(session), seen

    transcript, seen = asyncio.run(scenario())
    assert seen, "on_event was never called"
    assert {kind for kind, _ in seen} <= {"turn", "state"}, seen

    states = [p.get("state") for kind, p in seen if kind == "state"]
    assert set(states) <= STATES, states
    assert seen[-1] == ("state", {"state": "ended"}), seen[-1]
    assert states.count("ended") == 1, states

    # Every recorded turn, in order, with the documented fields.
    turns = [p for kind, p in seen if kind == "turn"]
    assert [(p["role"], p["text"], p["latency_ms"]) for p in turns] == [
        (t.role, t.text, t.latency_ms) for t in transcript
    ], turns
    for p in turns:
        assert {"role", "text", "latency_ms", "at"} <= set(p), p
        at = datetime.fromisoformat(p["at"])
        assert at.utcoffset() == timedelta(0), f"`at` must be UTC: {p['at']}"

    def is_state(name):
        return lambda e: e == ("state", {"state": name})

    def is_turn(role):
        return lambda e: e[0] == "turn" and e[1]["role"] == role

    greeting_turn = _index(seen, 0, is_turn("assistant"))
    user_turn = _index(seen, 0, is_turn("user"))
    reply_turn = _index(seen, user_turn + 1, is_turn("assistant"))
    assert 0 <= greeting_turn < user_turn < reply_turn, seen

    speaking = _index(seen, 0, is_state("speaking"))
    assert 0 <= speaking < greeting_turn, "no 'speaking' before the greeting was recorded"
    listening = _index(seen, speaking + 1, is_state("listening"))
    assert speaking < listening < user_turn, "no 'listening' between the greeting and the person"
    thinking = _index(seen, listening + 1, is_state("thinking"))
    assert listening < thinking < reply_turn, "no 'thinking' after the person spoke"
    replying = _index(seen, thinking + 1, is_state("speaking"))
    assert thinking < replying < reply_turn, "no 'speaking' for the reply"


def test_a_broken_observer_never_breaks_the_call() -> None:
    """A crashing console must not drop a real person's call."""

    async def scenario():
        calls = []

        async def on_event(kind: str, payload: dict) -> None:
            calls.append(kind)
            raise RuntimeError("observer bug")

        control = MockControl()
        session = _session(
            FakeLLM([(["Great, see you Tuesday."], False)]),
            LineListener(["Yes, Tuesday works."]),
            control=control,
            on_event=on_event,
        )
        transcript = await _run(session)
        return transcript, calls, control

    transcript, calls, control = asyncio.run(scenario())
    assert calls, "on_event was never called"
    assert [t.text for t in transcript] == [GREETING, "Yes, Tuesday works.", "Great, see you Tuesday."]
    assert control.hung_up


# ---------------------------------------------------------------------------
# Live registry
# ---------------------------------------------------------------------------


def test_the_live_registry_tracks_a_call_until_it_is_unregistered() -> None:
    from src.voiceagent.voice import live_registry

    async def scenario() -> None:
        session = _session()
        live_registry.register(
            "call-reg-1",
            session=session,
            room_name="room-reg-1",
            campaign_id="camp-1",
            contact_name="Asha Rao",
            is_test=True,
        )
        try:
            live = live_registry.get("call-reg-1")
            assert live is not None
            assert live.session is session
            assert (live.room_name, live.campaign_id, live.contact_name, live.is_test) == (
                "room-reg-1",
                "camp-1",
                "Asha Rao",
                True,
            )
            assert live.started_at is not None
            assert hasattr(live, "state") and hasattr(live, "turns")
            assert any(item is live for item in live_registry.all())

            live_registry.set_state("call-reg-1", "speaking")
            assert live_registry.get("call-reg-1").state == "speaking"
        finally:
            live_registry.unregister("call-reg-1")

        assert live_registry.get("call-reg-1") is None
        assert not any(item.room_name == "room-reg-1" for item in live_registry.all())
        assert live_registry.get("never-registered") is None

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Whisper guidance reaches the model
# ---------------------------------------------------------------------------


def test_guidance_is_an_uncached_system_block_after_the_cached_ones() -> None:
    """Anthropic: the two cached blocks stay byte-identical, so the cache still hits."""

    async def scenario() -> None:
        client = FakeAnthropicClient([["Sure."], ["Of course."], ["Right."]])
        llm = _llm(client)
        await _drain(llm)
        before = client.requests[0]["system"]
        assert len(before) == 2, before

        llm.add_guidance("Offer Thursday at ten instead.")
        await _drain(llm)
        await _drain(llm)
        for request in client.requests[1:]:
            system = request["system"]
            assert len(system) == 3, system
            assert system[:2] == before, "the cached blocks changed"
            assert "Offer Thursday at ten instead." in system[2]["text"], system[2]
            assert "cache_control" not in system[2], system[2]

    with _env(**ANTHROPIC_ENV):
        asyncio.run(scenario())


def test_guidance_is_appended_to_the_system_text_on_chat_completions() -> None:
    async def scenario() -> None:
        client = FakeOpenAIClient([["Sure."], ["Of course."], ["Right."]])
        llm = _llm(client)
        await _drain(llm)
        requests = client.completions.requests
        original = requests[0]["messages"][0]
        assert original["role"] == "system"

        llm.add_guidance("Offer Thursday at ten instead.")
        await _drain(llm)
        await _drain(llm)
        for request in requests[1:]:
            system = request["messages"][0]
            assert system["role"] == "system"
            assert system["content"].startswith(original["content"]), "the persona must still lead"
            assert "Offer Thursday at ten instead." in system["content"]

    with _env(**OPENAI_SHAPE_ENV):
        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Live endpoints
# ---------------------------------------------------------------------------


def test_live_calls_endpoint_is_empty_when_nothing_is_live() -> None:
    from src.voiceagent.voice import live_registry

    async def scenario() -> None:
        assert live_registry.all() == [], "a previous test left a call registered"
        async with _api() as (http, _):
            r = await http.get("/api/calls/live")
            assert r.status_code == 200, (r.status_code, r.text)
            assert r.json() == [], r.json()

    asyncio.run(scenario())


def test_live_calls_endpoint_lists_a_live_call() -> None:
    async def scenario() -> None:
        async with _api() as (http, _):
            with _live("call-live-1", _session(), room_name="room-live-1", is_test=True):
                r = await http.get("/api/calls/live")
            assert r.status_code == 200, (r.status_code, r.text)
            items = r.json()
            assert len(items) == 1, items
            item = items[0]
            expected = {
                "call_id", "room_name", "campaign_id", "contact_name",
                "started_at", "state", "is_test", "turns",
            }
            assert expected <= set(item), item
            assert item["call_id"] == "call-live-1"
            assert item["room_name"] == "room-live-1"
            assert item["campaign_id"] == "camp-1"
            assert item["contact_name"] == "Asha Rao"
            assert item["is_test"] is True
            datetime.fromisoformat(item["started_at"])

    asyncio.run(scenario())


def test_hangup_and_whisper_need_a_call_that_is_live_here() -> None:
    """A finished call, or one this process isn't running, is a 404 — not a crash."""

    async def scenario() -> None:
        async with _api() as (http, sessions):
            async with sessions() as db:
                db.add(storage.Campaign(id="camp-1", name="Smile Dental", goal="Confirm."))
                db.add(
                    storage.Contact(
                        id="ct-1", campaign_id="camp-1", full_name="Asha Rao", phone_e164="+15555550100"
                    )
                )
                db.add(
                    storage.Call(
                        id="call-done",
                        contact_id="ct-1",
                        campaign_id="camp-1",
                        status=storage.CallStatus.COMPLETED,
                    )
                )
                await db.commit()

            with _live("call-live-2", _session()):
                for call_id in ("call-done", "no-such-call"):
                    r = await http.post(f"/api/calls/{call_id}/hangup")
                    assert r.status_code == 404, (call_id, r.status_code, r.text)
                    r = await http.post(f"/api/calls/{call_id}/whisper", json={"text": "Offer Friday."})
                    assert r.status_code == 404, (call_id, r.status_code, r.text)

                # The same endpoints do exist for a live call.
                r = await http.post("/api/calls/call-live-2/whisper", json={"text": "Offer Friday."})
                assert r.status_code == 202, (r.status_code, r.text)
                r = await http.post("/api/calls/call-live-2/hangup")
                assert r.status_code == 202, (r.status_code, r.text)

    asyncio.run(scenario())


def test_hangup_asks_the_live_session_to_wrap_up() -> None:
    """The operator's End call: the session says goodbye, rather than the line dropping."""

    async def scenario() -> None:
        session = _session()
        asked = []
        original = getattr(session, "request_end", None)

        def spy():
            asked.append(True)
            return original() if original else None

        session.request_end = spy  # type: ignore[method-assign]
        async with _api() as (http, _):
            with _live("call-live-3", session):
                r = await http.post("/api/calls/call-live-3/hangup")
        assert r.status_code == 202, (r.status_code, r.text)
        assert asked == [True], "request_end() was not called"

    asyncio.run(scenario())


def test_whisper_reaches_the_model_and_is_announced() -> None:
    async def scenario() -> None:
        llm = FakeLLM()
        async with _api() as (http, _), _events() as seen:
            with _live("call-live-4", _session(llm)):
                r = await http.post(
                    "/api/calls/call-live-4/whisper", json={"text": "Offer Thursday at ten instead."}
                )
            await _until(lambda: any(e.type == "call.whisper" for e in seen), 1, "call.whisper")
        assert r.status_code == 202, (r.status_code, r.text)
        assert llm.guidance == ["Offer Thursday at ten instead."], llm.guidance
        whisper = next(e for e in seen if e.type == "call.whisper")
        assert whisper.payload.get("call_id") == "call-live-4", whisper.payload
        assert whisper.payload.get("text") == "Offer Thursday at ten instead.", whisper.payload

    asyncio.run(scenario())


def test_whisper_text_must_be_1_to_500_characters() -> None:
    async def scenario() -> None:
        llm = FakeLLM()
        async with _api() as (http, _):
            with _live("call-live-5", _session(llm)):
                for text in ("", "x" * 501):
                    r = await http.post("/api/calls/call-live-5/whisper", json={"text": text})
                    assert 400 <= r.status_code < 500, (len(text), r.status_code, r.text)
                r = await http.post("/api/calls/call-live-5/whisper", json={"text": "x" * 500})
                assert r.status_code == 202, (r.status_code, r.text)
        assert llm.guidance == ["x" * 500], [len(g) for g in llm.guidance]

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# A campaign call streams its events end to end
# ---------------------------------------------------------------------------


class _NoSuppression:
    async def suppress(self, *, contact_id: str, reason: str) -> None:
        pass


class _FakeTelephony:
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


async def _campaign_call():
    """One campaign call through the real pipeline. Returns (events, call row, telephony)."""
    from src.voiceagent.voice.pipeline import CallPipeline

    engine, sessions = await _temp_db()
    try:
        async with sessions() as db:
            db.add(storage.Campaign(id="camp-live", name="Smile Dental", goal="Confirm Tuesday."))
            db.add(
                storage.Contact(
                    id="ct-live", campaign_id="camp-live", full_name="Asha Rao", phone_e164="+15555550142"
                )
            )
            await db.commit()
        async with sessions() as db:
            contact = await db.get(storage.Contact, "ct-live")
            campaign = await db.get(storage.Campaign, "camp-live")

        outcome = CallOutcome(
            disposition=Disposition.COMPLETED,
            summary="Asha confirmed Tuesday.",
            needs_human_review=False,
            sentiment="positive",  # ignored by models that predate sentiment
        )
        client = FakeAnthropicClient([["Perfect, you're booked for Tuesday. Goodbye!"]], outcome)
        telephony = _FakeTelephony(LineListener(["Yes, Tuesday works."]))
        pipeline = CallPipeline(
            sessions,
            client,
            telephony,
            calendar=MockCalendar(),
            records=MockRecords(),
            suppression=_NoSuppression(),
            followups=False,
        )
        async with _events() as seen:
            try:
                await asyncio.wait_for(pipeline.place_call(contact, campaign), 4)
            except asyncio.TimeoutError:
                raise AssertionError(
                    f"the campaign call did not end; spoken: {telephony.speaker.spoken}"
                ) from None
            await asyncio.sleep(0.05)  # let the collector drain the bus queue
            events = list(seen)

        async with sessions() as db:
            row = (await db.execute(select(storage.Call))).scalars().one()
        return events, row, telephony
    finally:
        await engine.dispose()


def test_a_campaign_call_streams_turns_and_states_as_they_happen() -> None:
    with _env(**ANTHROPIC_ENV):
        events, row, _ = asyncio.run(_campaign_call())

    started = [e for e in events if e.type == "call.started"]
    assert len(started) == 1, [e.type for e in events]
    call_id = started[0].payload["call_id"]
    assert call_id == row.id
    mine = _for_call(events, call_id)
    types = [e.type for e in mine]

    payload = started[0].payload
    assert payload.get("campaign_id") == "camp-live" and payload.get("contact_name") == "Asha Rao", payload
    assert payload.get("is_test") is False, payload
    assert "+15555550142" not in str(payload.get("phone")), "the full number went onto the bus"

    for event in events:
        if event.type.startswith("call."):
            assert event.payload.get("call_id"), f"{event.type} has no call_id"

    turns = [e.payload for e in mine if e.type == "call.turn"]
    assert [(t["role"], t["text"]) for t in turns] == [
        ("assistant", "Hi Asha, this is an AI assistant calling on behalf of Smile Dental. Do you have a moment?"),
        ("user", "Yes, Tuesday works."),
        ("assistant", "Perfect, you're booked for Tuesday. Goodbye!"),
    ], turns
    for t in turns:
        assert {"role", "text", "latency_ms", "at"} <= set(t), t

    states = [e.payload.get("state") for e in mine if e.type == "call.state"]
    assert {"speaking", "listening", "thinking"} <= set(states), states
    assert states[-1] == "ended", states

    assert types.index("call.connected") < types.index("call.turn"), types
    last_turn = len(types) - 1 - types[::-1].index("call.turn")
    assert last_turn < types.index("call.ended") < types.index("call.extracted"), types

    ended = next(e.payload for e in mine if e.type == "call.ended")
    assert ended.get("turns") == 3, ended
    assert isinstance(ended.get("duration_seconds"), (int, float)) and ended["duration_seconds"] >= 0, ended

    extracted = next(e.payload for e in mine if e.type == "call.extracted")
    for key in ("disposition", "summary", "needs_review", "cost_usd", "sentiment"):
        assert key in extracted, f"call.extracted is missing {key}: {extracted}"
    assert extracted["sentiment"] == "positive", extracted


def test_a_campaign_call_saves_its_sentiment() -> None:
    with _env(**ANTHROPIC_ENV):
        _, row, _ = asyncio.run(_campaign_call())
    assert getattr(row, "sentiment", "<no column>") == "positive", getattr(row, "sentiment", "<no column>")


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
