"""Act on an extracted outcome.

Deliberately boring: this is a dispatch table, not an agent. By the time we get
here the model has already done the judgement work, and re-introducing an LLM
to decide "should I create the event" only adds a way to get it wrong.

Ordering is not arbitrary. Suppression runs first and unconditionally — an
opt-out must be honoured even when everything else about the call failed, and
even when the record is flagged for review. Everything else is gated behind
the review flag.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Protocol

from ..models import CallOutcome, Contact, Disposition

logger = logging.getLogger(__name__)


# --------------------------------------------------------------------------
# Integration points — implement these against your systems.
# --------------------------------------------------------------------------


class CalendarClient(Protocol):
    async def create_event(
        self,
        *,
        starts_at_local: str,
        timezone: str,
        duration_minutes: int,
        subject: str,
        notes: str,
        attendee_name: str,
    ) -> str:
        """Create the event, return its id."""
        ...


class RecordsClient(Protocol):
    async def log_call(self, *, contact_id: str, outcome: CallOutcome) -> None: ...

    async def upsert_fields(self, *, contact_id: str, fields: dict[str, str]) -> None: ...


class SuppressionList(Protocol):
    async def suppress(self, *, contact_id: str, reason: str) -> None: ...


# --------------------------------------------------------------------------
# Dispatch
# --------------------------------------------------------------------------


@dataclass
class DispatchResult:
    suppressed: bool = False
    calendar_event_id: str | None = None
    fields_written: int = 0
    queued_for_review: bool = False
    errors: list[str] = field(default_factory=list)


async def dispatch(
    outcome: CallOutcome,
    contact: Contact,
    *,
    calendar: CalendarClient,
    records: RecordsClient,
    suppression: SuppressionList,
) -> DispatchResult:
    result = DispatchResult()

    # 1. Opt-out. Unconditional, and before anything else — a person who asked
    #    not to be called again must be suppressed even if the rest of the
    #    record is unusable. This is the one action we never gate.
    if outcome.disposition is Disposition.DO_NOT_CALL:
        try:
            await suppression.suppress(
                contact_id=contact.contact_id, reason="Requested during call."
            )
            result.suppressed = True
        except Exception as exc:
            # Escalate loudly: a failed suppression means we may call them again.
            logger.exception("SUPPRESSION FAILED for %s", contact.contact_id)
            result.errors.append(f"suppression: {exc}")
            result.queued_for_review = True

    # 2. Always log the call itself, whatever happened. This is the audit
    #    trail and it should exist even for failures.
    try:
        await records.log_call(contact_id=contact.contact_id, outcome=outcome)
    except Exception as exc:
        logger.exception("Call logging failed for %s", contact.contact_id)
        result.errors.append(f"log_call: {exc}")

    # 3. Everything past this point writes data the model inferred. If it
    #    wasn't confident, a human looks before we touch anything.
    if outcome.needs_human_review:
        logger.info(
            "Holding writes for %s pending review: %s",
            contact.contact_id,
            outcome.review_reason,
        )
        result.queued_for_review = True
        return result

    if outcome.appointment is not None:
        appt = outcome.appointment
        try:
            result.calendar_event_id = await calendar.create_event(
                starts_at_local=appt.starts_at_local,
                timezone=appt.timezone,
                duration_minutes=appt.duration_minutes,
                subject=appt.subject,
                notes=appt.notes,
                attendee_name=contact.full_name,
            )
        except Exception as exc:
            logger.exception("Calendar create failed for %s", contact.contact_id)
            result.errors.append(f"calendar: {exc}")
            result.queued_for_review = True

    if outcome.collected:
        fields = {f.name: f.value for f in outcome.collected}
        try:
            await records.upsert_fields(contact_id=contact.contact_id, fields=fields)
            result.fields_written = len(fields)
        except Exception as exc:
            logger.exception("Field upsert failed for %s", contact.contact_id)
            result.errors.append(f"upsert: {exc}")
            result.queued_for_review = True

    return result
