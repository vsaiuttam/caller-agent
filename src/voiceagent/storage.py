"""Persistence. Async SQLAlchemy — SQLite for dev, Postgres for production.

Schema notes:
  - Suppression is keyed on phone number, not contact id. The same person can
    appear in several campaigns under different contact rows; an opt-out has
    to stop all of them, so the check is on the thing that's actually dialled.
  - Call transcripts live as JSON on the call row. They're written once at the
    end and read whole, so there's nothing to gain from normalising turns into
    their own table.
  - `next_attempt_at` on Contact is the retry clock. The scheduler queries on
    it, so it's indexed alongside status.
"""

from __future__ import annotations

import enum
import os
import logging
from datetime import datetime, timezone
from typing import Any

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Enum,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    inspect,
    text,
)
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

from .catalog import (
    DEFAULT_CONVERSATION_EFFORT,
    DEFAULT_CONVERSATION_MODEL,
    DEFAULT_EXTRACTION_EFFORT,
    DEFAULT_EXTRACTION_MODEL,
)

_raw_url = os.getenv("DATABASE_URL", "sqlite+aiosqlite:///./voiceagent.db")
# Render provides postgresql:// but SQLAlchemy async needs postgresql+asyncpg://
if _raw_url.startswith("postgresql://"):
    DATABASE_URL = _raw_url.replace("postgresql://", "postgresql+asyncpg://", 1)
elif _raw_url.startswith("postgres://"):
    DATABASE_URL = _raw_url.replace("postgres://", "postgresql+asyncpg://", 1)
else:
    DATABASE_URL = _raw_url


def utcnow() -> datetime:
    return datetime.now(timezone.utc)


class Base(DeclarativeBase):
    pass


# --------------------------------------------------------------------------
# Enums
# --------------------------------------------------------------------------


class CampaignStatus(str, enum.Enum):
    DRAFT = "draft"
    RUNNING = "running"
    PAUSED = "paused"
    COMPLETED = "completed"


class ContactStatus(str, enum.Enum):
    PENDING = "pending"          # eligible, waiting for a slot
    QUEUED = "queued"            # claimed by the runner, about to dial
    IN_PROGRESS = "in_progress"  # on a call right now
    COMPLETED = "completed"      # goal met, no further attempts
    EXHAUSTED = "exhausted"      # out of retries
    SUPPRESSED = "suppressed"    # opted out
    FAILED = "failed"


class CallStatus(str, enum.Enum):
    DIALING = "dialing"
    CONNECTED = "connected"
    COMPLETED = "completed"
    FAILED = "failed"


# --------------------------------------------------------------------------
# Tables
# --------------------------------------------------------------------------


class Campaign(Base):
    __tablename__ = "campaigns"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    goal: Mapped[str] = mapped_column(Text)
    fields_to_collect: Mapped[list[str]] = mapped_column(JSON, default=list)
    constraints: Mapped[list[str]] = mapped_column(JSON, default=list)

    # What the call is judged against: a list of {name, description, weight,
    # knockout}. Empty for informational campaigns, which score nothing. Stored
    # as JSON rather than its own table because it is read and written whole,
    # always in the context of its campaign, and never queried across rows.
    scorecard: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # The first thing said when the call connects. {first_name} and
    # {campaign_name} are substituted. Editable because the opening line does
    # more than any other single sentence to determine whether the person
    # stays on the call.
    greeting: Mapped[str] = mapped_column(
        Text,
        default="Hi {first_name}, this is an AI assistant calling on behalf of "
        "{campaign_name}. Do you have a moment?",
    )
    # Free-form additions to the agent's persona for this campaign — tone,
    # domain vocabulary, how to handle common objections. Appended to the
    # per-call prompt block, never to the shared persona (which must stay
    # byte-identical across campaigns for the prompt cache to hit).
    extra_instructions: Mapped[str] = mapped_column(Text, default="")

    # Spoken language for the call. Drives an explicit instruction in the
    # prompt — without one the model drifts to English mid-call when the
    # contact data is in Latin script.
    language: Mapped[str] = mapped_column(String(8), default="en")
    # Template this campaign was created from, for analytics. Null for
    # campaigns built from scratch.
    template_id: Mapped[str | None] = mapped_column(String(64), nullable=True)

    status: Mapped[CampaignStatus] = mapped_column(
        Enum(CampaignStatus), default=CampaignStatus.DRAFT
    )

    # Calling window, in each contact's *local* time. Enforced per contact
    # against their own timezone, not the server's.
    calling_hours_start: Mapped[int] = mapped_column(Integer, default=9)
    calling_hours_end: Mapped[int] = mapped_column(Integer, default=20)
    # ISO weekdays permitted (1=Mon .. 7=Sun). Default: weekdays only.
    calling_days: Mapped[list[int]] = mapped_column(JSON, default=lambda: [1, 2, 3, 4, 5])

    max_concurrent_calls: Mapped[int] = mapped_column(Integer, default=10)
    max_attempts: Mapped[int] = mapped_column(Integer, default=3)

    # --- Model selection -------------------------------------------------
    # Per campaign, not global: a reminder campaign and a negotiation campaign
    # have genuinely different needs, and forcing both onto one model means
    # overpaying for the first or under-serving the second.
    conversation_model: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_CONVERSATION_MODEL
    )
    conversation_effort: Mapped[str] = mapped_column(
        String(8), default=DEFAULT_CONVERSATION_EFFORT
    )
    extraction_model: Mapped[str] = mapped_column(
        String(64), default=DEFAULT_EXTRACTION_MODEL
    )
    extraction_effort: Mapped[str] = mapped_column(
        String(8), default=DEFAULT_EXTRACTION_EFFORT
    )

    # --- Spend control ---------------------------------------------------
    # A hard ceiling in USD on model spend. The runner pauses the campaign on
    # its own when this is crossed — a runaway loop against a list of 40,000
    # numbers should stop by itself, not when somebody notices the invoice.
    budget_usd: Mapped[float | None] = mapped_column(Float, nullable=True)
    spend_usd: Mapped[float] = mapped_column(Float, default=0.0)

    # SMS follow-up: send a summary text after each call. Requires Twilio.
    sms_followup: Mapped[bool] = mapped_column(Boolean, default=False)

    # Fired once per completed call with the extracted outcome. The one
    # integration point that needs no MCP server and no code from us.
    webhook_url: Mapped[str | None] = mapped_column(String(500), nullable=True)

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    contacts: Mapped[list["Contact"]] = relationship(back_populates="campaign")


class Contact(Base):
    __tablename__ = "contacts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)

    full_name: Mapped[str] = mapped_column(String(200))
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    timezone: Mapped[str] = mapped_column(String(64), default="America/New_York")
    attributes: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)

    status: Mapped[ContactStatus] = mapped_column(
        Enum(ContactStatus), default=ContactStatus.PENDING
    )
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    next_attempt_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    campaign: Mapped[Campaign] = relationship(back_populates="contacts")
    calls: Mapped[list["Call"]] = relationship(back_populates="contact")

    __table_args__ = (
        # The scheduler's hot query: eligible contacts for a campaign.
        Index("ix_contacts_dispatch", "campaign_id", "status", "next_attempt_at"),
    )


class Call(Base):
    __tablename__ = "calls"

    id: Mapped[str] = mapped_column(String(36), primary_key=True)
    contact_id: Mapped[str] = mapped_column(ForeignKey("contacts.id"), index=True)
    campaign_id: Mapped[str] = mapped_column(ForeignKey("campaigns.id"), index=True)

    status: Mapped[CallStatus] = mapped_column(Enum(CallStatus), default=CallStatus.DIALING)
    started_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)
    connected_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    ended_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # Provider-side identifiers, for reconciliation against phone bills and
    # for pulling recordings.
    provider_call_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    room_name: Mapped[str | None] = mapped_column(String(128), nullable=True)

    transcript: Mapped[list[dict[str, Any]]] = mapped_column(JSON, default=list)

    # Extraction results. Denormalised onto the call so the review queue and
    # dashboards can filter without parsing JSON.
    disposition: Mapped[str | None] = mapped_column(String(32), nullable=True, index=True)
    summary: Mapped[str | None] = mapped_column(Text, nullable=True)
    outcome: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    needs_human_review: Mapped[bool] = mapped_column(default=False, index=True)
    review_reason: Mapped[str | None] = mapped_column(Text, nullable=True)
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # What dispatch actually did, so a human reviewing later can see whether
    # the calendar event / record write went through.
    dispatch_result: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)

    # --- Qualification ---------------------------------------------------
    # Per-criterion ratings with their evidence, plus the derived verdict.
    # Score and band are denormalised into columns so the ranked queue can
    # sort and filter in SQL — the whole point of scoring is a list ordered
    # by who is worth talking to next, and that must not mean loading every
    # call's JSON to sort it.
    scores: Mapped[list[dict[str, Any]] | None] = mapped_column(JSON, nullable=True)
    qualification: Mapped[dict[str, Any] | None] = mapped_column(JSON, nullable=True)
    score: Mapped[int | None] = mapped_column(Integer, nullable=True, index=True)
    qualification_band: Mapped[str | None] = mapped_column(String(16), nullable=True, index=True)

    # --- Cost ledger -----------------------------------------------------
    # Actual token counts reported by the API, not estimates. Per call, because
    # "which calls are expensive" is a far more useful question than "what did
    # we spend" — a 20-minute call that went nowhere is the thing to find.
    input_tokens: Mapped[int] = mapped_column(Integer, default=0)
    output_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_read_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cache_write_tokens: Mapped[int] = mapped_column(Integer, default=0)
    cost_usd: Mapped[float] = mapped_column(Float, default=0.0)
    # Which models this specific call used. Denormalised off the campaign so a
    # cost comparison stays honest after somebody switches models mid-campaign.
    conversation_model: Mapped[str | None] = mapped_column(String(64), nullable=True)
    extraction_model: Mapped[str | None] = mapped_column(String(64), nullable=True)

    # --- Recording & SMS ---------------------------------------------------
    # Twilio recording URL for playback and QA.
    recording_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    recording_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    recording_duration: Mapped[int | None] = mapped_column(Integer, nullable=True)
    # Answering Machine Detection result from Twilio.
    amd_result: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # SMS follow-up message SID after the call.
    sms_sid: Mapped[str | None] = mapped_column(String(64), nullable=True)
    sms_status: Mapped[str | None] = mapped_column(String(16), nullable=True)

    # Simulated calls share every code path with real ones, which is the point
    # — but they must never reach the dashboard, the connect rate, or the CRM.
    # Every aggregate query filters on this.
    is_simulation: Mapped[bool] = mapped_column(Boolean, default=False, index=True)

    contact: Mapped[Contact] = relationship(back_populates="calls")


class Suppression(Base):
    """Do-not-call list. Checked before every dial, across all campaigns."""

    __tablename__ = "suppressions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    phone_e164: Mapped[str] = mapped_column(String(20), index=True)
    reason: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=utcnow)

    __table_args__ = (UniqueConstraint("phone_e164", name="uq_suppression_phone"),)


class Setting(Base):
    """Workspace-wide key/value settings.

    A single row per key, JSON-valued. Used for things a campaign can inherit
    but not everything needs its own copy of — the default model assignment,
    for one. Deliberately not a config file: these are edited from the UI at
    runtime, and a file that the app rewrites is a file that gets clobbered.
    """

    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    value: Mapped[dict[str, Any]] = mapped_column(JSON, default=dict)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), default=utcnow, onupdate=utcnow
    )


# --------------------------------------------------------------------------
# Engine / session
# --------------------------------------------------------------------------

_engine_kwargs: dict = {"echo": False, "pool_pre_ping": True}
if DATABASE_URL.startswith("sqlite"):
    # SQLite doesn't support pool_pre_ping or pool_size
    _engine_kwargs = {"echo": False}
else:
    # Postgres production: set reasonable pool limits
    _engine_kwargs["pool_size"] = 5
    _engine_kwargs["max_overflow"] = 10

engine = create_async_engine(DATABASE_URL, **_engine_kwargs)
SessionLocal = async_sessionmaker(engine, class_=AsyncSession, expire_on_commit=False)

_db_type = "PostgreSQL" if "postgresql" in DATABASE_URL else "SQLite"
logging.getLogger(__name__).info("Database: %s (%s)", _db_type, DATABASE_URL.split("@")[-1] if "@" in DATABASE_URL else DATABASE_URL)


async def init_db() -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        await conn.run_sync(_add_missing_columns)


def _add_missing_columns(conn) -> None:
    """Add columns that exist in the models but not yet in the database.

    `create_all` creates missing *tables* and silently ignores missing
    *columns*, so a schema change against an existing dev database fails at
    query time with a confusing 'no such column'. This closes that gap for the
    only migration shape that is safe to run unattended: additive, nullable or
    defaulted, never a drop or a type change.

    Anything beyond that — renames, type changes, backfills — needs Alembic
    and a human. This is not a substitute for one; it is what keeps an
    already-seeded dev database working across a pull.
    """
    inspector = inspect(conn)
    tables = set(inspector.get_table_names())

    for table in Base.metadata.sorted_tables:
        if table.name not in tables:
            continue  # create_all just made it, with every column

        present = {c["name"] for c in inspector.get_columns(table.name)}
        for column in table.columns:
            if column.name in present:
                continue

            ddl = f"ALTER TABLE {table.name} ADD COLUMN {column.name} " + column.type.compile(
                conn.dialect
            )
            literal = _default_literal(column)
            if literal is not None:
                ddl += f" DEFAULT {literal}"

            conn.execute(text(ddl))
            # Existing rows get the default; new columns are never NOT NULL
            # here, so a column without a sensible default just reads NULL and
            # the application-side `or <fallback>` handles it.
            if literal is not None:
                conn.execute(
                    text(f"UPDATE {table.name} SET {column.name} = {literal} "
                         f"WHERE {column.name} IS NULL")
                )


def _default_literal(column) -> str | None:
    """SQL literal for a column's Python-side default, or None if not scalar.

    Callable defaults (`utcnow`, `list`) and JSON containers are skipped
    deliberately — there is no portable literal for them, and every reader in
    the codebase already coerces null (`campaign.calling_days or []`).
    """
    default = getattr(column, "default", None)
    if default is None or getattr(default, "is_callable", False):
        return None

    value = getattr(default, "arg", None)
    if isinstance(value, bool):
        return "1" if value else "0"
    if isinstance(value, (int, float)):
        return str(value)
    if isinstance(value, str):
        escaped = value.replace("'", "''")
        return f"'{escaped}'"
    return None


async def get_session() -> AsyncSession:
    async with SessionLocal() as session:
        yield session
