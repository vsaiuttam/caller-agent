"""Sarvam AI STT (Saarika) and TTS (Bulbul) adapter.

Drop-in replacements for Deepgram STT and Cartesia TTS in the LiveKit
pipeline, and also used by the Twilio adapter for Sarvam-powered TTS.

Requires SARVAM_API_KEY in the environment.

Sarvam endpoints used:
    POST https://api.sarvam.ai/speech-to-text          (Saarika v2)
    POST https://api.sarvam.ai/text-to-speech           (Bulbul v2)
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

SARVAM_BASE = "https://api.sarvam.ai"

# Defaults — overridable via environment.
SARVAM_STT_LANGUAGE = os.getenv("SARVAM_STT_LANGUAGE", "hi-IN")
SARVAM_TTS_LANGUAGE = os.getenv("SARVAM_TTS_LANGUAGE", "hi-IN")
SARVAM_TTS_SPEAKER = os.getenv("SARVAM_TTS_SPEAKER", "meera")
SARVAM_TTS_MODEL = os.getenv("SARVAM_TTS_MODEL", "bulbul:v2")
SARVAM_STT_MODEL = os.getenv("SARVAM_STT_MODEL", "saarika:v2")


def _api_key() -> str:
    key = os.getenv("SARVAM_API_KEY", "")
    if not key:
        raise RuntimeError("SARVAM_API_KEY is not set")
    return key


class SarvamSTT:
    """Speech-to-text using Sarvam Saarika.

    Accepts raw PCM audio frames (16-bit, 16 kHz, mono) accumulated from the
    LiveKit audio stream. Transcription happens on each voiced segment detected
    by the VAD, so this class exposes a queue-based interface rather than a
    streaming WebSocket.
    """

    def __init__(self, *, language: str = SARVAM_STT_LANGUAGE, model: str = SARVAM_STT_MODEL) -> None:
        self._language = language
        self._model = model
        self._api_key = _api_key()
        self._audio_buffer = bytearray()
        self._results: asyncio.Queue[str] = asyncio.Queue()
        self._speech_started = asyncio.Event()
        self._client = httpx.AsyncClient(timeout=30.0)

    async def transcribe(self, audio_bytes: bytes) -> str | None:
        """Send audio to Sarvam STT and return the transcript."""
        wav_bytes = _pcm_to_wav(audio_bytes, sample_rate=16000, channels=1, sample_width=2)

        try:
            resp = await self._client.post(
                f"{SARVAM_BASE}/speech-to-text",
                headers={"api-subscription-key": self._api_key},
                files={"file": ("audio.wav", wav_bytes, "audio/wav")},
                data={
                    "language_code": self._language,
                    "model": self._model,
                    "with_timestamps": "false",
                },
            )
            resp.raise_for_status()
            data = resp.json()
            return data.get("transcript", "").strip()
        except Exception:
            logger.exception("Sarvam STT request failed")
            return None

    def push_audio(self, pcm_frame: bytes) -> None:
        """Accumulate audio frames from the LiveKit stream."""
        self._audio_buffer.extend(pcm_frame)

    async def flush(self) -> None:
        """Transcribe whatever audio has been buffered, then clear it."""
        if len(self._audio_buffer) < 1600:  # less than 50ms of audio
            self._audio_buffer.clear()
            return

        audio = bytes(self._audio_buffer)
        self._audio_buffer.clear()

        text = await self.transcribe(audio)
        if text:
            self._speech_started.set()
            await self._results.put(text)

    async def get_next(self) -> str | None:
        """Block until the next transcript is ready."""
        return await self._results.get()

    async def close(self) -> None:
        await self._client.aclose()


class SarvamTTS:
    """Text-to-speech using Sarvam Bulbul.

    Two output modes:
      - `synthesize()` returns raw PCM for LiveKit AudioSource.
      - `synthesize_wav()` returns the original WAV from Sarvam, ready for
        Twilio's <Play>. No re-encoding, no sample-rate guessing.
    """

    def __init__(
        self,
        *,
        language: str = SARVAM_TTS_LANGUAGE,
        speaker: str = SARVAM_TTS_SPEAKER,
        model: str = SARVAM_TTS_MODEL,
        target_sample_rate: int = 24000,
    ) -> None:
        self._language = language
        self._speaker = speaker
        self._model = model
        self._target_sample_rate = target_sample_rate
        self._api_key = _api_key()
        self._client = httpx.AsyncClient(timeout=10.0)

    async def _call_api(self, text: str) -> bytes:
        """Hit Sarvam TTS and return the raw WAV bytes."""
        resp = await self._client.post(
            f"{SARVAM_BASE}/text-to-speech",
            headers={
                "api-subscription-key": self._api_key,
                "Content-Type": "application/json",
            },
            json={
                "inputs": [text],
                "target_language_code": self._language,
                "speaker": self._speaker,
                "model": self._model,
                "enable_preprocessing": True,
            },
        )
        resp.raise_for_status()
        data = resp.json()
        audios = data.get("audios", [])
        if not audios:
            logger.warning("Sarvam TTS returned no audio for: %s", text[:60])
            return b""
        return base64.b64decode(audios[0])

    async def synthesize(self, text: str) -> bytes:
        """Convert text to raw PCM audio bytes (for LiveKit)."""
        try:
            wav_bytes = await self._call_api(text)
            return _wav_to_pcm(wav_bytes) if wav_bytes else b""
        except Exception:
            logger.exception("Sarvam TTS request failed")
            return b""

    async def synthesize_wav(self, text: str) -> bytes:
        """Convert text to WAV audio bytes (for Twilio <Play>).

        Returns the original WAV from Sarvam unchanged — correct sample rate,
        correct headers, no re-encoding.
        """
        try:
            return await self._call_api(text)
        except Exception:
            logger.exception("Sarvam TTS request failed")
            return b""

    async def close(self) -> None:
        await self._client.aclose()


# ---------------------------------------------------------------------------
# LiveKit-compatible wrappers
# ---------------------------------------------------------------------------


class SarvamLiveKitListener:
    """Implements the Listener protocol using Sarvam STT.

    Replaces the Deepgram-based LiveKitListener. Works with the VAD to detect
    speech boundaries, then sends accumulated audio to Sarvam for transcription.
    """

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
        """Called by the audio pump when VAD detects voice activity."""
        self._speech_started.set()


class SarvamLiveKitSpeaker:
    """Implements the Speaker protocol using Sarvam TTS.

    Replaces the Cartesia-based LiveKitSpeaker.
    """

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

        # Feed PCM in chunks to the audio source. Each frame is 20ms.
        # At 24kHz mono 16-bit: 24000 * 0.02 * 2 = 960 bytes per frame.
        frame_bytes = 960
        self._total_samples = len(pcm) // 2  # 16-bit = 2 bytes per sample

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
    """Wrap raw PCM in a WAV header for the Sarvam API."""
    buf = io.BytesIO()
    data_size = len(pcm)
    # RIFF header
    buf.write(b"RIFF")
    buf.write(struct.pack("<I", 36 + data_size))
    buf.write(b"WAVE")
    # fmt chunk
    buf.write(b"fmt ")
    buf.write(struct.pack("<I", 16))  # chunk size
    buf.write(struct.pack("<H", 1))   # PCM format
    buf.write(struct.pack("<H", channels))
    buf.write(struct.pack("<I", sample_rate))
    buf.write(struct.pack("<I", sample_rate * channels * sample_width))  # byte rate
    buf.write(struct.pack("<H", channels * sample_width))  # block align
    buf.write(struct.pack("<H", sample_width * 8))  # bits per sample
    # data chunk
    buf.write(b"data")
    buf.write(struct.pack("<I", data_size))
    buf.write(pcm)
    return buf.getvalue()


def _wav_to_pcm(wav_bytes: bytes) -> bytes:
    """Extract raw PCM data from a WAV file, skipping the header."""
    buf = io.BytesIO(wav_bytes)
    # Find the data chunk
    buf.read(4)  # RIFF
    buf.read(4)  # file size
    buf.read(4)  # WAVE

    while True:
        chunk_id = buf.read(4)
        if len(chunk_id) < 4:
            # No data chunk found, return everything after a 44-byte header
            return wav_bytes[44:] if len(wav_bytes) > 44 else wav_bytes
        chunk_size = struct.unpack("<I", buf.read(4))[0]
        if chunk_id == b"data":
            return buf.read(chunk_size)
        buf.read(chunk_size)
