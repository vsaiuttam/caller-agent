"""Tests for the live-microphone call protocol.

The browser is not here, so it's faked: a scripted list of messages in, a
captured list out. What matters is the same property the phone path has to
hold — the transcript may only contain what the person actually heard — plus
the message contract the frontend is written against.

Runs standalone (`python tests/test_live.py`) or under pytest. No API key and
no network.
"""

from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.voiceagent.live import LiveCall  # noqa: E402
from src.voiceagent.models import CallContext, Contact, Turn  # noqa: E402


class FakeLLM:
    """Stands in for ConversationLLM without touching the API."""

    def __init__(self, replies: list[list[str]]) -> None:
        self._replies = replies
        self.model = "fake-model"
        self.recorded: list[Turn] = []

    def record(self, turn: Turn) -> None:
        self.recorded.append(turn)

    async def generate(self):
        chunks = self._replies.pop(0) if self._replies else ["Alright, goodbye."]
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk


class FakeBrowser:
    """A scripted tab. Sends `script` in order, records everything received."""

    def __init__(self, script: list[dict]) -> None:
        self._script = list(script)
        self.sent: list[dict] = []

    async def send(self, message: dict) -> None:
        self.sent.append(message)

    async def receive(self) -> dict:
        if not self._script:
            raise ConnectionError("browser closed")
        await asyncio.sleep(0)
        return self._script.pop(0)

    def spoken_text(self) -> str:
        return " ".join(m["text"] for m in self.sent if m["type"] == "speak")

    def types(self) -> list[str]:
        return [m["type"] for m in self.sent]


def _call(llm: FakeLLM, greeting: str = "Hi, quick call about your appointment.") -> LiveCall:
    """A LiveCall with its model swapped for a fake.

    Constructed without an Anthropic client on purpose — nothing in the
    conversation loop touches one, and requiring a key to test turn-taking
    would defeat the point.
    """
    call = LiveCall.__new__(LiveCall)
    call._client = None
    call._contact = Contact(
        contact_id="test", full_name="Alex Morgan", phone_e164="+10000000000", timezone="UTC"
    )
    call._context = CallContext(campaign_id="test", goal="Confirm the appointment.")
    call._greeting = greeting
    call._extraction_model = None
    call._extraction_effort = None
    call._max_turns = 20
    call._llm = llm
    call.usage = None
    call.transcript = []
    call.turns = []
    call.ended_because = "the connection closed"
    call.disconnected = False
    call._turn_no = 0
    call._pending_ms = (None, None)
    return call


def test_greeting_is_only_recorded_once_the_browser_confirms_it() -> None:
    """Nothing is in the transcript until the speaker says it played.

    The greeting is sent for playback immediately, but an agent turn that the
    person never heard must not enter the history the model reasons over.
    """

    async def scenario() -> None:
        llm = FakeLLM([])
        call = _call(llm)
        browser = FakeBrowser([{"type": "end", "reason": "you hung up"}])

        await call.run(browser)

        assert "quick call" in browser.spoken_text(), browser.sent
        assert call.transcript == [], "greeting was recorded before it was played"

    asyncio.run(scenario())


def test_barge_in_records_only_the_played_prefix() -> None:
    """The transcript must not claim text the person was cut off before hearing.

    This is the failure that silently corrupts a call: if the agent believes
    it delivered something it did not, it never repeats it, and the rest of
    the conversation runs on a false shared understanding.
    """

    async def scenario() -> None:
        llm = FakeLLM(
            [
                [
                    "Your appointment is on Tuesday at two.",
                    "We also have Thursday morning free if that suits.",
                ]
            ]
        )
        call = _call(llm)
        browser = FakeBrowser(
            [
                {"type": "spoken", "text": "Hi, quick call about your appointment."},
                {"type": "utterance", "text": "Yeah, what about it?"},
                # Cut the agent off after the first sentence.
                {"type": "interrupt"},
                {"type": "spoken", "text": "Your appointment is on Tuesday at two."},
                {"type": "utterance", "text": "Sorry, hang on."},
                {"type": "spoken", "text": "No problem at all."},
                {"type": "end", "reason": "you hung up"},
            ]
        )

        await call.run(browser)

        agent_turns = [t.text for t in call.transcript if t.role == "assistant"]
        assert "Thursday" not in " ".join(agent_turns), (
            f"transcript claims unheard text: {agent_turns}"
        )
        assert "Your appointment is on Tuesday at two." in agent_turns
        assert call.ended_because == "you hung up"

    asyncio.run(scenario())


def test_an_unconfirmed_turn_is_dropped_rather_than_assumed() -> None:
    """Silence from the speaker means nothing was heard, so nothing is recorded.

    The agent repeating itself is recoverable. The agent convinced it already
    said something is not — so the ambiguous case fails towards repeating.
    """

    async def scenario() -> None:
        llm = FakeLLM([["Tuesday at two works."]])
        call = _call(llm)
        browser = FakeBrowser(
            [
                {"type": "spoken", "text": "Hi, quick call about your appointment."},
                {"type": "utterance", "text": "When is it?"},
                # No `spoken` for the answer — the tab's voice never played it.
                {"type": "utterance", "text": "Hello? Are you there?"},
                {"type": "end", "reason": "you hung up"},
            ]
        )

        await call.run(browser)

        agent_turns = [t.text for t in call.transcript if t.role == "assistant"]
        assert agent_turns == ["Hi, quick call about your appointment."], agent_turns

    asyncio.run(scenario())


def test_saying_goodbye_tells_the_browser_the_call_is_over() -> None:
    """Same closing heuristic as a real call, surfaced to the tab."""

    async def scenario() -> None:
        llm = FakeLLM([["That's all sorted. Thanks for your time, and goodbye."]])
        call = _call(llm)
        browser = FakeBrowser(
            [
                {"type": "spoken", "text": "Hi, quick call about your appointment."},
                {"type": "utterance", "text": "Tuesday is fine."},
                {"type": "spoken", "text": "That's all sorted. Thanks for your time, and goodbye."},
                {"type": "end", "reason": "the agent closed the call"},
            ]
        )

        await call.run(browser)

        assert "closing" in browser.types(), browser.types()

    asyncio.run(scenario())


def test_a_dropped_tab_is_a_disconnect_not_a_hangup() -> None:
    """Extraction is skipped when nobody is left to read it."""

    async def scenario() -> None:
        call = _call(FakeLLM([]))
        browser = FakeBrowser([])  # closes immediately

        await call.run(browser)

        assert call.disconnected
        assert call.ended_because == "the connection closed"

    asyncio.run(scenario())


def test_turn_timing_is_attached_to_the_turn_that_was_heard() -> None:
    """Latency is reported per confirmed turn, not per generated one."""

    async def scenario() -> None:
        llm = FakeLLM([["Tuesday at two works."]])
        call = _call(llm)
        browser = FakeBrowser(
            [
                {"type": "spoken", "text": "Hi, quick call about your appointment."},
                {"type": "utterance", "text": "When is it?"},
                {"type": "spoken", "text": "Tuesday at two works."},
                {"type": "end", "reason": "you hung up"},
            ]
        )

        await call.run(browser)

        answer = call.turns[-1]
        assert answer.role == "assistant"
        assert answer.first_chunk_ms is not None and answer.first_chunk_ms >= 0
        assert answer.total_ms is not None

        ends = [m for m in browser.sent if m["type"] == "turn_end"]
        assert ends[-1]["interrupted"] is False

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
