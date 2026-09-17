"""Sarvam AI STT (Saarika) and TTS (Bulbul) adapter.

Uses the official `sarvamapi` SDK. Drop-in for the Twilio adapter (TTS)
and optionally for the LiveKit adapter (STT + TTS).

Requires SARVAM_API_KEY in the environment and `sarvamapi` installed.
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import struct
from collections.abc import AsyncIterator

logger = logging.getLogger(__name__)

# Defaults — overridable via environment.
SARVAM_STT_LANGUAGE = os.getenv("SARVAM_STT_LANGUAGE", "en-IN")
SARVAM_TTS_LANGUAGE = os.getenv("SARVAM_TTS_LANGUAGE", "en-IN")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "shubh")
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saarika:v2")
SARVAM_TTS_SAMPLE_RATE = int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "22050"))


def _api_key() -> str:
    key = os.getenv("SARVAM_API_KEY", "")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    return key


def _make_client():
    """Create a SarvamAI client with the configured key."""
    from sarvamai import SarvamAI
    return SarvamAI(api_subscription_key=_api_key())


class SarvamTTS:
    """Text-to-speech using Sarvam Bulbul v3 via the official SDK.

    Two output modes:
      - `synthesize_mp3()` returns MP3 bytes for Twilio's <Play>.
      - `synthesize()` returns raw PCM for LiveKit AudioSource.
    """

    def __init__(
        self,
        *,
        language: str = SARVAM_TTS_LANGUAGE,
        speaker: str = SARVAM_TTS_SPEAKER,
        model: str = SARVAM_TTS_MODEL,
        sample_rate: int = SARVAM_TTS_SAMPLE_RATE,
    ) -> None:
        self._language = language
        self._speaker = speaker
        self._model = model
        self._sample_rate = sample_rate

    async def synthesize_mp3(self, text: str) -> bytes:
        """Convert text to MP3 audio bytes (for Twilio <Play>).

        Uses the SDK's convert_stream which returns MP3 directly.
        """
        loop = asyncio.get_running_loop()
        try:
            mp3_bytes = await loop.run_in_executor(None, self._call_sdk, text)
            if not mp3_bytes:
                logger.warning("Sarvam TTS returned empty audio for: %s", text[:60])
            return mp3_bytes or b""
        except Exception:
            logger.exception("Sarvam TTS failed")
            return b""

    async def synthesize(self, text: str) -> bytes:
        """Convert text to raw PCM audio bytes (for LiveKit)."""
        mp3_bytes = await self.synthesize_mp3(text)
        if not mp3_bytes:
            return b""
        # Convert MP3 to PCM for LiveKit audio frames
        return await asyncio.get_running_loop().run_in_executor(
            None, _mp3_to_pcm, mp3_bytes
        )

    def _call_sdk(self, text: str) -> bytes:
        """Synchronous SDK call — run in executor."""
        client = _make_client()
        response = client.text_to_speech.convert_stream(
            text=text,
            target_language_code=self._language,
            speaker=self._speaker,
            model=self._model,
            pace=1.0,
            speech_sample_rate=self._sample_rate,
        )
        return response if isinstance(response, bytes) else bytes(response)

    async def close(self) -> None:
        pass  # SDK client doesn't need explicit cleanup


class SarvamSTT:
    """Speech-to-text using Sarvam Saarika via the official SDK."""

    def __init__(self, *, language: str = SARVAM_STT_LANGUAGE, model: str = SARVAM_STT_MODEL) -> None:
        self._language = language
        self._model = model
        self._audio_buffer = bytearray()
        self._results: asyncio.Queue[str] = asyncio.Queue()
        self._speech_started = asyncio.Event()

    async def transcribe(self, audio_bytes: bytes) -> str | None:
        """Send audio to Sarvam STT and return the transcript."""
        wav_bytes = _pcm_to_wav(audio_bytes, sample_rate=16000, channels=1, sample_width=2)
        loop = asyncio.get_running_loop()
        try:
            result = await loop.run_in_executor(
                None, self._call_sdk, wav_bytes
            )
            return result
        except Exception:
            logger.exception("Sarvam STT request failed")
            return None

    def _call_sdk(self, wav_bytes: bytes) -> str | None:
        """Synchronous SDK call — run in executor."""
        import tempfile
        client = _make_client()

        # SDK expects a file path, so write to a temp file
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as f:
            f.write(wav_bytes)
            tmp_path = f.name

        try:
            response = client.speech_to_text.transcribe(
                file=open(tmp_path, "rb"),
                language_code=self._language,
                model=self._model,
            )
            return response.transcript.strip() if hasattr(response, "transcript") else ""
        finally:
            os.unlink(tmp_path)

    def push_audio(self, pcm_frame: bytes) -> None:
        """Accumulate audio frames from the LiveKit stream."""
        self._audio_buffer.extend(pcm_frame)

    async def flush(self) -> None:
        """Transcribe whatever audio has been buffered, then clear it."""
        if len(self._audio_buffer) < 1600:
            self._audio_buffer.clear()
            return

        audio = bytes(self._audio_buffer)
        self._audio_buffer.clear()

        text = await self.transcribe(audio)
        if text:
            self._speech_started.set()
            await self._results.put(text)

    async def get_next(self) -> str | None:
        return await self._results.get()

    async def close(self) -> None:
        pass


# ---------------------------------------------------------------------------
# LiveKit-compatible wrappers
# ---------------------------------------------------------------------------


class SarvamLiveKitListener:
    """Implements the Listener protocol using Sarvam STT."""

    def __init__(self, stt: SarvamSTT, vad_stream) -> None:
        self._stt = stt
        self._vad = vad_stream
        self._speech_started = asyncio.Event()

    async def utterances(self) -> AsyncIterator[str]:
        while True:
            text = await self._stt.get_next()
            if text is None:
                return
            self._speech_started.clear()
            yield text

    async def wait_for_speech_start(self) -> None:
        await self._speech_started.wait()

    def signal_speech(self) -> None:
        self._speech_started.set()


class SarvamLiveKitSpeaker:
    """Implements the Speaker protocol using Sarvam TTS."""

    def __init__(self, tts: SarvamTTS, audio_source) -> None:
        self._tts = tts
        self._source = audio_source
        self._current_text = ""
        self._played_samples = 0
        self._total_samples = 0
        self._cancelled = False

    async def say(self, text: str) -> None:
        self._current_text = text
        self._played_samples = 0
        self._total_samples = 0
        self._cancelled = False

        pcm = await self._tts.synthesize(text)
        if not pcm:
            self._current_text = ""
            return

        frame_bytes = 960  # 20ms at 24kHz mono 16-bit
        self._total_samples = len(pcm) // 2

        try:
            from livekit import rtc
        except ImportError:
            logger.error("livekit package required for SarvamLiveKitSpeaker")
            self._current_text = ""
            return

        offset = 0
        while offset < len(pcm) and not self._cancelled:
            end = min(offset + frame_bytes, len(pcm))
            chunk = pcm[offset:end]
            samples = len(chunk) // 2
            frame = rtc.AudioFrame(
                data=chunk,
                sample_rate=24000,
                num_channels=1,
                samples_per_channel=samples,
            )
            await self._source.capture_frame(frame)
            self._played_samples += samples
            offset = end

        self._current_text = ""

    async def stop(self) -> str:
        self._cancelled = True
        if not self._current_text or self._total_samples == 0:
            return ""
        ratio = min(1.0, self._played_samples / self._total_samples)
        cutoff = int(len(self._current_text) * ratio)
        partial = self._current_text[:cutoff].rstrip()
        self._current_text = ""
        return partial


# ---------------------------------------------------------------------------
# Audio helpers
# ---------------------------------------------------------------------------


def _pcm_to_wav(pcm: bytes, *, sample_rate: int, channels: int, sample_width: int) -> bytes:
    """Wrap raw PCM in a WAV header."""
    buf = io.BytesIO()
    data_size = len(pcm)
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))
    buf.write(struct.pack("<H", 1))  # PCM
    buf.write(struct.pack("<H", channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * channels * sample_width))
    buf.write(struct.pack("<H", channels * sample_width))
    buf.write(struct.pack("<H", sample_width * 8))
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm)
    return buf.getvalue()


def _mp3_to_pcm(mp3_bytes: bytes) -> bytes:
    """Convert MP3 to raw 16-bit 24kHz mono PCM.

    Uses the built-in audioop + wave if available, otherwise returns
    the MP3 bytes as-is (LiveKit can sometimes handle MP3 directly).
    """
    try:
        import subprocess
        # Use ffmpeg if available (installed on most Linux/Render deployments)
        proc = subprocess.run(
            [
                "ffmpeg", "-i", "pipe:0",
                "-f", "s16le", "-ar", "24000", "-ac", "1",
                "pipe:1",
            ],
            input=mp3_bytes,
            capture_output=True,
            timeout=5,
        )
        if proc.returncode == 0 and proc.stdout:
            return proc.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    logger.warning("ffmpeg not available for MP3→PCM conversion")
    return mp3_bytes
