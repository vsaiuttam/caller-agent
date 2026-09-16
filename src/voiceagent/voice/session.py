"""The live call: turn-taking, barge-in, transcript integrity.

Transport-agnostic on purpose. Everything the call actually *decides* lives
here and is testable with fakes; LiveKit, Deepgram, and Cartesia sit behind
the three protocols below. That keeps the logic stable across plugin API
churn, and means the barge-in behaviour can be tested without a phone line.

The subtle part is transcript integrity under barge-in. When the person
interrupts, the model has usually generated further ahead than the speaker
has played. If we record the generated text, the model believes it delivered
information the person never heard and will not repeat it — so the call
proceeds on a false shared understanding. We therefore record only what the
speaker confirms was played.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import Protocol

from ..llm import ConversationLLM
from ..models import Turn

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Transport seams
# --------------------------------------------------------------------------


class Listener(Protocol):
    """Streaming speech-to-text."""

    def utterances(self) -> AsyncIterator[str]:
        """Yield final user utterances as they complete."""
        ...

    async def wait_for_speech_start(self) -> None:
        """Resolve as soon as the person starts speaking. Drives barge-in."""
        ...


class Speaker(Protocol):
    """Streaming text-to-speech."""

    async def say(self, text: str) -> None:
        """Play `text`. Returns once it has finished playing."""
        ...

    async def stop(self) -> str:
        """Interrupt playback. Return the text actually played so far."""
        ...


class CallControl(Protocol):
    async def hangup(self) -> None: ...


# --------------------------------------------------------------------------
# Session
# --------------------------------------------------------------------------


class CallSession:
    def __init__(
        self,
        llm: ConversationLLM,
        listener: Listener,
        speaker: Speaker,
        control: CallControl,
        *,
        greeting: str,
        max_duration_seconds: int = 600,
        silence_timeout_seconds: float = 12.0,
    ) -> None:
        self._llm = llm
        self._listener = listener
        self._speaker = speaker
        self._control = control
        self._greeting = greeting
        self._max_duration = max_duration_seconds
        self._silence_timeout = silence_timeout_seconds

        self.transcript: list[Turn] = []
        self._silence_strikes = 0

    async def run(self) -> list[Turn]:
        """Drive the call to completion. Returns the transcript."""
        try:
            await asyncio.wait_for(self._conversation(), timeout=self._max_duration)
        except asyncio.TimeoutError:
            logger.info("Call hit max duration; closing")
            await self._speak_and_record(
                "I've taken enough of your time — thanks very much, and goodbye."
            )
        except Exception:
            logger.exception("Call session failed")
        finally:
            await self._control.hangup()

        return self.transcript

    # -- main loop ---------------------------------------------------------

    async def _conversation(self) -> None:
        await self._speak_and_record(self._greeting)

        utterances = self._listener.utterances()

        while True:
            try:
                user_text = await asyncio.wait_for(
                    utterances.__anext__(), timeout=self._silence_timeout
                )
            except asyncio.TimeoutError:
                if await self._handle_silence():
                    return
                continue
            except StopAsyncIteration:
                logger.info("Audio stream ended; caller hung up")
                return

            user_text = user_text.strip()
            if not user_text:
                continue

            self._silence_strikes = 0
            self._record("user", user_text)

            finished = await self._respond()
            if finished:
                return

    async def _handle_silence(self) -> bool:
        """Return True when we've given up and the call should end."""
        self._silence_strikes += 1
        if self._silence_strikes == 1:
            await self._speak_and_record("Sorry — are you still there?")
            return False
        await self._speak_and_record(
            "I'll let you go for now. Thanks for your time, and goodbye."
        )
        return True

    # -- speaking ----------------------------------------------------------

    async def _respond(self) -> bool:
        """Generate and speak one agent turn.

        Returns True if the agent signalled the call is over.
        """
        spoken: list[str] = []
        interrupted = False

        generation = self._llm.generate()
        barge_in = asyncio.create_task(self._listener.wait_for_speech_start())

        try:
            async for chunk in generation:
                speaking = asyncio.create_task(self._speaker.say(chunk))
                done, _ = await asyncio.wait(
                    {speaking, barge_in}, return_when=asyncio.FIRST_COMPLETED
                )

                if barge_in in done:
                    # The person started talking. Cut playback immediately and
                    # keep only what the speaker confirms was actually heard.
                    speaking.cancel()
                    played = await self._speaker.stop()
                    if played:
                        spoken.append(played)
                    interrupted = True
                    break

                await speaking
                spoken.append(chunk)
        finally:
            barge_in.cancel()
            await generation.aclose()

        text = " ".join(s.strip() for s in spoken if s.strip())
        if text:
            self._record("assistant", text)

        if interrupted:
            return False
        return _is_closing(text)

    async def _speak_and_record(self, text: str) -> None:
        await self._speaker.say(text)
        self._record("assistant", text)

    def _record(self, role: str, text: str) -> None:
        turn = Turn(role=role, text=text, started_at=datetime.now(timezone.utc))
        self.transcript.append(turn)
        self._llm.record(turn)


# Heuristic for "the agent just said goodbye". Cheap and good enough — the
# alternative is a model call per turn purely to ask whether the call is over,
# which is real latency and cost for a decision this shallow. If it misfires,
# the silence timeout closes the call a few seconds later anyway.
_CLOSING_MARKERS = (
    "goodbye",
    "bye for now",
    "take care",
    "have a great day",
    "have a good day",
    "thanks for your time",
)


def _is_closing(text: str) -> bool:
    lowered = text.lower()
    return any(marker in lowered for marker in _CLOSING_MARKERS)
