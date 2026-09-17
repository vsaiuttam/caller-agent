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
  response_queue — Speaker puts agent text; webhook handler reads & returns TwiML

The webhook server runs inside the worker process on a configurable port.
For Twilio to reach it, expose it publicly via ngrok, Cloudflare Tunnel, or
deploy to a host with a public IP.

    ngrok http 8765
    export TWILIO_WEBHOOK_URL=https://<id>.ngrok-free.app

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
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Per-call shared state
# ---------------------------------------------------------------------------


@dataclass
class _CallState:
    """Shared state between the webhook handlers and the protocol adapters."""

    call_sid: str = ""
    answered: asyncio.Event = field(default_factory=asyncio.Event)
    ended: asyncio.Event = field(default_factory=asyncio.Event)

    # Webhook → Listener: recognised speech from <Gather>
    speech_queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)

    # Speaker → Webhook: agent text to say
    response_queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)

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
    """Text-to-speech via Twilio's <Say> verb in the webhook response."""

    def __init__(self, state: _CallState) -> None:
        self._state = state
        self._current_text = ""

    async def say(self, text: str) -> None:
        self._current_text = text
        # Queue text for the webhook handler to pick up and return as TwiML.
        await self._state.response_queue.put(text)
        # In the webhook model, playback duration is handled by Twilio.
        # We approximate a wait so the session doesn't race ahead.
        words = len(text.split())
        await asyncio.sleep(min(words * 0.15, 8.0))

    async def stop(self) -> str:
        """Interrupt: return what was (approximately) played."""
        played = self._current_text
        self._current_text = ""
        return played


class TwilioControl:
    """Hangs up the call via Twilio REST API."""

    def __init__(self, state: _CallState, client) -> None:
        self._state = state
        self._client = client

    async def hangup(self) -> None:
        self._state.ended.set()
        self._state.speech_queue.put_nowait(None)  # unblock Listener
        if self._state.call_sid:
            try:
                await asyncio.to_thread(
                    self._client.calls(self._state.call_sid).update,
                    status="completed",
                )
            except Exception:
                logger.exception("Failed to hang up Twilio call %s", self._state.call_sid)


# ---------------------------------------------------------------------------
# Webhook server (embedded in the worker process)
# ---------------------------------------------------------------------------


def _build_webhook_app():
    """Create a Starlette app that handles Twilio voice webhooks."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import Response
    from starlette.routing import Route

    async def voice_handler(request: Request) -> Response:
        """Initial webhook when call connects. Wait for greeting, return TwiML."""
        room_name = request.path_params["room_name"]
        state = _active_calls.get(room_name)
        if not state:
            return Response("<Response><Hangup/></Response>", media_type="application/xml")

        # Mark call as answered
        form = await request.form()
        state.call_sid = str(form.get("CallSid", state.call_sid))
        state.answered.set()

        # Wait for the greeting from Speaker.say() — must respond within
        # Twilio's webhook timeout (~15s), so cap at 10s.
        try:
            greeting = await asyncio.wait_for(state.response_queue.get(), timeout=10.0)
        except asyncio.TimeoutError:
            greeting = "Hello, please hold while I connect."

        if greeting is None or state.ended.is_set():
            return Response("<Response><Hangup/></Response>", media_type="application/xml")

        twiml = _gather_twiml(room_name, greeting)
        return Response(twiml, media_type="application/xml")

    async def gather_handler(request: Request) -> Response:
        """Receives speech result, queues it, then enters the keep-alive loop.

        Instead of blocking on the LLM, we queue the speech and immediately
        redirect to the /twilio/wait/ heartbeat loop. That loop polls for
        the response every few seconds and keeps Twilio alive indefinitely
        with short Pause + Redirect cycles — no webhook ever blocks long
        enough for Twilio to time out.
        """
        room_name = request.path_params["room_name"]
        state = _active_calls.get(room_name)
        if not state or state.ended.is_set():
            return Response("<Response><Hangup/></Response>", media_type="application/xml")

        form = await request.form()
        speech = str(form.get("SpeechResult", "")).strip()

        if speech:
            state.speech_started.set()
            await state.speech_queue.put(speech)

        # Quick check — if the agent already has a response queued, return it
        # immediately (common when the LLM is fast or response was pre-computed).
        try:
            agent_text = await asyncio.wait_for(state.response_queue.get(), timeout=2.0)
        except asyncio.TimeoutError:
            # Not ready yet — enter the keep-alive heartbeat loop
            base = os.getenv("TWILIO_WEBHOOK_URL", "http://localhost:8765")
            return _heartbeat_twiml(base, room_name)

        if agent_text is None or state.ended.is_set():
            return Response(
                "<Response><Say>Thank you for your time. Goodbye.</Say><Hangup/></Response>",
                media_type="application/xml",
            )

        twiml = _gather_twiml(room_name, agent_text)
        return Response(twiml, media_type="application/xml")

    async def wait_handler(request: Request) -> Response:
        """Keep-alive heartbeat: polls for the agent response every ~5s.

        This endpoint forms a tight loop with Twilio:
          1. Wait up to 3s for the LLM response
          2. If ready → return the response as TwiML + Gather
          3. If not ready → return a short Pause + Redirect back here

        Each iteration is well under Twilio's ~15s timeout. The loop
        runs indefinitely until the agent responds or the call ends —
        no "application error" is ever possible.
        """
        room_name = request.path_params["room_name"]
        state = _active_calls.get(room_name)
        if not state or state.ended.is_set():
            return Response("<Response><Hangup/></Response>", media_type="application/xml")

        # Poll for response — short timeout keeps us well under Twilio's limit
        try:
            agent_text = await asyncio.wait_for(state.response_queue.get(), timeout=3.0)
        except asyncio.TimeoutError:
            # Still not ready — send another heartbeat
            base = os.getenv("TWILIO_WEBHOOK_URL", "http://localhost:8765")
            return _heartbeat_twiml(base, room_name)

        if agent_text is None or state.ended.is_set():
            return Response(
                "<Response><Say>Thank you for your time. Goodbye.</Say><Hangup/></Response>",
                media_type="application/xml",
            )

        twiml = _gather_twiml(room_name, agent_text)
        return Response(twiml, media_type="application/xml")

    async def status_handler(request: Request) -> Response:
        """Track call status changes (ringing, answered, completed, etc.)."""
        room_name = request.path_params["room_name"]
        state = _active_calls.get(room_name)
        if not state:
            return Response("ok")

        form = await request.form()
        status = str(form.get("CallStatus", ""))
        logger.info("Twilio call %s status: %s", room_name, status)

        if status in ("completed", "busy", "no-answer", "canceled", "failed"):
            state.ended.set()
            state.speech_queue.put_nowait(None)
            if status != "completed":
                state.answered.set()  # unblock dial() so it can raise

        return Response("ok")

    async def recording_handler(request: Request) -> Response:
        """Receives the recording callback when a call recording is ready."""
        room_name = request.path_params["room_name"]
        state = _active_calls.get(room_name)
        if not state:
            return Response("ok")

        form = await request.form()
        recording_url = str(form.get("RecordingUrl", ""))
        recording_sid = str(form.get("RecordingSid", ""))
        recording_duration = int(form.get("RecordingDuration", 0) or 0)

        if recording_url:
            # Twilio serves recordings at the URL with .mp3/.wav extension
            state.recording_url = recording_url
            state.recording_sid = recording_sid
            state.recording_duration = recording_duration
            logger.info(
                "Recording ready for %s: %s (%ds)",
                room_name, recording_sid, recording_duration,
            )

        return Response("ok")

    async def amd_handler(request: Request) -> Response:
        """Answering Machine Detection callback."""
        room_name = request.path_params["room_name"]
        state = _active_calls.get(room_name)
        if not state:
            return Response("ok")

        form = await request.form()
        amd_status = str(form.get("AnsweredBy", ""))
        state.amd_result = amd_status
        logger.info("AMD result for %s: %s", room_name, amd_status)

        # If it's a machine, we can optionally leave a voicemail or hang up
        if amd_status in ("machine_start", "machine_end_beep", "machine_end_silence", "fax"):
            # Signal that this is a voicemail/machine
            logger.info("Machine detected for %s, marking as voicemail", room_name)

        return Response("ok")

    routes = [
        Route("/twilio/voice/{room_name}", voice_handler, methods=["POST"]),
        Route("/twilio/gather/{room_name}", gather_handler, methods=["POST"]),
        Route("/twilio/wait/{room_name}", wait_handler, methods=["POST"]),
        Route("/twilio/status/{room_name}", status_handler, methods=["POST"]),
        Route("/twilio/recording/{room_name}", recording_handler, methods=["POST"]),
        Route("/twilio/amd/{room_name}", amd_handler, methods=["POST"]),
    ]

    return Starlette(routes=routes)


def _gather_twiml(room_name: str, say_text: str) -> str:
    """Build TwiML that says the agent's text and gathers the caller's reply."""
    base = os.getenv("TWILIO_WEBHOOK_URL", "http://localhost:8765")
    voice = os.getenv("TWILIO_VOICE", "Polly.Joanna-Neural")
    # Escape XML special characters in the text
    safe = (
        say_text
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )
    return (
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        f'<Gather input="speech" action="{base}/twilio/gather/{room_name}" '
        f'method="POST" speechTimeout="auto" language="en-US" '
        f'enhanced="true">'
        f'<Say voice="{voice}">{safe}</Say>'
        "</Gather>"
        # If no speech detected, redirect back to gather
        f'<Redirect method="POST">{base}/twilio/voice/{room_name}</Redirect>'
        "</Response>"
    )


def _heartbeat_twiml(base: str, room_name: str) -> "Response":
    """Return TwiML that keeps the call alive while waiting for the LLM.

    A short <Pause> followed by a <Redirect> back to the wait endpoint.
    Each cycle is ~3s — well under Twilio's ~15s webhook timeout. The loop
    continues indefinitely until the agent's response is ready.
    """
    from starlette.responses import Response

    return Response(
        '<?xml version="1.0" encoding="UTF-8"?>'
        "<Response>"
        '<Pause length="3"/>'
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

        state = _CallState()
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
            raise ConnectionError(f"Twilio dial failed for {phone_e164}: {exc}") from exc

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
