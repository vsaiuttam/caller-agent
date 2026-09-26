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

Ending is the other half. The model ends the call by writing an end marker
after its farewell (see `llm.EndMarkerFilter`); a phrase heuristic backs it
up; and every line the session says on its own — silence check-ins, the
timeout goodbye — comes from the call's `CallPhrases`, so a Hindi call never
suddenly apologises in English.

Tools: when the model stops mid-turn to use one (`llm.ToolPause`), the
console is told the agent is working, and a speaker that buffers whole turns
(Twilio) plays what was said so far — or a "let me check" — while the tool
runs, rather than leaving the caller in silence. What is said before and
after the tool is still one turn.
"""

from __future__ import annotations

import asyncio
import logging
import time
import unicodedata
from collections.abc import AsyncIterator, Awaitable, Callable
from datetime import datetime, timezone
from typing import Protocol

from ..llm import ConversationLLM, ToolPause
from ..models import Turn
from .phrases import CallPhrases, phrases_for

logger = logging.getLogger(__name__)

# ("turn", {...}) and ("state", {...}) — see CallSession.
EventCallback = Callable[[str, dict], Awaitable[None]]


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
    """One live call.

    `on_event`, when given, is told what happens as it happens:

      ("turn",  {"role", "text", "latency_ms", "at"})  after every recorded turn
      ("state", {"state": s})  s = "speaking" (agent turn handed to the
                               speaker), "listening" (handed over; waiting for
                               the person), "thinking" (the person's utterance
                               arrived), "working" (a tool is about to run;
                               the payload also has "tools", their ids),
                               "ended" (always last)

    It is awaited inline so events arrive in order, and anything it raises is
    logged and swallowed: a broken observer must never break a call. Keep it
    fast — it sits between the person finishing and the reply starting.
    """

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
        phrases: CallPhrases | None = None,
        on_event: EventCallback | None = None,
    ) -> None:
        self._llm = llm
        self._listener = listener
        self._speaker = speaker
        self._control = control
        self._greeting = greeting
        self._max_duration = max_duration_seconds
        self._silence_timeout = silence_timeout_seconds
        self._phrases = phrases or phrases_for("en")
        self._on_event = on_event

        self.transcript: list[Turn] = []
        # What broke the call, if something did. run() still hangs up and
        # returns the transcript so far; this is how a caller tells a call
        # that failed from one that finished.
        self.error: Exception | None = None
        self._silence_strikes = 0
        # Set by request_end(): an operator pressed "End call".
        self._end_requested = asyncio.Event()

    @property
    def llm(self) -> ConversationLLM:
        return self._llm

    def request_end(self) -> None:
        """Ask the call to wrap up politely.

        Waiting for the person: say the default goodbye and end. Mid-reply:
        end as soon as that reply has been handed over — cutting the agent
        off mid-sentence would be the rudest possible way to end a call.
        """
        self._end_requested.set()

    async def run(self) -> list[Turn]:
        """Drive the call to completion. Returns the transcript."""
        try:
            await asyncio.wait_for(self._conversation(), timeout=self._max_duration)
        except asyncio.TimeoutError:
            logger.info("Call hit max duration; closing")
            await self._speak_and_record(self._phrases.goodbye_timeout)
        except Exception as exc:
            logger.exception("Call session failed")
            self.error = exc
        finally:
            await self._control.hangup()
            await self._emit("state", {"state": "ended"})

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
        end_requested = asyncio.create_task(self._end_requested.wait())

        try:
            while True:
                if pending is None:
                    pending = asyncio.create_task(_next_utterance(utterances))

                # The silence clock starts when the agent stops talking, not
                # when its reply was handed over. Webhook transports queue a
                # whole turn at once and play it for seconds afterwards.
                done, _ = await asyncio.wait(
                    {pending, end_requested},
                    timeout=self._silence_timeout + self._playback_remaining(),
                    return_when=asyncio.FIRST_COMPLETED,
                )
                if not done:
                    if await self._handle_silence():
                        return
                    continue

                if pending not in done:
                    # Only the operator's request woke us: nobody is talking,
                    # so say goodbye and go.
                    await self._speak_and_record(self._phrases.goodbye_default)
                    return

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
                await self._set_state("thinking")
                await self._record("user", user_text)

                finished = await self._respond()
                if finished:
                    return
        finally:
            end_requested.cancel()
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
            await self._speak_and_record(self._phrases.still_there)
            return False
        await self._speak_and_record(self._phrases.goodbye_silence)
        return True

    # -- speaking ----------------------------------------------------------

    async def _respond(self) -> bool:
        """Generate and speak one agent turn.

        Returns True if the call is over: the model asked to end it (or said
        a recognisable goodbye), or an operator asked while it was talking.
        An interrupted reply never ends the call — whatever the person said
        over it still deserves an answer.
        """
        spoken: list[str] = []
        interrupted = False
        # Webhook transports (Twilio) buffer the turn and play it on flush();
        # streaming ones start playing the first chunk as it arrives. Latency
        # is measured to whichever of those puts audio on the line — which,
        # on a turn that uses a tool, may be the interim played meanwhile.
        buffered = hasattr(self._speaker, "flush")
        started = time.perf_counter()
        latency_ms: int | None = None
        # Whether "speaking" has been said since the turn started or since
        # the last tool pause, which reported "working".
        announced = False

        generation = self._llm.generate()
        barge_in = asyncio.create_task(self._listener.wait_for_speech_start())

        try:
            async for chunk in generation:
                if isinstance(chunk, ToolPause):
                    if await self._pause_for_tools(chunk) and latency_ms is None:
                        latency_ms = _elapsed_ms(started)
                    announced = False
                    continue
                if not buffered and not announced:
                    if latency_ms is None:
                        latency_ms = _elapsed_ms(started)
                    await self._set_state("speaking")
                    announced = True
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

        # Flush buffered audio for webhook-based transports (Twilio).
        # Streaming transports (LiveKit) play each chunk as it arrives and
        # don't implement flush().
        if buffered:
            if text:
                await self._set_state("speaking")
            await self._speaker.flush()
            if latency_ms is None:
                latency_ms = _elapsed_ms(started)

        if text:
            await self._record("assistant", text, latency_ms=latency_ms)
            logger.info("Agent reply ready in %s ms", latency_ms)
        await self._set_state("listening")

        if interrupted:
            return False
        ending = (
            getattr(self._llm, "end_requested", False)
            or _is_closing(text)
            or self._end_requested.is_set()
        )
        if ending and not text:
            # Asked to end but said nothing: never hang up on silence.
            await self._speak_and_record(self._phrases.goodbye_default)
        return ending

    async def _pause_for_tools(self, pause: ToolPause) -> bool:
        """Cover a tool the model is about to run. True if audio went out for it.

        A streaming speaker has already played everything said so far, so
        only a buffering one has anything to do: play that now, as an
        interim, instead of holding it until the tool is done.
        """
        await self._emit("state", {"state": "working", "tools": list(pause.tools)})
        flush_interim = getattr(self._speaker, "flush_interim", None)
        if flush_interim is None:
            return False
        await flush_interim()
        return True

    async def _speak_and_record(self, text: str) -> None:
        await self._set_state("speaking")
        await self._speaker.say(text)
        if hasattr(self._speaker, "flush"):
            await self._speaker.flush()
        await self._record("assistant", text)
        await self._set_state("listening")

    async def _record(self, role: str, text: str, *, latency_ms: int | None = None) -> None:
        turn = Turn(
            role=role,
            text=text,
            started_at=datetime.now(timezone.utc),
            latency_ms=latency_ms,
        )
        self.transcript.append(turn)
        self._llm.record(turn)
        await self._emit(
            "turn",
            {
                "role": role,
                "text": text,
                "latency_ms": latency_ms,
                "at": turn.started_at.isoformat(),
            },
        )

    # -- observer ----------------------------------------------------------

    async def _set_state(self, state: str) -> None:
        await self._emit("state", {"state": state})

    async def _emit(self, kind: str, payload: dict) -> None:
        if self._on_event is None:
            return
        try:
            await self._on_event(kind, payload)
        except Exception:
            logger.exception("Call event observer failed on %r; call continues", kind)


async def _next_utterance(utterances: AsyncIterator[str]) -> str:
    # A coroutine wrapper, because create_task() will not take __anext__()'s
    # awaitable directly.
    return await utterances.__anext__()


def _elapsed_ms(since: float) -> int:
    return int((time.perf_counter() - since) * 1000)


# Backstop for "the agent just said goodbye", for the turns where the model
# forgot the end marker. Cheap and good enough — the alternative is a model
# call per turn purely to ask whether the call is over, which is real latency
# and cost for a decision this shallow.
#
# Farewells only, never thank-yous: "dhanyavaad" or "thank you" mid-call means
# thanks, not goodbye, and ending on it would hang up on people. Hindi's
# "नमस्ते!" closing is also a greeting, so it is left to the marker too.
_CLOSING_MARKERS = tuple(
    unicodedata.normalize("NFC", marker)
    for marker in (
        "goodbye",
        "bye for now",
        "take care",
        "have a great day",
        "have a good day",
        "thanks for your time",
        "alvida",
        "अलविदा",
        "khuda hafiz",
        "ख़ुदा हाफ़िज़",
        "خدا حافظ",
        "phir milenge",
        "फिर मिलेंगे",
    )
)


def _is_closing(text: str) -> bool:
    # NFC, because Devanagari nukta letters (ख़, फ़) arrive both precomposed
    # and as letter + nukta, and the two must compare equal.
    lowered = unicodedata.normalize("NFC", text).lower()
    return any(marker in lowered for marker in _CLOSING_MARKERS)
