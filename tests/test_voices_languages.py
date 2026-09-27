"""Voices and languages: pick a Sarvam speaker, and call in Telugu (and eight more).

Covers docs/v3-spec.md §4 and §5: GET /api/voices lists Sarvam bulbul:v3
speakers with their details and filters by language; the voice preview is
WAV, cached, refuses an unknown voice, and answers 409 when the deployment
has no Sarvam key; every language in `templates.LANGUAGES` (now including
te, ta, kn, ml, mr, bn, gu, pa and od) has a native name, a spoken-register
instruction, its own CallPhrases written in its own script, and a Sarvam
`xx-IN` code that the TTS path actually uses.

Drives the real app over ASGI with the harness from test_accounts.py. No
network: Sarvam's API is answered by a patched `httpx.AsyncClient.send`
that only intercepts requests to sarvam.ai. Runs standalone
(`python tests/test_voices_languages.py`) or under pytest.
"""

from __future__ import annotations

import base64
import io
import json
import sys
import wave
from contextlib import contextmanager
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import httpx  # noqa: E402
from test_accounts import _env, _fresh_ip, _run, _show  # noqa: E402
from test_providers_api import BASE, get_json  # noqa: E402

from src.voiceagent import templates  # noqa: E402
from src.voiceagent.voice import phrases  # noqa: E402
from src.voiceagent.voice import sarvam_voice  # noqa: E402
from src.voiceagent.voice import twilio_adapter as tw  # noqa: E402

NEW_LANGUAGES = ("te", "ta", "kn", "ml", "mr", "bn", "gu", "pa", "od")
SARVAM_CODES = {"en-IN", "hi-IN", "bn-IN", "gu-IN", "kn-IN", "ml-IN", "mr-IN", "od-IN", "pa-IN", "ta-IN", "te-IN"}
# Unicode block of each new language's script.
SCRIPTS = {
    "te": (0x0C00, 0x0C7F), "ta": (0x0B80, 0x0BFF), "kn": (0x0C80, 0x0CFF), "ml": (0x0D00, 0x0D7F),
    "mr": (0x0900, 0x097F), "bn": (0x0980, 0x09FF), "gu": (0x0A80, 0x0AFF), "pa": (0x0A00, 0x0A7F),
    "od": (0x0B00, 0x0B7F),
}
VOICE_FIELDS = {"id", "name", "gender", "languages", "provider", "sample_text"}
NO_SARVAM = dict(BASE, SARVAM_API_KEY=None, SARVAM_TTS_LANGUAGE=None)
WITH_SARVAM = dict(BASE, SARVAM_API_KEY="sarvam-test-key", SARVAM_TTS_LANGUAGE=None)


def _wav() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as out:
        out.setnchannels(1)
        out.setsampwidth(2)
        out.setframerate(22050)
        out.writeframes(b"\x00\x00" * 2205)
    return buffer.getvalue()


WAV = _wav()


@contextmanager
def _sarvam():
    """Answer Sarvam's text-to-speech API in-process; record each request body."""
    seen: list[dict] = []
    real = httpx.AsyncClient.send

    async def send(self, request, *args, **kwargs):
        if request.url.host.endswith("sarvam.ai"):
            seen.append(json.loads(request.content or b"{}"))
            return httpx.Response(200, json={"audios": [base64.b64encode(WAV).decode()]}, request=request)
        return await real(self, request, *args, **kwargs)

    httpx.AsyncClient.send = send
    try:
        yield seen
    finally:
        httpx.AsyncClient.send = real


def _in_script(text: str, block: tuple[int, int]) -> bool:
    return any(block[0] <= ord(ch) <= block[1] for ch in text)


def _language(code: str):
    return next((lang for lang in templates.LANGUAGES if lang.code == code), None)


# ---------------------------------------------------------------------------
# GET /api/voices
# ---------------------------------------------------------------------------


def test_every_voice_is_a_sarvam_speaker_with_its_details() -> None:
    async def scenario(http, sessions):
        return await get_json(http, "/api/voices")

    voices = _run(scenario, _fresh_ip(), **NO_SARVAM)
    assert isinstance(voices, list) and len(voices) >= 2, voices
    for voice in voices:
        assert VOICE_FIELDS <= set(voice), f"{voice.get('id')} lacks {sorted(VOICE_FIELDS - set(voice))}"
        assert voice["provider"] == "sarvam", voice
        assert isinstance(voice["languages"], list) and voice["languages"], voice
        assert isinstance(voice["name"], str) and voice["name"].strip(), voice
        assert isinstance(voice["sample_text"], str) and voice["sample_text"].strip(), voice
    ids = [v["id"] for v in voices]
    assert len(ids) == len(set(ids)), "voice ids must be unique"
    assert sarvam_voice.SARVAM_TTS_SPEAKER in ids, "the default speaker must be one of the voices"


def test_voices_filter_by_language() -> None:
    async def scenario(http, sessions):
        every = await get_json(http, "/api/voices")
        telugu = await get_json(http, "/api/voices?language=te")
        hindi = await get_json(http, "/api/voices?language=hi")
        french = await http.get("/api/voices?language=fr")
        return every, telugu, hindi, french

    every, telugu, hindi, french = _run(scenario, _fresh_ip(), **NO_SARVAM)
    assert telugu and hindi, "Telugu and Hindi both have voices"
    assert all("te" in v["languages"] for v in telugu), [v["id"] for v in telugu if "te" not in v["languages"]]
    assert all("hi" in v["languages"] for v in hindi)
    assert {v["id"] for v in telugu} == {v["id"] for v in every if "te" in v["languages"]}, "filter mismatch"
    if french.status_code == 200:
        assert french.json() == [], "no Sarvam voice speaks French"
    else:
        assert french.status_code in (400, 422), _show(french)


# ---------------------------------------------------------------------------
# POST /api/voices/preview
# ---------------------------------------------------------------------------


def test_the_preview_needs_a_sarvam_key_and_says_so_with_409() -> None:
    async def scenario(http, sessions):
        return await http.post("/api/voices/preview", json={"voice": sarvam_voice.SARVAM_TTS_SPEAKER, "language": "te"})

    with _sarvam() as seen:
        r = _run(scenario, _fresh_ip(), **NO_SARVAM)
    assert r.status_code == 409, _show(r)
    assert "sarvam" in r.text.lower(), f"the 409 should name what is missing: {r.text}"
    assert seen == [], "nothing should reach Sarvam without a key"


def test_the_preview_refuses_an_unknown_voice() -> None:
    async def scenario(http, sessions):
        return await http.post("/api/voices/preview", json={"voice": "no-such-speaker", "language": "hi"})

    with _sarvam() as seen:
        r = _run(scenario, _fresh_ip(), **WITH_SARVAM)
    assert r.status_code == 400, _show(r)
    assert seen == [], "an unknown voice must be refused before calling Sarvam"


def test_the_preview_is_wav_in_the_chosen_voice_and_language_and_is_cached() -> None:
    voice = sarvam_voice.SARVAM_TTS_SPEAKER

    async def scenario(http, sessions):
        body = {"voice": voice, "language": "te"}
        first = await http.post("/api/voices/preview", json=body)
        second = await http.post("/api/voices/preview", json=body)
        other = await http.post("/api/voices/preview", json=dict(body, text="నమస్కారం, ఇది ఒక పరీక్ష."))
        return first, second, other

    with _sarvam() as seen:
        first, second, other = _run(scenario, _fresh_ip(), **WITH_SARVAM)
    for r in (first, second, other):
        assert r.status_code == 200, _show(r)
        assert r.headers["content-type"].startswith("audio/wav"), r.headers["content-type"]
        assert r.content[:4] == b"RIFF", r.content[:12]
    assert len(seen) == 2, f"the same voice, language and text should be served from cache: {len(seen)} requests"
    assert seen[0]["speaker"] == voice and seen[0]["target_language_code"] == "te-IN", seen[0]
    assert seen[1]["text"] == "నమస్కారం, ఇది ఒక పరీక్ష.", seen[1]


# ---------------------------------------------------------------------------
# Languages
# ---------------------------------------------------------------------------


def test_every_new_language_is_offered() -> None:
    codes = [lang.code for lang in templates.LANGUAGES]
    missing = [code for code in ("en", "hi", *NEW_LANGUAGES) if code not in codes]
    assert not missing, f"missing languages: {missing}"
    assert len(codes) == len(set(codes)), codes

    async def scenario(http, sessions):
        return await get_json(http, "/api/languages")

    listed = {lang["code"] for lang in _run(scenario, _fresh_ip(), **NO_SARVAM)}
    assert set(NEW_LANGUAGES) <= listed, sorted(set(NEW_LANGUAGES) - listed)


def test_every_language_has_a_native_name_and_a_spoken_register_instruction() -> None:
    for lang in templates.LANGUAGES:
        assert lang.name.strip() and lang.native_name.strip() and lang.instruction.strip(), lang.code
        assert templates.language_instruction(lang.code) == lang.instruction, lang.code
    for code in NEW_LANGUAGES:
        lang = _language(code)
        assert lang is not None, code
        assert _in_script(lang.native_name, SCRIPTS[code]), f"{code}: native name {lang.native_name!r}"
        instruction = lang.instruction.lower()
        assert lang.name.lower() in instruction, f"{code}: the instruction should name the language"
        assert "english" in instruction, f"{code}: keep English loanwords, switch if they switch"
        assert "switch" in instruction, f"{code}: switch language if the person does"


def test_every_language_has_its_own_call_phrases() -> None:
    english = phrases.phrases_for("en")
    for lang in templates.LANGUAGES:
        assert phrases.has_phrases(lang.code), f"no CallPhrases for {lang.code}"
        own = phrases.phrases_for(lang.code)
        for field in ("still_there", "goodbye_silence", "goodbye_timeout", "goodbye_default", "voicemail", "checking"):
            assert getattr(own, field).strip(), (lang.code, field)
        assert own.acknowledgements and all(a.strip() for a in own.acknowledgements), lang.code
        if lang.code != "en":
            assert own != english, f"{lang.code} falls back to English phrases"
    assert not phrases.has_phrases("fr"), "has_phrases must not claim a language we don't have"


def test_the_new_languages_phrases_are_written_in_their_own_script() -> None:
    for code in NEW_LANGUAGES:
        own = phrases.phrases_for(code)
        for field in ("still_there", "goodbye_default", "voicemail", "checking"):
            text = getattr(own, field)
            assert _in_script(text, SCRIPTS[code]), f"{code}.{field} is not in its script: {text!r}"


def test_every_language_maps_to_a_sarvam_code() -> None:
    for lang in templates.LANGUAGES:
        assert lang.sarvam_code in SARVAM_CODES, (lang.code, lang.sarvam_code)
    for code in ("en", "hi", *NEW_LANGUAGES):
        expected = "en-IN" if code == "en" else f"{code}-IN"
        assert _language(code).sarvam_code == expected, (code, _language(code).sarvam_code)


def test_a_call_in_each_new_language_speaks_through_that_languages_voice() -> None:
    with _env(SARVAM_TTS_LANGUAGE=None):
        for code in NEW_LANGUAGES:
            assert tw._tts_language(code) == f"{code}-IN", (code, tw._tts_language(code))
        assert tw._tts_language("hi") == "hi-IN"


# ---------------------------------------------------------------------------


def _run_all() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"pass  {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
