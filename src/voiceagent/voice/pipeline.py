"""End-to-end handling of one call.

This is the integration seam the runner injects: dial → converse → persist →
extract → act → reschedule. Written against protocols rather than LiveKit
directly, so the whole path can be exercised with fakes.

Ordering matters at the end. The transcript is persisted *before* extraction
runs, so a crash in extraction never loses the call. Extraction and dispatch
then update the same row. If the process dies between them, the call is on
disk with no outcome and gets picked up by the reconciliation sweep rather
than silently disappearing.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Protocol

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..catalog import CONVERSATION, EXTRACTION, TokenUsage, resolve
from ..followup import MISSED, followup_columns, send_followups
from ..llm import ConversationLLM
from ..models import CallContext, Contact as ContactModel, Disposition, ScoreCriterion
from ..orchestrator.events import (
    CALL_ENDED,
    CALL_EXTRACTED,
    CALL_STARTED,
    CAMPAIGN_UPDATED,
    Event,
    bus,
)
from ..orchestrator.scheduler import is_terminal, next_attempt_after
from ..postcall.actions import CalendarClient, RecordsClient, SuppressionList, dispatch
from ..postcall.extract import extract_outcome
from ..scoring import qualify_outcome
from ..storage import Call, CallStatus, Campaign, CampaignStatus, Contact, ContactStatus
from ..webhooks import fire_webhook
from ..templates import language_instruction
from .session import CallControl, CallNotPlaced, CallSession, Listener, Speaker

logger = logging.getLogger(__name__)


class Telephony(Protocol):
    """Places the outbound leg and returns the media plumbing for it."""

    async def dial(
        self, *, phone_e164: str, room_name: str
    ) -> tuple[Listener, Speaker, CallControl, str]:
        """Dial and wait for answer.

        Returns (listener, speaker, control, provider_call_sid).
        Raises on busy / no-answer / rejected.
        """
        ...


class CallPipeline:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        client,
        telephony: Telephony,
        *,
        calendar: CalendarClient,
        records: RecordsClient,
        suppression: SuppressionList,
        followups: bool = True,
    ) -> None:
        self._sessions = session_factory
        self._client = client
        self._telephony = telephony
        self._calendar = calendar
        self._records = records
        self._suppression = suppression
        # Off for mock telephony: a scripted call must never text a real number.
        self._followups = followups

    async def place_call(self, contact: Contact, campaign: Campaign) -> None:
        call_id = str(uuid.uuid4())
        room_name = f"call-{call_id}"
        greeting = _greeting(contact, campaign)

        # Synthesize the greeting while the phone rings, so the person isn't
        # left in silence after picking up.
        prefetch = getattr(self._telephony, "prefetch_speech", None)
        if prefetch:
            prefetch(greeting)

        await self._create_call_row(call_id, contact, campaign, room_name)
        await bus.publish(
            Event(
                CALL_STARTED,
                {
                    "call_id": call_id,
                    "campaign_id": campaign.id,
                    "contact_id": contact.id,
                    "contact_name": contact.full_name,
                    "phone": _mask(contact.phone_e164),
                },
            )
        )

        transcript = []
        disposition = Disposition.FAILED
        # One ledger per call, shared by the conversation and the extraction
        # that follows it, so the cost we record is the cost of the whole call.
        usage = TokenUsage()

        try:
            listener, speaker, control, sid = await self._telephony.dial(
                phone_e164=contact.phone_e164, room_name=room_name
            )
        except Exception as exc:
            logger.info("Dial failed for %s: %s", contact.id, exc)
            await self._finish(
                call_id, contact, campaign, [], Disposition.NO_ANSWER, usage,
                room_name=room_name, rang=not isinstance(exc, CallNotPlaced),
            )
            return

        await self._mark_connected(call_id, sid)

        # Check AMD result — if a machine was detected, handle voicemail
        amd_result = None
        if hasattr(self._telephony, "get_call_state"):
            state = self._telephony.get_call_state(room_name)
            if state:
                amd_result = state.amd_result

        if amd_result and amd_result in (
            "machine_start", "machine_end_beep", "machine_end_silence", "fax",
            "machine",  # Telnyx AMD result
        ):
            logger.info("Voicemail detected for %s (AMD: %s)", contact.id, amd_result)
            # Leave a voicemail message via the speaker, then hang up
            voicemail_msg = greeting + (
                " We were unable to reach you. We'll try again later. Thank you."
            )
            try:
                await speaker.say(voicemail_msg)
                # Webhook transports only play what has been flushed.
                if hasattr(speaker, "flush"):
                    await speaker.flush()
            except Exception:
                logger.debug("Could not leave voicemail for %s", contact.id)
            try:
                await control.hangup()
            except Exception:
                pass
            await self._finish(
                call_id, contact, campaign, [], Disposition.VOICEMAIL, usage,
                room_name=room_name, amd_result=amd_result,
            )
            return

        try:
            llm = ConversationLLM(
                self._client,
                contact=_to_model(contact),
                context=_to_context(campaign),
                model=campaign.conversation_model,
                effort=campaign.conversation_effort,
                usage=usage,
            )
            session = CallSession(
                llm=llm,
                listener=listener,
                speaker=speaker,
                control=control,
                greeting=greeting,
                max_duration_seconds=600,
            )
            transcript = await session.run()
            disposition = Disposition.COMPLETED if transcript is not None and len(transcript) > 0 else Disposition.NO_ANSWER
        except Exception:
            logger.exception("Conversation failed for call %s", call_id)
            disposition = Disposition.FAILED

        await self._finish(
            call_id, contact, campaign, transcript, disposition, usage,
            room_name=room_name, amd_result=amd_result,
        )

    # -- persistence steps -------------------------------------------------

    async def _create_call_row(self, call_id, contact, campaign, room_name) -> None:
        async with self._sessions() as session:
            session.add(
                Call(
                    id=call_id,
                    contact_id=contact.id,
                    campaign_id=campaign.id,
                    status=CallStatus.DIALING,
                    room_name=room_name,
                )
            )
            await session.execute(
                update(Contact)
                .where(Contact.id == contact.id)
                .values(status=ContactStatus.IN_PROGRESS, attempts=Contact.attempts + 1)
            )
            await session.commit()

    async def _mark_connected(self, call_id: str, sid: str | None) -> None:
        async with self._sessions() as session:
            await session.execute(
                update(Call)
                .where(Call.id == call_id)
                .values(
                    status=CallStatus.CONNECTED,
                    connected_at=datetime.now(timezone.utc),
                    provider_call_sid=sid,
                )
            )
            await session.commit()

    async def _finish(
        self, call_id, contact, campaign, transcript, fallback_disposition, usage,
        *, room_name: str | None = None, amd_result: str | None = None,
        rang: bool = True,
    ) -> None:
        now = datetime.now(timezone.utc)
        usage = usage if usage is not None else TokenUsage()

        # Retrieve recording info from the Twilio call state before cleanup
        recording_url = None
        recording_sid = None
        recording_duration = None
        if room_name and hasattr(self._telephony, "get_call_state"):
            state = self._telephony.get_call_state(room_name)
            if state:
                recording_url = state.recording_url
                recording_sid = state.recording_sid
                recording_duration = state.recording_duration

        # 1. Durable first. Everything after this can fail and be retried.
        async with self._sessions() as session:
            values = {
                "status": CallStatus.COMPLETED,
                "ended_at": now,
                "transcript": [t.model_dump(mode="json") for t in transcript],
            }
            if recording_url:
                values["recording_url"] = recording_url
                values["recording_sid"] = recording_sid
                values["recording_duration"] = recording_duration
            if amd_result:
                values["amd_result"] = amd_result

            await session.execute(
                update(Call).where(Call.id == call_id).values(**values)
            )
            await session.commit()

        await bus.publish(
            Event(CALL_ENDED, {"call_id": call_id, "turns": len(transcript)})
        )

        # 2. Extract.
        context = _to_context(campaign)
        outcome = await extract_outcome(
            self._client,
            contact=_to_model(contact),
            context=context,
            turns=transcript,
            call_started_at_iso=now.isoformat(),
            model=campaign.extraction_model,
            effort=campaign.extraction_effort,
            usage=usage,
        )
        if not transcript:
            outcome.disposition = fallback_disposition

        # 2a. Score it. Arithmetic over the model's per-criterion ratings, so
        #     the number is reproducible and can be re-derived later if the
        #     campaign's weights change.
        qualification = qualify_outcome(context, outcome) if context.scorecard else None

        # 3. Act.
        result = await dispatch(
            outcome,
            _to_model(contact),
            calendar=self._calendar,
            records=self._records,
            suppression=self._suppression,
        )

        # 4. Record the outcome, the bill, and the contact's next state.
        cost = usage.cost_usd()
        next_at = next_attempt_after(outcome.disposition, contact.attempts, now)
        if outcome.disposition is Disposition.DO_NOT_CALL:
            contact_status = ContactStatus.SUPPRESSED
        elif is_terminal(outcome.disposition):
            contact_status = ContactStatus.COMPLETED
        elif contact.attempts >= campaign.max_attempts:
            contact_status = ContactStatus.EXHAUSTED
        else:
            contact_status = ContactStatus.PENDING

        async with self._sessions() as session:
            await session.execute(
                update(Call)
                .where(Call.id == call_id)
                .values(
                    disposition=outcome.disposition.value,
                    summary=outcome.summary,
                    outcome=outcome.model_dump(mode="json"),
                    scores=[s.model_dump(mode="json") for s in outcome.scores],
                    qualification=(
                        qualification.model_dump(mode="json") if qualification else None
                    ),
                    score=qualification.score if qualification else None,
                    qualification_band=qualification.band.value if qualification else None,
                    needs_human_review=outcome.needs_human_review,
                    review_reason=outcome.review_reason or None,
                    dispatch_result={
                        "suppressed": result.suppressed,
                        "calendar_event_id": result.calendar_event_id,
                        "fields_written": result.fields_written,
                        "queued_for_review": result.queued_for_review,
                        "errors": result.errors,
                    },
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    cost_usd=cost,
                    conversation_model=resolve(campaign.conversation_model, CONVERSATION),
                    extraction_model=resolve(campaign.extraction_model, EXTRACTION),
                )
            )
            await session.execute(
                update(Contact)
                .where(Contact.id == contact.id)
                .values(status=contact_status, next_attempt_at=next_at)
            )

            # Spend is incremented in SQL rather than read-modify-written, so
            # concurrent calls finishing at the same moment don't lose each
            # other's cost — with hundreds of calls in flight that is not a
            # theoretical race.
            await session.execute(
                update(Campaign)
                .where(Campaign.id == campaign.id)
                .values(spend_usd=Campaign.spend_usd + cost)
            )
            await session.commit()

        await self._enforce_budget(campaign.id)

        await bus.publish(
            Event(
                CALL_EXTRACTED,
                {
                    "call_id": call_id,
                    "disposition": outcome.disposition.value,
                    "summary": outcome.summary,
                    "needs_review": outcome.needs_human_review,
                    "cost_usd": cost,
                },
            )
        )

        if campaign.webhook_url:
            await fire_webhook(
                campaign.webhook_url,
                {
                    "event": "call.completed",
                    "call_id": call_id,
                    "campaign_id": campaign.id,
                    "contact_id": contact.id,
                    "contact_name": contact.full_name,
                    "phone_masked": _mask(contact.phone_e164),
                    "outcome": outcome.model_dump(mode="json"),
                    "cost_usd": cost,
                    "occurred_at": now.isoformat(),
                },
            )

        # 5. Follow-up SMS / WhatsApp, on whichever channels the campaign has on.
        if rang:
            await self._send_followups(call_id, contact, campaign, outcome)

    async def _send_followups(self, call_id, contact, campaign, outcome) -> None:
        sms = bool(getattr(campaign, "sms_followup", False))
        whatsapp = bool(getattr(campaign, "whatsapp_followup", False))
        if not self._followups or not (sms or whatsapp):
            return

        if outcome.disposition in MISSED:
            # One "sorry we missed you" per contact, not one per retry.
            async with self._sessions() as session:
                earlier = await session.scalar(
                    select(func.count())
                    .select_from(Call)
                    .where(Call.contact_id == contact.id, Call.id != call_id)
                )
            if earlier:
                return

        results = await send_followups(
            to=contact.phone_e164,
            call_id=call_id,
            contact_name=contact.full_name,
            campaign_name=campaign.name,
            outcome=outcome,
            sms=sms,
            whatsapp=whatsapp,
        )
        if not results:
            return
        async with self._sessions() as session:
            await session.execute(
                update(Call).where(Call.id == call_id).values(**followup_columns(results))
            )
            await session.commit()

    async def _enforce_budget(self, campaign_id: str) -> None:
        """Pause a campaign that has spent its cap.

        Checked after the write rather than before the call, so the cap is a
        stop rather than a gate — a call already in flight always finishes.
        Hanging up on someone mid-sentence to save four cents is not a
        behaviour worth having.
        """
        async with self._sessions() as session:
            campaign = await session.get(Campaign, campaign_id)
            if (
                campaign is None
                or campaign.budget_usd is None
                or campaign.status is not CampaignStatus.RUNNING
                or (campaign.spend_usd or 0.0) < campaign.budget_usd
            ):
                return

            campaign.status = CampaignStatus.PAUSED
            await session.commit()

        logger.warning("Campaign %s paused: spend cap reached", campaign_id)
        await bus.publish(
            Event(
                CAMPAIGN_UPDATED,
                {"campaign_id": campaign_id, "paused_reason": "budget_reached"},
            )
        )


# --------------------------------------------------------------------------
# Mapping helpers (ORM row -> plain model used by prompts/extraction)
# --------------------------------------------------------------------------


def _to_model(contact: Contact) -> ContactModel:
    return ContactModel(
        contact_id=contact.id,
        full_name=contact.full_name,
        phone_e164=contact.phone_e164,
        timezone=contact.timezone,
        attributes={k: str(v) for k, v in (contact.attributes or {}).items()},
    )


def _to_criteria(raw) -> list[ScoreCriterion]:
    """Campaign scorecard rows into criteria, dropping anything malformed.

    A bad criterion costs the campaign its scoring, never its ability to dial.
    """
    criteria: list[ScoreCriterion] = []
    for entry in raw or []:
        try:
            criteria.append(ScoreCriterion.model_validate(entry))
        except Exception:  # noqa: BLE001
            logger.warning("Skipping unusable scorecard entry on campaign: %r", entry)
    return criteria


def _to_context(campaign: Campaign) -> CallContext:
    return CallContext(
        campaign_id=campaign.id,
        goal=campaign.goal,
        scorecard=_to_criteria(campaign.scorecard),
        fields_to_collect=campaign.fields_to_collect or [],
        constraints=campaign.constraints or [],
        extra_instructions=campaign.extra_instructions or "",
        language_instruction=language_instruction(campaign.language or "en"),
    )


def _greeting(contact: Contact, campaign: Campaign) -> str:
    """Render the campaign's opening line.

    Unknown placeholders are left as literal text rather than raising — a
    typo'd `{customer}` in the UI must not take the call down at connect time.
    """
    first_name = contact.full_name.split()[0] if contact.full_name else "there"
    template = campaign.greeting or (
        "Hi {first_name}, this is an AI assistant calling on behalf of "
        "{campaign_name}. Do you have a moment?"
    )
    try:
        return template.format(
            first_name=first_name,
            full_name=contact.full_name,
            campaign_name=campaign.name,
        )
    except (KeyError, IndexError, ValueError):
        logger.warning("Greeting template for campaign %s has bad placeholders", campaign.id)
        return template


def _mask(phone: str) -> str:
    """Never put a full number on the event bus — it ends up in browser logs."""
    return phone[:-4].rstrip() + "••••" if len(phone) > 4 else "••••"
