"""The voices a campaign can speak in: Sarvam's Bulbul v3 speakers.

One voice for every campaign made an appointment reminder and a collections
call sound like the same person, and there was no way to pick a woman's
voice for a women's clinic. These are every speaker `bulbul:v3` accepts, per
Sarvam's text-to-speech reference (checked 2026-09-27): 37 speakers, all of
whom speak all eleven of Sarvam's languages. Speaker ids are lowercase and
case-sensitive in the API.

Because every speaker covers every Sarvam language, the language filter on
GET /api/voices is really a question of whether we can voice that language
at all: every campaign language maps to a Sarvam code (templates.py —
Urdu and Hinglish through the Hindi voice), so each voice lists them all.

A preview is a real synthesis on the deployment's Sarvam key, so previews
are cached by (voice, language, text) and rate-limited per person.
"""

from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

from ..templates import LANGUAGES, LANGUAGES_BY_CODE, sarvam_code

PROVIDER = "sarvam"
DEFAULT_VOICE = "shubh"

_MALE = (
    "shubh", "aditya", "rahul", "rohan", "amit", "dev", "ratan", "varun", "manan",
    "sumit", "kabir", "aayan", "ashutosh", "advait", "anand", "tarun", "sunny",
    "mani", "gokul", "vijay", "mohit", "rehan", "soham",
)
_FEMALE = (
    "ritu", "priya", "neha", "pooja", "simran", "kavya", "ishita", "shreya",
    "roopa", "tanya", "shruti", "suhani", "kavitha", "rupali",
)

# A line to audition a voice with, per language: short, and the kind of
# thing the voice will actually say on a call.
SAMPLE_TEXT: dict[str, str] = {
    "en": "Hi, this is a quick call about your appointment. Do you have a minute?",
    "hi": "नमस्ते, आपकी appointment के बारे में एक छोटी सी कॉल है। क्या आपके पास एक मिनट है?",
    "ur": "नमस्ते, आपकी appointment के बारे में एक छोटी सी कॉल है। क्या आपके पास एक मिनट है?",
    "hi-en": "Hi, aapki appointment ke baare mein ek chhoti si call hai. Ek minute hai aapke paas?",
    "te": "నమస్కారం, మీ appointment గురించి చిన్న కాల్. ఒక్క నిమిషం మాట్లాడగలరా?",
    "ta": "வணக்கம், உங்க appointment பத்தி ஒரு சின்ன கால். ஒரு நிமிஷம் பேசலாமா?",
    "kn": "ನಮಸ್ಕಾರ, ನಿಮ್ಮ appointment ಬಗ್ಗೆ ಒಂದು ಚಿಕ್ಕ ಕಾಲ್. ಒಂದು ನಿಮಿಷ ಮಾತಾಡಬಹುದಾ?",
    "ml": "നമസ്കാരം, നിങ്ങളുടെ appointment-നെ കുറിച്ച് ഒരു ചെറിയ കോൾ ആണ്. ഒരു മിനിറ്റ് സംസാരിക്കാമോ?",
    "mr": "नमस्कार, तुमच्या appointment बद्दल एक छोटा कॉल आहे. एक मिनिट बोलू शकता का?",
    "bn": "নমস্কার, আপনার appointment নিয়ে একটা ছোট্ট কল। এক মিনিট কথা বলা যাবে?",
    "gu": "નમસ્તે, તમારી appointment વિશે એક નાનો કૉલ છે. એક મિનિટ વાત કરી શકો?",
    "pa": "ਸਤ ਸ੍ਰੀ ਅਕਾਲ, ਤੁਹਾਡੀ appointment ਬਾਰੇ ਇੱਕ ਛੋਟੀ ਜਿਹੀ ਕਾਲ ਹੈ। ਕੀ ਇੱਕ ਮਿੰਟ ਗੱਲ ਹੋ ਸਕਦੀ ਹੈ?",
    "od": "ନମସ୍କାର, ଆପଣଙ୍କ appointment ବିଷୟରେ ଗୋଟିଏ ଛୋଟ କଲ। ଗୋଟିଏ ମିନିଟ କଥା ହୋଇପାରିବେ କି?",
}


@dataclass(frozen=True)
class Voice:
    id: str
    name: str
    gender: str  # "male" | "female"

    def to_dict(self, language: str | None = None) -> dict:
        return {
            "id": self.id,
            "name": self.name,
            "gender": self.gender,
            "languages": [lang.code for lang in LANGUAGES],
            "provider": PROVIDER,
            "sample_text": sample_text(language),
            "default": self.id == DEFAULT_VOICE,
        }


VOICES: list[Voice] = [
    *(Voice(id=v, name=v.capitalize(), gender="male") for v in _MALE),
    *(Voice(id=v, name=v.capitalize(), gender="female") for v in _FEMALE),
]
VOICES_BY_ID = {v.id: v for v in VOICES}


def sample_text(language: str | None) -> str:
    return SAMPLE_TEXT.get((language or "en").lower(), SAMPLE_TEXT["en"])


def voices_for(language: str | None) -> list[dict]:
    """Voices that can speak `language` (all of them, for a language we
    support; none for one we don't). No language lists everything."""
    if language and language.lower() not in LANGUAGES_BY_CODE:
        return []
    return [v.to_dict(language) for v in VOICES]


# Previews by (voice, language, text). Small: a preview is a few seconds of
# audio, and the same handful are auditioned over and over while choosing.
_PREVIEW_MAX = 64
_previews: OrderedDict[tuple[str, str, str], bytes] = OrderedDict()


async def synthesize_preview(voice: str, language: str, text: str) -> bytes:
    """WAV audio of `text` in `voice`. Cached; raises on a Sarvam failure.

    Module-level so a test can stand in for Sarvam.
    """
    key = (voice, language, text)
    cached = _previews.get(key)
    if cached is not None:
        _previews.move_to_end(key)
        return cached

    from .sarvam_voice import SarvamTTS

    tts = SarvamTTS(language=sarvam_code(language), speaker=voice)
    try:
        audio = await tts.synthesize_wav(text)
    finally:
        await tts.close()
    if not audio:
        raise RuntimeError("Sarvam returned no audio for this preview.")
    _previews[key] = audio
    while len(_previews) > _PREVIEW_MAX:
        _previews.popitem(last=False)
    return audio
