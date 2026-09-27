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
Devanagari; every other language is in its own script, which Sarvam's voice
for it reads. They are short and spoken-register on purpose — "సరే, తర్వాత
మాట్లాడదాం", not the formal written line — and written by hand, never
machine-translated at runtime. Phrasing is genderless throughout: the voice's
gender varies by campaign, and Hindi, Marathi and Gujarati verbs agree with
the speaker's.
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
    "te": CallPhrases(
        still_there="క్షమించండి, మీరు లైన్‌లో ఉన్నారా?",
        goodbye_silence="సరే, తర్వాత మాట్లాడదాం. మీ సమయానికి ధన్యవాదాలు!",
        goodbye_timeout="మీ సమయం చాలా తీసుకున్నాను. చాలా ధన్యవాదాలు!",
        goodbye_default="మీ సమయానికి చాలా ధన్యవాదాలు. మంచి రోజు గడపండి!",
        voicemail="క్షమించండి, మిమ్మల్ని అందుకోలేకపోయాం. మళ్ళీ తర్వాత కాల్ చేస్తాం. ధన్యవాదాలు!",
        acknowledgements=("సరే.", "అలాగే.", "హా, సరే.", "ఓకే."),
        checking="ఒక్క నిమిషం, చూసి చెప్తాను.",
    ),
    "ta": CallPhrases(
        still_there="மன்னிக்கவும், நீங்க லைன்ல இருக்கீங்களா?",
        goodbye_silence="சரி, அப்புறம் பேசலாம். உங்க நேரத்துக்கு நன்றி!",
        goodbye_timeout="உங்க நேரத்தை நிறைய எடுத்துக்கிட்டேன். ரொம்ப நன்றி!",
        goodbye_default="உங்க நேரத்துக்கு ரொம்ப நன்றி. இந்த நாள் நல்லா அமையட்டும்!",
        voicemail="மன்னிக்கவும், உங்களைத் தொடர்பு கொள்ள முடியலை. அப்புறம் மறுபடியும் கூப்பிடுறோம். நன்றி!",
        acknowledgements=("சரி.", "ஆமா.", "புரிஞ்சது.", "ஓகே."),
        checking="ஒரு நிமிஷம், பார்த்துச் சொல்றேன்.",
    ),
    "kn": CallPhrases(
        still_there="ಕ್ಷಮಿಸಿ, ನೀವು ಲೈನ್‌ನಲ್ಲಿ ಇದ್ದೀರಾ?",
        goodbye_silence="ಸರಿ, ಆಮೇಲೆ ಮಾತಾಡೋಣ. ನಿಮ್ಮ ಸಮಯಕ್ಕೆ ಧನ್ಯವಾದಗಳು!",
        goodbye_timeout="ನಿಮ್ಮ ತುಂಬಾ ಸಮಯ ತಗೊಂಡೆ. ತುಂಬಾ ಧನ್ಯವಾದಗಳು!",
        goodbye_default="ನಿಮ್ಮ ಸಮಯಕ್ಕೆ ತುಂಬಾ ಧನ್ಯವಾದಗಳು. ನಿಮ್ಮ ದಿನ ಚೆನ್ನಾಗಿರಲಿ!",
        voicemail="ಕ್ಷಮಿಸಿ, ನಿಮ್ಮನ್ನು ಸಂಪರ್ಕಿಸಲು ಆಗಲಿಲ್ಲ. ಆಮೇಲೆ ಮತ್ತೆ ಕಾಲ್ ಮಾಡ್ತೀವಿ. ಧನ್ಯವಾದಗಳು!",
        acknowledgements=("ಸರಿ.", "ಹೌದಾ.", "ಆಯ್ತು.", "ಓಕೆ."),
        checking="ಒಂದು ನಿಮಿಷ, ನೋಡಿ ಹೇಳ್ತೀನಿ.",
    ),
    "ml": CallPhrases(
        still_there="ക്ഷമിക്കണം, നിങ്ങൾ ലൈനിൽ ഉണ്ടോ?",
        goodbye_silence="ശരി, പിന്നെ സംസാരിക്കാം. നിങ്ങളുടെ സമയത്തിന് നന്ദി!",
        goodbye_timeout="നിങ്ങളുടെ ഒരുപാട് സമയം എടുത്തു. വളരെ നന്ദി!",
        goodbye_default="നിങ്ങളുടെ സമയത്തിന് വളരെ നന്ദി. നല്ലൊരു ദിവസം ആകട്ടെ!",
        voicemail="ക്ഷമിക്കണം, നിങ്ങളെ കിട്ടിയില്ല. പിന്നീട് വീണ്ടും വിളിക്കാം. നന്ദി!",
        acknowledgements=("ശരി.", "ഓക്കെ.", "മനസ്സിലായി.", "ആണോ."),
        checking="ഒരു നിമിഷം, നോക്കിയിട്ട് പറയാം.",
    ),
    # Marathi and Gujarati verbs agree with the speaker's gender in places;
    # these are phrased so they don't (passive, or "let's").
    "mr": CallPhrases(
        still_there="माफ करा, तुम्ही लाइनवर आहात का?",
        goodbye_silence="ठीक आहे, आपण नंतर बोलू. तुमच्या वेळेबद्दल धन्यवाद!",
        goodbye_timeout="तुमचा बराच वेळ घेतला. खूप खूप धन्यवाद!",
        goodbye_default="तुमच्या वेळेबद्दल खूप धन्यवाद. तुमचा दिवस छान जावो!",
        voicemail="माफ करा, तुमच्याशी बोलणं झालं नाही. आम्ही नंतर पुन्हा कॉल करू. धन्यवाद!",
        acknowledgements=("हो.", "बरं.", "ठीक आहे.", "ओके."),
        checking="एक मिनिट, जरा बघूया.",
    ),
    "bn": CallPhrases(
        still_there="দুঃখিত, আপনি কি লাইনে আছেন?",
        goodbye_silence="ঠিক আছে, পরে কথা হবে। আপনার সময়ের জন্য ধন্যবাদ!",
        goodbye_timeout="আপনার অনেকটা সময় নিয়ে নিলাম। অনেক ধন্যবাদ!",
        goodbye_default="আপনার সময়ের জন্য অনেক ধন্যবাদ। আপনার দিন ভালো কাটুক!",
        voicemail="দুঃখিত, আপনার সঙ্গে কথা বলা গেল না। আমরা পরে আবার ফোন করব। ধন্যবাদ!",
        acknowledgements=("আচ্ছা।", "হ্যাঁ।", "ঠিক আছে।", "ওকে।"),
        checking="এক মিনিট, একটু দেখে নিই।",
    ),
    "gu": CallPhrases(
        still_there="માફ કરજો, તમે લાઇન પર છો?",
        goodbye_silence="સારું, પછી વાત કરીએ. તમારા સમય માટે આભાર!",
        goodbye_timeout="તમારો ઘણો સમય લીધો. ખૂબ ખૂબ આભાર!",
        goodbye_default="તમારા સમય માટે ખૂબ આભાર. તમારો દિવસ શુભ રહે!",
        voicemail="માફ કરજો, તમારી સાથે વાત ન થઈ શકી. અમે પછી ફરી કૉલ કરીશું. આભાર!",
        acknowledgements=("હા.", "સારું.", "બરાબર.", "ઓકે."),
        checking="એક મિનિટ, જરા જોઈ લઈએ.",
    ),
    "pa": CallPhrases(
        still_there="ਮਾਫ਼ ਕਰਨਾ, ਕੀ ਤੁਸੀਂ ਲਾਈਨ 'ਤੇ ਹੋ?",
        goodbye_silence="ਕੋਈ ਗੱਲ ਨਹੀਂ, ਅਸੀਂ ਬਾਅਦ ਵਿੱਚ ਗੱਲ ਕਰਾਂਗੇ। ਤੁਹਾਡੇ ਸਮੇਂ ਲਈ ਧੰਨਵਾਦ!",
        goodbye_timeout="ਤੁਹਾਡਾ ਕਾਫ਼ੀ ਸਮਾਂ ਲੈ ਲਿਆ। ਬਹੁਤ-ਬਹੁਤ ਧੰਨਵਾਦ!",
        goodbye_default="ਤੁਹਾਡੇ ਸਮੇਂ ਲਈ ਬਹੁਤ ਧੰਨਵਾਦ। ਤੁਹਾਡਾ ਦਿਨ ਵਧੀਆ ਲੰਘੇ!",
        voicemail="ਮਾਫ਼ ਕਰਨਾ, ਤੁਹਾਡੇ ਨਾਲ ਗੱਲ ਨਹੀਂ ਹੋ ਸਕੀ। ਅਸੀਂ ਬਾਅਦ ਵਿੱਚ ਫਿਰ ਕਾਲ ਕਰਾਂਗੇ। ਧੰਨਵਾਦ!",
        acknowledgements=("ਜੀ।", "ਅੱਛਾ।", "ਠੀਕ ਹੈ।", "ਹਾਂ ਜੀ।"),
        checking="ਇੱਕ ਮਿੰਟ, ਜ਼ਰਾ ਦੇਖ ਲੈਂਦੇ ਹਾਂ।",
    ),
    "od": CallPhrases(
        still_there="କ୍ଷମା କରିବେ, ଆପଣ ଲାଇନରେ ଅଛନ୍ତି କି?",
        goodbye_silence="ଠିକ ଅଛି, ପରେ କଥା ହେବା। ଆପଣଙ୍କ ସମୟ ପାଇଁ ଧନ୍ୟବାଦ!",
        goodbye_timeout="ଆପଣଙ୍କର ବହୁତ ସମୟ ନେଲି। ବହୁତ ଧନ୍ୟବାଦ!",
        goodbye_default="ଆପଣଙ୍କ ସମୟ ପାଇଁ ବହୁତ ଧନ୍ୟବାଦ। ଆପଣଙ୍କ ଦିନ ଶୁଭ ହେଉ!",
        voicemail="କ୍ଷମା କରିବେ, ଆପଣଙ୍କ ସହ କଥା ହୋଇପାରିଲା ନାହିଁ। ଆମେ ପରେ ପୁଣି କଲ କରିବୁ। ଧନ୍ୟବାଦ!",
        acknowledgements=("ହଁ।", "ଆଚ୍ଛା।", "ଠିକ ଅଛି।", "ଓକେ।"),
        checking="ଗୋଟିଏ ମିନିଟ, ଟିକେ ଦେଖିନେଉଛି।",
    ),
}

# The same sets under the name tests and the API read.
PHRASES = _PHRASES


def has_phrases(language: str | None) -> bool:
    """Whether a language has its own phrase set rather than English's."""
    return (language or "").strip().lower() in _PHRASES


def phrases_for(language: str | None) -> CallPhrases:
    """The phrase set for a campaign language code; English when unknown."""
    return _PHRASES.get((language or "").strip().lower(), _PHRASES["en"])
