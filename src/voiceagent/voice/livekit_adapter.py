"""LiveKit + STT/TTS adapter.

Supports two voice backends:
  - **deepgram+cartesia** (default): Deepgram streaming STT, Cartesia TTS.
  - **sarvam**: Sarvam Saarika STT + Bulbul TTS. Set VOICE_PROVIDER=sarvam.

⚠️ This is the one version-sensitive file in the project. LiveKit's agents SDK
has changed its plugin surface across 0.x and 1.x releases, so the two spots
marked VERIFY below should be checked against the version you actually install
(`pip show livekit-agents`) before the first real call. Everything else in the
codebase talks to the three protocols in `session.py` and is unaffected by that
churn — that separation is why the adapter is isolated here rather than being
threaded through the call logic.

Outbound flow: create a room, dial the PSTN leg into it via the SIP service,
then wire the participant's audio track to STT and our synthesized audio back
out through TTS.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import AsyncIterator

from livekit import api, rtc
from livekit.plugins import silero

VOICE_PROVIDER = os.getenv("VOICE_PROVIDER", "deepgram").lower()

logger = logging.getLogger(__name__)


class LiveKitListener:
    """Deepgram streaming STT over the caller's audio track."""

    def __init__(self, stt_stream, vad_stream) -> None:
        self._stt = stt_stream
        self._vad = vad_stream
        self._speech_started = asyncio.Event()

    async def utterances(self) -> AsyncIterator[str]:
        # VERIFY: event enum name. Recent versions expose
        # `SpeechEventType.FINAL_TRANSCRIPT`; some 0.x releases used
        # `is_final` on the event instead.
        from livekit.plugins import deepgram as _dg

        async for event in self._stt:
            if event.type == _dg.SpeechEventType.FINAL_TRANSCRIPT:
                text = event.alternatives[0].text.strip()
                if text:
                    self._speech_started.clear()
                    yield text
            elif event.type == _dg.SpeechEventType.START_OF_SPEECH:
                self._speech_started.set()

    async def wait_for_speech_start(self) -> None:
        """Resolve on voice activity, not on a final transcript.

        Waiting for a transcript would add STT latency (several hundred ms) to
        every interruption, which is long enough that the caller talks over
        the agent for a full clause before it stops. VAD fires in tens of ms.
        """
        await self._speech_started.wait()


class LiveKitSpeaker:
    """Cartesia TTS into the room, with interrupt support."""

    def __init__(self, tts, audio_source: rtc.AudioSource) -> None:
        self._tts = tts
        self._source = audio_source
        self._current_text = ""
        self._played_frames = 0
        self._total_frames = 0
        self._cancelled = False

    async def say(self, text: str) -> None:
        self._current_text = text
        self._played_frames = 0
        self._total_frames = 0
        self._cancelled = False

        # VERIFY: synthesize() returns an async iterable of SynthesizedAudio
        # in current releases; older ones returned a ChunkedStream requiring
        # explicit .aclose().
        stream = self._tts.synthesize(text)
        try:
            async for chunk in stream:
                if self._cancelled:
                    break
                await self._source.capture_frame(chunk.frame)
                self._played_frames += chunk.frame.samples_per_channel
                self._total_frames += chunk.frame.samples_per_channel
        finally:
            aclose = getattr(stream, "aclose", None)
            if aclose is not None:
                await aclose()

        self._current_text = ""

    async def stop(self) -> str:
        """Cut playback and estimate what the caller actually heard.

        Proportional estimate from frames played. It's approximate — TTS pacing
        isn't uniform across a sentence — but it errs toward *under*-reporting,
        which is the safe direction: the agent may repeat something already
        heard, rather than assume something unheard was delivered.
        """
        self._cancelled = True
        if not self._current_text or self._total_frames == 0:
            return ""

        ratio = min(1.0, self._played_frames / self._total_frames)
        cutoff = int(len(self._current_text) * ratio)
        partial = self._current_text[:cutoff].rstrip()
        self._current_text = ""
        return partial


class LiveKitControl:
    def __init__(self, room: rtc.Room) -> None:
        self._room = room

    async def hangup(self) -> None:
        await self._room.disconnect()


class LiveKitTelephony:
    """Places outbound PSTN calls through LiveKit's SIP service."""

    def __init__(
        self,
        *,
        livekit_url: str | None = None,
        api_key: str | None = None,
        api_secret: str | None = None,
        sip_trunk_id: str | None = None,
        caller_id: str | None = None,
        answer_timeout: float = 30.0,
    ) -> None:
        self._url = livekit_url or os.environ["LIVEKIT_URL"]
        self._key = api_key or os.environ["LIVEKIT_API_KEY"]
        self._secret = api_secret or os.environ["LIVEKIT_API_SECRET"]
        self._trunk = sip_trunk_id or os.environ["LIVEKIT_SIP_TRUNK_ID"]
        self._caller_id = caller_id or os.getenv("CALLER_ID_E164", "")
        self._answer_timeout = answer_timeout

    async def dial(self, *, phone_e164: str, room_name: str):
        lkapi = api.LiveKitAPI(self._url, self._key, self._secret)

        try:
            await lkapi.sip.create_sip_participant(
                api.CreateSIPParticipantRequest(
                    sip_trunk_id=self._trunk,
                    sip_call_to=phone_e164,
                    room_name=room_name,
                    participant_identity="caller",
                    participant_name=phone_e164,
                    # Block until the leg is answered so a busy or unanswered
                    # number raises here rather than surfacing as a silent
                    # call the agent talks into.
                    wait_until_answered=True,
                )
            )
        except Exception as exc:
            await lkapi.aclose()
            raise ConnectionError(f"Dial failed for {phone_e164}: {exc}") from exc

        token = (
            api.AccessToken(self._key, self._secret)
            .with_identity("agent")
            .with_grants(api.VideoGrants(room_join=True, room=room_name))
            .to_jwt()
        )

        room = rtc.Room()
        await room.connect(self._url, token)

        track = await _wait_for_audio_track(room, timeout=self._answer_timeout)

        source = rtc.AudioSource(sample_rate=24_000, num_channels=1)
        outbound = rtc.LocalAudioTrack.create_audio_track("agent-voice", source)
        await room.local_participant.publish_track(
            outbound, rtc.TrackPublishOptions(source=rtc.TrackSource.SOURCE_MICROPHONE)
        )

        control = LiveKitControl(room)

        if VOICE_PROVIDER == "sarvam":
            listener, speaker, pump_task = await self._setup_sarvam(track, source)
        else:
            listener, speaker, pump_task = await self._setup_deepgram_cartesia(track, source)

        original_hangup = control.hangup

        async def hangup_and_cleanup() -> None:
            pump_task.cancel()
            await lkapi.aclose()
            await original_hangup()

        control.hangup = hangup_and_cleanup  # type: ignore[method-assign]

        return (listener, speaker, control, room_name)

    async def _setup_deepgram_cartesia(self, track, source):
        """Wire Deepgram STT + Cartesia TTS (the original path)."""
        from livekit.plugins import cartesia, deepgram

        stt = deepgram.STT(model="nova-3", interim_results=True)
        tts = cartesia.TTS(model="sonic-2")
        vad = silero.VAD.load()

        stt_stream = stt.stream()
        vad_stream = vad.stream()
        audio_stream = rtc.AudioStream(track)

        async def pump() -> None:
            async for event in audio_stream:
                stt_stream.push_frame(event.frame)
                vad_stream.push_frame(event.frame)

        pump_task = asyncio.create_task(pump())
        return LiveKitListener(stt_stream, vad_stream), LiveKitSpeaker(tts, source), pump_task

    async def _setup_sarvam(self, track, source):
        """Wire Sarvam Saarika STT + Bulbul TTS."""
        from .sarvam_voice import SarvamLiveKitListener, SarvamLiveKitSpeaker, SarvamSTT, SarvamTTS

        sarvam_stt = SarvamSTT()
        sarvam_tts = SarvamTTS(target_sample_rate=24000)
        vad = silero.VAD.load()
        vad_stream = vad.stream()
        audio_stream = rtc.AudioStream(track)

        listener = SarvamLiveKitListener(sarvam_stt, vad_stream)

        async def pump() -> None:
            speaking = False
            async for event in audio_stream:
                frame_bytes = bytes(event.frame.data)
                vad_stream.push_frame(event.frame)
                sarvam_stt.push_audio(frame_bytes)

                try:
                    vad_event = vad_stream.__anext__()
                    done = asyncio.ensure_future(vad_event)
                    if done.done():
                        ve = done.result()
                        if hasattr(ve, "type"):
                            vtype = str(ve.type)
                            if "START" in vtype:
                                speaking = True
                                listener.signal_speech()
                            elif "END" in vtype and speaking:
                                speaking = False
                                await sarvam_stt.flush()
                except (StopAsyncIteration, asyncio.CancelledError):
                    pass

        pump_task = asyncio.create_task(pump())
        return listener, SarvamLiveKitSpeaker(sarvam_tts, source), pump_task


async def _wait_for_audio_track(room: rtc.Room, timeout: float) -> rtc.Track:
    """Wait for the caller's audio track to be subscribed."""
    fut: asyncio.Future[rtc.Track] = asyncio.get_running_loop().create_future()

    # Handle the race where the track was already subscribed before we
    # registered the handler.
    for participant in room.remote_participants.values():
        for publication in participant.track_publications.values():
            if publication.track and publication.kind == rtc.TrackKind.KIND_AUDIO:
                return publication.track

    @room.on("track_subscribed")
    def _on_track(track: rtc.Track, *_):
        if track.kind == rtc.TrackKind.KIND_AUDIO and not fut.done():
            fut.set_result(track)

    return await asyncio.wait_for(fut, timeout=timeout)
