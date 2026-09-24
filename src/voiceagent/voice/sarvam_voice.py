"""Sarvam AI STT (Saarika) and TTS (Bulbul) adapter.

Uses httpx to call the Sarvam REST API directly — fully async, no SDK dep.
Drop-in for the Twilio adapter (TTS) and optionally for LiveKit (STT + TTS).

Requires SARVAM_API_KEY in the environment.
"""

from __future__ import annotations

import asyncio
import base64
import io
import logging
import os
import struct
from collections.abc import AsyncIterator

import httpx

logger = logging.getLogger(__name__)

# Defaults — overridable via environment.
SARVAM_STT_LANGUAGE = os.getenv("SARVAM_STT_LANGUAGE", "en-IN")
SARVAM_TTS_LANGUAGE = os.getenv("SARVAM_TTS_LANGUAGE", "en-IN")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "shubh")
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v3")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saarika:v2")
SARVAM_TTS_SAMPLE_RATE = int(os.getenv("SARVAM_TTS_SAMPLE_RATE", "22050"))

SARVAM_TTS_URL = "https://api.sarvam.ai/text-to-speech"
SARVAM_STT_URL = "https://api.sarvam.ai/speech-to-text"


def _api_key() -> str:
    key = os.getenv("SARVAM_API_KEY", "")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    return key


def _headers() -> dict[str, str]:
    return {
        "api-subscription-key": _api_key(),
        "Content-Type": "application/json",
    }


class SarvamTTS:
    """Text-to-speech using Sarvam Bulbul v3 via REST API.

    Two output modes:
      - ``synthesize_wav()`` returns WAV bytes for Twilio's <Play>.
      - ``synthesize()`` returns raw PCM for LiveKit AudioSource.

    Keep one instance alive for the process where you can: the HTTP client
    holds its connection open, and a fresh TLS handshake to Sarvam measured
    ~600 ms on top of a ~570 ms synthesis — paid on every agent turn.
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
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=httpx.Timeout(10.0, connect=5.0))
        return self._client

    async def synthesize_wav(self, text: str) -> bytes:
        """Convert text to WAV audio bytes (for Twilio <Play>).

        The Sarvam API returns base64-encoded WAV. We decode and return raw bytes.
        """
        try:
            client = await self._get_client()
            payload = {
                "text": text,
                "target_language_code": self._language,
                "speaker": self._speaker,
                "model": self._model,
                "pace": 1.0,
                "speech_sample_rate": self._sample_rate,
            }
            # Bulbul v3 documents enable_preprocessing as unsupported.
            if self._model != "bulbul:v3":
                payload["enable_preprocessing"] = True
            resp = await client.post(
                SARVAM_TTS_URL,
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()

            # API returns {"audios": ["base64-encoded-wav", ...]}
            audios = data.get("audios", [])
            if not audios:
                logger.warning("Sarvam TTS returned no audios for: %s", text[:60])
                return b""

            wav_bytes = base64.b64decode(audios[0])
            logger.info("Sarvam TTS OK: %d bytes for %r", len(wav_bytes), text[:40])
            return wav_bytes

        except httpx.HTTPStatusError as exc:
            logger.error("Sarvam TTS HTTP %d: %s", exc.response.status_code, exc.response.text[:200])
            return b""
        except Exception:
            logger.exception("Sarvam TTS failed")
            return b""

    async def synthesize(self, text: str) -> bytes:
        """Convert text to raw PCM audio bytes (for LiveKit)."""
        wav_bytes = await self.synthesize_wav(text)
        if not wav_bytes:
            return b""
        return _wav_to_pcm(wav_bytes)

    async def close(self) -> None:
        if self._client and not self._client.is_closed:
            await self._client.aclose()


class SarvamSTT:
    """Speech-to-text using Sarvam Saarika via REST API."""

    def __init__(self, *, language: str = SARVAM_STT_LANGUAGE, model: str = SARVAM_STT_MODEL) -> None:
        self._language = language
        self._model = model
        self._audio_buffer = bytearray()
        self._results: asyncio.Queue[str] = asyncio.Queue()
        self._speech_started = asyncio.Event()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None or self._client.is_closed:
            self._client = httpx.AsyncClient(timeout=10.0)
        return self._client

    async def transcribe(self, audio_bytes: bytes) -> str | None:
        """Send audio to Sarvam STT and return the transcript."""
        wav_bytes = _pcm_to_wav(audio_bytes, sample_rate=16000, channels=1, sample_width=2)
        try:
            client = await self._get_client()
            # STT API expects multipart file upload
            files = {"file": ("audio.wav", wav_bytes, "audio/wav")}
            data = {
                "language_code": self._language,
                "model": self._model,
            }
            headers = {"api-subscription-key": _api_key()}
            resp = await client.post(
                SARVAM_STT_URL,
                headers=headers,
                data=data,
                files=files,
            )
            resp.raise_for_status()
            result = resp.json()
            transcript = result.get("transcript", "").strip()
            if transcript:
                logger.info("Sarvam STT: %r", transcript[:60])
            return transcript or None
        except Exception:
            logger.exception("Sarvam STT request failed")
            return None

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
        if self._client and not self._client.is_closed:
            await self._client.aclose()


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


def wav_seconds(wav_bytes: bytes) -> float | None:
    """Playback length of a WAV file from its header, or None if unreadable."""
    if len(wav_bytes) < 44 or wav_bytes[:4] != b"RIFF" or wav_bytes[8:12] != b"WAVE":
        return None
    byte_rate = 0
    pos = 12
    while pos <= len(wav_bytes) - 8:
        chunk_id = wav_bytes[pos:pos + 4]
        chunk_size = struct.unpack_from("<I", wav_bytes, pos + 4)[0]
        if chunk_id == b"fmt " and pos + 16 <= len(wav_bytes) - 4:
            byte_rate = struct.unpack_from("<I", wav_bytes, pos + 16)[0]
        elif chunk_id == b"data":
            # Streamed WAVs can carry a placeholder size; trust the bytes we hold.
            data_size = min(chunk_size, len(wav_bytes) - pos - 8)
            return data_size / byte_rate if byte_rate else None
        pos += 8 + chunk_size
    return None


def _wav_to_pcm(wav_bytes: bytes) -> bytes:
    """Extract raw PCM data from a WAV file, skipping the 44-byte header."""
    if len(wav_bytes) <= 44:
        return wav_bytes
    # Standard WAV header is 44 bytes; data starts after
    if wav_bytes[:4] == b"RIFF" and wav_bytes[8:12] == b"WAVE":
        # Find the 'data' chunk
        pos = 12
        while pos < len(wav_bytes) - 8:
            chunk_id = wav_bytes[pos:pos + 4]
            chunk_size = struct.unpack_from("<I", wav_bytes, pos + 4)[0]
            if chunk_id == b"data":
                return wav_bytes[pos + 8:pos + 8 + chunk_size]
            pos += 8 + chunk_size
    return wav_bytes[44:]  # fallback: assume standard header
