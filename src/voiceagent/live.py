"""Take the call yourself, out loud.

`simulate.py` answers "does this campaign hold up against a difficult
person?" by having a model play the person. This answers a different question
— "what is this actually like to be on the receiving end of?" — and no model
can answer it. Speech recognition mishears words a model would never produce,
real people trail off and start again, and the pause before the agent replies
is only uncomfortable when you are the one sitting through it.

The browser is the transport. It holds the microphone and the loudspeaker;
this module holds the model, the transcript, and the rules about what may be
written into it. That is the same seam `voice/session.py` draws between
`Listener`/`Speaker` and the call logic — Deepgram and Cartesia on a real
call, `SpeechRecognition` and `speechSynthesis` in a browser tab, the same
decisions in the middle either way.

One rule carries over unchanged, and it is the reason this is not just a chat
box wired to a microphone: **an agent turn is recorded only once the client
confirms what was actually played.** Interrupt the agent and the browser
reports the prefix it managed to speak; that prefix is what enters the
transcript. A turn that is never confirmed is dropped rather than recorded
optimistically — an agent repeating itself is a recoverable annoyance, an
agent convinced it already said something it never said is not.

Protocol, browser → here:

    {"type": "utterance", "text": ...}   a final speech-to-text result
    {"type": "interrupt"}                the person started talking over us
    {"type": "spoken",    "text": ...}   what the speaker actually played
    {"type": "end",       "reason": ...} hang up; extraction runs after this

Here → browser:

    {"type": "speak",     "turn": n, "text": ...}   a chunk to say now
    {"type": "turn_end",  "turn": n, ...}           generation finished
    {"type": "heard",     "text": ...}              utterance accepted
    {"type": "closing"}                             the agent said goodbye
    {"type": "error",     "message": ...}           the turn failed

`spoken` must arrive before the next `utterance`, which is the browser's job:
it knows when its own speaker stopped.
"""

from __future__ import annotations

import asyncio
import contextlib
import logging
import time
from datetime import datetime, timezone
from typing import Any, Protocol

from .catalog import EXTRACTION, TokenUsage, resolve
from .llm import ConversationLLM
from .models import CallContext, Contact, Turn
from .postcall.extract import extract_outcome
from .providers import auth_error_types, overloaded_error_types, rate_limit_error_types
from .scoring import qualify_outcome
from .simulate import SimulatedTurn, SimulationResult
from .voice.session import _is_closing

logger = logging.getLogger(__name__)

# A browser tab left open on a live call is a slow leak of model tokens, and a
# speech recogniser that mishears a radio in the background will happily talk
# to it all afternoon. Both of these are backstops, not targets.
MAX_TURNS = 80
MAX_TEXT_CHARS = 1500


class Transport(Protocol):
    """The browser tab, as far as this module is concerned."""

    async def send(self, message: dict[str, Any]) -> None: ...

    async def receive(self) -> dict[str, Any]:
        """Next message from the browser. Raises when the socket closes."""
        ...


class LiveCall:
    """One call between a person at a microphone and the real agent."""

    def __init__(
        self,
        client,
        *,
        contact: Contact,
        context: CallContext,
        greeting: str,
        conversation_model: str | None = None,
        conversation_effort: str | None = None,
        extraction_model: str | None = None,
        extraction_effort: str | None = None,
        max_turns: int = MAX_TURNS,
    ) -> None:
        self._client = client
        self._contact = contact
        self._context = context
        self._greeting = greeting
        self._extraction_model = extraction_model
        self._extraction_effort = extraction_effort
        self._max_turns = max_turns

        self.usage = TokenUsage()
        self._llm = ConversationLLM(
            client,
            contact=contact,
            context=context,
            model=conversation_model,
            effort=conversation_effort,
            usage=self.usage,
        )

        self.transcript: list[Turn] = []
        self.turns: list[SimulatedTurn] = []
        self.ended_because = "the connection closed"
        # Set when the tab went away rather than hanging up. Extraction is
        # skipped in that case: it costs real money and there is nobody left
        # to read it.
        self.disconnected = False

        self._turn_no = 0
        # Timing for the turn currently in the air. Attached to the turn when
        # the browser confirms what it played, since that is the only point at
        # which we know the turn happened at all.
        self._pending_ms: tuple[int | None, int | None] = (None, None)

    @property
    def conversation_model(self) -> str:
        return self._llm.model

    # -- the call ----------------------------------------------------------

    async def run(self, transport: Transport) -> None:
        """Drive the call until the browser ends it or the socket drops."""
        inbox: asyncio.Queue[dict[str, Any]] = asyncio.Queue()
        interrupted = asyncio.Event()
        reader = asyncio.create_task(self._read(transport, inbox, interrupted))

        await transport.send(
            {"type": "speak", "turn": 0, "text": self._greeting}
        )
        await transport.send(
            {
                "type": "turn_end",
                "turn": 0,
                "first_chunk_ms": None,
                "total_ms": None,
                "interrupted": False,
            }
        )

        try:
            while len(self.transcript) < self._max_turns:
                message = await inbox.get()
                kind = message.get("type")

                if kind == "spoken":
                    self._record_spoken(message.get("text"))
                    if self.said_goodbye():
                        # Told, not enforced: the browser stops listening and
                        # offers to end the call. Hanging up from here would
                        # cut off audio the person is still hearing.
                        await transport.send({"type": "closing"})

                elif kind == "utterance":
                    text = _clean(message.get("text"))
                    if not text:
                        continue
                    self._record("user", text)
                    await transport.send({"type": "heard", "text": text})
                    await self._respond(transport, interrupted)

                elif kind == "end":
                    self.ended_because = _clean(message.get("reason")) or "you hung up"
                    return

                elif kind == "closed":
                    self.ended_because = "the connection closed"
                    self.disconnected = True
                    return

                # "interrupt" is acted on by the reader, which sets the event
                # while a turn is still generating and therefore not reading
                # this queue. Nothing left to do with it here.

            self.ended_because = "the call hit its turn limit"
        finally:
            reader.cancel()

    async def _read(
        self,
        transport: Transport,
        inbox: asyncio.Queue[dict[str, Any]],
        interrupted: asyncio.Event,
    ) -> None:
        """Feed the queue, and flag barge-in the moment it arrives.

        Barge-in has to reach a turn that is mid-generation and therefore not
        reading the queue yet, so the event is set here rather than in the
        main loop. The message is still queued: what was actually played
        arrives right behind it and the loop needs to see that.
        """
        while True:
            try:
                message = await transport.receive()
            except Exception:  # noqa: BLE001 - any transport failure is a hangup
                await inbox.put({"type": "closed"})
                return

            if not isinstance(message, dict):
                continue
            if message.get("type") == "interrupt":
                interrupted.set()
            await inbox.put(message)

    async def _respond(self, transport: Transport, interrupted: asyncio.Event) -> None:
        """Generate one agent turn, streaming chunks as they're speakable."""
        interrupted.clear()
        self._turn_no += 1
        turn_no = self._turn_no

        started = time.perf_counter()
        first_chunk_at: float | None = None
        cut_short = False

        generation = self._llm.generate()
        chunks = generation.__aiter__()
        watch = asyncio.create_task(interrupted.wait())

        try:
            while True:
                nxt = asyncio.create_task(chunks.__anext__())
                done, _ = await asyncio.wait(
                    {nxt, watch}, return_when=asyncio.FIRST_COMPLETED
                )

                if watch in done:
                    # They started talking. Stop generating — every further
                    # token costs money to produce and will never be heard.
                    nxt.cancel()
                    with contextlib.suppress(asyncio.CancelledError):
                        await nxt
                    cut_short = True
                    break

                try:
                    chunk = nxt.result()
                except StopAsyncIteration:
                    break

                if first_chunk_at is None:
                    first_chunk_at = time.perf_counter()
                await transport.send({"type": "speak", "turn": turn_no, "text": chunk})

        except (*auth_error_types(), *rate_limit_error_types(), *overloaded_error_types()):
            # Not a turn that went wrong — a bad key, an exhausted quota, or a
            # provider at capacity will fail every remaining turn the same way.
            # Let it out so the caller says so once, plainly, instead of the
            # person on the line hearing dead air over and over.
            raise
        except Exception as exc:  # noqa: BLE001
            logger.exception("Live turn failed")
            # Best-effort: the usual reason a turn fails mid-flight is that the
            # tab it was talking to has gone away.
            with contextlib.suppress(Exception):
                await transport.send(
                    {"type": "error", "message": f"The agent turn failed: {exc}"}
                )
        finally:
            watch.cancel()
            with contextlib.suppress(Exception):
                await generation.aclose()

        self._pending_ms = (
            int((first_chunk_at - started) * 1000) if first_chunk_at else None,
            int((time.perf_counter() - started) * 1000),
        )
        await transport.send(
            {
                "type": "turn_end",
                "turn": turn_no,
                "first_chunk_ms": self._pending_ms[0],
                "total_ms": self._pending_ms[1],
                "interrupted": cut_short,
            }
        )

    # -- transcript --------------------------------------------------------

    def _record_spoken(self, text: Any) -> None:
        """Record an agent turn from what the browser confirms it played."""
        first_chunk_ms, total_ms = self._pending_ms
        self._pending_ms = (None, None)

        spoken = _clean(text)
        if not spoken:
            # Cut off before a single word made it out, or the browser had no
            # voice to speak with. Recording nothing is the right failure —
            # the agent will simply say it again.
            return

        self._record("assistant", spoken)
        self.turns[-1].first_chunk_ms = first_chunk_ms
        self.turns[-1].total_ms = total_ms

    def _record(self, role: str, text: str) -> None:
        turn = Turn(role=role, text=text, started_at=datetime.now(timezone.utc))
        self.transcript.append(turn)
        self._llm.record(turn)
        self.turns.append(SimulatedTurn(role=role, text=text))

    def said_goodbye(self) -> bool:
        """Whether the last confirmed agent turn closed the call.

        Same heuristic a real call uses, so a mic test ends where the real
        thing would rather than on a rule invented for the browser.
        """
        for turn in reversed(self.transcript):
            if turn.role == "assistant":
                return _is_closing(turn.text)
        return False

    # -- after the call ----------------------------------------------------

    async def extract(self) -> SimulationResult:
        """Run the real extractor over the transcript, exactly as a call does."""
        outcome = await extract_outcome(
            self._client,
            contact=self._contact,
            context=self._context,
            turns=self.transcript,
            call_started_at_iso=datetime.now(timezone.utc).isoformat(),
            model=self._extraction_model,
            effort=self._extraction_effort,
            usage=self.usage,
        )

        return SimulationResult(
            transcript=self.transcript,
            turns=self.turns,
            outcome=outcome,
            usage=self.usage,
            qualification=(
                qualify_outcome(self._context, outcome) if self._context.scorecard else None
            ),
            conversation_model=self.conversation_model,
            extraction_model=resolve(self._extraction_model, EXTRACTION),
            # Not one of the scripted personas — the person was you. Kept in
            # the same shape so a mic test saves and renders like any other
            # rehearsal.
            persona="live",
            ended_because=self.ended_because,
        )


def _clean(value: Any) -> str:
    """Whatever the browser sent, as trimmed and bounded text."""
    if not isinstance(value, str):
        return ""
    return value.strip()[:MAX_TEXT_CHARS]


__all__ = ["LiveCall", "Transport", "MAX_TURNS"]
