"""Telnyx telephony adapter.

Places outbound PSTN calls through Telnyx's Call Control API and bridges
Telnyx's webhook-based model with the streaming Listener/Speaker/CallControl
protocols used by the rest of the pipeline.

Architecture
------------
Telnyx Call Control is webhook-driven. When a call connects, Telnyx POSTs
events (call.initiated, call.answered, call.hangup, etc.) to your webhook URL.
We use `gather_using_speak` to speak the agent's text and gather speech input
in a single command.

Required env vars
-----------------
    TELNYX_API_KEY       — starts with KEY...
    TELNYX_PHONE_NUMBER  — your Telnyx number in E.164 (+1...)
    TELNYX_WEBHOOK_URL   — public base URL for callbacks
    TELNYX_WEBHOOK_PORT  — local port for the webhook server (default 8765)
    TELNYX_CONNECTION_ID — (optional) SIP connection / TeXML app ID
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator
from dataclasses import dataclass, field

import httpx

logger = logging.getLogger(__name__)

TELNYX_API_BASE = "https://api.telnyx.com/v2"


# ---------------------------------------------------------------------------
# Per-call shared state
# ---------------------------------------------------------------------------


@dataclass
class _CallState:
    """Shared state between the webhook handlers and the protocol adapters."""

    call_control_id: str = ""
    call_leg_id: str = ""
    answered: asyncio.Event = field(default_factory=asyncio.Event)
    ended: asyncio.Event = field(default_factory=asyncio.Event)

    # Webhook → Listener: recognised speech from gather
    speech_queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)

    # Speaker → Webhook: agent text to say
    response_queue: asyncio.Queue[str | None] = field(default_factory=asyncio.Queue)

    # Barge-in signal
    speech_started: asyncio.Event = field(default_factory=asyncio.Event)

    # Recording
    recording_url: str | None = None
    recording_sid: str | None = None
    recording_duration: int | None = None

    # AMD result
    amd_result: str | None = None


# Global registry of active calls, keyed by client_state (room_name).
_active_calls: dict[str, _CallState] = {}


# ---------------------------------------------------------------------------
# Protocol implementations
# ---------------------------------------------------------------------------


class TelnyxListener:
    """Speech-to-text via Telnyx's gather command."""

    def __init__(self, state: _CallState) -> None:
        self._state = state

    async def utterances(self) -> AsyncIterator[str]:
        while not self._state.ended.is_set():
            try:
                text = await asyncio.wait_for(self._state.speech_queue.get(), timeout=1.0)
            except asyncio.TimeoutError:
                continue
            if text is None:
                return
            self._state.speech_started.clear()
            yield text

    async def wait_for_speech_start(self) -> None:
        await self._state.speech_started.wait()
        self._state.speech_started.clear()


class TelnyxSpeaker:
    """Text-to-speech via Telnyx's speak command."""

    def __init__(self, state: _CallState, api_key: str) -> None:
        self._state = state
        self._api_key = api_key
        self._current_text = ""

    async def say(self, text: str) -> None:
        self._current_text = text
        await self._state.response_queue.put(text)
        # Approximate playback wait
        words = len(text.split())
        await asyncio.sleep(min(words * 0.15, 8.0))

    async def stop(self) -> str:
        played = self._current_text
        self._current_text = ""
        return played


class TelnyxControl:
    """Hangs up the call via Telnyx Call Control API."""

    def __init__(self, state: _CallState, api_key: str) -> None:
        self._state = state
        self._api_key = api_key

    async def hangup(self) -> None:
        self._state.ended.set()
        self._state.speech_queue.put_nowait(None)
        if self._state.call_control_id:
            try:
                async with httpx.AsyncClient() as client:
                    await client.post(
                        f"{TELNYX_API_BASE}/calls/{self._state.call_control_id}/actions/hangup",
                        headers={"Authorization": f"Bearer {self._api_key}"},
                        json={"client_state": ""},
                        timeout=10.0,
                    )
            except Exception:
                logger.exception("Failed to hang up Telnyx call %s", self._state.call_control_id)


# ---------------------------------------------------------------------------
# Telnyx API helpers
# ---------------------------------------------------------------------------


async def _telnyx_command(api_key: str, call_control_id: str, action: str, payload: dict) -> dict:
    """Send a Call Control command to Telnyx."""
    async with httpx.AsyncClient() as client:
        resp = await client.post(
            f"{TELNYX_API_BASE}/calls/{call_control_id}/actions/{action}",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
            },
            json=payload,
            timeout=15.0,
        )
        resp.raise_for_status()
        return resp.json()


async def _gather_using_speak(api_key: str, call_control_id: str, text: str, room_name: str):
    """Speak text and gather speech input simultaneously."""
    safe_text = text.replace('"', '\\"')
    await _telnyx_command(api_key, call_control_id, "gather_using_speak", {
        "payload": safe_text,
        "voice": "female",
        "language": "en-US",
        "minimum_digits": 1,
        "maximum_digits": 0,  # No DTMF, speech only
        "valid_digits": "",
        "inter_digit_timeout_secs": 20,
        "gather_speech": {
            "language": "en-US",
            "timeout_secs": 15,
        },
        "client_state": room_name,
    })


# ---------------------------------------------------------------------------
# Webhook server
# ---------------------------------------------------------------------------


def _build_webhook_app(api_key: str):
    """Create a Starlette app that handles Telnyx Call Control webhooks."""
    from starlette.applications import Starlette
    from starlette.requests import Request
    from starlette.responses import JSONResponse, Response
    from starlette.routing import Route

    async def webhook_handler(request: Request) -> Response:
        """Handle all Telnyx Call Control events."""
        try:
            body = await request.json()
        except Exception:
            return Response("bad request", status_code=400)

        data = body.get("data", {})
        event_type = data.get("event_type", "")
        payload = data.get("payload", {})
        client_state = payload.get("client_state", "")

        # Decode base64 client_state if needed
        if client_state:
            import base64
            try:
                client_state = base64.b64decode(client_state).decode("utf-8")
            except Exception:
                pass  # Already plain text

        state = _active_calls.get(client_state)

        logger.info("Telnyx event: %s for %s", event_type, client_state or "unknown")

        if event_type == "call.initiated":
            # Call is being placed
            if state:
                state.call_control_id = payload.get("call_control_id", "")
                state.call_leg_id = payload.get("call_leg_id", "")

        elif event_type == "call.answered":
            if state:
                state.call_control_id = payload.get("call_control_id", "")
                state.answered.set()

                # Start gathering — send the greeting
                try:
                    greeting = await asyncio.wait_for(state.response_queue.get(), timeout=15.0)
                except asyncio.TimeoutError:
                    greeting = "Hello, please hold."

                if greeting and not state.ended.is_set():
                    import base64
                    encoded = base64.b64encode(client_state.encode()).decode()
                    await _telnyx_command(api_key, state.call_control_id, "gather_using_speak", {
                        "payload": greeting,
                        "voice": "female",
                        "language": "en-US",
                        "inter_digit_timeout_secs": 30,
                        "valid_digits": "",
                        "minimum_digits": 1,
                        "maximum_digits": 0,
                        "client_state": encoded,
                    })

        elif event_type == "call.gather.ended":
            if state and not state.ended.is_set():
                # Speech was gathered
                speech = payload.get("speech", {})
                result_text = speech.get("result", "").strip() if speech else ""
                digits = payload.get("digits", "")

                if result_text:
                    state.speech_started.set()
                    await state.speech_queue.put(result_text)

                # Wait for agent's response
                try:
                    agent_text = await asyncio.wait_for(state.response_queue.get(), timeout=30.0)
                except asyncio.TimeoutError:
                    agent_text = "I need a moment, please hold."

                if agent_text is None or state.ended.is_set():
                    # Hang up
                    await _telnyx_command(api_key, state.call_control_id, "speak", {
                        "payload": "Thank you for your time. Goodbye.",
                        "voice": "female",
                        "language": "en-US",
                        "client_state": "",
                    })
                    await asyncio.sleep(2)
                    try:
                        await _telnyx_command(api_key, state.call_control_id, "hangup", {})
                    except Exception:
                        pass
                else:
                    import base64
                    encoded = base64.b64encode(client_state.encode()).decode()
                    await _telnyx_command(api_key, state.call_control_id, "gather_using_speak", {
                        "payload": agent_text,
                        "voice": "female",
                        "language": "en-US",
                        "inter_digit_timeout_secs": 30,
                        "valid_digits": "",
                        "minimum_digits": 1,
                        "maximum_digits": 0,
                        "client_state": encoded,
                    })

        elif event_type == "call.speak.ended":
            # Speaking finished, if no gather was active we might need to gather
            pass

        elif event_type in ("call.hangup", "call.machine.detection.ended"):
            if state:
                if event_type == "call.machine.detection.ended":
                    result = payload.get("result", "")
                    state.amd_result = result
                    if result in ("machine", "fax"):
                        logger.info("Machine detected for %s", client_state)
                else:
                    state.ended.set()
                    state.speech_queue.put_nowait(None)
                    if not state.answered.is_set():
                        state.answered.set()

        elif event_type == "call.recording.saved":
            if state:
                recording_urls = payload.get("recording_urls", {})
                state.recording_url = recording_urls.get("mp3", "")
                state.recording_sid = payload.get("recording_id", "")
                duration = payload.get("duration_secs", 0)
                state.recording_duration = int(duration) if duration else None
                logger.info("Recording saved for %s: %s", client_state, state.recording_sid)

        return JSONResponse({"status": "ok"})

    routes = [
        Route("/telnyx/webhook", webhook_handler, methods=["POST"]),
        # Telnyx sometimes sends to the root path
        Route("/", webhook_handler, methods=["POST"]),
    ]

    return Starlette(routes=routes)


# ---------------------------------------------------------------------------
# Main adapter
# ---------------------------------------------------------------------------


class TelnyxTelephony:
    """Places outbound PSTN calls through Telnyx's Call Control API."""

    def __init__(
        self,
        *,
        api_key: str | None = None,
        from_number: str | None = None,
        webhook_url: str | None = None,
        webhook_port: int | None = None,
        connection_id: str | None = None,
        answer_timeout: float = 30.0,
    ) -> None:
        self._api_key = api_key or os.environ["TELNYX_API_KEY"]
        self._from = from_number or os.environ["TELNYX_PHONE_NUMBER"]
        self._webhook_url = webhook_url or os.getenv("TELNYX_WEBHOOK_URL", "http://localhost:8765")
        self._webhook_port = webhook_port or int(os.getenv("TELNYX_WEBHOOK_PORT", "8765"))
        self._connection_id = connection_id or os.getenv("TELNYX_CONNECTION_ID", "")
        self._answer_timeout = answer_timeout
        self._server_started = False
        self._server_task: asyncio.Task | None = None

    async def _ensure_server(self) -> None:
        if self._server_started:
            return

        import uvicorn

        app = _build_webhook_app(self._api_key)
        config = uvicorn.Config(
            app,
            host="0.0.0.0",
            port=self._webhook_port,
            log_level="warning",
        )
        server = uvicorn.Server(config)
        self._server_task = asyncio.create_task(server.serve())
        self._server_started = True
        await asyncio.sleep(0.5)
        logger.info(
            "Telnyx webhook server listening on port %d (public URL: %s)",
            self._webhook_port,
            self._webhook_url,
        )

    async def dial(self, *, phone_e164: str, room_name: str):
        """Place an outbound call and return protocol adapters.

        Returns (TelnyxListener, TelnyxSpeaker, TelnyxControl, call_control_id).
        Raises ConnectionError on failure.
        """
        await self._ensure_server()

        state = _CallState()
        _active_calls[room_name] = state

        import base64
        encoded_state = base64.b64encode(room_name.encode()).decode()

        try:
            create_payload = {
                "to": phone_e164,
                "from": self._from,
                "webhook_url": f"{self._webhook_url}/telnyx/webhook",
                "webhook_url_method": "POST",
                "client_state": encoded_state,
                "record": "record-from-answer",
                "answering_machine_detection": "detect",
            }
            if self._connection_id:
                create_payload["connection_id"] = self._connection_id

            async with httpx.AsyncClient() as client:
                resp = await client.post(
                    f"{TELNYX_API_BASE}/calls",
                    headers={
                        "Authorization": f"Bearer {self._api_key}",
                        "Content-Type": "application/json",
                    },
                    json=create_payload,
                    timeout=15.0,
                )
                resp.raise_for_status()
                call_data = resp.json().get("data", {})
                state.call_control_id = call_data.get("call_control_id", "")
                state.call_leg_id = call_data.get("call_leg_id", "")
        except Exception as exc:
            _active_calls.pop(room_name, None)
            raise ConnectionError(f"Telnyx dial failed for {phone_e164}: {exc}") from exc

        logger.info("Telnyx call placed: %s -> %s (ID: %s)", self._from, phone_e164, state.call_control_id)

        # Wait for the call to be answered
        try:
            await asyncio.wait_for(state.answered.wait(), timeout=self._answer_timeout)
        except asyncio.TimeoutError:
            _active_calls.pop(room_name, None)
            raise ConnectionError(f"No answer from {phone_e164} within {self._answer_timeout}s")

        if state.ended.is_set():
            _active_calls.pop(room_name, None)
            raise ConnectionError(f"Call to {phone_e164} ended before connecting")

        listener = TelnyxListener(state)
        speaker = TelnyxSpeaker(state, self._api_key)
        control = TelnyxControl(state, self._api_key)

        original_hangup = control.hangup

        async def hangup_and_cleanup() -> None:
            await original_hangup()
            _active_calls.pop(room_name, None)

        control.hangup = hangup_and_cleanup  # type: ignore[method-assign]

        return listener, speaker, control, state.call_control_id

    def get_call_state(self, room_name: str) -> _CallState | None:
        return _active_calls.get(room_name)
