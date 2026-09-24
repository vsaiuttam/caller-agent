"""Tests for the logic that's easiest to get subtly wrong.

Runs standalone (`python tests/test_core.py`) or under pytest. No API key and
no network — the two areas covered here are exactly the ones that don't need
either, and that would be miserable to debug against a live phone call.
"""

from __future__ import annotations

import asyncio
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.voiceagent.integrations.mocks import (  # noqa: E402
    InterruptingListener,
    MockControl,
    MockSpeaker,
)
from src.voiceagent.models import Disposition, Turn  # noqa: E402
from src.voiceagent.orchestrator.scheduler import (  # noqa: E402
    BACKOFF,
    EXHAUSTED,
    OK,
    OUTSIDE_HOURS,
    SUPPRESSED,
    CallingWindow,
    check_eligibility,
    is_terminal,
    next_attempt_after,
    next_window_open,
)
from src.voiceagent.voice.session import CallSession  # noqa: E402

BUSINESS_HOURS = CallingWindow(9, 20, frozenset({1, 2, 3, 4, 5}))


# ---------------------------------------------------------------------------
# Scheduler
# ---------------------------------------------------------------------------


def test_calling_hours_use_contact_timezone() -> None:
    """18:00 UTC on a Wednesday: 13:00 in New York, 02:00 in Tokyo."""
    now = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)

    base = dict(
        window=BUSINESS_HOURS,
        now_utc=now,
        attempts=0,
        max_attempts=3,
        next_attempt_at=None,
        is_suppressed=False,
    )

    assert check_eligibility(tz_name="America/New_York", **base) == OK
    assert check_eligibility(tz_name="Asia/Tokyo", **base) == OUTSIDE_HOURS


def test_weekend_is_excluded() -> None:
    saturday = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)  # 12:00 NY, Sat
    assert (
        check_eligibility(
            tz_name="America/New_York",
            window=BUSINESS_HOURS,
            now_utc=saturday,
            attempts=0,
            max_attempts=3,
            next_attempt_at=None,
            is_suppressed=False,
        )
        == OUTSIDE_HOURS
    )


def test_suppression_beats_everything() -> None:
    """A suppressed number is rejected even inside the window with attempts left."""
    now = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)
    assert (
        check_eligibility(
            tz_name="America/New_York",
            window=BUSINESS_HOURS,
            now_utc=now,
            attempts=0,
            max_attempts=3,
            next_attempt_at=None,
            is_suppressed=True,
        )
        == SUPPRESSED
    )


def test_backoff_and_exhaustion() -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)
    common = dict(
        tz_name="America/New_York",
        window=BUSINESS_HOURS,
        now_utc=now,
        max_attempts=3,
        is_suppressed=False,
    )

    assert check_eligibility(attempts=3, next_attempt_at=None, **common) == EXHAUSTED
    assert (
        check_eligibility(
            attempts=1, next_attempt_at=now + timedelta(hours=1), **common
        )
        == BACKOFF
    )
    assert (
        check_eligibility(
            attempts=1, next_attempt_at=now - timedelta(hours=1), **common
        )
        == OK
    )


def test_next_window_open_rolls_to_monday() -> None:
    """Saturday afternoon in NY should resolve to Monday 09:00 local."""
    saturday = datetime(2026, 8, 15, 16, 0, tzinfo=timezone.utc)
    opens = next_window_open("America/New_York", BUSINESS_HOURS, saturday)

    from zoneinfo import ZoneInfo

    local = opens.astimezone(ZoneInfo("America/New_York"))
    assert local.isoweekday() == 1, f"expected Monday, got weekday {local.isoweekday()}"
    assert local.hour == 9, f"expected 09:00, got {local.hour}:00"


def test_retry_policy_terminal_states() -> None:
    now = datetime(2026, 8, 12, 18, 0, tzinfo=timezone.utc)

    for disposition in (
        Disposition.COMPLETED,
        Disposition.DECLINED,
        Disposition.DO_NOT_CALL,
        Disposition.WRONG_NUMBER,
    ):
        assert is_terminal(disposition), disposition
        assert next_attempt_after(disposition, 1, now) is None

    assert not is_terminal(Disposition.NO_ANSWER)

    # Backoff must grow, or a number that never answers gets dialled daily.
    first = next_attempt_after(Disposition.NO_ANSWER, 1, now)
    second = next_attempt_after(Disposition.NO_ANSWER, 2, now)
    assert first and second and second > first


# ---------------------------------------------------------------------------
# Barge-in
# ---------------------------------------------------------------------------


class FakeLLM:
    """Stands in for ConversationLLM without touching the API."""

    def __init__(self, replies: list[list[str]]) -> None:
        self._replies = replies
        self.recorded: list[Turn] = []

    def record(self, turn: Turn) -> None:
        self.recorded.append(turn)

    async def generate(self):
        chunks = self._replies.pop(0) if self._replies else ["Alright, goodbye."]
        for chunk in chunks:
            await asyncio.sleep(0)
            yield chunk


def test_barge_in_records_only_what_was_heard() -> None:
    """The transcript must not contain text the caller was cut off before hearing.

    This is the failure that silently corrupts a call: if the agent believes it
    delivered something it did not, it never repeats it, and the rest of the
    conversation proceeds on a false shared understanding.
    """

    async def scenario() -> None:
        llm = FakeLLM(
            [
                [
                    "Your appointment is on Tuesday at two.",
                    "We also have Thursday morning free if that suits better.",
                ],
                ["No problem at all. Goodbye."],
            ]
        )
        listener = InterruptingListener(["Sorry, hang on."], interrupt_after=0.02)
        speaker = MockSpeaker(chars_per_second=200.0)

        session = CallSession(
            llm=llm,  # type: ignore[arg-type]
            listener=listener,
            speaker=speaker,
            control=MockControl(),
            greeting="Hi, quick call about your appointment.",
            max_duration_seconds=5,
            silence_timeout_seconds=0.3,
        )
        transcript = await session.run()

        agent_text = " ".join(t.text for t in transcript if t.role == "assistant")
        spoken_text = " ".join(speaker.spoken)

        # Nothing may be claimed that the speaker never played.
        for turn in transcript:
            if turn.role != "assistant":
                continue
            assert turn.text in spoken_text or any(
                turn.text in played for played in speaker.spoken
            ), f"transcript claims unspoken text: {turn.text!r}"

        assert "Hi, quick call" in agent_text

    asyncio.run(scenario())


class SlowToAnswerListener:
    """Says nothing for longer than the silence timeout, then answers."""

    def __init__(self, delay: float, line: str) -> None:
        self._delay = delay
        self._line = line

    async def utterances(self):
        await asyncio.sleep(self._delay)
        yield self._line

    async def wait_for_speech_start(self) -> None:
        await asyncio.Event().wait()


def test_a_long_pause_does_not_end_the_call() -> None:
    """After "are you still there?", the person's answer must still be heard.

    Timing out a read used to cancel the listener's generator mid-await,
    which finalises it — so the session took the first long pause for a
    hang-up and ended the call right after asking whether they were there.
    """

    async def scenario() -> list[Turn]:
        session = CallSession(
            llm=FakeLLM([["Great, thanks. Goodbye."]]),  # type: ignore[arg-type]
            listener=SlowToAnswerListener(0.25, "Sorry, yes, I'm here."),
            speaker=MockSpeaker(chars_per_second=10_000.0),
            control=MockControl(),
            greeting="Hi, quick call.",
            max_duration_seconds=5,
            silence_timeout_seconds=0.1,
        )
        return await session.run()

    texts = [t.text for t in asyncio.run(scenario())]
    assert texts[1] == "Sorry — are you still there?", texts
    assert "Sorry, yes, I'm here." in texts, texts
    assert texts[-1] == "Great, thanks. Goodbye.", texts


# ---------------------------------------------------------------------------
# Schema
# ---------------------------------------------------------------------------


def test_an_added_boolean_column_uses_a_default_postgres_accepts() -> None:
    """Postgres rejects `BOOLEAN DEFAULT 0`, and this runs at startup.

    A 1/0 literal passed every local run on SQLite and then stopped the API
    from booting on Render's Postgres.
    """
    from sqlalchemy import create_engine, text

    from src.voiceagent.storage import Base, Campaign, _add_missing_columns, _default_literal

    assert _default_literal(Campaign.__table__.c.whatsapp_followup) == "FALSE"

    # And the keyword still works end to end on SQLite.
    engine = create_engine("sqlite://")
    with engine.begin() as conn:
        Base.metadata.create_all(conn)
        conn.execute(Campaign.__table__.insert().values(id="c1", name="n", goal="g"))
        # An existing database from before the column was added.
        conn.execute(text("ALTER TABLE campaigns DROP COLUMN whatsapp_followup"))
        _add_missing_columns(conn)
        value = conn.execute(text("SELECT whatsapp_followup FROM campaigns")).scalar()
    assert value == 0, value


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
