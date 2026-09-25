"""Graceful call ending: the agent says goodbye in the call's language, then hangs up.

The bug this guards against was reported by a user: the person says "thank
you" / "bye", the agent's reply isn't recognised as a goodbye (worst in
Hindi), the line goes quiet, and then an English "Sorry, are you still
there?" plays before the call is dropped.

Covered here: the `[END_CALL]` marker filter, the model wrapper's end flag,
the localized stock phrases, and the session rules that decide when a call
is over. Runs standalone (`python tests/test_call_ending.py`) or under
pytest. No API key, no network. Names that don't exist yet are imported
inside the tests, so each test reports its own result instead of the whole
file failing at import.
"""

from __future__ import annotations

import asyncio
import inspect
import logging
import os
import sys
import tempfile
import unicodedata
from contextlib import contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.integrations.mocks import (  # noqa: E402
    MockCalendar,
    MockControl,
    MockRecords,
    MockSpeaker,
)
from src.voiceagent.models import (  # noqa: E402
    CallContext,
    CallOutcome,
    Contact,
    Disposition,
)
from src.voiceagent.voice.session import CallSession  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)

GREETING = "Hi Asha, it's Smile Dental calling."

# The spec's table (docs/v2-spec.md §1.1), copied verbatim. Compared after NFC
# normalisation, so a nukta written precomposed or combined reads the same.
EXPECTED_PHRASES = {
    "en": {
        "still_there": "Sorry, are you still there?",
        "goodbye_silence": "I'll let you go for now. Thanks for your time — goodbye!",
        "goodbye_timeout": "I've taken enough of your time. Thank you so much — goodbye!",
        "goodbye_default": "Thank you so much for your time. Have a great day — goodbye!",
        "voicemail": "Sorry we missed you. We'll try again later. Thank you!",
        "acknowledgements": ("Okay.", "Mm-hmm.", "Got it.", "Right."),
    },
    "hi": {
        "still_there": "माफ़ कीजिए, क्या आप अभी भी लाइन पर हैं?",
        "goodbye_silence": "कोई बात नहीं, हम बाद में बात करेंगे। आपके समय के लिए धन्यवाद, नमस्ते!",
        "goodbye_timeout": "आपका काफ़ी समय ले लिया। बहुत-बहुत धन्यवाद, नमस्ते!",
        "goodbye_default": "आपके समय के लिए बहुत-बहुत धन्यवाद। आपका दिन शुभ हो, नमस्ते!",
        "voicemail": "माफ़ कीजिए, आपसे बात नहीं हो पाई। हम बाद में फिर कॉल करेंगे। धन्यवाद!",
        "acknowledgements": ("जी।", "अच्छा।", "ठीक है।", "जी, एक सेकंड।"),
    },
    "ur": {
        "still_there": "माफ़ कीजिए, क्या आप अभी लाइन पर हैं?",
        "goodbye_silence": "कोई बात नहीं, हम बाद में बात करेंगे। आपके वक़्त का शुक्रिया, ख़ुदा हाफ़िज़!",
        "goodbye_timeout": "आपका काफ़ी वक़्त ले लिया। बहुत-बहुत शुक्रिया, ख़ुदा हाफ़िज़!",
        "goodbye_default": "आपके वक़्त का बहुत शुक्रिया। आपका दिन अच्छा गुज़रे, ख़ुदा हाफ़िज़!",
        "voicemail": "माफ़ कीजिए, आपसे बात नहीं हो सकी। हम बाद में फिर कॉल करेंगे। शुक्रिया!",
        "acknowledgements": ("जी।", "अच्छा।", "ठीक है।"),
    },
    "hi-en": {
        "still_there": "Sorry, kya aap abhi line par hain?",
        "goodbye_silence": "Koi baat nahi, hum baad mein baat karenge. Thank you, bye!",
        "goodbye_timeout": "Aapka kaafi time le liya. Thank you so much, bye!",
        "goodbye_default": "Aapke time ke liye bahut shukriya. Aapka din achha ho, bye!",
        "voicemail": "Sorry, aapse baat nahi ho paayi. Hum baad mein phir call karenge. Thank you!",
        "acknowledgements": ("Haan ji.", "Achha.", "Theek hai.", "Okay."),
    },
}
PHRASE_FIELDS = (
    "still_there",
    "goodbye_silence",
    "goodbye_timeout",
    "goodbye_default",
    "voicemail",
    "acknowledgements",
)


def _nfc(value):
    if isinstance(value, str):
        return unicodedata.normalize("NFC", value)
    return tuple(_nfc(v) for v in value)


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


# The model wrapper picks its request shape from the configured provider, and
# the repo's .env may name any of them. Pin one per test.
ANTHROPIC_ENV = dict(MODEL_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant-test-key")
OPENAI_SHAPE_ENV = dict(MODEL_PROVIDER="gemini", GEMINI_API_KEY="test-gemini-key")


class FakeLLM:
    """Stands in for ConversationLLM. Each reply is (chunks, end_requested).

    Like the real wrapper, `end_requested` is reset when a turn starts; it is
    then set for the turn straight away, so a session that ignores an
    interruption and reads the flag anyway gets caught.
    """

    def __init__(self, replies: list[tuple[list[str], bool]], *, gap: float = 0.0) -> None:
        self._replies = list(replies)
        self._gap = gap
        self.end_requested = False
        self.recorded = []
        self.generating = asyncio.Event()

    def record(self, turn) -> None:
        self.recorded.append(turn)

    async def generate(self):
        self.end_requested = False
        chunks, end = self._replies.pop(0) if self._replies else (["Okay."], False)
        self.end_requested = end
        self.generating.set()
        for i, chunk in enumerate(chunks):
            if i:
                await asyncio.sleep(self._gap)
            else:
                await asyncio.sleep(0)
            yield chunk


class SilentListener:
    """The person never says anything and never interrupts."""

    async def utterances(self):
        await asyncio.Event().wait()
        yield ""  # pragma: no cover - unreachable, makes this a generator

    async def wait_for_speech_start(self) -> None:
        await asyncio.Event().wait()


class LineListener:
    """Says each line in turn, then stays on the line in silence.

    Staying on the line matters: a listener that ran out would look like a
    hang-up and end the call on its own, hiding whether the session decided
    to end it.
    """

    def __init__(self, lines: list[str], *, gap: float = 0.01, hang_up_after: bool = False) -> None:
        self._lines = list(lines)
        self._gap = gap
        self._hang_up_after = hang_up_after

    async def utterances(self):
        for line in self._lines:
            await asyncio.sleep(self._gap)
            yield line
        if not self._hang_up_after:
            await asyncio.Event().wait()

    async def wait_for_speech_start(self) -> None:
        await asyncio.Event().wait()


class InterruptFirstReply(LineListener):
    """Talks over the agent's first reply only, then behaves."""

    def __init__(self, lines: list[str], *, after: float) -> None:
        super().__init__(lines)
        self._after = after
        self._interrupted = False

    async def wait_for_speech_start(self) -> None:
        if not self._interrupted:
            self._interrupted = True
            await asyncio.sleep(self._after)
            return
        await asyncio.Event().wait()


class FastSpeaker(MockSpeaker):
    """MockSpeaker's contract, timed with one sleep per line.

    MockSpeaker sleeps once per character; on Windows' ~15ms timer that makes
    every line take the better part of a second whatever the rate. Same
    semantics here: `spoken` records what played, and `stop()` returns the
    prefix heard so far. `chars_per_second=None` plays instantly.
    """

    def __init__(self, *, chars_per_second: float | None = None) -> None:
        super().__init__()
        self._cps = chars_per_second
        self._started = 0.0

    async def say(self, text: str) -> None:
        loop = asyncio.get_running_loop()
        self._current, self._started = text, loop.time()
        await asyncio.sleep(len(text) / self._cps if self._cps else 0)
        self.spoken.append(text)
        self._current = ""

    async def stop(self) -> str:
        if not self._current:
            return ""
        heard = int((asyncio.get_running_loop().time() - self._started) * (self._cps or 1e9))
        partial = self._current[:heard].rstrip()
        self._current = ""
        if partial:
            self.spoken.append(partial)
        return partial


def _session(llm, listener, **kwargs) -> tuple[CallSession, MockSpeaker, MockControl]:
    speaker = kwargs.pop("speaker", None) or FastSpeaker()
    control = MockControl()
    kwargs.setdefault("max_duration_seconds", 5)
    kwargs.setdefault("silence_timeout_seconds", 0.5)
    session = CallSession(
        llm=llm,  # type: ignore[arg-type]
        listener=listener,
        speaker=speaker,
        control=control,
        greeting=GREETING,
        **kwargs,
    )
    return session, speaker, control


async def _run(session: CallSession, timeout: float = 3.0, task: asyncio.Task | None = None):
    """Run (or await) a session, failing with the transcript if it never ends."""
    try:
        return await asyncio.wait_for(task or session.run(), timeout)
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
        return SimpleNamespace(
            parsed_output=self._owner.outcome, stop_reason="end_turn", usage=None
        )


class FakeAnthropicClient:
    """Anthropic-shaped: `messages.stream` for the call, `messages.parse` for extraction."""

    def __init__(self, replies: list[list[str]], outcome: CallOutcome | None = None) -> None:
        self.replies = [list(r) for r in replies]
        self.outcome = outcome or CallOutcome(
            disposition=Disposition.COMPLETED,
            summary="The person confirmed the appointment.",
            needs_human_review=False,
        )
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
                    choices=[SimpleNamespace(delta=SimpleNamespace(content=delta))],
                    usage=None,
                )

        return events()


class FakeOpenAIClient:
    """The `chat/completions` shape (Gemini, OpenAI, Sarvam, NVIDIA)."""

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


# ---------------------------------------------------------------------------
# EndMarkerFilter
# ---------------------------------------------------------------------------


def test_the_end_marker_is_the_documented_token() -> None:
    from src.voiceagent.llm import END_CALL_MARKER

    assert END_CALL_MARKER == "[END_CALL]", END_CALL_MARKER


def test_a_marker_at_the_end_is_removed_and_flagged() -> None:
    """The farewell is spoken; the marker never reaches TTS."""
    from src.voiceagent.llm import EndMarkerFilter

    f = EndMarkerFilter()
    assert f.found is False
    out = f.feed("Thanks so much, goodbye! [END_CALL]") + f.flush()
    assert "[" not in out and "END_CALL" not in out, out
    assert out.strip() == "Thanks so much, goodbye!", out
    assert f.found is True


def test_a_marker_split_across_feeds_is_never_emitted() -> None:
    """Model deltas cut the marker anywhere; no fragment of it may be spoken.

    Text before the possible marker is safe and comes out at once; only the
    trailing `[EN` is held until it resolves.
    """
    from src.voiceagent.llm import EndMarkerFilter

    f = EndMarkerFilter()
    first = f.feed("Bye! [EN")
    assert "Bye!" in first, f"safe text was held back: {first!r}"
    assert "[" not in first, f"a marker fragment was emitted: {first!r}"
    assert f.found is False

    rest = f.feed("D_CA") + f.feed("LL]")
    assert f.found is True
    out = first + rest + f.flush()
    assert out.strip() == "Bye!", out

    # One character at a time is the worst case for a streaming filter.
    g = EndMarkerFilter()
    text = "Alright, take care. [END_CALL]"
    out = "".join(g.feed(ch) for ch in text) + g.flush()
    assert out.strip() == "Alright, take care.", out
    assert g.found is True


def test_everything_after_the_marker_is_dropped() -> None:
    """A model that keeps talking after the marker must not be heard."""
    from src.voiceagent.llm import EndMarkerFilter

    f = EndMarkerFilter()
    out = f.feed("Goodbye! [END_CALL] Oh, and one more thing")
    assert f.found is True
    out += f.feed(" about your bill.") + f.flush()
    assert out.strip() == "Goodbye!", out


def test_text_without_a_marker_passes_through_unchanged() -> None:
    from src.voiceagent.llm import EndMarkerFilter

    f = EndMarkerFilter()
    parts = ["Does Tuesday ", "at two work ", "for you?"]
    out = "".join(f.feed(p) for p in parts) + f.flush()
    assert out == "Does Tuesday at two work for you?", out
    assert f.found is False


def test_a_bracket_that_is_not_the_marker_is_released() -> None:
    """A held-back `[` is spoken once it turns out not to be the marker."""
    from src.voiceagent.llm import EndMarkerFilter

    f = EndMarkerFilter()
    first = f.feed("Room [")
    assert not first.endswith("["), f"a possible marker start was emitted early: {first!r}"
    out = first + f.feed("B] is free.") + f.flush()
    assert out == "Room [B] is free.", out
    assert f.found is False

    # Resolved at end of stream: a dangling prefix is flushed as text.
    g = EndMarkerFilter()
    out = g.feed("Press [EN") + g.flush()
    assert out == "Press [EN", out
    assert g.found is False

    # A near miss is not the marker.
    h = EndMarkerFilter()
    out = h.feed("See [END_CALLS] below.") + h.flush()
    assert out == "See [END_CALLS] below.", out
    assert h.found is False


# ---------------------------------------------------------------------------
# ConversationLLM
# ---------------------------------------------------------------------------


def test_the_model_wrapper_never_emits_the_marker_and_flags_the_end() -> None:
    """The marker is stripped before clause flushing, so no chunk carries any of it."""

    async def scenario() -> None:
        client = FakeAnthropicClient(
            [["Great, see you then", ". Bye! [END", "_CALL]"], ["Sure, what time suits you?"]]
        )
        llm = _llm(client)
        assert llm.end_requested is False

        chunks = await _drain(llm)
        assert all("[" not in c and "END_CALL" not in c for c in chunks), chunks
        assert " ".join(c.strip() for c in chunks) == "Great, see you then. Bye!", chunks
        assert llm.end_requested is True

        # Reset at the start of every turn.
        chunks = await _drain(llm)
        assert " ".join(chunks) == "Sure, what time suits you?", chunks
        assert llm.end_requested is False

    with _env(**ANTHROPIC_ENV):
        asyncio.run(scenario())


def test_a_turn_that_is_only_the_marker_yields_nothing_but_requests_the_end() -> None:
    async def scenario() -> None:
        llm = _llm(FakeAnthropicClient([["[END_", "CALL]"]]))
        chunks = await _drain(llm)
        assert chunks == [], chunks
        assert llm.end_requested is True

    with _env(**ANTHROPIC_ENV):
        asyncio.run(scenario())


def test_the_marker_is_filtered_on_the_chat_completions_path_too() -> None:
    """Gemini/OpenAI/Sarvam share the same filter: it sits before clause flushing."""

    async def scenario() -> None:
        llm = _llm(FakeOpenAIClient([["Theek hai, ", "phir milenge! [END_CA", "LL] extra"]]))
        chunks = await _drain(llm)
        joined = " ".join(c.strip() for c in chunks)
        assert "[" not in joined and "extra" not in joined, chunks
        assert joined == "Theek hai, phir milenge!", chunks
        assert llm.end_requested is True

    with _env(**OPENAI_SHAPE_ENV):
        asyncio.run(scenario())


def test_the_persona_tells_the_model_how_to_end_the_call() -> None:
    """The model can only use the marker if the prompt teaches it."""
    from src.voiceagent.llm import END_CALL_MARKER
    from src.voiceagent.prompts import VOICE_PERSONA

    assert END_CALL_MARKER in VOICE_PERSONA
    lowered = VOICE_PERSONA.lower()
    # One of the Hindi "I'm done" signals the spec lists must be named.
    assert "dhanyavaad" in lowered or "धन्यवाद" in VOICE_PERSONA, "no Hindi end signal in persona"


# ---------------------------------------------------------------------------
# Stock phrases
# ---------------------------------------------------------------------------


def test_phrases_match_the_spec_for_every_language() -> None:
    from src.voiceagent.voice.phrases import phrases_for

    for language, expected in EXPECTED_PHRASES.items():
        phrases = phrases_for(language)
        for field in PHRASE_FIELDS:
            got = getattr(phrases, field)
            assert _nfc(got) == _nfc(expected[field]), f"{language}.{field}: {got!r}"
        assert isinstance(phrases.acknowledgements, tuple), type(phrases.acknowledgements)


def test_phrases_fall_back_to_english_and_ignore_case() -> None:
    from src.voiceagent.voice.phrases import phrases_for

    english = phrases_for("en")
    for unknown in (None, "", "fr", "xx-YY"):
        assert phrases_for(unknown) == english, unknown
    assert phrases_for("HI") == phrases_for("hi")
    assert phrases_for("Hi-EN") == phrases_for("hi-en")
    assert phrases_for("UR") == phrases_for("ur")
    assert phrases_for("EN") == english


def test_phrases_are_immutable() -> None:
    import dataclasses

    from src.voiceagent.voice.phrases import CallPhrases, phrases_for

    phrases = phrases_for("hi")
    assert isinstance(phrases, CallPhrases)
    try:
        phrases.still_there = "changed"  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("CallPhrases must be a frozen dataclass")


# ---------------------------------------------------------------------------
# Session: when the call ends, and what is said
# ---------------------------------------------------------------------------


def test_the_call_ends_when_the_model_asks_to_end_it() -> None:
    """end_requested ends the call after the reply, even without goodbye words."""

    async def scenario() -> None:
        llm = FakeLLM([(["Perfect, you're booked for Tuesday at two."], True)])
        session, _speaker, control = _session(
            llm, LineListener(["Yes, Tuesday works.", "Also, one more thing."])
        )
        transcript = await _run(session)
        texts = [t.text for t in transcript]
        assert texts == [
            GREETING,
            "Yes, Tuesday works.",
            "Perfect, you're booked for Tuesday at two.",
        ], texts
        assert control.hung_up

    asyncio.run(scenario())


def test_a_model_that_ends_silently_still_says_goodbye_in_the_calls_language() -> None:
    """The person hears a warm Hindi goodbye, not dead air and not English."""
    from src.voiceagent.voice.phrases import phrases_for

    hindi = phrases_for("hi")

    async def scenario() -> None:
        llm = FakeLLM([([], True)])
        session, speaker, control = _session(llm, LineListener(["बस, इतना ही।"]), phrases=hindi)
        transcript = await _run(session)
        texts = [t.text for t in transcript]
        assert texts == [GREETING, "बस, इतना ही।", hindi.goodbye_default], texts
        assert hindi.goodbye_default in speaker.spoken, speaker.spoken
        assert control.hung_up

    asyncio.run(scenario())


def test_without_phrases_the_session_says_the_english_goodbye() -> None:
    async def scenario() -> None:
        session, _speaker, _control = _session(FakeLLM([([], True)]), LineListener(["That's all."]))
        transcript = await _run(session)
        assert transcript[-1].text == EXPECTED_PHRASES["en"]["goodbye_default"], transcript[-1].text

    asyncio.run(scenario())


def test_silence_lines_are_spoken_in_the_calls_language() -> None:
    """No hard-coded English: a Hindi call asks "are you there?" in Hindi."""
    from src.voiceagent.voice.phrases import phrases_for

    hindi = phrases_for("hi")

    async def scenario() -> None:
        session, _speaker, control = _session(
            FakeLLM([]), SilentListener(), phrases=hindi, silence_timeout_seconds=0.05
        )
        transcript = await _run(session)
        texts = [t.text for t in transcript]
        assert texts == [GREETING, hindi.still_there, hindi.goodbye_silence], texts
        assert control.hung_up

    asyncio.run(scenario())


def test_the_default_silence_lines_are_the_english_phrases() -> None:
    async def scenario() -> None:
        session, _speaker, _control = _session(
            FakeLLM([]), SilentListener(), silence_timeout_seconds=0.05
        )
        transcript = await _run(session)
        texts = [t.text for t in transcript]
        assert texts == [
            GREETING,
            EXPECTED_PHRASES["en"]["still_there"],
            EXPECTED_PHRASES["en"]["goodbye_silence"],
        ], texts

    asyncio.run(scenario())


def test_hitting_max_duration_says_goodbye_in_the_calls_language() -> None:
    from src.voiceagent.voice.phrases import phrases_for

    urdu = phrases_for("ur")

    async def scenario() -> None:
        session, _speaker, control = _session(
            FakeLLM([]),
            SilentListener(),
            phrases=urdu,
            silence_timeout_seconds=5,
            max_duration_seconds=0.2,
        )
        transcript = await _run(session)
        assert transcript[-1].text == urdu.goodbye_timeout, [t.text for t in transcript]
        assert control.hung_up

    asyncio.run(scenario())


def test_an_interrupted_reply_never_ends_the_call() -> None:
    """The person talked over the goodbye: they have something to say, so listen.

    The first reply both asks to end and says "goodbye", but is cut off. The
    call must go on; the next reply (which does end it) is the last turn, and
    nothing after it is heard.
    """

    async def scenario() -> None:
        llm = FakeLLM(
            [
                (["Alright, that's everything, thanks so much for your time, goodbye and take care!"], True),
                (["Sure, Friday works, you're all set."], True),
            ]
        )
        listener = InterruptFirstReply(
            ["Yes, that works.", "Wait, can we do Friday?", "Hello?"], after=0.05
        )
        session, _speaker, control = _session(
            llm, listener, speaker=FastSpeaker(chars_per_second=200.0)
        )
        transcript = await _run(session)
        user = [t.text for t in transcript if t.role == "user"]
        assert user == ["Yes, that works.", "Wait, can we do Friday?"], user
        assert transcript[-1].text == "Sure, Friday works, you're all set.", transcript[-1].text
        assert control.hung_up

    asyncio.run(scenario())


def test_a_bare_thank_you_from_the_agent_does_not_end_the_call() -> None:
    """"Dhanyavaad" mid-conversation is politeness, not a farewell."""

    async def scenario() -> None:
        llm = FakeLLM(
            [
                (["Thank you!"], False),
                (["Dhanyavaad."], False),
                (["धन्यवाद।"], False),
                (["Shukriya!"], False),
            ]
        )
        lines = ["Haan ji.", "Tuesday theek hai.", "Do baje.", "Bas itna hi.", "Okay."]
        session, _speaker, _control = _session(
            llm, LineListener(lines, hang_up_after=True), silence_timeout_seconds=2
        )
        transcript = await _run(session)
        user = [t.text for t in transcript if t.role == "user"]
        assert user == lines, f"the call ended on a thank-you: {[t.text for t in transcript]}"

    asyncio.run(scenario())


def test_a_hindi_farewell_ends_the_call_even_without_the_marker() -> None:
    async def scenario() -> None:
        llm = FakeLLM([(["ठीक है, फिर मिलेंगे।"], False)])
        session, _speaker, control = _session(
            llm, LineListener(["हाँ, बस इतना ही।", "हैलो?"])
        )
        transcript = await _run(session)
        texts = [t.text for t in transcript]
        assert texts == [GREETING, "हाँ, बस इतना ही।", "ठीक है, फिर मिलेंगे।"], texts
        assert control.hung_up

    asyncio.run(scenario())


def test_request_end_while_waiting_says_goodbye_and_hangs_up() -> None:
    """The operator's "End call" button while the line is quiet."""
    from src.voiceagent.voice.phrases import phrases_for

    hinglish = phrases_for("hi-en")

    async def scenario() -> None:
        session, _speaker, control = _session(
            FakeLLM([]), SilentListener(), phrases=hinglish, silence_timeout_seconds=5
        )
        run = asyncio.create_task(session.run())
        await _until(lambda: len(session.transcript) >= 1, what="the greeting")
        result = session.request_end()
        if inspect.isawaitable(result):
            await result
        transcript = await _run(session, 2, run)
        texts = [t.text for t in transcript]
        assert texts == [GREETING, hinglish.goodbye_default], texts
        assert control.hung_up

    asyncio.run(scenario())


def test_request_end_mid_reply_ends_right_after_that_reply() -> None:
    """The reply in progress finishes; nothing more is said or heard."""

    async def scenario() -> None:
        llm = FakeLLM([(["Let me check that for you.", "Tuesday at two is free."], False)], gap=0.1)
        session, _speaker, control = _session(
            llm, LineListener(["Is Tuesday free?", "Great, book it."]), silence_timeout_seconds=5
        )
        run = asyncio.create_task(session.run())
        await asyncio.wait_for(llm.generating.wait(), 2)
        result = session.request_end()
        if inspect.isawaitable(result):
            await result
        transcript = await _run(session, 2, run)
        texts = [t.text for t in transcript]
        assert texts == [
            GREETING,
            "Is Tuesday free?",
            "Let me check that for you. Tuesday at two is free.",
        ], texts
        assert control.hung_up

    asyncio.run(scenario())


# ---------------------------------------------------------------------------
# The closing heuristic
# ---------------------------------------------------------------------------


def test_is_closing_recognises_farewells_in_every_language() -> None:
    from src.voiceagent.voice.session import _is_closing

    farewells = [
        "Goodbye!",
        "Theek hai ji, alvida!",
        "Alvida!",
        "ठीक है, अलविदा।",
        "Accha ji, khuda hafiz.",
        "Khuda Hafiz!",
        "बहुत शुक्रिया, ख़ुदा हाफ़िज़!",
        "شکریہ، خدا حافظ",
        "Chaliye, phir milenge!",
        "ठीक है, फिर मिलेंगे।",
    ]
    missed = [text for text in farewells if not _is_closing(text)]
    assert not missed, f"not recognised as closing: {missed}"


def test_is_closing_ignores_a_bare_thank_you() -> None:
    """Thanks are said all through a call; only a farewell ends it."""
    from src.voiceagent.voice.session import _is_closing

    thanks = [
        "Dhanyavaad.",
        "धन्यवाद।",
        "Shukriya!",
        "शुक्रिया।",
        "Thank you.",
        "Thank you so much!",
        "Thanks!",
    ]
    wrong = [text for text in thanks if _is_closing(text)]
    assert not wrong, f"a bare thank-you counted as closing: {wrong}"

    # नमस्ते is also a greeting; as a farewell it is the marker's job.
    assert not _is_closing("नमस्ते! मैं Smile Dental से बोल रही हूँ।")


# ---------------------------------------------------------------------------
# Callers: the pipeline passes the campaign's language through
# ---------------------------------------------------------------------------


async def _temp_db():
    path = Path(tempfile.mkdtemp()) / "call_ending.db"
    engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
    async with engine.begin() as conn:
        await conn.run_sync(storage.Base.metadata.create_all)
    return engine, async_sessionmaker(engine, expire_on_commit=False)


async def _seed_hindi_campaign(sessions):
    async with sessions() as db:
        db.add(
            storage.Campaign(
                id="camp-hi",
                name="Smile Dental",
                goal="Remind Asha about her cleaning on Tuesday.",
                language="hi",
                greeting="नमस्ते {first_name}, Smile Dental से बात कर रहे हैं।",
            )
        )
        db.add(
            storage.Contact(
                id="ct-hi",
                campaign_id="camp-hi",
                full_name="Asha Rao",
                phone_e164="+919800000001",
                timezone="Asia/Kolkata",
            )
        )
        await db.commit()
    async with sessions() as db:
        return await db.get(storage.Contact, "ct-hi"), await db.get(storage.Campaign, "camp-hi")


class _NoSuppression:
    async def suppress(self, *, contact_id: str, reason: str) -> None:
        pass


class _FakeTelephony:
    """Answers at once with the given listener and a fast speaker."""

    def __init__(self, listener, *, machine: bool = False) -> None:
        self.listener = listener
        self.speaker = FastSpeaker()
        self.control = MockControl()
        self.machine = machine
        self.calls: list[tuple] = []

    def prepare_call(self, room_name: str, *, language: str, greeting: str) -> None:
        self.calls.append(("prepare_call", room_name, language, greeting))

    async def dial(self, *, phone_e164: str, room_name: str):
        self.calls.append(("dial", room_name))
        return self.listener, self.speaker, self.control, "CA-test"

    def get_call_state(self, room_name: str):
        return SimpleNamespace(
            amd_result="machine_start" if self.machine else None,
            recording_url=None,
            recording_sid=None,
            recording_duration=None,
        )


async def _place_call(telephony, client) -> None:
    from src.voiceagent.voice.pipeline import CallPipeline

    engine, sessions = await _temp_db()
    try:
        contact, campaign = await _seed_hindi_campaign(sessions)
        pipeline = CallPipeline(
            sessions,
            client,
            telephony,
            calendar=MockCalendar(),
            records=MockRecords(),
            suppression=_NoSuppression(),
            followups=False,
        )
        # A call that doesn't end falls back to a 12s silence timeout; fail fast.
        try:
            await asyncio.wait_for(pipeline.place_call(contact, campaign), 4)
        except asyncio.TimeoutError:
            raise AssertionError(
                f"the campaign call did not end within 4s; spoken: {telephony.speaker.spoken}"
            ) from None
    finally:
        await engine.dispose()


def test_voicemail_is_left_in_the_campaigns_language() -> None:
    from src.voiceagent.voice.phrases import phrases_for

    hindi = phrases_for("hi")

    async def scenario() -> None:
        telephony = _FakeTelephony(SilentListener(), machine=True)
        await _place_call(telephony, FakeAnthropicClient([]))
        spoken = " ".join(telephony.speaker.spoken)
        assert _nfc(hindi.voicemail) in _nfc(spoken), spoken
        assert "नमस्ते Asha" in spoken, spoken
        assert "unable to reach you" not in spoken, spoken
        assert telephony.control.hung_up

    with _env(**ANTHROPIC_ENV):
        asyncio.run(scenario())


def test_a_hindi_campaign_call_that_ends_silently_says_goodbye_in_hindi() -> None:
    """End to end through the pipeline: marker filtered, Hindi goodbye, no English."""
    from src.voiceagent.voice.phrases import phrases_for

    hindi = phrases_for("hi")

    async def scenario() -> None:
        telephony = _FakeTelephony(LineListener(["ठीक है, धन्यवाद।"]))
        await _place_call(telephony, FakeAnthropicClient([["[END_CALL]"]]))
        spoken = telephony.speaker.spoken
        assert spoken[-1] == hindi.goodbye_default, spoken
        assert not any("END_CALL" in s or "still there" in s.lower() for s in spoken), spoken
        assert telephony.control.hung_up

    with _env(**ANTHROPIC_ENV):
        asyncio.run(scenario())


def test_a_hindi_farewell_is_spoken_without_the_marker_and_ends_the_call() -> None:
    async def scenario() -> None:
        telephony = _FakeTelephony(LineListener(["ठीक है, धन्यवाद।"]))
        client = FakeAnthropicClient([["जी, आपका दिन शुभ हो। नमस्ते! [END", "_CALL]"]])
        await _place_call(telephony, client)
        spoken = " ".join(telephony.speaker.spoken)
        assert "END_CALL" not in spoken and "[" not in spoken, spoken
        assert spoken.endswith("जी, आपका दिन शुभ हो। नमस्ते!"), spoken
        assert "still there" not in spoken.lower(), spoken
        assert telephony.control.hung_up

    with _env(**ANTHROPIC_ENV):
        asyncio.run(scenario())


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
