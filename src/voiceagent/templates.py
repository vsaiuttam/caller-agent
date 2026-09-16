"""Prebuilt campaign templates.

Static data, not database rows: these are product content that ships with the
app and is version-controlled alongside the prompts they configure. A user
picks one, it fills the campaign builder, and they edit from there — the
template is a starting point, never a locked configuration.

Each template carries per-language greetings because an opening line does not
survive translation intact: the Hindi and Urdu versions here are written to
sound natural on a call, not transliterated from the English.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import Any


@dataclass(frozen=True)
class Language:
    code: str
    name: str
    native_name: str
    # Spoken-language instruction injected into the agent's prompt. Explicit
    # because a model given Hindi contact data will otherwise drift into
    # English mid-call.
    instruction: str


LANGUAGES: list[Language] = [
    Language(
        code="en",
        name="English",
        native_name="English",
        instruction="Speak English throughout the call.",
    ),
    Language(
        code="hi",
        name="Hindi",
        native_name="हिन्दी",
        instruction=(
            "Speak Hindi throughout the call, in the conversational register most "
            "Indian callers use on the phone — everyday Hindi with common English "
            "loanwords left as-is (appointment, confirm, email, address). Do not "
            "use heavily Sanskritised vocabulary; it sounds stilted spoken aloud. "
            "If the person replies in English, switch to English and stay there."
        ),
    ),
    Language(
        code="ur",
        name="Urdu",
        native_name="اردو",
        instruction=(
            "Speak Urdu throughout the call, in a natural conversational register. "
            "Common English loanwords (appointment, confirm, email) are normal in "
            "speech — keep them. If the person replies in English or Hindi, switch "
            "to match them."
        ),
    ),
    Language(
        code="hi-en",
        name="Hinglish",
        native_name="Hinglish",
        instruction=(
            "Speak natural Hinglish — Hindi sentence structure with English words "
            "mixed in the way urban Indian speakers actually talk on the phone. Do "
            "not translate technical or business terms into formal Hindi. Follow "
            "the person's lead: if they use more English, use more English."
        ),
    ),
]


@dataclass(frozen=True)
class CampaignTemplate:
    id: str
    name: str
    category: str
    description: str
    goal: str
    greetings: dict[str, str]  # language code → opening line
    fields_to_collect: list[str]
    constraints: list[str]
    # What the call is judged against: {name, description, weight, knockout}.
    # Empty on informational campaigns — a delivery confirmation has a result,
    # not a score.
    scorecard: list[dict[str, Any]] = field(default_factory=list)
    extra_instructions: str = ""
    # Rough guidance shown on the card, not enforced.
    typical_duration: str = "2–4 min"
    languages: list[str] = field(default_factory=lambda: ["en", "hi", "ur", "hi-en"])

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


CATEGORIES = [
    "All",
    "Healthcare",
    "Real Estate",
    "Finance",
    "E-commerce",
    "Education",
    "Hospitality",
    "Services",
    "HR & Recruitment",
]


TEMPLATES: list[CampaignTemplate] = [
    CampaignTemplate(
        id="appointment-confirmation",
        name="Appointment confirmation",
        category="Healthcare",
        description=(
            "Confirms an upcoming appointment and reschedules it if the time no "
            "longer works. The highest-volume outbound use case in most clinics."
        ),
        goal=(
            "Confirm the person still wants their upcoming appointment. If the "
            "existing time no longer works, agree a specific new date and time. "
            "Do not end the call with a vague 'sometime next week' — get an actual slot."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant calling from {campaign_name} about your upcoming appointment. Do you have a moment?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ, आपकी appointment के बारे में। क्या आप एक मिनट बात कर सकते हैं?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ بول رہی ہوں، آپ کی اپائنٹمنٹ کے بارے میں۔ کیا آپ ایک منٹ بات کر سکتے ہیں؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant bol rahi hoon, aapki appointment ke baare mein. Ek minute baat kar sakte hain?",
        },
        fields_to_collect=[
            "Whether the existing appointment still works",
            "Preferred day and time if rescheduling",
            "Best contact number or email for the confirmation",
        ],
        constraints=[
            "Never give medical advice of any kind",
            "Do not discuss test results, diagnoses, or treatment",
            "Do not quote prices or discuss insurance coverage",
            "If they ask a clinical question, offer to have a staff member call back",
        ],
        extra_instructions=(
            "Many people take these calls at work and are brief. Lead with the date "
            "and time so they can confirm in one word if nothing has changed."
        ),
        typical_duration="1–3 min",
    ),
    CampaignTemplate(
        id="lead-qualification",
        name="Lead qualification",
        category="Real Estate",
        description=(
            "Qualifies an inbound enquiry against budget, timeline, and location "
            "before a human agent spends time on it."
        ),
        goal=(
            "Establish whether this enquiry is worth an agent's time: what they are "
            "looking for, their budget range, their timeline, and whether they are "
            "already working with another agent. Book a viewing or a callback if "
            "they qualify."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant from {campaign_name} following up on your property enquiry. Is now an okay time?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ, आपकी property enquiry के बारे में। अभी बात करना ठीक रहेगा?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ بول رہی ہوں، آپ کی پراپرٹی انکوائری کے بارے میں۔ کیا ابھی بات کرنا ٹھیک رہے گا؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant bol rahi hoon, aapki property enquiry ke regarding. Abhi baat karna theek rahega?",
        },
        fields_to_collect=[
            "Property type and number of bedrooms wanted",
            "Budget range",
            "Preferred locations or areas",
            "Timeline to move",
            "Whether they are already working with another agent",
            "Best time for an agent to call back",
        ],
        constraints=[
            "Never quote a specific price for a specific property",
            "Do not promise availability of any listing",
            "Do not discuss commission or fees",
            "Do not pressure anyone who says they are just browsing",
        ],
        scorecard=[
            {
                "name": "Genuine intent",
                "description": "Actively looking, not idly browsing or comparing for later.",
                "weight": 5,
                "knockout": True,
            },
            {
                "name": "Budget stated",
                "description": (
                    "Gave a real range, however rough, and it is at or above "
                    "₹50 lakh. EDIT: set your minimum. 'Depends' is not a budget."
                ),
                "weight": 4,
            },
            {
                "name": "Timeline",
                "description": "Moving within six months. Sooner scores higher.",
                "weight": 4,
            },
            {
                "name": "Unrepresented",
                "description": "Not already working with another agent on this search.",
                "weight": 3,
            },
            {
                "name": "Next step agreed",
                "description": "Accepted a viewing or a callback at a specific time.",
                "weight": 3,
            },
        ],
        extra_instructions=(
            "Budget is the question people are most guarded about. Ask it after they "
            "have described what they want, not before, and accept a range."
        ),
        typical_duration="3–5 min",
    ),
    CampaignTemplate(
        id="payment-reminder",
        name="Payment reminder",
        category="Finance",
        description=(
            "A courtesy reminder about an outstanding balance. Deliberately soft — "
            "collections tone creates complaints and does not improve recovery."
        ),
        goal=(
            "Remind the person of an outstanding balance, confirm they are aware of "
            "it, and find out when they expect to pay. Offer to send payment details "
            "again if they need them."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant calling from {campaign_name} with a quick account reminder. Is this a good time?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ, आपके account के बारे में एक reminder देने के लिए। क्या अभी बात कर सकते हैं?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ بول رہی ہوں، آپ کے اکاؤنٹ کے بارے میں یاد دہانی کے لیے۔ کیا ابھی بات کر سکتے ہیں؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant bol rahi hoon, aapke account ka ek reminder dene ke liye. Abhi baat kar sakte hain?",
        },
        fields_to_collect=[
            "Whether they are aware of the outstanding balance",
            "Expected payment date",
            "Whether they need payment details resent",
            "Any dispute or issue they want to raise",
        ],
        constraints=[
            "Never threaten legal action, collections, or service disconnection",
            "Do not discuss the balance with anyone other than the account holder",
            "If they dispute the amount, record it and escalate — never argue",
            "Do not take card or bank details over the call under any circumstances",
            "If they say they cannot pay, be understanding and offer a callback",
        ],
        extra_instructions=(
            "Tone matters more here than anywhere else. This is a reminder between "
            "a business and its customer, not a demand. If they sound distressed, "
            "offer a callback from a person and close warmly."
        ),
        typical_duration="2–3 min",
    ),
    CampaignTemplate(
        id="delivery-confirmation",
        name="Delivery confirmation",
        category="E-commerce",
        description=(
            "Confirms someone will be available for a delivery slot, and reschedules "
            "if not. Cuts failed-delivery costs substantially."
        ),
        goal=(
            "Confirm the person will be available to receive their delivery in the "
            "scheduled window. If not, agree an alternative slot or a safe place to "
            "leave the parcel."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant from {campaign_name} about your delivery. Quick question — do you have a second?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ, आपकी delivery के बारे में। एक छोटा सा सवाल है, एक मिनट है आपके पास?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ بول رہی ہوں، آپ کی ڈیلیوری کے بارے میں۔ ایک چھوٹا سا سوال ہے، ایک منٹ ہے آپ کے پاس؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant, aapki delivery ke baare mein. Chhota sa question hai, ek minute hai?",
        },
        fields_to_collect=[
            "Whether they will be available in the scheduled window",
            "Alternative delivery date or time if not",
            "Safe place to leave the parcel if nobody will be home",
            "Any access instructions for the driver",
        ],
        constraints=[
            "Never confirm the contents or value of the parcel",
            "Do not process refunds, returns, or cancellations",
            "Do not share the driver's personal details or phone number",
        ],
        typical_duration="1–2 min",
    ),
    CampaignTemplate(
        id="course-enrolment",
        name="Course enrolment follow-up",
        category="Education",
        description=(
            "Follows up with prospective students who enquired but did not enrol, "
            "and identifies what is blocking them."
        ),
        goal=(
            "Find out whether the person is still interested in enrolling, what is "
            "holding them back, and book a call with an admissions counsellor if "
            "there is genuine interest."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant from {campaign_name} following up on your course enquiry. Do you have a couple of minutes?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ, आपने जो course के बारे में पूछा था उसी सिलसिले में। दो मिनट बात कर सकते हैं?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ بول رہی ہوں، آپ کی کورس انکوائری کے سلسلے میں۔ کیا دو منٹ بات کر سکتے ہیں؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant, aapki course enquiry ke silsile mein. Do minute baat kar sakte hain?",
        },
        fields_to_collect=[
            "Whether they are still considering enrolling",
            "What is holding them back (fees, timing, format, something else)",
            "Preferred start date or batch",
            "Whether they want a counsellor to call them",
        ],
        constraints=[
            "Never guarantee admission, placement, or a job outcome",
            "Do not quote fees or offer discounts",
            "Do not disparage other institutions",
            "Do not pressure anyone who says they have chosen elsewhere",
        ],
        extra_instructions=(
            "The useful information here is the objection, not the yes. If they are "
            "not enrolling, find out why before closing — that is the point of the call."
        ),
        typical_duration="3–4 min",
    ),
    CampaignTemplate(
        id="reservation-confirmation",
        name="Reservation confirmation",
        category="Hospitality",
        description=(
            "Confirms a booking, captures party size changes, and picks up special "
            "requirements before the guest arrives."
        ),
        goal=(
            "Confirm the reservation is still wanted, verify the party size and time, "
            "and capture any dietary requirements or special occasions."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant calling from {campaign_name} to confirm your booking. Do you have a moment?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ, आपकी booking confirm करने के लिए। एक मिनट बात कर सकते हैं?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ بول رہی ہوں، آپ کی بکنگ کنفرم کرنے کے لیے۔ کیا ایک منٹ بات کر سکتے ہیں؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant, aapki booking confirm karne ke liye. Ek minute hai?",
        },
        fields_to_collect=[
            "Whether the booking is still wanted",
            "Final party size",
            "Dietary requirements or allergies",
            "Whether it is a special occasion",
        ],
        constraints=[
            "Never guarantee a specific table or seating area",
            "Do not quote menu prices",
            "Do not take payment or card details",
        ],
        typical_duration="1–2 min",
    ),
    CampaignTemplate(
        id="service-feedback",
        name="Post-service feedback",
        category="Services",
        description=(
            "Collects a short satisfaction rating and open feedback after a job is "
            "completed, and flags anyone unhappy for immediate follow-up."
        ),
        goal=(
            "Find out how satisfied the customer was with the recent service, capture "
            "specific feedback, and flag anything that needs a human to follow up."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant from {campaign_name}. We finished a job for you recently — mind if I ask how it went?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ। हमने हाल ही में आपका काम पूरा किया था — पूछ सकती हूँ कैसा रहा?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ ہوں۔ ہم نے حال ہی میں آپ کا کام مکمل کیا تھا — کیا پوچھ سکتی ہوں کیسا رہا؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant. Humne recently aapka kaam complete kiya tha — pooch sakti hoon kaisa raha?",
        },
        fields_to_collect=[
            "Overall satisfaction, one to five",
            "What went well",
            "What could have been better",
            "Whether they would use the service again",
            "Whether they want someone to follow up",
        ],
        constraints=[
            "Never argue with negative feedback or defend the company",
            "Do not offer refunds, discounts, or compensation",
            "If they are unhappy, acknowledge it, capture the detail, and escalate",
        ],
        extra_instructions=(
            "A low score is more valuable than a high one. When someone is "
            "dissatisfied, slow down and get the specifics rather than moving to the "
            "next question."
        ),
        typical_duration="2–4 min",
    ),
    CampaignTemplate(
        id="interview-scheduling",
        name="Interview scheduling",
        category="HR & Recruitment",
        description=(
            "Reaches shortlisted candidates, confirms they are still interested, and "
            "books an interview slot."
        ),
        goal=(
            "Confirm the candidate is still interested in the role, check their "
            "availability, and book a specific interview slot."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant calling from {campaign_name} about your application. Is now a good time?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ, आपकी application के बारे में। क्या अभी बात कर सकते हैं?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ بول رہی ہوں، آپ کی درخواست کے بارے میں۔ کیا ابھی بات کر سکتے ہیں؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant, aapki application ke baare mein. Abhi baat kar sakte hain?",
        },
        fields_to_collect=[
            "Whether they are still interested in the role",
            "Availability for an interview over the next two weeks",
            "Preferred interview format (in person, phone, video)",
            "Notice period if currently employed",
        ],
        constraints=[
            "Never discuss salary, benefits, or compensation",
            "Do not make any statement about their likelihood of being hired",
            "Do not ask about age, marital status, religion, caste, or family plans",
            "Do not disclose who else is interviewing",
        ],
        scorecard=[
            {
                "name": "Still interested",
                "description": "Actively wants to proceed, not merely being polite.",
                "weight": 5,
                "knockout": True,
            },
            {
                "name": "Notice period",
                "description": (
                    "Can start within 60 days. EDIT: set your hiring window."
                ),
                "weight": 4,
            },
            {
                "name": "Availability to interview",
                "description": "Offered concrete slots in the next two weeks, not 'anytime'.",
                "weight": 3,
            },
            {
                "name": "Communication",
                "description": (
                    "Clear, answers what was asked, does not need everything repeated. "
                    "Judge the substance, not the accent or the fluency of their English."
                ),
                "weight": 2,
            },
        ],
        extra_instructions=(
            "Candidates often take these calls near colleagues. Keep it short and "
            "avoid naming the hiring company loudly at the start if they sound "
            "constrained — offer to call back instead."
        ),
        typical_duration="2–3 min",
    ),
    CampaignTemplate(
        id="candidate-screening",
        name="Candidate screening",
        category="HR & Recruitment",
        description=(
            "First-round screen against the role's hard requirements. Produces a "
            "ranked shortlist with the evidence for every rating attached."
        ),
        goal=(
            "Screen this applicant against the role's requirements. Establish what "
            "they have actually done rather than what is on their CV, when they could "
            "start, and whether their expectations are in range. Get specifics — how "
            "long, on what, and what they personally did."
        ),
        greetings={
            "en": "Hi {first_name}, this is an AI assistant calling from {campaign_name} about the role you applied for. Do you have five minutes?",
            "hi": "नमस्ते {first_name} जी, मैं {campaign_name} से AI असिस्टेंट बोल रही हूँ, आपने जिस role के लिए apply किया था उसके बारे में। पाँच मिनट बात कर सकते हैं?",
            "ur": "السلام علیکم {first_name} صاحب، میں {campaign_name} سے AI اسسٹنٹ بول رہی ہوں، آپ نے جس role کے لیے اپلائی کیا تھا اُس کے بارے میں۔ کیا پانچ منٹ بات کر سکتے ہیں؟",
            "hi-en": "Hi {first_name}, main {campaign_name} se AI assistant bol rahi hoon, aapne jis role ke liye apply kiya tha uske baare mein. Paanch minute baat kar sakte hain?",
        },
        fields_to_collect=[
            "Years of hands-on experience in the core skill",
            "What they personally built or owned most recently",
            "Current notice period",
            "Expected compensation range",
            "Willingness to work from the role's location",
        ],
        constraints=[
            "Do not ask about age, marital status, religion, caste, gender, pregnancy, or family plans",
            "Do not state or imply whether they will progress",
            "Do not disclose the salary band, other applicants, or who else is interviewing",
            "Do not negotiate compensation — record what they say and stop there",
            "If they ask something about the role you were not told, say so and offer a callback",
        ],
        # Every threshold is written into the criterion itself, with the
        # numbers as EDIT-ME placeholders. A criterion like "has the experience
        # the role requires" cannot be judged by anything that was not told
        # what the role requires — and a model asked to judge it will pass
        # people rather than admit it cannot. Left vague, a knockout silently
        # approves everybody, which is the worst failure this feature has.
        scorecard=[
            {
                "name": "Core skill depth",
                "description": (
                    "Describes work they personally did, with specifics. Naming a "
                    "technology is not evidence of having used it."
                ),
                "weight": 5,
            },
            {
                "name": "Meets minimum experience",
                "description": (
                    "At least 5 years hands-on with the core skill. "
                    "EDIT: set the number this role actually requires."
                ),
                "weight": 5,
                "knockout": True,
            },
            {
                "name": "Notice period",
                "description": (
                    "Can start within 60 days. EDIT: set your hiring window."
                ),
                "weight": 3,
            },
            {
                "name": "Compensation in range",
                "description": (
                    "Expectation is at or below ₹25 lakh per year. "
                    "EDIT: set the band for this role."
                ),
                "weight": 3,
            },
            {
                "name": "Location workable",
                "description": (
                    "Can work from the Bangalore office. "
                    "EDIT: set your location and arrangement."
                ),
                "weight": 3,
                "knockout": True,
            },
            {
                "name": "Communication",
                "description": (
                    "Answers the question asked, gives specifics when pressed. Judge "
                    "clarity of thought, never accent or fluency in English."
                ),
                "weight": 2,
            },
        ],
        extra_instructions=(
            "Push once for specifics when an answer is generic — 'I worked on the "
            "backend' should become what they built and for how long. Push once, "
            "not twice; this is a screen, not an interrogation, and a candidate who "
            "feels cross-examined tells their network about it."
        ),
        typical_duration="4–6 min",
    ),
]


def get_template(template_id: str) -> CampaignTemplate | None:
    return next((t for t in TEMPLATES if t.id == template_id), None)


def language_instruction(code: str) -> str:
    match = next((lang for lang in LANGUAGES if lang.code == code), None)
    return match.instruction if match else LANGUAGES[0].instruction
