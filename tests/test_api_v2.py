"""API v2: async test calls, saved conversations, recordings, sentiment.

Nothing is lost: a test call returns at once and saves its transcript as it
goes, any conversation downloads as TXT or JSON, Twilio's late recording
callback lands on the call row, and every call records how the person felt.

Drives the real FastAPI app over ASGI against a throwaway SQLite database,
with the telephony adapter and the model client faked — no network, no key,
and no real Twilio (the Twilio credentials are unset for the test-call tests,
so even a wrong implementation cannot place a real call). Runs standalone
(`python tests/test_api_v2.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import logging
import os
import sys
import tempfile
from contextlib import asynccontextmanager, contextmanager, suppress
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import func, select  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import providers, storage  # noqa: E402
from src.voiceagent.api import app as app_module  # noqa: E402
from src.voiceagent.integrations.mocks import MockControl, MockSpeaker  # noqa: E402
from src.voiceagent.models import CallOutcome, Disposition, Turn  # noqa: E402
from src.voiceagent.orchestrator.events import bus  # noqa: E402
from src.voiceagent.voice import twilio_adapter as tw  # noqa: E402
from src.voiceagent.voice.session import CallNotPlaced  # noqa: E402

# Imported up front: first imports are slow on some machines, and a test call
# may import these lazily inside the request, which would eat into the time
# the request has to return in.
import src.voiceagent.postcall.extract  # noqa: E402, F401
import src.voiceagent.scoring  # noqa: E402, F401

logging.getLogger().setLevel(logging.WARNING)

PHONE = "+15555550123"

# A model key so the provider check passes, Twilio selected, and no real
# Twilio/Telnyx credentials anywhere in reach.
TEST_CALL_ENV = dict(
    MODEL_PROVIDER="anthropic",
    ANTHROPIC_API_KEY="sk-ant-test-key",
    TELEPHONY="twilio",
    TWILIO_ACCOUNT_SID=None,
    TWILIO_AUTH_TOKEN=None,
    TWILIO_PHONE_NUMBER=None,
    TWILIO_WHATSAPP_FROM=None,
    TELNYX_API_KEY=None,
    TELNYX_PHONE_NUMBER=None,
    ADMIN_PASSWORD=None,
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


async def _temp_db():
    path = Path(tempfile.mkdtemp()) / "api_v2.db"
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


async def _until(predicate, timeout: float = 2.0, what: str = "condition") -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


async def _event(seen, kind: str, call_id: str, timeout: float = 3.0):
    def find():
        return next(
            (e for e in seen if e.type == kind and (e.payload or {}).get("call_id") == call_id), None
        )

    try:
        await _until(lambda: find() is not None, timeout, kind)
    except AssertionError:
        mine = [e.type for e in seen if (e.payload or {}).get("call_id") == call_id]
        raise AssertionError(f"no {kind} for {call_id} within {timeout}s; got {mine}") from None
    return find()


async def _row(sessions, call_id: str):
    async with sessions() as db:
        return await db.get(storage.Call, call_id)


async def _row_when(sessions, call_id: str, predicate, timeout: float = 1.0):
    """The call row once `predicate(row)` holds, or as it is at the timeout."""
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while True:
        row = await _row(sessions, call_id)
        if (row is not None and predicate(row)) or loop.time() > deadline:
            return row
        await asyncio.sleep(0.02)


async def _count_calls(sessions) -> int:
    async with sessions() as db:
        return await db.scalar(select(func.count()).select_from(storage.Call))


async def _seed_campaign(sessions, *, language: str = "en") -> None:
    async with sessions() as db:
        db.add(
            storage.Campaign(
                id="camp-1",
                name="Smile Dental",
                goal="Confirm Asha's cleaning on Tuesday.",
                language=language,
                greeting="Hi {first_name}, it's {campaign_name} calling.",
            )
        )
        await db.commit()


def _test_call_body(**overrides) -> dict:
    body = {
        "campaign_id": "camp-1",
        "phone_number": PHONE,
        "contact_name": "Asha Rao",
        "send_sms": False,
        "send_whatsapp": False,
    }
    body.update(overrides)
    return body


async def _post_test_call(http, body: dict):
    try:
        return await asyncio.wait_for(http.post("/api/test-call", json=body), 5)
    except asyncio.TimeoutError:
        raise AssertionError(
            "POST /api/test-call did not return while the phone was still ringing; "
            "the call must run in a background task (asyncio.create_task), not inside the request"
        ) from None


# -- fakes ----------------------------------------------------------------------


class FastSpeaker(MockSpeaker):
    """MockSpeaker's contract without its per-character sleeps (slow on Windows)."""

    async def say(self, text: str) -> None:
        await asyncio.sleep(0)
        self.spoken.append(text)


class GatedListener:
    """Says nothing until `gate` is set, then its lines; then stays on the line."""

    def __init__(self, lines: list[str]) -> None:
        self._lines = list(lines)
        self.gate = asyncio.Event()

    async def utterances(self):
        await self.gate.wait()
        for line in self._lines:
            await asyncio.sleep(0.01)
            yield line
        await asyncio.Event().wait()

    async def wait_for_speech_start(self) -> None:
        await asyncio.Event().wait()


class _AnsweringTelephony:
    def __init__(self, listener) -> None:
        self.listener = listener
        self.speaker = FastSpeaker()
        self.control = MockControl()
        self.calls: list[tuple] = []

    def prepare_call(self, room_name: str, *, language: str, greeting: str) -> None:
        self.calls.append(("prepare_call", room_name, language, greeting))

    async def dial(self, *, phone_e164: str, room_name: str):
        self.calls.append(("dial", room_name, phone_e164))
        return self.listener, self.speaker, self.control, "CA-test"

    def get_call_state(self, room_name: str):
        return None


class _RefusingTelephony:
    """Rings until `release` is set, then refuses — like an unverified trial number."""

    def __init__(self) -> None:
        self.release = asyncio.Event()
        self.calls: list[tuple] = []

    def prepare_call(self, room_name: str, *, language: str, greeting: str) -> None:
        self.calls.append(("prepare_call", room_name, language, greeting))

    async def dial(self, *, phone_e164: str, room_name: str):
        self.calls.append(("dial", room_name, phone_e164))
        await self.release.wait()
        raise CallNotPlaced("Twilio refused the call: the number is unverified on this trial account.")

    def get_call_state(self, room_name: str):
        return None

    @property
    def dialled_room(self) -> str | None:
        return next((c[1] for c in self.calls if c[0] == "dial"), None)


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
        deltas = self._owner.replies.pop(0) if self._owner.replies else ["Okay."]
        return _FakeStream(deltas)

    async def parse(self, **kwargs):
        return SimpleNamespace(parsed_output=self._owner.outcome, stop_reason="end_turn", usage=None)


class FakeAnthropicClient:
    """Anthropic-shaped: `messages.stream` for the call, `messages.parse` for extraction."""

    def __init__(self, replies: list[list[str]], outcome: CallOutcome) -> None:
        self.replies = [list(r) for r in replies]
        self.outcome = outcome
        self.messages = _FakeMessages(self)

    async def close(self) -> None:
        pass


@contextmanager
def _fake_model(client):
    """Hand the fake client to whoever asks for one (today: `make_client()`)."""
    factory = lambda *args, **kwargs: client  # noqa: E731
    with _patched(app_module, "make_client", factory), _patched(providers, "make_client", factory):
        yield


# ---------------------------------------------------------------------------
# Naming
# ---------------------------------------------------------------------------


def test_the_api_is_called_samvaad() -> None:
    assert app_module.app.title == "Samvaad API", app_module.app.title


# ---------------------------------------------------------------------------
# POST /api/test-call is asynchronous
# ---------------------------------------------------------------------------


def test_the_test_call_seams_exist() -> None:
    """The names the rest of the team (and these tests) build on."""
    assert callable(getattr(app_module, "_test_call_telephony", None)), "_test_call_telephony missing"
    run = getattr(app_module, "_run_test_call", None)
    assert run is not None and inspect.iscoroutinefunction(run), "_run_test_call must be async"
    assert list(inspect.signature(run).parameters) == ["call_id", "room_name", "body", "setup"]

    with _env(
        TELEPHONY="twilio",
        TWILIO_ACCOUNT_SID="AC-test",
        TWILIO_AUTH_TOKEN="test-token",
        TWILIO_PHONE_NUMBER="+15550000000",
    ):
        assert isinstance(app_module._test_call_telephony(), tw.TwilioTelephony)


async def _refused_test_call() -> SimpleNamespace:
    """Start a test call whose dial is refused. Captures the row before and after."""
    telephony = _RefusingTelephony()
    client = FakeAnthropicClient([], CallOutcome(
        disposition=Disposition.FAILED, summary="n/a", needs_human_review=False
    ))
    async with _api() as (http, sessions), _events() as seen:
        await _seed_campaign(sessions)
        with _patched(app_module, "_test_call_telephony", lambda: telephony), _fake_model(client):
            try:
                response = await _post_test_call(http, _test_call_body())
                assert response.status_code == 202, (response.status_code, response.text)
                call_id = response.json()["call_id"]
                ringing = await _row(sessions, call_id)
                contact = None
                if ringing is not None:
                    async with sessions() as db:
                        contact = await db.get(storage.Contact, ringing.contact_id)
                await _until(lambda: telephony.dialled_room is not None, 2, "the dial")
            finally:
                telephony.release.set()
            failed = await _event(seen, "call.failed", call_id)
            after = await _row_when(sessions, call_id, lambda r: r.status == storage.CallStatus.FAILED)
            events = [e for e in seen if (e.payload or {}).get("call_id") == call_id]
    return SimpleNamespace(
        response=response, call_id=call_id, ringing=ringing, contact=contact,
        telephony=telephony, failed=failed, after=after, events=events,
    )


def test_a_test_call_returns_202_at_once_with_a_dialing_row() -> None:
    """The browser gets a call_id to watch while the phone is still ringing."""
    with _env(**TEST_CALL_ENV):
        result = asyncio.run(_refused_test_call())

    body = result.response.json()
    assert body.get("status") == "dialing" and body.get("call_id"), body
    row = result.ringing
    assert row is not None, "no Call row while the phone was ringing"
    assert row.status == storage.CallStatus.DIALING, row.status
    assert row.is_simulation is True
    assert row.campaign_id == "camp-1"
    assert row.room_name and row.room_name == result.telephony.dialled_room, (
        row.room_name, result.telephony.calls,
    )
    # The placeholder contact must never be dialled by the campaign runner.
    assert result.contact is not None and result.contact.status == storage.ContactStatus.SUPPRESSED


def test_a_refused_test_call_is_marked_failed_and_announced() -> None:
    with _env(**TEST_CALL_ENV):
        result = asyncio.run(_refused_test_call())

    error = result.failed.payload.get("error")
    assert isinstance(error, str) and error.strip(), result.failed.payload
    assert "Traceback" not in error, error
    assert result.after.status == storage.CallStatus.FAILED, result.after.status
    assert "call.connected" not in [e.type for e in result.events], [e.type for e in result.events]


def test_a_test_call_announces_itself_as_a_test_with_a_masked_number() -> None:
    with _env(**TEST_CALL_ENV):
        result = asyncio.run(_refused_test_call())

    started = [e for e in result.events if e.type == "call.started"]
    assert len(started) == 1, [e.type for e in result.events]
    payload = started[0].payload
    assert payload.get("is_test") is True, payload
    assert payload.get("campaign_id") == "camp-1", payload
    assert payload.get("contact_name") == "Asha Rao", payload
    assert payload.get("phone") and PHONE not in payload["phone"], payload


def test_test_call_validation_errors_are_still_synchronous() -> None:
    """Bad input is refused on the spot, with no row and no dial."""

    async def scenario() -> None:
        telephony = _RefusingTelephony()
        async with _api() as (http, sessions):
            await _seed_campaign(sessions)
            with _patched(app_module, "_test_call_telephony", lambda: telephony):
                r = await _post_test_call(http, _test_call_body(phone_number="12345"))
                assert 400 <= r.status_code < 500, ("bad phone", r.status_code, r.text)

                with _env(TELEPHONY="mock"):
                    r = await _post_test_call(http, _test_call_body())
                assert 400 <= r.status_code < 500, ("TELEPHONY=mock", r.status_code, r.text)

                with _env(MODEL_PROVIDER="nvidia", NVIDIA_API_KEY=None):
                    r = await _post_test_call(http, _test_call_body())
                assert r.status_code >= 400, ("no provider", r.status_code, r.text)

            assert await _count_calls(sessions) == 0, "a rejected request created a call row"
            assert telephony.calls == [], telephony.calls

    with _env(**TEST_CALL_ENV):
        asyncio.run(scenario())


async def _answered_test_call() -> SimpleNamespace:
    """A test call that connects, talks, and ends; the person waits for a gate."""
    listener = GatedListener(["Yes, Tuesday works."])
    telephony = _AnsweringTelephony(listener)
    outcome = CallOutcome(
        disposition=Disposition.COMPLETED,
        summary="Asha confirmed Tuesday at two.",
        needs_human_review=False,
        sentiment="positive",  # ignored by models that predate sentiment
    )
    client = FakeAnthropicClient([["Perfect, you're booked for Tuesday. Goodbye! [END_CALL]"]], outcome)
    async with _api() as (http, sessions), _events() as seen:
        await _seed_campaign(sessions, language="hi-en")
        with _patched(app_module, "_test_call_telephony", lambda: telephony), _fake_model(client):
            try:
                response = await _post_test_call(http, _test_call_body())
                assert response.status_code == 202, (response.status_code, response.text)
                call_id = response.json()["call_id"]

                await _event(seen, "call.turn", call_id)
                after_greeting = await _row_when(sessions, call_id, lambda r: len(r.transcript or []) >= 1)
            finally:
                listener.gate.set()
            extracted = await _event(seen, "call.extracted", call_id, timeout=5)
            final = await _row_when(sessions, call_id, lambda r: r.status == storage.CallStatus.COMPLETED)
            events = [e for e in seen if (e.payload or {}).get("call_id") == call_id]
    return SimpleNamespace(
        call_id=call_id, telephony=telephony, after_greeting=after_greeting,
        extracted=extracted, final=final, events=events,
    )


def test_a_test_call_prepares_the_call_in_the_campaigns_language() -> None:
    with _env(**TEST_CALL_ENV):
        result = asyncio.run(_answered_test_call())

    kinds = [c[0] for c in result.telephony.calls]
    assert kinds == ["prepare_call", "dial"], result.telephony.calls
    _, room, language, greeting = result.telephony.calls[0]
    assert room == result.telephony.calls[1][1] == result.final.room_name, result.telephony.calls
    assert language == "hi-en", language
    assert greeting == "Hi Asha, it's Smile Dental calling.", greeting


def test_a_test_call_saves_the_transcript_after_every_turn() -> None:
    """If the process dies mid-call, what was said is already on disk."""
    with _env(**TEST_CALL_ENV):
        result = asyncio.run(_answered_test_call())

    saved = result.after_greeting.transcript or []
    assert [t.get("text") for t in saved] == ["Hi Asha, it's Smile Dental calling."], saved


def test_a_finished_test_call_is_saved_and_reported() -> None:
    with _env(**TEST_CALL_ENV):
        result = asyncio.run(_answered_test_call())

    row = result.final
    assert row.status == storage.CallStatus.COMPLETED, row.status
    texts = [t.get("text") for t in row.transcript or []]
    assert texts == [
        "Hi Asha, it's Smile Dental calling.",
        "Yes, Tuesday works.",
        "Perfect, you're booked for Tuesday. Goodbye!",
    ], texts
    assert row.disposition == "completed", row.disposition
    assert getattr(row, "sentiment", None) == "positive", getattr(row, "sentiment", "<no column>")

    types = [e.type for e in result.events]
    assert types.index("call.connected") < types.index("call.turn"), types
    assert "call.state" in types, types
    assert types.index("call.ended") < types.index("call.extracted"), types

    payload = result.extracted.payload
    assert payload.get("sentiment") == "positive", payload
    result_obj = payload.get("result")
    assert isinstance(result_obj, dict), payload
    assert result_obj.get("call_id") == result.call_id, result_obj
    for key in ("followups", "median_first_chunk_ms", "outcome", "turns"):
        assert key in result_obj, f"result is missing {key}"


# ---------------------------------------------------------------------------
# GET /api/calls/{id}/transcript
# ---------------------------------------------------------------------------

T0 = datetime(2026, 9, 1, 10, 0, 0, tzinfo=timezone.utc)


async def _seed_finished_call(sessions, *, sentiment: str | None = None) -> None:
    turns = [
        Turn(role="assistant", text="Hi Asha, it's Smile Dental calling.", started_at=T0),
        Turn(role="user", text="Hi! Yes, Tuesday works.", started_at=T0 + timedelta(seconds=5)),
        Turn(
            role="assistant",
            text="Perfect, see you Tuesday.",
            started_at=T0 + timedelta(seconds=67),
            latency_ms=800,
        ),
    ]
    extra = {"sentiment": sentiment} if sentiment is not None else {}
    async with sessions() as db:
        db.add(storage.Campaign(id="camp-1", name="Smile Dental", goal="Confirm Tuesday."))
        db.add(
            storage.Contact(
                id="ct-1", campaign_id="camp-1", full_name="Asha Rao", phone_e164="+15555550100"
            )
        )
        db.add(
            storage.Call(
                id="call-1",
                contact_id="ct-1",
                campaign_id="camp-1",
                status=storage.CallStatus.COMPLETED,
                started_at=T0,
                connected_at=T0,
                ended_at=T0 + timedelta(seconds=70),
                transcript=[t.model_dump(mode="json") for t in turns],
                disposition="completed",
                summary="Asha confirmed Tuesday at two.",
                **extra,
            )
        )
        await db.commit()


TRANSCRIPT_LINES = [
    "[00:00] Agent: Hi Asha, it's Smile Dental calling.",
    "[00:05] Asha Rao: Hi! Yes, Tuesday works.",
    "[01:07] Agent: Perfect, see you Tuesday.",
]


def test_a_transcript_downloads_as_text() -> None:
    async def scenario() -> httpx.Response:
        async with _api() as (http, sessions):
            await _seed_finished_call(sessions)
            return await http.get("/api/calls/call-1/transcript?format=txt")

    r = asyncio.run(scenario())
    assert r.status_code == 200, (r.status_code, r.text)
    assert "attachment" in r.headers.get("content-disposition", ""), r.headers
    text = r.text
    lines = [line.strip() for line in text.splitlines()]
    for expected in TRANSCRIPT_LINES:
        assert expected in lines, f"missing line {expected!r} in:\n{text}"
    header = text.split(TRANSCRIPT_LINES[0])[0]
    assert "Asha Rao" in header, header
    assert "Smile Dental" in header or "camp-1" in header, header
    # The started date, in whatever format ("2026-09-01", "1 Sep 2026", ...).
    assert "2026" in header and ("09" in header or "Sep" in header), header
    assert "completed" in header, header
    assert "Asha confirmed Tuesday at two." in header, header


def test_text_is_the_default_transcript_format() -> None:
    async def scenario() -> httpx.Response:
        async with _api() as (http, sessions):
            await _seed_finished_call(sessions)
            return await http.get("/api/calls/call-1/transcript")

    r = asyncio.run(scenario())
    assert r.status_code == 200, (r.status_code, r.text)
    lines = [line.strip() for line in r.text.splitlines()]
    assert TRANSCRIPT_LINES[1] in lines, r.text


def test_a_transcript_downloads_as_json() -> None:
    async def scenario() -> httpx.Response:
        async with _api() as (http, sessions):
            await _seed_finished_call(sessions, sentiment="positive")
            return await http.get("/api/calls/call-1/transcript?format=json")

    r = asyncio.run(scenario())
    assert r.status_code == 200, (r.status_code, r.text)
    assert "attachment" in r.headers.get("content-disposition", ""), r.headers
    data = json.loads(r.content)
    expected_keys = {
        "call_id", "contact_name", "campaign_id", "started_at",
        "disposition", "summary", "sentiment", "turns",
    }
    assert expected_keys <= set(data), data
    assert data["call_id"] == "call-1"
    assert data["contact_name"] == "Asha Rao"
    assert data["campaign_id"] == "camp-1"
    assert data["disposition"] == "completed"
    assert data["summary"] == "Asha confirmed Tuesday at two."
    assert data["sentiment"] == "positive"
    assert datetime.fromisoformat(data["started_at"].replace("Z", "+00:00")).date().isoformat() == "2026-09-01"
    assert [t["text"] for t in data["turns"]] == [
        "Hi Asha, it's Smile Dental calling.",
        "Hi! Yes, Tuesday works.",
        "Perfect, see you Tuesday.",
    ], data["turns"]


def test_transcript_export_rejects_unknown_calls_and_formats() -> None:
    async def scenario() -> tuple[int, int, int]:
        async with _api() as (http, sessions):
            await _seed_finished_call(sessions)
            ok = await http.get("/api/calls/call-1/transcript?format=txt")
            missing = await http.get("/api/calls/no-such-call/transcript")
            bad = await http.get("/api/calls/call-1/transcript?format=xml")
            return ok.status_code, missing.status_code, bad.status_code

    ok, missing, bad = asyncio.run(scenario())
    assert ok == 200, f"the export route doesn't exist yet (got {ok}), so the 404 below means nothing"
    assert missing == 404, missing
    assert bad == 400, bad


# ---------------------------------------------------------------------------
# Recordings arrive after hang-up
# ---------------------------------------------------------------------------


async def _post_recording(room: str, *, keep_state: bool):
    """Deliver Twilio's recording callback. Returns the row's recording fields."""
    engine, sessions = await _temp_db()
    saved = storage.SessionLocal
    storage.SessionLocal = sessions  # looked up at call time, per the spec
    try:
        async with sessions() as db:
            db.add(storage.Campaign(id="camp-1", name="Smile Dental", goal="Confirm."))
            db.add(storage.Contact(id="ct-1", campaign_id="camp-1", full_name="Asha Rao", phone_e164="+15555550100"))
            db.add(
                storage.Call(
                    id="call-rec", contact_id="ct-1", campaign_id="camp-1",
                    status=storage.CallStatus.COMPLETED, room_name=room,
                )
            )
            await db.commit()

        if keep_state:
            tw._active_calls[room] = tw._CallState()
        else:
            tw._active_calls.pop(room, None)

        transport = httpx.ASGITransport(app=tw._build_webhook_app())
        async with httpx.AsyncClient(transport=transport, base_url="http://test") as http:
            r = await http.post(
                f"/twilio/recording/{room}",
                data={
                    "RecordingUrl": "https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE123",
                    "RecordingSid": "RE123",
                    "RecordingDuration": "42",
                },
            )
        assert r.status_code == 200, r.status_code

        row = await _row_when(sessions, "call-rec", lambda c: c.recording_sid == "RE123")
        return row.recording_url, row.recording_sid, row.recording_duration
    finally:
        storage.SessionLocal = saved
        tw._active_calls.pop(room, None)
        await engine.dispose()


def test_a_recording_that_arrives_after_hang_up_is_saved() -> None:
    """Twilio posts the recording once the call state is gone; it must still land."""
    fields = asyncio.run(_post_recording("call-rec-gone", keep_state=False))
    assert fields == (
        "https://api.twilio.com/2010-04-01/Accounts/AC1/Recordings/RE123",
        "RE123",
        42,
    ), fields


def test_a_recording_that_arrives_mid_call_is_saved_too() -> None:
    fields = asyncio.run(_post_recording("call-rec-live", keep_state=True))
    assert fields[1:] == ("RE123", 42), fields


# ---------------------------------------------------------------------------
# Sentiment
# ---------------------------------------------------------------------------


def test_sentiment_is_positive_neutral_or_negative() -> None:
    from src.voiceagent.models import Sentiment

    assert issubclass(Sentiment, str)
    assert {s.value for s in Sentiment} == {"positive", "neutral", "negative"}
    assert Sentiment.NEUTRAL.value == "neutral"


def test_old_stored_outcomes_still_load_as_neutral() -> None:
    """Outcomes saved before sentiment existed must keep validating."""
    from src.voiceagent.models import Sentiment

    old = {"disposition": "completed", "summary": "Booked.", "needs_human_review": False}
    outcome = CallOutcome.model_validate(old)
    assert outcome.sentiment == Sentiment.NEUTRAL, outcome
    assert outcome.sentiment_reason == "", outcome


def test_sentiment_round_trips_through_a_saved_outcome() -> None:
    from src.voiceagent.models import Sentiment

    outcome = CallOutcome(
        disposition=Disposition.DECLINED,
        summary="Not interested.",
        needs_human_review=False,
        sentiment=Sentiment.NEGATIVE,
        sentiment_reason="Annoyed to be called at dinner.",
    )
    stored = outcome.model_dump(mode="json")
    assert stored["sentiment"] == "negative", stored
    restored = CallOutcome.model_validate(stored)
    assert restored.sentiment == Sentiment.NEGATIVE
    assert restored.sentiment_reason == "Annoyed to be called at dinner."
    # It is part of what the extractor is asked to fill in.
    assert "sentiment" in CallOutcome.model_json_schema()["properties"]


def test_calls_have_an_indexed_nullable_sentiment_column() -> None:
    column = storage.Call.__table__.c.get("sentiment")
    assert column is not None, "Call has no sentiment column"
    assert column.nullable is True
    assert column.index is True
    assert getattr(column.type, "length", None) == 16, column.type


def test_calls_carry_their_sentiment_through_the_api() -> None:
    async def scenario() -> tuple[list, dict]:
        async with _api() as (http, sessions):
            await _seed_finished_call(sessions, sentiment="negative")
            listed = (await http.get("/api/calls")).json()
            detail = (await http.get("/api/calls/call-1")).json()
            return listed, detail

    listed, detail = asyncio.run(scenario())
    assert [c.get("sentiment") for c in listed] == ["negative"], listed
    assert detail.get("sentiment") == "negative", detail


def test_the_dashboard_counts_sentiment_for_real_calls_only() -> None:
    async def scenario() -> dict:
        now = datetime.now(timezone.utc) - timedelta(hours=1)
        async with _api() as (http, sessions):
            async with sessions() as db:
                db.add(storage.Campaign(id="camp-1", name="Smile Dental", goal="Confirm."))
                db.add(storage.Contact(id="ct-1", campaign_id="camp-1", full_name="Asha Rao", phone_e164="+15555550100"))
                rows = [
                    ("positive", False), ("positive", False), ("negative", False),
                    ("negative", True),  # a rehearsal: never on the dashboard
                    (None, False),
                ]
                for i, (sentiment, simulated) in enumerate(rows):
                    db.add(
                        storage.Call(
                            id=f"call-{i}", contact_id="ct-1", campaign_id="camp-1",
                            status=storage.CallStatus.COMPLETED, started_at=now,
                            disposition="completed", is_simulation=simulated,
                            **({"sentiment": sentiment} if sentiment else {}),
                        )
                    )
                await db.commit()
            r = await http.get("/api/stats")
            assert r.status_code == 200, (r.status_code, r.text)
            return r.json()

    stats = asyncio.run(scenario())
    breakdown = stats.get("sentiment_breakdown")
    assert isinstance(breakdown, dict), stats
    assert breakdown.get("positive") == 2, breakdown
    assert breakdown.get("negative") == 1, breakdown
    assert breakdown.get("neutral", 0) == 0, breakdown


# ---------------------------------------------------------------------------


def _run_all() -> int:
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
