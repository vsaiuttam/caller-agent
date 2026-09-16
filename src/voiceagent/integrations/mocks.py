"""Mock implementations so the full loop runs with no external accounts.

`MockTelephony` is the useful one: it replaces the phone line with a scripted
counterpart, which means the runner, the LLM turn loop, extraction, dispatch,
and the live UI feed can all be exercised end to end using nothing but an
Anthropic key. It also makes the barge-in path reproducible, which a real
phone call never is.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from collections.abc import AsyncIterator

from ..models import CallOutcome

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Post-call integrations
# --------------------------------------------------------------------------


class MockCalendar:
    def __init__(self) -> None:
        self.events: list[dict] = []

    async def create_event(self, **kwargs) -> str:
        event_id = f"mock-event-{uuid.uuid4().hex[:8]}"
        self.events.append({"id": event_id, **kwargs})
        logger.info("[mock calendar] %s at %s", kwargs.get("subject"), kwargs.get("starts_at_local"))
        return event_id


class MockRecords:
    def __init__(self) -> None:
        self.calls: list[tuple[str, CallOutcome]] = []
        self.fields: list[tuple[str, dict[str, str]]] = []

    async def log_call(self, *, contact_id: str, outcome: CallOutcome) -> None:
        self.calls.append((contact_id, outcome))
        logger.info("[mock records] logged %s -> %s", contact_id, outcome.disposition.value)

    async def upsert_fields(self, *, contact_id: str, fields: dict[str, str]) -> None:
        self.fields.append((contact_id, fields))
        logger.info("[mock records] wrote %d fields for %s", len(fields), contact_id)


# --------------------------------------------------------------------------
# Telephony
# --------------------------------------------------------------------------


class ScriptedListener:
    """Replays a fixed set of caller utterances with realistic pacing."""

    def __init__(self, script: list[str], *, gap_seconds: float = 0.4) -> None:
        self._script = list(script)
        self._gap = gap_seconds
        self._speech_started = asyncio.Event()

    async def utterances(self) -> AsyncIterator[str]:
        for line in self._script:
            await asyncio.sleep(self._gap)
            yield line

    async def wait_for_speech_start(self) -> None:
        # Never fires: the scripted caller waits politely rather than
        # interrupting. Barge-in is covered by InterruptingListener below.
        await self._speech_started.wait()


class InterruptingListener(ScriptedListener):
    """Cuts the agent off mid-sentence. Use to exercise the barge-in path."""

    def __init__(self, script: list[str], *, interrupt_after: float = 0.35) -> None:
        super().__init__(script)
        self._interrupt_after = interrupt_after

    async def wait_for_speech_start(self) -> None:
        await asyncio.sleep(self._interrupt_after)


class MockSpeaker:
    """Records what was 'played', including partial playback on interruption."""

    def __init__(self, *, chars_per_second: float = 16.0) -> None:
        self._rate = chars_per_second
        self._current = ""
        self._played_chars = 0
        self.spoken: list[str] = []

    async def say(self, text: str) -> None:
        self._current = text
        self._played_chars = 0
        # Simulate playback time so interruption lands mid-utterance the way
        # it would on a real call.
        for i, _ in enumerate(text, start=1):
            await asyncio.sleep(1 / self._rate)
            self._played_chars = i
        self.spoken.append(text)
        self._current = ""

    async def stop(self) -> str:
        partial = self._current[: self._played_chars].rstrip()
        self._current = ""
        self._played_chars = 0
        if partial:
            self.spoken.append(partial)
        return partial


class MockControl:
    def __init__(self) -> None:
        self.hung_up = False

    async def hangup(self) -> None:
        self.hung_up = True


class MockTelephony:
    """Answers every call with a scripted counterpart."""

    DEFAULT_SCRIPT = [
        "Yeah, sure, I've got a minute.",
        "Tuesday afternoon works better for me, if you have anything then.",
        "Two o'clock is fine.",
        "No, that's everything. Thanks.",
    ]

    def __init__(
        self,
        script: list[str] | None = None,
        *,
        answer_rate: float = 1.0,
        interrupting: bool = False,
    ) -> None:
        self._script = script or self.DEFAULT_SCRIPT
        self._answer_rate = answer_rate
        self._interrupting = interrupting

    async def dial(self, *, phone_e164: str, room_name: str):
        await asyncio.sleep(0.5)  # ring

        if self._answer_rate < 1.0:
            import random

            if random.random() > self._answer_rate:
                raise ConnectionError(f"No answer from {phone_e164}")

        listener = (
            InterruptingListener(self._script)
            if self._interrupting
            else ScriptedListener(self._script)
        )
        logger.info("[mock telephony] connected %s in %s", phone_e164, room_name)
        return listener, MockSpeaker(), MockControl(), f"mock-sid-{uuid.uuid4().hex[:8]}"
