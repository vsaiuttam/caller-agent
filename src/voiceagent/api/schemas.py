"""Request/response shapes for the HTTP API.

Kept separate from the ORM models so the wire format can change without a
migration, and so we never accidentally serialise a column that shouldn't
leave the server (full phone numbers go out masked; see `CallSummary`).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, Field

from ..catalog import (
    DEFAULT_CONVERSATION_EFFORT,
    DEFAULT_CONVERSATION_MODEL,
    DEFAULT_EXTRACTION_EFFORT,
    DEFAULT_EXTRACTION_MODEL,
)


# --------------------------------------------------------------------------
# Campaigns
# --------------------------------------------------------------------------


DEFAULT_GREETING = (
    "Hi {first_name}, this is an AI assistant calling on behalf of "
    "{campaign_name}. Do you have a moment?"
)


class ScoreCriterionIn(BaseModel):
    """One row of a campaign's scorecard."""

    name: str = Field(min_length=1, max_length=120)
    description: str = ""
    weight: int = Field(default=1, ge=1, le=5)
    knockout: bool = False


class CampaignCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)
    goal: str = Field(min_length=1)
    # What the call is judged against. Empty is normal — a delivery
    # confirmation has nothing to score.
    scorecard: list[ScoreCriterionIn] = Field(default_factory=list, max_length=20)
    greeting: str = Field(
        default=DEFAULT_GREETING,
        description="Opening line. {first_name}, {full_name}, {campaign_name} are substituted.",
    )
    fields_to_collect: list[str] = Field(default_factory=list)
    constraints: list[str] = Field(default_factory=list)
    extra_instructions: str = Field(
        default="", description="Free-form persona guidance for this campaign."
    )
    language: str = Field(default="en", description="Language code: en, hi, ur, hi-en.")
    template_id: str | None = Field(
        default=None, description="Template this campaign was created from, if any."
    )
    calling_hours_start: int = Field(default=9, ge=0, le=23)
    calling_hours_end: int = Field(default=20, ge=1, le=24)
    calling_days: list[int] = Field(default_factory=lambda: [1, 2, 3, 4, 5])
    max_concurrent_calls: int = Field(default=10, ge=1, le=500)
    max_attempts: int = Field(default=3, ge=1, le=10)

    # Model selection. Null means "use the workspace default", resolved in the
    # route — not `model_fields_set`, because the UI posts a complete object
    # and every field would look deliberately set. Validated against the
    # catalog rather than by an Enum here, so adding a model to catalog.py is
    # the only edit needed.
    conversation_model: str | None = None
    conversation_effort: str | None = None
    extraction_model: str | None = None
    extraction_effort: str | None = None

    budget_usd: float | None = Field(
        default=None, ge=0, description="Hard spend cap in USD. The campaign pauses itself at it."
    )
    sms_followup: bool = Field(
        default=False, description="Text the person after each call. Requires Twilio."
    )
    whatsapp_followup: bool = Field(
        default=False,
        description="WhatsApp the person after each call. Requires TWILIO_WHATSAPP_FROM.",
    )
    webhook_url: str | None = Field(
        default=None, max_length=500, description="POSTed once per completed call."
    )


class CampaignUpdate(BaseModel):
    """Partial update. Omitted fields are left unchanged."""

    name: str | None = Field(default=None, min_length=1, max_length=200)
    goal: str | None = Field(default=None, min_length=1)
    scorecard: list[ScoreCriterionIn] | None = Field(default=None, max_length=20)
    greeting: str | None = None
    fields_to_collect: list[str] | None = None
    constraints: list[str] | None = None
    extra_instructions: str | None = None
    language: str | None = None
    calling_hours_start: int | None = Field(default=None, ge=0, le=23)
    calling_hours_end: int | None = Field(default=None, ge=1, le=24)
    calling_days: list[int] | None = None
    max_concurrent_calls: int | None = Field(default=None, ge=1, le=500)
    max_attempts: int | None = Field(default=None, ge=1, le=10)
    conversation_model: str | None = None
    conversation_effort: str | None = None
    extraction_model: str | None = None
    extraction_effort: str | None = None
    budget_usd: float | None = Field(default=None, ge=0)
    sms_followup: bool | None = None
    whatsapp_followup: bool | None = None
    webhook_url: str | None = None


class CampaignOut(CampaignCreate):
    id: str
    status: str
    created_at: datetime
    # Always concrete on the way out — nulls were resolved at creation, so a
    # reader never has to know what the default was at the time.
    conversation_model: str = DEFAULT_CONVERSATION_MODEL
    conversation_effort: str = DEFAULT_CONVERSATION_EFFORT
    extraction_model: str = DEFAULT_EXTRACTION_MODEL
    extraction_effort: str = DEFAULT_EXTRACTION_EFFORT
    # Rolled-up counts so the list view doesn't need N+1 queries.
    total_contacts: int = 0
    pending: int = 0
    completed: int = 0
    needs_review: int = 0
    spend_usd: float = 0.0


# --------------------------------------------------------------------------
# Models & settings
# --------------------------------------------------------------------------


class ModelDefaults(BaseModel):
    """Workspace defaults, inherited by new campaigns."""

    conversation_model: str = DEFAULT_CONVERSATION_MODEL
    conversation_effort: str = DEFAULT_CONVERSATION_EFFORT
    extraction_model: str = DEFAULT_EXTRACTION_MODEL
    extraction_effort: str = DEFAULT_EXTRACTION_EFFORT


class EstimateRequest(BaseModel):
    conversation_model: str = DEFAULT_CONVERSATION_MODEL
    conversation_effort: str = DEFAULT_CONVERSATION_EFFORT
    extraction_model: str = DEFAULT_EXTRACTION_MODEL
    extraction_effort: str = DEFAULT_EXTRACTION_EFFORT
    contacts: int = Field(default=1000, ge=1, le=1_000_000)
    exchanges: int = Field(default=8, ge=1, le=60)
    connect_rate: float = Field(default=0.55, ge=0.0, le=1.0)


# --------------------------------------------------------------------------
# Rehearsal — against a simulated person, or against your own voice
# --------------------------------------------------------------------------


class CallSetupRequest(BaseModel):
    """Everything needed to run a call with no contact row and no phone line.

    A campaign_id seeds the defaults; every field can still be overridden, so
    a prompt can be trialled before the campaign exists. Shared by both ways
    of trying a campaign out, because the setup is genuinely the same — only
    who plays the person differs.
    """

    campaign_id: str | None = None

    goal: str | None = Field(default=None, min_length=1)
    # Overridable so a scorecard can be trialled against a persona before it is
    # saved onto the campaign — the whole point of rehearsing.
    scorecard: list[ScoreCriterionIn] | None = None
    greeting: str | None = None
    fields_to_collect: list[str] | None = None
    constraints: list[str] | None = None
    extra_instructions: str | None = None
    language: str | None = None

    contact_name: str = "Alex Morgan"
    contact_timezone: str = "America/New_York"
    contact_attributes: dict[str, str] = Field(default_factory=dict)

    conversation_model: str | None = None
    conversation_effort: str | None = None
    extraction_model: str | None = None
    extraction_effort: str | None = None

    # Rehearsals are inspectable in the calls list when saved, and always
    # excluded from aggregates. Off by default so experimenting doesn't
    # accumulate rows nobody asked for.
    save: bool = False


class SimulationRequest(CallSetupRequest):
    """Rehearse against a scripted persona played by Claude."""

    persona: str = "cooperative"
    max_exchanges: int = Field(default=8, ge=1, le=20)


class TestCallRequest(CallSetupRequest):
    """Place a real phone call to test the campaign on an actual phone."""

    phone_number: str = Field(
        pattern=r"^\+[1-9]\d{6,14}$",
        description="E.164 phone number to call, e.g. +14155550123",
    )
    # Follow-ups to the number called once the call ends. Null means "do what
    # the campaign does".
    send_sms: bool | None = None
    send_whatsapp: bool | None = None


class LiveCallRequest(CallSetupRequest):
    """Rehearse against yourself, over the browser's microphone.

    Arrives as the first message on the /api/live socket rather than as a
    request body, so it is validated by hand at the top of that handler.
    """


# --------------------------------------------------------------------------
# Contacts
# --------------------------------------------------------------------------


class ContactCreate(BaseModel):
    full_name: str
    phone_e164: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    timezone: str = "America/New_York"
    attributes: dict[str, str] = Field(default_factory=dict)


class ContactBulkCreate(BaseModel):
    contacts: list[ContactCreate] = Field(min_length=1, max_length=10_000)


class ContactOut(BaseModel):
    id: str
    full_name: str
    phone_masked: str
    timezone: str
    status: str
    attempts: int
    next_attempt_at: datetime | None


class BulkResult(BaseModel):
    created: int
    skipped_suppressed: int
    skipped_duplicate: int


# --------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------


class CallSummary(BaseModel):
    id: str
    campaign_id: str
    contact_id: str
    contact_name: str
    phone_masked: str
    status: str
    disposition: str | None
    summary: str | None
    needs_human_review: bool
    review_reason: str | None
    started_at: datetime
    ended_at: datetime | None
    duration_seconds: int | None
    cost_usd: float = 0.0
    is_simulation: bool = False
    # Null when the campaign has no scorecard, which is most of them.
    score: int | None = None
    qualification_band: str | None = None


class CallDetail(CallSummary):
    transcript: list[dict[str, Any]]
    outcome: dict[str, Any] | None
    # Per-criterion ratings with their evidence, and the derived verdict. Kept
    # separate from `outcome` because the model produced one and we computed
    # the other, and a reviewer arguing with a score needs to know which.
    scores: list[dict[str, Any]] = Field(default_factory=list)
    qualification: dict[str, Any] | None = None
    dispatch_result: dict[str, Any] | None
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0
    conversation_model: str | None = None
    extraction_model: str | None = None
    # Recording
    recording_url: str | None = None
    recording_sid: str | None = None
    recording_duration: int | None = None
    # Answering Machine Detection
    amd_result: str | None = None
    # Follow-up messages and their delivery status
    sms_sid: str | None = None
    sms_status: str | None = None
    whatsapp_sid: str | None = None
    whatsapp_status: str | None = None
    followup_errors: dict[str, str] | None = None


class FollowupResend(BaseModel):
    sms: bool = False
    whatsapp: bool = False


class ReviewDecision(BaseModel):
    approve: bool
    note: str = ""


# --------------------------------------------------------------------------
# Suppression
# --------------------------------------------------------------------------


class SuppressionCreate(BaseModel):
    phone_e164: str = Field(pattern=r"^\+[1-9]\d{6,14}$")
    reason: str = "Manually added"


class SuppressionOut(BaseModel):
    phone_masked: str
    reason: str
    created_at: datetime


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


class HourBucket(BaseModel):
    hour: str = Field(description="ISO hour, e.g. 2026-08-12T14:00:00Z")
    label: str = Field(description="Short display label, e.g. '14:00'")
    total: int
    connected: int


class DashboardStats(BaseModel):
    campaigns_running: int
    calls_today: int
    calls_in_progress: int
    connect_rate: float = Field(description="Fraction of dials that reached a person.")
    completion_rate: float = Field(description="Fraction of reached calls that met the goal.")
    avg_duration_seconds: int
    pending_review: int
    suppressed_total: int
    disposition_breakdown: dict[str, int]

    # Model spend over the same 24h window, and what it works out to per
    # connected call — the number that tells you whether a model swap paid off.
    spend_usd: float = 0.0
    spend_delta: float | None = None
    cost_per_connected_call_usd: float = 0.0
    cache_hit_rate: float = Field(
        default=0.0,
        description="Share of prompt input served from cache. The prompt layout's KPI.",
    )

    # Deltas against the preceding 24h window, as fractional change (0.12 = +12%).
    # None when the prior window had no data — a delta against zero is
    # meaningless and the UI renders it as "—" rather than "+100%".
    calls_delta: float | None = None
    connect_rate_delta: float | None = None
    avg_duration_delta: float | None = None

    volume_by_hour: list[HourBucket] = Field(default_factory=list)
