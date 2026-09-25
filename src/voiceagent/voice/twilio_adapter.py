"""Twilio telephony adapter.

Places outbound PSTN calls through Twilio's Programmable Voice API and bridges
Twilio's webhook-based conversation model with the streaming Listener/Speaker/
CallControl protocols used by the rest of the pipeline.

Architecture
------------
Twilio's voice API is webhook-driven: when a call connects, Twilio POSTs to
your server expecting TwiML back. Each <Gather> collects speech, then POSTs
the result to another URL, where you respond with <Say> + another <Gather>.

To bridge this with the async-iterator model the CallSession expects, each
active call gets a pair of asyncio queues:

  speech_queue  — webhook handler puts recognised speech; Listener yields it
  response_queue — Speaker puts the agent's reply; webhook handler returns it

The webhook server runs inside the worker process on a configurable port.
For Twilio to reach it, expose it publicly via ngrok, Cloudflare Tunnel, or
deploy to a host with a public IP.

    ngrok http 8765
    export TWILIO_WEBHOOK_URL=https://<id>.ngrok-free.app

Latency
-------
The caller hears dead air from the moment they stop talking until Twilio
fetches the reply's TwiML. These keep that short:

  * The webhook holds Twilio's request open until the reply is ready
    (REPLY_WAIT_SECONDS, under Twilio's 15s limit). A short hold followed by
    a fixed <Pause> adds that pause to every reply that misses the hold.
  * A reply that isn't ready within TWILIO_FILLER_AFTER_MS of the caller
    finishing is covered by a short acknowledgement ("Okay.", "जी।") while
    it is made — silence reads as a dropped line, a filler reads as a
    person listening.
  * Sarvam synthesis starts per sentence as the model streams, so audio for
    the first sentence is ready while the second is still being generated.
  * `prepare_call` synthesizes the greeting and the acknowledgements while
    the phone rings, in the call's language.
  * One Sarvam client per TTS language for the process, so each turn skips
    a TLS handshake.
  * Audio is 8 kHz, which is all a phone line carries anyway.

Language
--------
Each call listens and speaks in its campaign's language (see `prepare_call`).
SARVAM_STT_LANGUAGE and SARVAM_TTS_LANGUAGE, when set, pin every call to one
language instead.

Required env vars
-----------------
    TWILIO_ACCOUNT_SID      — starts with AC...
    TWILIO_AUTH_TOKEN        — from Twilio console
    TWILIO_PHONE_NUMBER      — your Twilio number in E.164 (+1...)
    TWILIO_WEBHOOK_URL       — public base URL for callbacks
    TWILIO_WEBHOOK_PORT      — local port for the webhook server (default 8765)
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import time
from collections import OrderedDict
from collections.abc import AsyncIterator
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import TYPE_CHECKING
from xml.sax.saxutils import escape

from .phrases import phrases_for
from .session import CallNotPlaced

if TYPE_CHECKING:
    from .sarvam_voice import SarvamTTS

logger = logging.getLogger(__name__)

VOICE_PROVIDER = os.getenv("VOICE_PROVIDER", "twilio").lower()

# <Gather> tuning. The speech model decides how fast Twilio notices the caller
# has finished; which one is quickest for a given language is worth measuring
# rather than assuming (e.g. experimental_conversations, googlev2_telephony,
# deepgram_nova-3). Empty keeps Twilio's default for the language.
SPEECH_MODEL = os.getenv("TWILIO_SPEECH_MODEL", "").strip()
SPEECH_TIMEOUT = os.getenv("TWILIO_SPEECH_TIMEOUT", "auto").strip() or "auto"
# Seconds Twilio keeps listening after the agent finishes. Kept just under the
# session's 12s silence timeout, so the line is not deaf while the agent
# decides whether to ask "are you still there?".
GATHER_TIMEOUT = int(os.getenv("TWILIO_GATHER_TIMEOUT", "10"))
# How long a webhook holds Twilio's request open waiting for the reply.
# Twilio abandons a webhook at 15s.
REPLY_WAIT_SECONDS = float(os.getenv("TWILIO_REPLY_WAIT", "9"))
# A phone line carries 8 kHz audio. Anything richer is a bigger file for
# Twilio to download before it can start playing.
SARVAM_TWILIO_SAMPLE_RATE = int(os.getenv("SARVAM_TWILIO_SAMPLE_RATE", "8000"))

# Synthesized audio, keyed by a hash of text + voice + language. Served to
# Twilio's <Play> and reused whenever the same line is said again — the
# campaign greeting, the stock silence prompts and the acknowledgements are
# identical across calls. Bounded LRU.
_AUDIO_STORE_MAX = 256
_audio_store: OrderedDict[str, bytes] = OrderedDict()
# Synthesis in flight, so two requests for the same line share one API call.
_inflight: dict[str, asyncio.Task[str | None]] = {}
# The process's SarvamTTS clients, one per TTS language, created on first use.
_tts_clients: dict[str, SarvamTTS] = {}
# The TTS language of the synthesis running in this task. `_synthesize_sarvam`
# is a one-argument seam (text in, audio out), so the language travels with
# the task's context rather than through its signature.
_synthesis_language: ContextVar[str] = ContextVar("_synthesis_language", default="en-IN")
# Languages from `prepare_call`, waiting for their room to be dialled.
_prepared_languages: dict[str, str] = {}


# ---------------------------------------------------------------------------
# Per-call language. The overrides are read when used, not at import.
# ---------------------------------------------------------------------------


def _gather_language(language: str) -> str:
    """Twilio <Gather> speech-recognition language for a campaign language."""
    pinned = os.getenv("SARVAM_STT_LANGUAGE", "").strip()
    if pinned:
        return pinned
    if language in ("hi", "hi-en"):
        return "hi-IN"
    if language == "ur":
        return "ur-IN"
    # The Sarvam voice is an Indian voice, and its callers speak Indian English.
    return "en-IN" if VOICE_PROVIDER == "sarvam" else "en-US"


def _tts_language(language: str) -> str:
    """Sarvam TTS language for a campaign language.

    Urdu calls are written in Devanagari (see phrases.py), so the Hindi
    voice, which reads Devanagari, speaks them.
    """
    pinned = os.getenv("SARVAM_TTS_LANGUAGE", "").strip()
    if pinned:
        return pinned
    return "hi-IN" if language in ("hi", "hi-en", "ur") else "en-IN"


def _filler_after_seconds() -> float:
    """TWILIO_FILLER_AFTER_MS as seconds; 0 turns acknowledgements off."""
    try:
        return max(0.0, float(os.getenv("TWILIO_FILLER_AFTER_MS", "1200")) / 1000)
    except ValueError:
        return 1.2


# ---------------------------------------------------------------------------
# Per-call shared state
# ---------------------------------------------------------------------------


@dataclass
class _Reply:
    """One agent turn, as the webhook handler will render it.

    `segments` are (text, audio_id) pairs: audio_id is Sarvam audio played
    with <Play>, or None to fall back to Twilio's <Say> for that sentence.
    """

    segments: list[tuple[str, str | None]]
    seconds: float
    # The session hung up after this turn: play it, then end the call.
    final: bool = False
    delivered: asyncio.Event = field(default_factory=asyncio.Event)
    play_until: float = 0.0  # monotonic time playback should finish

    def mark_delivered(self) -> None:
        # Allow a moment for Twilio to fetch the audio before it plays.
        self.play_until = time.monotonic() + self.seconds + 0.5
        self.delivered.set()


@dataclass
class _CallState:
    """Shared state between the webhook handlers and the protocol adapters."""

    call_sid: str = ""
    answered: asyncio.Event = field(default_factory=asyncio.Event)
    ended: asyncio.Event = field(default_factory=asyncio.Event)
    # Twilio reported the call over, so there is nothing left to hang up.
    completed: bool = False

    # The campaign's language code (en, hi, ur, hi-en), from prepare_call.
    language: str = "en"
    # Index of the acknowledgement last played, so the next one differs.
    last_acknowledgement: int = -1

    # Webhook → Listener: recognised speech from <Gather>
    speech_queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)

    # Speaker → Webhook: the agent's reply
    response_queue: asyncio.Queue[_Reply | None] = field(default_factory=asyncio.Queue)
    last_reply: _Reply | None = None

    # Barge-in signal
    speech_started: asyncio.Event = field(default_factory=asyncio.Event)

    # Recording URL populated by Twilio's recording callback
    recording_url: str | None = None
    recording_sid: str | None = None
    recording_duration: int | None = None

    # Answering Machine Detection result
    amd_result: str | None = None  # "human", "machine_start", "machine_end_beep", etc.


# Global registry of active calls, keyed by room_name.
_active_calls: dict[str, _CallState] = {}


# ---------------------------------------------------------------------------
# Protocol implementations
# ---------------------------------------------------------------------------


class TwilioListener:
    """Speech-to-text via Twilio's built-in <Gather input='speech'>."""

    def __init__(self, state: _CallState) -> None:
        self._state = state

    async def utterances(self) -> AsyncIterator[str]:
        while not self._state.ended.is_set():
            try:
                text = await asyncio.wait_for(self._state.speech_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if text is None:  # sentinel: call ended
                return
            self._state.speech_started.clear()
            yield text

    async def wait_for_speech_start(self) -> None:
        """Resolve when the caller starts speaking.

        In the webhook model we don't get a real-time VAD signal, so this
        resolves immediately if speech is already queued, or waits for the
        next Gather result. This means barge-in is turn-level rather than
        sub-utterance — acceptable for telephony where Twilio's own Gather
        already handles interruption at the TwiML level.
        """
        await self._state.speech_started.wait()
        self._state.speech_started.clear()


class TwilioSpeaker:
    """Speaks through the TwiML returned by the webhook handlers.

    The LLM streams multiple chunks per turn, but Twilio reads exactly ONE
    response per webhook cycle. ``say()`` therefore collects chunks — starting
    Sarvam synthesis for each one immediately, so audio is being made while
    the model is still writing — and ``flush()`` queues the complete turn as a
    single reply. ``CallSession`` calls ``flush()`` after each generation loop.
    """

    def __init__(self, state: _CallState) -> None:
        self._state = state
        self._pending: list[tuple[str, asyncio.Future[str | None] | None]] = []

    async def say(self, text: str) -> None:
        """Buffer a chunk and start synthesizing it. Queues nothing yet."""
        text = text.strip()
        if text:
            audio = (
                synthesis(text, _tts_language(self._state.language))
                if VOICE_PROVIDER == "sarvam"
                else None
            )
            self._pending.append((text, audio))

    async def flush(self) -> None:
        """Queue the buffered turn as ONE reply for the webhook."""
        pending, self._pending = self._pending, []
        if not pending:
            return

        audio_ids = await asyncio.gather(
            *(_audio_id_or_none(future) for _, future in pending)
        )
        segments = [(text, audio_id) for (text, _), audio_id in zip(pending, audio_ids)]
        reply = _Reply(
            segments=segments,
            seconds=sum(_segment_seconds(text, audio_id) for text, audio_id in segments),
        )
        self._state.last_reply = reply
        await self._state.response_queue.put(reply)

    async def stop(self) -> str:
        """Interrupt: return what was played.

        Nothing buffered here has reached the caller — Twilio only plays a
        turn once it is flushed — so the honest answer is nothing.
        """
        self._pending.clear()
        return ""

    def playback_remaining(self) -> float:
        """Seconds until the last reply finishes playing on the call."""
        reply = self._state.last_reply
        if reply is None:
            return 0.0
        if not reply.delivered.is_set():
            # Plays as soon as Twilio collects it — normally at once, since a
            # webhook is usually already waiting for it.
            return reply.seconds
        return max(0.0, reply.play_until - time.monotonic())


class TwilioControl:
    """Hangs up the call via Twilio REST API."""

    def __init__(self, state: _CallState, client) -> None:
        self._state = state
        self._client = client

    async def hangup(self) -> None:
        state = self._state
        if not state.ended.is_set():
            # The session hangs up the moment it has queued its goodbye.
            # Ending the call now would cut that goodbye off unheard.
            await _let_last_reply_play(state)

        state.ended.set()
        state.speech_queue.put_nowait(None)   # unblock Listener
        state.response_queue.put_nowait(None)  # unblock webhook handler
        if state.call_sid and not state.completed:
            try:
                await asyncio.to_thread(
                    self._client.calls(state.call_sid).update,
                    status="completed",
                )
            except Exception:
                logger.exception("Failed to hang up Twilio call %s", state.call_sid)


async def _let_last_reply_play(state: _CallState) -> None:
    reply = state.last_reply
    if reply is None:
        return

    if not reply.delivered.is_set():
        # Not collected yet: render it with <Hangup/> so Twilio ends the call
        # itself once the goodbye has played.
        reply.final = True
        try:
            await asyncio.wait_for(reply.delivered.wait(), timeout=REPLY_WAIT_SECONDS + 3)
        except asyncio.TimeoutError:
            return

    remaining = reply.play_until - time.monotonic()
    if remaining > 0:
        try:
            # Returns early if Twilio reports the call over first.
            await asyncio.wait_for(state.ended.wait(), timeout=min(remaining + 1.0, 30.0))
        except asyncio.TimeoutError:
            pass


# ---------------------------------------------------------------------------
# Speech synthesis (Sarvam) and the audio store
# ---------------------------------------------------------------------------


def _voice_key(tts_language: str) -> str:
    from .sarvam_voice import SARVAM_TTS_MODEL, SARVAM_TTS_SPEAKER

    return f"{SARVAM_TTS_MODEL}|{SARVAM_TTS_SPEAKER}|{tts_language}|{SARVAM_TWILIO_SAMPLE_RATE}"


def _audio_id(text: str, tts_language: str) -> str:
    # Content-addressed: the same line in the same voice and language is the
    # same file, so it is synthesized once and Twilio may cache it across
    # calls. The language is part of it because the same words read as
    # English and as Hindi are two different recordings.
    return hashlib.sha256(f"{_voice_key(tts_language)}|{text}".encode()).hexdigest()[:20]


def synthesis(text: str, tts_language: str) -> asyncio.Future[str | None]:
    """Start (or join) synthesis of `text`; resolves to its audio id or None.

    Deduplicated: a line already stored resolves at once, and a line being
    synthesized is shared rather than requested twice.
    """
    audio_id = _audio_id(text, tts_language)
    if audio_id in _audio_store:
        _audio_store.move_to_end(audio_id)
        done: asyncio.Future[str | None] = asyncio.get_running_loop().create_future()
        done.set_result(audio_id)
        return done

    task = _inflight.get(audio_id)
    if task is None:
        task = asyncio.create_task(_synthesize_into_store(audio_id, text, tts_language))
        _inflight[audio_id] = task
        task.add_done_callback(lambda _: _inflight.pop(audio_id, None))
    return task


def prefetch_speech(text: str, language: str = "en") -> None:
    """Synthesize a line ahead of need — the greeting, while the phone rings.

    Without this the person answers and waits through a synthesis before
    hearing anything. Fire-and-forget; a no-op unless Sarvam is the voice.
    """
    if VOICE_PROVIDER == "sarvam" and text.strip():
        synthesis(text.strip(), _tts_language(language))


async def _audio_id_or_none(future: asyncio.Future[str | None] | None) -> str | None:
    if future is None:
        return None
    # Shielded: synthesis is shared, so one caller giving up must not cancel it
    # for another.
    return await asyncio.shield(future)


async def _synthesize_into_store(audio_id: str, text: str, tts_language: str) -> str | None:
    # This runs as its own task, so the language set here is this synthesis's
    # alone.
    _synthesis_language.set(tts_language)
    audio = await _synthesize_sarvam(text)
    if not audio:
        return None
    _audio_store[audio_id] = audio
    while len(_audio_store) > _AUDIO_STORE_MAX:
        _audio_store.popitem(last=False)
    return audio_id


async def _synthesize_sarvam(text: str) -> bytes | None:
    """Call Sarvam Bulbul TTS. None on failure, so the turn falls back to <Say>."""
    from .sarvam_voice import SarvamTTS

    language = _synthesis_language.get()
    tts = _tts_clients.get(language)
    if tts is None:
        tts = _tts_clients[language] = SarvamTTS(
            language=language, sample_rate=SARVAM_TWILIO_SAMPLE_RATE
        )
    try:
        return await asyncio.wait_for(tts.synthesize_wav(text), timeout=8.0) or None
    except asyncio.TimeoutError:
        logger.warning("Sarvam TTS timed out for: %s", text[:60])
        return None
    except Exception:
        logger.exception("Sarvam TTS failed, falling back to <Say>")
        return None


def _segment_seconds(text: str, audio_id: str | None) -> float:
    if audio_id and (audio := _audio_store.get(audio_id)):
        from .sarvam_voice import wav_seconds

        seconds = wav_seconds(audio)
        if seconds is not None:
            return seconds
    # <Say>, or audio we can't measure: roughly 14 spoken characters a second.
    return len(text) / 14.0


# ---------------------------------------------------------------------------
# Webhook server (embedded in the worker process)
# ---------------------------------------------------------------------------


def _webhook_base() -> str:
    return os.getenv("TWILIO_WEBHOOK_URL", "http://localhost:8765")


def _build_webhook_app():
    """Create a Starlette app that handles Twilio voice webhooks."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Route

    def _safe_xml(text: str) -> Response:
        return Response(text, media_type="application/xml")

    def _error_twiml(room_name: str) -> Response:
        """Fallback TwiML when a handler crashes. Never let Twilio see a 500."""
        return _safe_xml(
            '<?xml version="1.0" encoding="UTF-8"?>'
            "<Response>"
            '<Pause length="2"/>'
            f'<Redirect method="POST">{_webhook_base()}/twilio/wait/{room_name}</Redirect>'
            "</Response>"
        )

    async def _reply_or_heartbeat(
        room_name: str, state: _CallState, *, acknowledge_after: float = 0.0
    ) -> Response:
        """Hold the request until the agent's reply is ready, then return it.

        Twilio plays our response the instant it arrives, so every
        millisecond between the reply being ready and this returning is
        silence on the line. If the reply is slower than the hold, fall back
        to a short heartbeat so the webhook never hits Twilio's timeout.

        With `acknowledge_after` (the caller has just finished speaking), a
        reply that isn't ready by then is covered by a short acknowledgement
        instead, and Twilio comes back for the reply at /twilio/wait.
        """
        hold = REPLY_WAIT_SECONDS
        if acknowledge_after > 0:
            try:
                reply = await asyncio.wait_for(
                    state.response_queue.get(), timeout=acknowledge_after
                )
            except asyncio.TimeoutError:
                acknowledgement = _next_acknowledgement(state)
                if acknowledgement is not None:
                    return _safe_xml(_acknowledgement_twiml(room_name, *acknowledgement))
                hold -= acknowledge_after
            else:
                return _reply_response(room_name, state, reply)

        try:
            reply = await asyncio.wait_for(state.response_queue.get(), timeout=hold)
        except asyncio.TimeoutError:
            return _heartbeat_twiml(_webhook_base(), room_name)
        return _reply_response(room_name, state, reply)

    def _reply_response(room_name: str, state: _CallState, reply: _Reply | None) -> Response:
        if reply is None:
            return _safe_xml(
                "<Response><Say>Thank you for your time. Goodbye.</Say>"
                "<Hangup/></Response>"
            )
        return _safe_xml(_reply_twiml(room_name, reply, state.language))

    async def voice_handler(request: Request) -> Response:
        """Initial webhook when call connects. Wait for greeting, return TwiML."""
        room_name = request.path_params["room_name"]
        try:
            state = _active_calls.get(room_name)
            if not state:
                logger.warning("voice_handler: no state for %s", room_name)
                return _safe_xml("<Response><Hangup/></Response>")

            # Mark call as answered
            form = await request.form()
            state.call_sid = str(form.get("CallSid", state.call_sid))
            state.answered.set()
            return await _reply_or_heartbeat(room_name, state)
        except Exception:
            logger.exception("voice_handler crashed for %s", room_name)
            return _error_twiml(room_name)

    async def gather_handler(request: Request) -> Response:
        """Receives speech result, queues it, then returns the agent's reply."""
        room_name = request.path_params["room_name"]
        try:
            state = _active_calls.get(room_name)
            if not state or state.ended.is_set():
                return _safe_xml("<Response><Hangup/></Response>")

            form = await request.form()
            speech = str(form.get("SpeechResult", "")).strip()
            logger.info("gather_handler %s: speech=%r", room_name, speech[:80] if speech else "")

            if not speech:
                return await _reply_or_heartbeat(room_name, state)

            # A reply still queued now was produced while the caller was
            # talking (e.g. "are you still there?" as they began to answer).
            # They never heard it, and returning it here would answer this
            # utterance with the previous turn's reply.
            _drop_stale_replies(state)
            state.speech_started.set()
            await state.speech_queue.put(speech)
            return await _reply_or_heartbeat(
                room_name, state, acknowledge_after=_filler_after_seconds()
            )
        except Exception:
            logger.exception("gather_handler crashed for %s", room_name)
            return _error_twiml(room_name)

    async def wait_handler(request: Request) -> Response:
        """Heartbeat and no-speech fallthrough: return the reply once it's ready."""
        room_name = request.path_params["room_name"]
        try:
            state = _active_calls.get(room_name)
            if not state or state.ended.is_set():
                return _safe_xml("<Response><Hangup/></Response>")
            return await _reply_or_heartbeat(room_name, state)
        except Exception:
            logger.exception("wait_handler crashed for %s", room_name)
            return _error_twiml(room_name)

    async def status_handler(request: Request) -> Response:
        """Track call status changes (ringing, answered, completed, etc.)."""
        try:
            room_name = request.path_params["room_name"]
            state = _active_calls.get(room_name)
            if not state:
                return Response("ok")

            form = await request.form()
            status = str(form.get("CallStatus", ""))
            logger.info("Twilio call %s status: %s", room_name, status)

            if status in ("completed", "busy", "no-answer", "canceled", "failed"):
                state.completed = True
                state.ended.set()
                state.speech_queue.put_nowait(None)
                state.response_queue.put_nowait(None)  # unblock waiting handlers
                if status != "completed":
                    state.answered.set()  # unblock dial() so it can raise
        except Exception:
            logger.exception("status_handler crashed")
        return Response("ok")

    async def recording_handler(request: Request) -> Response:
        """Receives the recording callback when a call recording is ready."""
        try:
            room_name = request.path_params["room_name"]
            state = _active_calls.get(room_name)
            if not state:
                return Response("ok")

            form = await request.form()
            recording_url = str(form.get("RecordingUrl", ""))
            recording_sid = str(form.get("RecordingSid", ""))
            recording_duration = int(form.get("RecordingDuration", 0) or 0)

            if recording_url:
                state.recording_url = recording_url
                state.recording_sid = recording_sid
                state.recording_duration = recording_duration
                logger.info(
                    "Recording ready for %s: %s (%ds)",
                    room_name, recording_sid, recording_duration,
                )
        except Exception:
            logger.exception("recording_handler crashed")
        return Response("ok")

    async def amd_handler(request: Request) -> Response:
        """Answering Machine Detection callback."""
        try:
            room_name = request.path_params["room_name"]
            state = _active_calls.get(room_name)
            if not state:
                return Response("ok")

            form = await request.form()
            amd_status = str(form.get("AnsweredBy", ""))
            state.amd_result = amd_status
            logger.info("AMD result for %s: %s", room_name, amd_status)

            if amd_status in ("machine_start", "machine_end_beep", "machine_end_silence", "fax"):
                logger.info("Machine detected for %s, marking as voicemail", room_name)
        except Exception:
            logger.exception("amd_handler crashed")
        return Response("ok")

    async def audio_handler(request: Request) -> Response:
        """Serve Sarvam-synthesized audio for Twilio's <Play> verb."""
        audio_id = request.path_params["audio_id"]
        audio = _audio_store.get(audio_id)
        if audio is None:
            return Response("not found", status_code=404)
        # Sarvam returns WAV; detect format from header
        mime = "audio/wav" if audio[:4] == b"RIFF" else "audio/mpeg"
        # The id is a hash of the text and voice, so the content never changes.
        return Response(audio, media_type=mime, headers={"Cache-Control": "public, max-age=86400"})

    async def message_status_handler(request: Request) -> Response:
        """Delivery receipts for the post-call SMS and WhatsApp follow-ups."""
        try:
            from ..followup import record_delivery_status

            form = await request.form()
            await record_delivery_status(
                call_id=request.path_params["call_id"],
                channel=request.path_params["channel"],
                message_sid=str(form.get("MessageSid", "")),
                status=str(form.get("MessageStatus", "")),
                error_code=str(form.get("ErrorCode", "") or ""),
            )
        except Exception:
            logger.exception("message_status_handler crashed")
        return Response("ok")

    routes = [
        Route("/twilio/voice/{room_name}", voice_handler, methods=["POST"]),
        Route("/twilio/gather/{room_name}", gather_handler, methods=["POST"]),
        Route("/twilio/wait/{room_name}", wait_handler, methods=["POST"]),
        Route("/twilio/status/{room_name}", status_handler, methods=["POST"]),
        Route("/twilio/recording/{room_name}", recording_handler, methods=["POST"]),
        Route("/twilio/amd/{room_name}", amd_handler, methods=["POST"]),
        Route("/twilio/audio/{audio_id}", audio_handler, methods=["GET"]),
        Route(
            "/twilio/message-status/{call_id}/{channel}",
            message_status_handler,
            methods=["POST"],
        ),
    ]

    return Starlette(routes=routes)


def _drop_stale_replies(state: _CallState) -> None:
    """Discard queued replies the caller talked over.

    The end-of-call sentinel and a final goodbye are kept: the first must
    still end the call, and the second is what the session is waiting on to
    hang up.
    """
    keep: list[_Reply | None] = []
    while True:
        try:
            item = state.response_queue.get_nowait()
        except asyncio.QueueEmpty:
            break
        if item is None or item.final:
            keep.append(item)
        else:
            logger.info("Dropping unheard reply: %s", item.segments[0][0][:60])
            item.delivered.set()
    for item in keep:
        state.response_queue.put_nowait(item)


def _next_acknowledgement(state: _CallState) -> tuple[str, str | None] | None:
    """(text, audio id) of the acknowledgement to play now, or None.

    Rotates through the call's acknowledgements and never repeats the last
    one — "Okay. … Okay. … Okay." sounds like a machine. With the Sarvam
    voice only audio already synthesized is used: making one now would add
    exactly the wait it is there to cover.
    """
    acknowledgements = phrases_for(state.language).acknowledgements
    tts_language = _tts_language(state.language)
    count = len(acknowledgements)
    for step in range(1, count + 1):
        index = (state.last_acknowledgement + step) % count
        if index == state.last_acknowledgement:
            continue
        text = acknowledgements[index]
        audio_id = None
        if VOICE_PROVIDER == "sarvam":
            audio_id = _audio_id(text, tts_language)
            if audio_id not in _audio_store:
                continue
        state.last_acknowledgement = index
        return text, audio_id
    return None


_XML_QUOTES = {'"': "&quot;", "'": "&apos;"}


def _speak_twiml(text: str, audio_id: str | None) -> str:
    """One line: Sarvam audio with <Play>, else Twilio's own voice with <Say>."""
    if audio_id:
        return f"<Play>{_webhook_base()}/twilio/audio/{audio_id}</Play>"
    voice = os.getenv("TWILIO_VOICE", "Polly.Joanna-Neural")
    return f'<Say voice="{voice}">{escape(text, _XML_QUOTES)}</Say>'


def _acknowledgement_twiml(room_name: str, text: str, audio_id: str | None) -> str:
    """Say the acknowledgement, then come straight back for the reply.

    Not a turn: it is never queued as a reply, so it never reaches the
    transcript or the model.
    """
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"{_speak_twiml(text, audio_id)}"
        f'<Redirect method="POST">{_webhook_base()}/twilio/wait/{room_name}</Redirect>'
        "</Response>"
    )


def _reply_twiml(room_name: str, reply: _Reply, language: str) -> str:
    """Build TwiML that speaks the agent's reply and gathers the caller's next line.

    Each sentence plays as pre-synthesized Sarvam audio with <Play>, or with
    Twilio's built-in <Say> where synthesis failed or isn't configured. A
    final reply is played outside <Gather> and followed by <Hangup/>. The
    caller is listened to in the call's language.
    """
    base = _webhook_base()
    speak = "".join(_speak_twiml(text, audio_id) for text, audio_id in reply.segments)
    reply.mark_delivered()

    if reply.final:
        return f'<?xml version="1.0" encoding="UTF-8"?><Response>{speak}<Hangup/></Response>'

    gather_attrs = (
        f'input="speech" action="{base}/twilio/gather/{room_name}" method="POST" '
        f'speechTimeout="{SPEECH_TIMEOUT}" timeout="{GATHER_TIMEOUT}" '
        f'language="{_gather_language(language)}"'
    )
    if SPEECH_MODEL:
        gather_attrs += f' speechModel="{SPEECH_MODEL}"'
        # Only Twilio's phone_call model has an enhanced tier.
        if SPEECH_MODEL == "phone_call":
            gather_attrs += ' enhanced="true"'

    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f"<Gather {gather_attrs}>{speak}</Gather>"
        # No speech before the Gather timed out: wait for the session to
        # decide what to say next.
        f'<Redirect method="POST">{base}/twilio/wait/{room_name}</Redirect>'
        "</Response>"
    )


def _heartbeat_twiml(base: str, room_name: str) -> "Response":
    """Return TwiML that keeps the call alive while waiting for the LLM.

    Only reached when a reply takes longer than REPLY_WAIT_SECONDS. The pause
    is short because a reply arriving during it waits for the pause to end.
    """
    from starlette.responses import Response

    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Pause length="1"/>'
        f'<Redirect method="POST">{base}/twilio/wait/{room_name}</Redirect>'
        "</Response>",
        media_type="application/xml",
    )


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------


class TwilioTelephony:
    """Places outbound PSTN calls through Twilio's Programmable Voice."""

    def __init__(
        self,
        *,
        account_sid: str | None = None,
        auth_token: str | None = None,
        from_number: str | None = None,
        webhook_url: str | None = None,
        webhook_port: int | None = None,
        answer_timeout: float = 30.0,
    ) -> None:
        from twilio.rest import Client

        self._sid = account_sid or os.environ["TWILIO_ACCOUNT_SID"]
        self._token = auth_token or os.environ["TWILIO_AUTH_TOKEN"]
        self._from = from_number or os.environ["TWILIO_PHONE_NUMBER"]
        # When running on a single-port host (Render, Railway), the webhook
        # routes are mounted on the main FastAPI app at /twilio/*. The
        # TWILIO_WEBHOOK_URL should be the public URL of the main app, and
        # we use the same port — no separate webhook server needed.
        self._webhook_url = (
            webhook_url
            or os.getenv("TWILIO_WEBHOOK_URL")
            or os.getenv("RENDER_EXTERNAL_URL")  # Render auto-sets this
            or "http://localhost:8765"
        )
        self._webhook_port = webhook_port or int(os.getenv("TWILIO_WEBHOOK_PORT", "8765"))
        self._answer_timeout = answer_timeout
        self._client = Client(self._sid, self._token)
        self._server_started = False
        self._server_task: asyncio.Task | None = None

    def prepare_call(self, room_name: str, *, language: str, greeting: str) -> None:
        """Set up the next call to `room_name` before it is dialled.

        Remembers the call's language — what <Gather> listens for and which
        voice language Sarvam speaks in — and, with the Sarvam voice, starts
        synthesizing the greeting and this language's acknowledgements, so
        both are ready by the time someone answers.
        """
        _prepared_languages[room_name] = language
        for line in (greeting, *phrases_for(language).acknowledgements):
            prefetch_speech(line, language)

    async def _ensure_server(self) -> None:
        """Start the embedded webhook server if it isn't running yet.

        When TWILIO_WEBHOOK_URL points to the main app (e.g. on Render where
        the routes are mounted at /twilio/* on the FastAPI app), skip starting
        a separate server — the main app already handles the webhooks.
        """
        if self._server_started:
            return

        # If the webhook URL matches the main app (Render, etc.), the routes
        # are already mounted on the main FastAPI app — no separate server.
        port_str = str(self._webhook_port)
        if self._webhook_url and "localhost" not in self._webhook_url and f":{port_str}" not in self._webhook_url:
            self._server_started = True
            logger.info("Twilio webhooks routed through main app at %s", self._webhook_url)
            return

        import uvicorn

        app = _build_webhook_app()
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self._webhook_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)

        self._server_task = asyncio.create_task(server.serve())
        self._server_started = True
        # Give the server a moment to bind
        await asyncio.sleep(0.5)
        logger.info(
            "Twilio webhook server listening on port %d (public URL: %s)",
            self._webhook_port,
            self._webhook_url,
        )

    async def dial(self, *, phone_e164: str, room_name: str):
        """Place an outbound call and return protocol adapters.

        Returns (TwilioListener, TwilioSpeaker, TwilioControl, call_sid).
        Raises ConnectionError on busy / no-answer / rejected.
        """
        await self._ensure_server()

        state = _CallState(language=_prepared_languages.pop(room_name, "en"))
        _active_calls[room_name] = state

        try:
            call = await asyncio.to_thread(
                self._client.calls.create,
                to=phone_e164,
                from_=self._from,
                url=f"{self._webhook_url}/twilio/voice/{room_name}",
                method="POST",
                status_callback=f"{self._webhook_url}/twilio/status/{room_name}",
                status_callback_method="POST",
                status_callback_event=["initiated", "ringing", "answered", "completed"],
                # Call recording — stores full audio for QA and playback
                record=True,
                recording_status_callback=f"{self._webhook_url}/twilio/recording/{room_name}",
                recording_status_callback_method="POST",
                recording_status_callback_event=["completed"],
                # Answering Machine Detection — detect voicemail vs human
                machine_detection="DetectMessageEnd",
                async_amd=True,
                async_amd_status_callback=f"{self._webhook_url}/twilio/amd/{room_name}",
                async_amd_status_callback_method="POST",
            )
        except Exception as exc:
            _active_calls.pop(room_name, None)
            raise CallNotPlaced(f"Twilio dial failed for {phone_e164}: {exc}") from exc

        state.call_sid = call.sid
        logger.info("Twilio call placed: %s -> %s (SID: %s)", self._from, phone_e164, call.sid)

        # Wait for the call to be answered
        try:
            await asyncio.wait_for(state.answered.wait(), timeout=self._answer_timeout)
        except asyncio.TimeoutError:
            _active_calls.pop(room_name, None)
            raise ConnectionError(f"No answer from {phone_e164} within {self._answer_timeout}s")

        if state.ended.is_set():
            _active_calls.pop(room_name, None)
            raise ConnectionError(f"Call to {phone_e164} ended before connecting (busy/rejected)")

        listener = TwilioListener(state)
        speaker = TwilioSpeaker(state)
        control = TwilioControl(state, self._client)

        # Wrap hangup to also clean up the registry
        original_hangup = control.hangup

        async def hangup_and_cleanup() -> None:
            await original_hangup()
            _active_calls.pop(room_name, None)

        control.hangup = hangup_and_cleanup  # type: ignore[method-assign]

        return listener, speaker, control, call.sid

    def get_call_state(self, room_name: str) -> _CallState | None:
        """Access the call state for a room to retrieve recording/AMD info."""
        return _active_calls.get(room_name)
