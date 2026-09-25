"""Latency v2: per-call language on Twilio, and no dead air while a reply is made.

Drives the real Twilio webhook app over ASGI through a real
`TwilioTelephony.dial()`, with Twilio's REST client, the model, and Sarvam
all faked, so there is no account, no network and no key. Covers
`prepare_call` (the call's language and pre-synthesized audio), the Gather
STT language, the TTS language in the audio cache key, and the
acknowledgement filler served when a reply is slow.

Runs standalone (`python tests/test_latency_v2.py`) or under pytest. Env vars
the spec names (TWILIO_FILLER_AFTER_MS, SARVAM_STT_LANGUAGE,
SARVAM_TTS_LANGUAGE) are set per test, so they must be read at call time.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import sys
import tempfile
import time
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from types import SimpleNamespace
from xml.sax.saxutils import escape

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.integrations.mocks import MockCalendar, MockRecords  # noqa: E402
from src.voiceagent.voice import twilio_adapter as tw  # noqa: E402
from src.voiceagent.voice.sarvam_voice import _pcm_to_wav  # noqa: E402
from src.voiceagent.voice.session import CallNotPlaced, CallSession  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)

GREETING = "Hi Asha, it's Smile Dental calling."
HI_GREETING = "नमस्ते Asha, Smile Dental से बात कर रहे हैं।"
QUOTES = {'"': "&quot;", "'": "&apos;"}


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


# Neither language override is set unless a test sets it.
NO_LANGUAGE_PINS = dict(SARVAM_STT_LANGUAGE=None, SARVAM_TTS_LANGUAGE=None)


def _wav(seconds: float) -> bytes:
    return _pcm_to_wav(b"\x00\x00" * int(8000 * seconds), sample_rate=8000, channels=1, sample_width=2)


class FakeSynth:
    """Stands in for Sarvam. Every distinct text gets distinct audio bytes.

    Accepts any extra arguments (the TTS language may be passed along) and
    records them. Texts in `fail` synthesize to None, like a Sarvam error.
    """

    def __init__(self, *, fail: set[str] | frozenset[str] = frozenset(), delay: float = 0.01) -> None:
        self.fail = set(fail)
        self.delay = delay
        self.calls: list[tuple[str, tuple, dict]] = []
        self.audio: dict[str, bytes] = {}

    async def __call__(self, text: str, *args, **kwargs) -> bytes | None:
        self.calls.append((text, args, kwargs))
        await asyncio.sleep(self.delay)
        if text in self.fail:
            return None
        audio = self.audio.get(text) or _wav(0.2 + 0.01 * len(self.audio))
        self.audio[text] = audio
        return audio

    def texts(self, since: int = 0) -> list[str]:
        return [text for text, _, _ in self.calls[since:]]

    def languages(self, text: str) -> set[str]:
        """Language codes passed alongside `text`, if the implementation passes any."""
        found = set()
        for called, args, kwargs in self.calls:
            if called == text:
                for value in [*args, *kwargs.values()]:
                    if isinstance(value, str) and re.fullmatch(r"[a-z]{2}-IN", value):
                        found.add(value)
        return found


@contextmanager
def _voice(provider: str, synthesize=None):
    """Pin the voice provider — the package loads .env, which may say sarvam."""
    real = tw.VOICE_PROVIDER, tw._synthesize_sarvam
    tw.VOICE_PROVIDER = provider
    if synthesize is not None:
        tw._synthesize_sarvam = synthesize
    try:
        yield
    finally:
        tw.VOICE_PROVIDER, tw._synthesize_sarvam = real
        tw._audio_store.clear()
        tw._inflight.clear()


class _FakeCalls:
    def __init__(self) -> None:
        self.created: list[dict] = []
        self.hangups: list[str] = []

    def create(self, **kwargs):
        self.created.append(kwargs)
        return SimpleNamespace(sid=f"CA-test-{len(self.created)}")

    def __call__(self, sid: str):
        calls = self

        class _Call:
            def update(self, **_):
                calls.hangups.append(sid)

        return _Call()


def _telephony():
    """A real TwilioTelephony whose REST client is a fake. No server is started."""
    tele = tw.TwilioTelephony(
        account_sid="AC-test",
        auth_token="test-token",
        from_number="+15550000000",
        webhook_url="https://samvaad.test",
    )
    tele._client = SimpleNamespace(calls=_FakeCalls())
    return tele


class SlowLLM:
    """Takes `delay` seconds before its reply starts — a slow model turn."""

    def __init__(self, replies: list[list[str]], *, delay: float) -> None:
        self._replies = list(replies)
        self._delay = delay
        self.end_requested = False

    def record(self, turn) -> None:
        pass

    async def generate(self):
        chunks = self._replies.pop(0) if self._replies else ["Okay then."]
        await asyncio.sleep(self._delay)
        for chunk in chunks:
            yield chunk


def _http() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=tw._build_webhook_app()), base_url="http://test"
    )


async def _until(predicate, timeout: float = 2.0, what: str = "condition") -> None:
    loop = asyncio.get_running_loop()
    deadline = loop.time() + timeout
    while not predicate():
        if loop.time() > deadline:
            raise AssertionError(f"timed out waiting for {what}")
        await asyncio.sleep(0.01)


@dataclass
class _Call:
    room: str
    session: CallSession
    run: asyncio.Task
    greeting_twiml: str


async def _start_call(
    http: httpx.AsyncClient,
    room: str,
    *,
    llm,
    language: str | None,
    greeting: str = GREETING,
    tele=None,
) -> _Call:
    """Prepare (when a language is given), dial, answer, and start the session.

    Returns once Twilio has fetched the greeting.
    """
    tele = tele or _telephony()
    session_kwargs = {}
    if language is not None:
        from src.voiceagent.voice.phrases import phrases_for

        tele.prepare_call(room, language=language, greeting=greeting)
        session_kwargs["phrases"] = phrases_for(language)

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
        **session_kwargs,
    )
    run = asyncio.create_task(session.run())
    response = await asyncio.wait_for(answering, 5)
    return _Call(room, session, run, response.text)


async def _end_call(http: httpx.AsyncClient, call: _Call):
    await http.post(f"/twilio/status/{call.room}", data={"CallStatus": "completed"})
    try:
        return await asyncio.wait_for(call.run, 5)
    finally:
        tw._active_calls.pop(call.room, None)


def _gather_language(twiml: str) -> str | None:
    match = re.search(r'<Gather[^>]*\blanguage="([^"]+)"', twiml)
    return match.group(1) if match else None


def _spoken_acks(twiml: str, acks) -> list[str]:
    """Acknowledgements said with <Say> in this TwiML."""
    return [ack for ack in acks if f">{escape(ack, QUOTES)}</Say>" in twiml]


def _play_paths(twiml: str) -> list[str]:
    return [
        url.replace(tw._webhook_base(), "")
        for url in re.findall(r"<Play>([^<]+)</Play>", twiml)
    ]


async def _gather(http: httpx.AsyncClient, room: str, speech: str) -> tuple[str, float]:
    started = time.perf_counter()
    r = await http.post(f"/twilio/gather/{room}", data={"SpeechResult": speech})
    return r.text, time.perf_counter() - started


# ---------------------------------------------------------------------------
# Per-call language: prepare_call and the Gather STT language
# ---------------------------------------------------------------------------


def test_gather_listens_in_the_calls_language() -> None:
    """A Hindi campaign's call is transcribed as Hindi, not as US English."""
    expected = {"en": "en-US", "hi": "hi-IN", "hi-en": "hi-IN", "ur": "ur-IN"}

    async def scenario() -> dict[str, str | None]:
        heard = {}
        async with _http() as http:
            for language in expected:
                room = f"t-gather-lang-{language}"
                call = await _start_call(http, room, llm=SlowLLM([], delay=0), language=language)
                heard[language] = _gather_language(call.greeting_twiml)
                await _end_call(http, call)
        return heard

    with _env(**NO_LANGUAGE_PINS), _voice("twilio"):
        heard = asyncio.run(scenario())
    assert heard == expected, heard


def test_with_the_sarvam_voice_english_is_heard_as_indian_english() -> None:
    async def scenario() -> dict[str, str | None]:
        heard = {}
        async with _http() as http:
            for language in ("en", "hi"):
                room = f"t-gather-sarvam-{language}"
                call = await _start_call(http, room, llm=SlowLLM([], delay=0), language=language)
                heard[language] = _gather_language(call.greeting_twiml)
                await _end_call(http, call)
        return heard

    with _env(**NO_LANGUAGE_PINS), _voice("sarvam", FakeSynth()):
        heard = asyncio.run(scenario())
    assert heard == {"en": "en-IN", "hi": "hi-IN"}, heard


def test_the_stt_language_env_var_wins_when_set() -> None:
    async def scenario() -> str | None:
        async with _http() as http:
            call = await _start_call(http, "t-gather-pinned", llm=SlowLLM([], delay=0), language="hi")
            heard = _gather_language(call.greeting_twiml)
            await _end_call(http, call)
        return heard

    with _env(SARVAM_STT_LANGUAGE="en-IN", SARVAM_TTS_LANGUAGE=None), _voice("sarvam", FakeSynth()):
        heard = asyncio.run(scenario())
    assert heard == "en-IN", heard


def test_prepare_call_presynthesizes_the_greeting_and_acknowledgements() -> None:
    """While the phone rings, so the first thing the person hears isn't a wait."""
    from src.voiceagent.voice.phrases import phrases_for

    synth = FakeSynth()
    wanted = {HI_GREETING, *phrases_for("hi").acknowledgements}

    async def scenario() -> None:
        _telephony().prepare_call("t-prepare-hi", language="hi", greeting=HI_GREETING)
        await _until(lambda: wanted <= set(synth.texts()), 2, "the greeting and acknowledgements")

    with _env(**NO_LANGUAGE_PINS), _voice("sarvam", synth):
        asyncio.run(scenario())
    assert set(synth.texts()) >= wanted, synth.texts()


def test_prepare_call_synthesizes_nothing_with_the_twilio_voice() -> None:
    synth = FakeSynth()

    async def scenario() -> None:
        _telephony().prepare_call("t-prepare-twilio", language="hi", greeting=HI_GREETING)
        await asyncio.sleep(0.1)

    with _env(**NO_LANGUAGE_PINS), _voice("twilio", synth):
        asyncio.run(scenario())
    assert synth.calls == [], synth.texts()


def test_the_tts_language_is_part_of_the_audio_cache_key() -> None:
    """The same words in an English call and a Hindi call are two different recordings."""
    synth = FakeSynth()
    line = "Hello from Smile Dental."

    async def scenario() -> None:
        tele = _telephony()
        tele.prepare_call("t-cache-en", language="en", greeting=line)
        tele.prepare_call("t-cache-hi", language="hi", greeting=line)
        await _until(lambda: synth.texts().count(line) >= 2, 2, "one synthesis per language")

    with _env(**NO_LANGUAGE_PINS), _voice("sarvam", synth):
        asyncio.run(scenario())
    assert synth.texts().count(line) == 2, synth.texts()
    languages = synth.languages(line)
    if languages:  # only checkable when the language is passed to the synthesizer
        assert languages == {"en-IN", "hi-IN"}, languages


def test_a_pinned_tts_language_shares_one_recording_across_calls() -> None:
    synth = FakeSynth()
    line = "Hello from Smile Dental."

    async def scenario() -> None:
        tele = _telephony()
        tele.prepare_call("t-pinned-en", language="en", greeting=line)
        tele.prepare_call("t-pinned-hi", language="hi", greeting=line)
        await asyncio.sleep(0.2)

    with _env(SARVAM_STT_LANGUAGE=None, SARVAM_TTS_LANGUAGE="hi-IN"), _voice("sarvam", synth):
        asyncio.run(scenario())
    assert synth.texts().count(line) == 1, synth.texts()


# ---------------------------------------------------------------------------
# Acknowledgement fillers
# ---------------------------------------------------------------------------


def test_a_slow_reply_is_covered_by_an_acknowledgement() -> None:
    """"Okay." now and the answer a moment later, instead of silence."""
    from src.voiceagent.voice.phrases import phrases_for

    acks = phrases_for("en").acknowledgements
    reply = "Tuesday at two is free."

    async def scenario() -> None:
        room = "t-filler-slow"
        async with _http() as http:
            call = await _start_call(http, room, llm=SlowLLM([[reply]], delay=0.6), language="en")

            twiml, elapsed = await _gather(http, room, "Is Tuesday free?")
            said = _spoken_acks(twiml, acks)
            assert len(said) == 1, f"expected one acknowledgement: {twiml}"
            assert reply not in twiml, twiml
            assert "<Redirect" in twiml and f"/twilio/wait/{room}" in twiml, twiml
            assert elapsed < 0.45, f"the acknowledgement took {elapsed:.2f}s"

            r = await http.post(f"/twilio/wait/{room}")
            assert reply in r.text, r.text
            assert not _spoken_acks(r.text, acks), r.text

            transcript = await _end_call(http, call)
        texts = [t.text for t in transcript]
        assert not any(ack in texts for ack in acks), f"a filler was recorded: {texts}"
        assert texts[-1] == reply, texts

    with _env(TWILIO_FILLER_AFTER_MS="100", **NO_LANGUAGE_PINS), _voice("twilio"):
        asyncio.run(scenario())


def test_a_fast_reply_needs_no_acknowledgement() -> None:
    """Under the default threshold the reply itself comes back, unpadded."""
    reply = "Tuesday at two is free."
    fillers = ("Okay.", "Mm-hmm.", "Got it.", "Right.")

    async def scenario() -> None:
        room = "t-filler-fast"
        async with _http() as http:
            call = await _start_call(http, room, llm=SlowLLM([[reply]], delay=0.2), language=None)
            twiml, _ = await _gather(http, room, "Is Tuesday free?")
            assert reply in twiml, twiml
            assert not _spoken_acks(twiml, fillers), twiml
            await _end_call(http, call)

    with _env(TWILIO_FILLER_AFTER_MS=None, **NO_LANGUAGE_PINS), _voice("twilio"):
        asyncio.run(scenario())


def test_acknowledgements_can_be_turned_off() -> None:
    reply = "Tuesday at two is free."
    fillers = ("Okay.", "Mm-hmm.", "Got it.", "Right.")

    async def scenario() -> None:
        room = "t-filler-off"
        async with _http() as http:
            call = await _start_call(http, room, llm=SlowLLM([[reply]], delay=0.4), language=None)
            twiml, _ = await _gather(http, room, "Is Tuesday free?")
            assert reply in twiml, twiml
            assert not _spoken_acks(twiml, fillers), twiml
            await _end_call(http, call)

    with _env(TWILIO_FILLER_AFTER_MS="0", **NO_LANGUAGE_PINS), _voice("twilio"):
        asyncio.run(scenario())


def test_acknowledgements_rotate_and_never_repeat_back_to_back() -> None:
    from src.voiceagent.voice.phrases import phrases_for

    acks = phrases_for("en").acknowledgements
    replies = [["Tuesday works."], ["Two o'clock it is."], ["You're all set."]]

    async def scenario() -> list[str]:
        room = "t-filler-rotate"
        used = []
        async with _http() as http:
            call = await _start_call(http, room, llm=SlowLLM(replies, delay=0.3), language="en")
            for speech in ("Is Tuesday free?", "Two o'clock?", "Great."):
                twiml, _ = await _gather(http, room, speech)
                said = _spoken_acks(twiml, acks)
                assert len(said) == 1, twiml
                used.append(said[0])
                await http.post(f"/twilio/wait/{room}")
            await _end_call(http, call)
        return used

    with _env(TWILIO_FILLER_AFTER_MS="50", **NO_LANGUAGE_PINS), _voice("twilio"):
        used = asyncio.run(scenario())
    assert all(a != b for a, b in zip(used, used[1:])), f"the same filler twice in a row: {used}"


def test_sarvam_acknowledgements_play_from_cached_audio() -> None:
    """In a Hindi call the filler is Hindi audio made while the phone rang."""
    from src.voiceagent.voice.phrases import phrases_for

    acks = phrases_for("hi").acknowledgements
    reply = "जी, मंगलवार दो बजे खाली है।"
    synth = FakeSynth()

    async def scenario() -> None:
        room = "t-filler-sarvam"
        async with _http() as http:
            call = await _start_call(
                http, room, llm=SlowLLM([[reply]], delay=0.6), language="hi", greeting=HI_GREETING
            )
            await _until(lambda: set(acks) <= set(synth.audio), 2, "the acknowledgements to be cached")
            hot_path = len(synth.calls)

            twiml, elapsed = await _gather(http, room, "क्या मंगलवार खाली है?")
            plays = _play_paths(twiml)
            assert len(plays) == 1 and f"/twilio/wait/{room}" in twiml, twiml
            assert elapsed < 0.45, f"the acknowledgement took {elapsed:.2f}s"
            audio = (await http.get(plays[0])).content
            assert audio in {synth.audio[a] for a in acks}, "the filler is not an acknowledgement's audio"

            r = await http.post(f"/twilio/wait/{room}")
            reply_audio = [(await http.get(p)).content for p in _play_paths(r.text)]
            assert synth.audio.get(reply) in reply_audio, r.text

            await _end_call(http, call)
            synthesized_mid_call = set(synth.texts(hot_path))
            assert not synthesized_mid_call & set(acks), f"synthesized on the hot path: {synthesized_mid_call}"

    with _env(TWILIO_FILLER_AFTER_MS="100", **NO_LANGUAGE_PINS), _voice("sarvam", synth):
        asyncio.run(scenario())


def test_sarvam_never_synthesizes_an_acknowledgement_mid_call() -> None:
    """No cached filler audio means no filler — never a synthesis while the person waits."""
    from src.voiceagent.voice.phrases import phrases_for

    acks = phrases_for("en").acknowledgements
    reply = "Tuesday at two is free."
    synth = FakeSynth(fail={*acks, reply})  # nothing cached; the reply falls back to <Say>

    async def scenario() -> None:
        room = "t-filler-uncached"
        async with _http() as http:
            call = await _start_call(http, room, llm=SlowLLM([[reply]], delay=0.5), language="en")
            await _until(lambda: set(acks) <= set(synth.texts()), 2, "the prepare step to finish")
            hot_path = len(synth.calls)

            twiml, _ = await _gather(http, room, "Is Tuesday free?")
            assert not _spoken_acks(twiml, acks), twiml
            if reply not in twiml:  # a plain hold-and-redirect is fine; a filler isn't
                assert not _play_paths(twiml), twiml
                twiml = (await http.post(f"/twilio/wait/{room}")).text
            assert reply in twiml, twiml

            await _end_call(http, call)
            assert not set(synth.texts(hot_path)) & set(acks), synth.texts(hot_path)

    with _env(TWILIO_FILLER_AFTER_MS="100", **NO_LANGUAGE_PINS), _voice("sarvam", synth):
        asyncio.run(scenario())


# ---------------------------------------------------------------------------
# Callers prepare the call before dialling
# ---------------------------------------------------------------------------


class _NoSuppression:
    async def suppress(self, *, contact_id: str, reason: str) -> None:
        pass


class _RecordingTelephony:
    """Records the order of prepare_call and dial; refuses the dial."""

    def __init__(self) -> None:
        self.calls: list[tuple] = []

    def prepare_call(self, room_name: str, *, language: str, greeting: str) -> None:
        self.calls.append(("prepare_call", room_name, language, greeting))

    async def dial(self, *, phone_e164: str, room_name: str):
        self.calls.append(("dial", room_name))
        raise CallNotPlaced("refused in test")

    def get_call_state(self, room_name: str):
        return None


def test_the_pipeline_prepares_the_call_in_its_language_before_dialling() -> None:
    from src.voiceagent.voice.pipeline import CallPipeline

    async def scenario() -> list[tuple]:
        path = Path(tempfile.mkdtemp()) / "latency.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
        try:
            async with engine.begin() as conn:
                await conn.run_sync(storage.Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                db.add(
                    storage.Campaign(
                        id="camp-hi",
                        name="Smile Dental",
                        goal="Remind Asha about her cleaning.",
                        language="hi",
                        greeting="नमस्ते {first_name}, Smile Dental से बात कर रहे हैं।",
                    )
                )
                db.add(
                    storage.Contact(
                        id="ct-hi", campaign_id="camp-hi", full_name="Asha Rao", phone_e164="+919800000001"
                    )
                )
                await db.commit()
            async with sessions() as db:
                contact = await db.get(storage.Contact, "ct-hi")
                campaign = await db.get(storage.Campaign, "camp-hi")

            telephony = _RecordingTelephony()
            pipeline = CallPipeline(
                sessions,
                SimpleNamespace(),
                telephony,
                calendar=MockCalendar(),
                records=MockRecords(),
                suppression=_NoSuppression(),
                followups=False,
            )
            await asyncio.wait_for(pipeline.place_call(contact, campaign), 3)
            return telephony.calls
        finally:
            await engine.dispose()

    calls = asyncio.run(scenario())
    assert [c[0] for c in calls] == ["prepare_call", "dial"], calls
    _, prepared_room, language, greeting = calls[0]
    assert prepared_room == calls[1][1], calls
    assert language == "hi", calls
    assert greeting == HI_GREETING, calls


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
