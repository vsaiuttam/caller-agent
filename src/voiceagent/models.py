"""Core data models.

Split into three groups:
  - Inputs   : who we're calling and why (Contact, CallContext)
  - Runtime  : what happens during the call (Turn)
  - Outputs  : what we extracted and what to do about it (CallOutcome)

CallOutcome is the structured-output target for post-call extraction, so it
must stay compatible with the Claude structured-outputs schema subset:
no recursive models, no numeric/length constraints. Descriptions are used by
the model as field-level instructions, so they're written for it, not for us.
"""

from __future__ import annotations

from datetime import datetime
from enum import Enum

from pydantic import BaseModel, Field


# --------------------------------------------------------------------------
# Inputs
# --------------------------------------------------------------------------


class Contact(BaseModel):
    """A person to call. Sourced from the caller's list."""

    contact_id: str
    full_name: str
    phone_e164: str = Field(description="E.164 format, e.g. +14155550123")
    timezone: str = Field(description="IANA timezone, e.g. America/New_York")
    # Free-form per-contact facts the agent may reference on the call
    # (account number, last order, prior appointment...). Kept as a flat
    # mapping so it renders deterministically into the cached prompt prefix.
    attributes: dict[str, str] = Field(default_factory=dict)


class ScoreCriterion(BaseModel):
    """One thing a campaign judges the person against.

    The same machinery covers a recruiter screening candidates and a sales team
    qualifying leads — "five years of Python" and "budget over ₹10 lakh" are the
    same kind of statement about what a good outcome looks like.
    """

    name: str = Field(description="Short label, e.g. 'Notice period' or 'Budget'.")
    description: str = Field(
        default="", description="What good looks like, in the words you'd brief a person with."
    )
    # Relative importance. Absolute values don't matter, only their ratio.
    weight: int = Field(default=1, ge=1, le=5)
    # A knockout that isn't met disqualifies regardless of everything else —
    # a candidate who can't start for six months fails the requirement no
    # matter how well the rest of the call went.
    knockout: bool = False


class CallContext(BaseModel):
    """Why this specific call is happening and what counts as success."""

    campaign_id: str
    goal: str = Field(description="What this call needs to accomplish, in one or two sentences.")
    # What the call is judged against. Empty means the call is informational —
    # plenty of campaigns (delivery confirmations, reminders) score nothing.
    scorecard: list[ScoreCriterion] = Field(default_factory=list)
    # Explicit list of what to collect. Drives both the in-call prompt and the
    # extraction schema's `collected` field, so the two stay in sync.
    fields_to_collect: list[str] = Field(default_factory=list)
    # Hard boundaries: things the agent must not offer, promise, or discuss.
    constraints: list[str] = Field(default_factory=list)
    # Free-form persona additions for this campaign (tone, vocabulary,
    # objection handling). Appended to the per-call prompt block.
    extra_instructions: str = ""
    # Spoken-language instruction for the agent, resolved from the campaign's
    # language code. Lives in the per-call block rather than the shared
    # persona, so campaigns in different languages still share a cached prefix.
    language_instruction: str = "Speak English throughout the call."
    max_duration_seconds: int = 600


# --------------------------------------------------------------------------
# Runtime
# --------------------------------------------------------------------------


class Turn(BaseModel):
    role: str  # "user" (the person) | "assistant" (the agent)
    text: str
    started_at: datetime
    # Agent turns only: milliseconds from the person finishing to the reply
    # being ready to play. Measured on live calls, so the dead air a caller
    # sits through is a number on the call record rather than an impression.
    latency_ms: int | None = None


# --------------------------------------------------------------------------
# Outputs
# --------------------------------------------------------------------------


class Disposition(str, Enum):
    """How the call ended. Drives routing, retry policy, and reporting."""

    COMPLETED = "completed"
    PARTIAL = "partial"  # reached them, got some but not all of the goal
    CALLBACK_REQUESTED = "callback_requested"
    DECLINED = "declined"  # asked us not to proceed
    DO_NOT_CALL = "do_not_call"  # explicit opt-out — suppress permanently
    VOICEMAIL = "voicemail"
    NO_ANSWER = "no_answer"
    WRONG_NUMBER = "wrong_number"
    FAILED = "failed"  # technical failure mid-call


class Sentiment(str, Enum):
    """How the person came across on the call, overall."""

    POSITIVE = "positive"
    NEUTRAL = "neutral"
    NEGATIVE = "negative"


class CollectedField(BaseModel):
    """One piece of information gathered during the call."""

    name: str = Field(description="Field name, matching one of the requested fields_to_collect.")
    value: str
    verbatim: bool = Field(
        description="True if the value was stated explicitly by the person, "
        "false if it was inferred from context."
    )


class Appointment(BaseModel):
    """A scheduling commitment made on the call."""

    starts_at_local: str = Field(description="ISO 8601 local datetime as agreed on the call.")
    timezone: str = Field(description="IANA timezone the person is in.")
    duration_minutes: int
    subject: str
    notes: str = Field(default="", description="Anything relevant to whoever attends.")


class CriterionScore(BaseModel):
    """How the person did against one criterion, with the evidence for it."""

    name: str = Field(description="The criterion name, copied exactly from the list provided.")
    rating: int = Field(
        description="0 = never addressed on the call, 1 = clearly falls short, "
        "2 = partially meets, 3 = meets, 4 = clearly exceeds."
    )
    met: bool = Field(description="True only if the transcript shows they meet this.")
    evidence: str = Field(
        description="A short quote or close paraphrase from the transcript supporting "
        "the rating. Empty when the criterion never came up."
    )


class QualificationBand(str, Enum):
    """The coarse verdict a human actually sorts by."""

    STRONG = "strong"
    POSSIBLE = "possible"
    WEAK = "weak"
    DISQUALIFIED = "disqualified"  # failed a knockout
    NOT_ASSESSED = "not_assessed"  # campaign defines no scorecard


class Qualification(BaseModel):
    """The weighted result. Computed in Python, never asked of the model.

    The model rates each criterion against evidence; the arithmetic happens
    here. That keeps a score comparable between two calls made a month apart,
    lets a changed weighting be re-applied to calls already made, and means a
    number that decides whether a person gets interviewed can be checked by
    hand.
    """

    score: int = Field(default=0, description="0-100, weighted across the scorecard.")
    band: QualificationBand = QualificationBand.NOT_ASSESSED
    reasons: str = ""
    disqualified_by: str = Field(
        default="", description="The knockout criterion that failed, if any."
    )


class CallOutcome(BaseModel):
    """Structured result of one call. The extraction target."""

    disposition: Disposition
    summary: str = Field(description="Two to three sentences on what happened, for a human skimming a queue.")
    collected: list[CollectedField] = Field(default_factory=list)
    # One entry per criterion the campaign defined. The model fills these in;
    # `Qualification` is derived from them afterwards.
    scores: list[CriterionScore] = Field(default_factory=list)
    appointment: Appointment | None = Field(
        default=None, description="Set only if a specific time was actually agreed on the call."
    )
    # The extractor's own confidence gate. If the model is unsure what was
    # agreed, it says so here rather than guessing — and we route to a human
    # instead of writing wrong data into the CRM.
    needs_human_review: bool
    review_reason: str = Field(
        default="", description="Why review is needed. Empty when needs_human_review is false."
    )
    # Defaulted so outcomes stored before sentiment existed still load.
    sentiment: Sentiment = Field(
        default=Sentiment.NEUTRAL,
        description="The person's overall attitude on the call: positive, neutral or negative.",
    )
    sentiment_reason: str = Field(
        default="", description="One short phrase from the call that shows the sentiment."
    )

    # Note there is no `qualification` field here. This model is the schema
    # handed to the extractor, and the weighted verdict is not the extractor's
    # to give — `scoring.qualify` derives it from `scores` afterwards and it
    # travels alongside the outcome, not inside it.
