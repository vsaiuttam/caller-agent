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
import time
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


class CallNotPlaced(ConnectionError):
    """The provider refused to place the call at all — nobody's phone rang.

    Distinct from an unanswered call (a plain ConnectionError), which is
    worth a "sorry we missed you" message; this is our problem, not theirs.
    """


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
        # One read stays pending across silence timeouts. Timing out a read
        # with `wait_for` cancels it, and cancelling an async generator
        # mid-await finalises it: the next read raises StopAsyncIteration and
        # the first long pause gets taken for a hang-up.
        pending: asyncio.Task | None = None

        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(_next_utterance(utterances))

                # The silence clock starts when the agent stops talking, not
                # when its reply was handed over. Webhook transports queue a
                # whole turn at once and play it for seconds afterwards.
                done, _ = await asyncio.wait(
                    {pending}, timeout=self._silence_timeout + self._playback_remaining()
                )
                if not done:
                    if await self._handle_silence():
                        return
                    continue

                task, pending = pending, None
                try:
                    user_text = task.result()
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
        finally:
            if pending is not None:
                pending.cancel()

    def _playback_remaining(self) -> float:
        """Seconds of agent audio still to play, for speakers that report it."""
        remaining = getattr(self._speaker, "playback_remaining", None)
        return remaining() if remaining else 0.0

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
        # Webhook transports (Twilio) buffer the turn and play it on flush();
        # streaming ones start playing the first chunk as it arrives. Latency
        # is measured to whichever of those puts audio on the line.
        buffered = hasattr(self._speaker, "flush")
        started = time.perf_counter()
        latency_ms: int | None = None

        generation = self._llm.generate()
        barge_in = asyncio.create_task(self._listener.wait_for_speech_start())

        try:
            async for chunk in generation:
                if latency_ms is None and not buffered:
                    latency_ms = _elapsed_ms(started)
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

        # Flush buffered audio for webhook-based transports (Twilio).
        # Streaming transports (LiveKit) play each chunk as it arrives and
        # don't implement flush().
        if buffered:
            await self._speaker.flush()
            latency_ms = _elapsed_ms(started)

        text = " ".join(s.strip() for s in spoken if s.strip())
        if text:
            self._record("assistant", text, latency_ms=latency_ms)
            logger.info("Agent reply ready in %s ms", latency_ms)

        if interrupted:
            return False
        return _is_closing(text)

    async def _speak_and_record(self, text: str) -> None:
        await self._speaker.say(text)
        if hasattr(self._speaker, "flush"):
            await self._speaker.flush()
        self._record("assistant", text)

    def _record(self, role: str, text: str, *, latency_ms: int | None = None) -> None:
        turn = Turn(
            role=role,
            text=text,
            started_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
        )
        self.transcript.append(turn)
        self._llm.record(turn)


async def _next_utterance(utterances: AsyncIterator[str]) -> str:
    # A coroutine wrapper, because create_task() will not take __anext__()'s
    # awaitable directly.
    return await utterances.__anext__()


def _elapsed_ms(since: float) -> int:
    return int((time.perf_counter() - since) * 1000)


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
