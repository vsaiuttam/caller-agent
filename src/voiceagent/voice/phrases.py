"""The stock lines a call says on its own, in the call's language.

Everything the model says is already in the campaign's language — the prompt
sees to that. These are the lines the *session* says without asking the
model: the silence check-in, the goodbyes, the voicemail, the short
acknowledgements played while a reply is being prepared, and the "one
moment, let me check" that covers a tool the model reached for without
saying anything first. A Hindi call that
suddenly says "Sorry — are you still there?" in English is the single most
jarring moment a caller can hit, so none of these are hard-coded anywhere
else.

Hindi and Urdu are written in Devanagari because the TTS voice reads
Devanagari. Phrasing is genderless throughout: the voice's gender varies by
configuration, and Hindi verbs agree with the speaker's.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class CallPhrases:
    still_there: str        # first silence strike
    goodbye_silence: str    # second silence strike, then hang up
    goodbye_timeout: str    # max call duration reached
    goodbye_default: str    # model ended without a farewell, or operator hung up
    voicemail: str          # appended to the greeting on voicemail
    acknowledgements: tuple[str, ...]  # short fillers while a reply is prepared
    checking: str           # said while a tool runs, if the model said nothing first


_PHRASES: dict[str, CallPhrases] = {
    "en": CallPhrases(
        still_there="Sorry, are you still there?",
        goodbye_silence="I'll let you go for now. Thanks for your time — goodbye!",
        goodbye_timeout="I've taken enough of your time. Thank you so much — goodbye!",
        goodbye_default="Thank you so much for your time. Have a great day — goodbye!",
        voicemail="Sorry we missed you. We'll try again later. Thank you!",
        acknowledgements=("Okay.", "Mm-hmm.", "Got it.", "Right."),
        checking="One moment, let me check that.",
    ),
    "hi": CallPhrases(
        still_there="माफ़ कीजिए, क्या आप अभी भी लाइन पर हैं?",
        goodbye_silence="कोई बात नहीं, हम बाद में बात करेंगे। आपके समय के लिए धन्यवाद, नमस्ते!",
        goodbye_timeout="आपका काफ़ी समय ले लिया। बहुत-बहुत धन्यवाद, नमस्ते!",
        goodbye_default="आपके समय के लिए बहुत-बहुत धन्यवाद। आपका दिन शुभ हो, नमस्ते!",
        voicemail="माफ़ कीजिए, आपसे बात नहीं हो पाई। हम बाद में फिर कॉल करेंगे। धन्यवाद!",
        acknowledgements=("जी।", "अच्छा।", "ठीक है।", "जी, एक सेकंड।"),
        checking="एक सेकंड, ज़रा देख लेते हैं।",
    ),
    "ur": CallPhrases(
        still_there="माफ़ कीजिए, क्या आप अभी लाइन पर हैं?",
        goodbye_silence="कोई बात नहीं, हम बाद में बात करेंगे। आपके वक़्त का शुक्रिया, ख़ुदा हाफ़िज़!",
        goodbye_timeout="आपका काफ़ी वक़्त ले लिया। बहुत-बहुत शुक्रिया, ख़ुदा हाफ़िज़!",
        goodbye_default="आपके वक़्त का बहुत शुक्रिया। आपका दिन अच्छा गुज़रे, ख़ुदा हाफ़िज़!",
        voicemail="माफ़ कीजिए, आपसे बात नहीं हो सकी। हम बाद में फिर कॉल करेंगे। शुक्रिया!",
        acknowledgements=("जी।", "अच्छा।", "ठीक है।"),
        checking="एक लम्हा, ज़रा देख लेते हैं।",
    ),
    "hi-en": CallPhrases(
        still_there="Sorry, kya aap abhi line par hain?",
        goodbye_silence="Koi baat nahi, hum baad mein baat karenge. Thank you, bye!",
        goodbye_timeout="Aapka kaafi time le liya. Thank you so much, bye!",
        goodbye_default="Aapke time ke liye bahut shukriya. Aapka din achha ho, bye!",
        voicemail="Sorry, aapse baat nahi ho paayi. Hum baad mein phir call karenge. Thank you!",
        acknowledgements=("Haan ji.", "Achha.", "Theek hai.", "Okay."),
        checking="Ek second, check kar lete hain.",
    ),
}


def phrases_for(language: str | None) -> CallPhrases:
    """The phrase set for a campaign language code; English when unknown."""
    return _PHRASES.get((language or "").strip().lower(), _PHRASES["en"])
