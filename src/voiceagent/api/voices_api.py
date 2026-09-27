"""Voices and languages for the campaign builder (v3).

GET /api/voices lists every Sarvam Bulbul v3 speaker; POST /api/voices/preview
plays one. The preview spends the deployment's own Sarvam key, so it is
cached (voice/voices.py) and limited per person here.
"""

from __future__ import annotations

import logging
import os

from fastapi import APIRouter, HTTPException, Request, Response

from ..providers import _is_placeholder
from ..templates import LANGUAGES_BY_CODE
from ..voice import voices
from .access import RateLimiter, requester_key
from .schemas import VoicePreviewRequest

logger = logging.getLogger(__name__)

router = APIRouter()

# Auditioning is a handful of clicks; this is well above that and well
# below running up a bill.
PREVIEWS_PER_MINUTE = 20
preview_limiter = RateLimiter(PREVIEWS_PER_MINUTE, 60.0)


@router.get("/api/voices")
async def list_voices(language: str | None = None) -> list[dict]:
    return voices.voices_for(language)


@router.post("/api/voices/preview")
async def preview_voice(body: VoicePreviewRequest, request: Request) -> Response:
    """A few seconds of `voice` speaking, as audio/wav."""
    if _is_placeholder(os.getenv("SARVAM_API_KEY", "")):
        raise HTTPException(
            409, "Voice previews need a Sarvam key. Set SARVAM_API_KEY on the server to hear voices."
        )
    if body.voice not in voices.VOICES_BY_ID:
        raise HTTPException(400, f"Unknown voice: {body.voice}")
    language = body.language.lower()
    if language not in LANGUAGES_BY_CODE:
        raise HTTPException(400, f"Unknown language: {body.language}")
    if not preview_limiter.allow(requester_key(request)):
        raise HTTPException(429, "Too many previews in a minute. Try again shortly.")

    text = (body.text or "").strip() or voices.sample_text(language)
    try:
        audio = await voices.synthesize_preview(body.voice, language, text)
    except Exception as exc:  # noqa: BLE001
        logger.warning("Voice preview failed: %s", type(exc).__name__)
        raise HTTPException(502, "Sarvam could not make this preview. Try again in a moment.") from exc
    return Response(content=audio, media_type="audio/wav", headers={"Cache-Control": "private, max-age=3600"})
