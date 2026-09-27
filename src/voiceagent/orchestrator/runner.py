"""Campaign runner: decides who gets dialled next, and how many at once.

One runner per process; several processes may run against the same database.
Contacts are therefore claimed with a conditional UPDATE — a worker only wins
a contact if its status is still PENDING when the write lands. Two workers
racing for the same row means one of them updates zero rows and moves on.

The runner does not place calls itself. It hands a claimed contact to an
injected `place_call` coroutine, which keeps this loop testable without
LiveKit, a phone line, or an Anthropic key.

Pre-call heads-up: on a campaign that asks for one, a contact who becomes
due is sent a short text first ("we'll call you in 10 minutes") and is
dialled on a later tick, once the lead time has passed. An unknown number
that rings unannounced is screened out; one that was expected gets answered.
One heads-up per 12 hours, however many retries follow it.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta, timezone

from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from .. import followup
from ..followup import SendResult, compose_precall
from ..storage import Call, CallStatus, Campaign, CampaignStatus, Contact, ContactStatus, Suppression
from .events import CAMPAIGN_UPDATED, Event, bus
from .scheduler import OK, CallingWindow, check_eligibility, next_window_open

logger = logging.getLogger(__name__)

PlaceCall = Callable[[Contact, Campaign], Awaitable[None]]
SendPrecall = Callable[[str, str, str], Awaitable[SendResult]]

# A retry inside this long after a heads-up is dialled without another one:
# one text announcing a call is useful, a text before every attempt is spam.
PRECALL_REPEAT_AFTER = timedelta(hours=12)

# How long to sleep when there's nothing eligible to dial. Short enough that
# a campaign resuming at 9am local starts promptly, long enough not to spin.
_IDLE_SLEEP_SECONDS = 15

# A contact IN_PROGRESS with no call started for this long is not on a call:
# the process that was dialling it went away (a redeploy, a crash). Longer
# than any call runs (the session caps them at 10 minutes of talk) plus ring.
STALE_AFTER = timedelta(minutes=10)


def _aware(moment: datetime | None) -> datetime | None:
    # SQLite hands back naive datetimes for timezone-aware columns.
    if moment is None:
        return None
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


async def recover_stale_contacts(session_factory: async_sessionmaker, *, now: datetime | None = None) -> int:
    """Put contacts stranded IN_PROGRESS by a restart back in the queue.

    A redeploy mid-call leaves the contact IN_PROGRESS forever: the runner
    only picks up PENDING, so that person is never called again and the
    campaign never finishes. Run at start-up, before the first tick. A
    contact counts as stranded when its latest call started more than
    STALE_AFTER ago — or it has no call and was created that long ago. The
    call rows left DIALING or CONNECTED are closed as failed. The attempt
    already counted stays counted; max_attempts still bounds the retries.

    Returns how many contacts were reset.
    """
    now = now or datetime.now(timezone.utc)
    cutoff = now - STALE_AFTER
    async with session_factory() as session:
        contacts = (
            await session.execute(
                select(Contact.id, Contact.created_at).where(Contact.status == ContactStatus.IN_PROGRESS)
            )
        ).all()
        if not contacts:
            return 0
        ids = [row.id for row in contacts]
        latest = dict(
            (
                await session.execute(
                    select(Call.contact_id, func.max(Call.started_at))
                    .where(Call.contact_id.in_(ids))
                    .group_by(Call.contact_id)
                )
            ).all()
        )
        stale = [
            row.id
            for row in contacts
            if (_aware(latest.get(row.id)) or _aware(row.created_at) or now) <= cutoff
        ]
        if stale:
            await session.execute(
                update(Contact)
                .where(Contact.id.in_(stale), Contact.status == ContactStatus.IN_PROGRESS)
                .values(status=ContactStatus.PENDING)
            )
            await session.execute(
                update(Call)
                .where(
                    Call.contact_id.in_(stale),
                    Call.status.in_([CallStatus.DIALING, CallStatus.CONNECTED]),
                    Call.started_at <= cutoff,
                )
                .values(
                    status=CallStatus.FAILED,
                    ended_at=now,
                    summary="Interrupted: the server restarted during this call.",
                )
            )
            await session.commit()

    if stale:
        logger.warning("Recovered %d contacts left in progress by a restart", len(stale))
    else:
        logger.info("Recovered 0 contacts: none were stranded in progress")
    return len(stale)


class CampaignRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        place_call: PlaceCall,
        *,
        poll_batch_size: int = 50,
        send_precall: SendPrecall | None = None,
        precall: bool = True,
    ) -> None:
        self._sessions = session_factory
        self._place_call = place_call
        self._batch_size = poll_batch_size
        # None sends through followup.send_precall, looked up when used.
        self._send_precall = send_precall
        # Off for mock telephony: scripted calls go to made-up people.
        self._precall = precall
        self._active: dict[str, set[asyncio.Task]] = {}
        self._stopping = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------

    async def run_forever(self) -> None:
        logger.info("Campaign runner started")
        try:
            await recover_stale_contacts(self._sessions)
        except Exception:
            # Recovery is housekeeping; a failure here must not stop dialling.
            logger.exception("Stale-contact recovery failed")
        while not self._stopping.is_set():
            try:
                dispatched = await self._tick()
            except Exception:
                # A failure in one tick must not kill the loop — the whole
                # dialler stopping because one database call timed out is a
                # far worse outcome than one delayed batch.
                logger.exception("Runner tick failed")
                dispatched = 0

            if dispatched == 0:
                try:
                    await asyncio.wait_for(
                        self._stopping.wait(), timeout=_IDLE_SLEEP_SECONDS
                    )
                except asyncio.TimeoutError:
                    pass

        await self._drain()
        logger.info("Campaign runner stopped")

    def stop(self) -> None:
        self._stopping.set()

    async def _drain(self) -> None:
        """Let in-flight calls finish. Never hang up on someone mid-sentence."""
        tasks = [t for tasks in self._active.values() for t in tasks]
        if tasks:
            logger.info("Draining %d in-flight calls", len(tasks))
            await asyncio.gather(*tasks, return_exceptions=True)

    # -- dispatch ----------------------------------------------------------

    async def _tick(self) -> int:
        async with self._sessions() as session:
            campaigns = (
                await session.execute(
                    select(Campaign).where(Campaign.status == CampaignStatus.RUNNING)
                )
            ).scalars().all()

        total = 0
        for campaign in campaigns:
            total += await self._dispatch_campaign(campaign)
        return total

    def _in_flight(self, campaign_id: str) -> int:
        tasks = self._active.get(campaign_id)
        if not tasks:
            return 0
        # Reap finished tasks lazily rather than keeping a callback registry.
        done = {t for t in tasks if t.done()}
        tasks -= done
        return len(tasks)

    async def _dispatch_campaign(self, campaign: Campaign) -> int:
        capacity = campaign.max_concurrent_calls - self._in_flight(campaign.id)
        if capacity <= 0:
            return 0

        now = datetime.now(timezone.utc)
        window = CallingWindow.from_campaign(
            campaign.calling_hours_start,
            campaign.calling_hours_end,
            campaign.calling_days,
        )

        dispatched = 0
        async with self._sessions() as session:
            candidates = (
                await session.execute(
                    select(Contact)
                    .where(
                        Contact.campaign_id == campaign.id,
                        Contact.status == ContactStatus.PENDING,
                    )
                    .limit(self._batch_size)
                )
            ).scalars().all()

            if not candidates:
                return 0

            # One query for the whole batch rather than per contact.
            numbers = {c.phone_e164 for c in candidates}
            suppressed = set(
                (
                    await session.execute(
                        select(Suppression.phone_e164).where(
                            Suppression.phone_e164.in_(numbers)
                        )
                    )
                ).scalars().all()
            )

            for contact in candidates:
                if dispatched >= capacity:
                    break

                reason = check_eligibility(
                    tz_name=contact.timezone,
                    window=window,
                    now_utc=now,
                    attempts=contact.attempts,
                    max_attempts=campaign.max_attempts,
                    next_attempt_at=_aware(contact.next_attempt_at),
                    is_suppressed=contact.phone_e164 in suppressed,
                )

                if reason != OK:
                    await self._defer(session, contact, reason, window, now)
                    continue

                if self._needs_heads_up(campaign, contact, now):
                    await self._send_heads_up(session, contact, campaign, now)
                    continue

                # Conditional claim: only wins if still PENDING.
                claimed = await session.execute(
                    update(Contact)
                    .where(
                        Contact.id == contact.id,
                        Contact.status == ContactStatus.PENDING,
                    )
                    .values(status=ContactStatus.QUEUED)
                )
                if claimed.rowcount == 0:
                    continue  # another worker got there first

                task = asyncio.create_task(self._run_call(contact, campaign))
                self._active.setdefault(campaign.id, set()).add(task)
                dispatched += 1

            await session.commit()

        if dispatched:
            await bus.publish(
                Event(
                    CAMPAIGN_UPDATED,
                    {"campaign_id": campaign.id, "dispatched": dispatched},
                )
            )
        return dispatched

    def _needs_heads_up(self, campaign: Campaign, contact: Contact, now: datetime) -> bool:
        if not (self._precall and getattr(campaign, "precall_enabled", False)):
            return False
        sent_at = _aware(getattr(contact, "precall_sent_at", None))
        return sent_at is None or now - sent_at >= PRECALL_REPEAT_AFTER

    async def _send_heads_up(self, session, contact: Contact, campaign: Campaign, now: datetime) -> None:
        """Text the contact that a call is coming, and hold the call for the lead time.

        Claimed first with a conditional write, like a dial: two workers
        racing for the same contact send one message, not two. The contact
        stays PENDING throughout, so the call is an ordinary dispatch on a
        later tick. A heads-up that fails to send holds nothing back — the
        call goes ahead on the next tick, and the failure is on the contact.
        """
        lead = timedelta(minutes=max(2, min(240, campaign.precall_lead_minutes or 10)))
        previous = contact.precall_sent_at
        claimed = await session.execute(
            update(Contact)
            .where(
                Contact.id == contact.id,
                Contact.status == ContactStatus.PENDING,
                Contact.precall_sent_at.is_(None) if previous is None else Contact.precall_sent_at == previous,
            )
            .values(precall_sent_at=now, precall_status="sending", next_attempt_at=now + lead)
        )
        if claimed.rowcount == 0:
            return  # another worker is sending it

        text = compose_precall(
            campaign.precall_message,
            contact_name=contact.full_name,
            company=campaign.name,
            minutes=int(lead.total_seconds() // 60),
        )
        send = self._send_precall or followup.send_precall
        channel = campaign.precall_channel or followup.SMS
        try:
            result = await send(channel, contact.phone_e164, text)
            status = result.status
        except Exception:  # noqa: BLE001 - a heads-up never costs the call
            logger.exception("Heads-up for contact %s failed", contact.id)
            status = "failed"

        values: dict = {"precall_status": status[:16]}
        if status == "failed":
            values["next_attempt_at"] = None
        await session.execute(update(Contact).where(Contact.id == contact.id).values(**values))
        # Keep the in-memory row in step with what was written, since the
        # session is committed with it at the end of this pass.
        contact.precall_sent_at = now
        contact.precall_status = values["precall_status"]
        contact.next_attempt_at = values.get("next_attempt_at", now + lead)
        logger.info("Heads-up (%s) for contact %s: %s", channel, contact.id, status)

    async def _defer(self, session, contact: Contact, reason: str, window, now) -> None:
        """Park an ineligible contact so we stop reconsidering it every tick."""
        from .scheduler import BACKOFF, EXHAUSTED, OUTSIDE_HOURS, SUPPRESSED

        if reason == SUPPRESSED:
            contact.status = ContactStatus.SUPPRESSED
        elif reason == EXHAUSTED:
            contact.status = ContactStatus.EXHAUSTED
        elif reason == OUTSIDE_HOURS:
            contact.next_attempt_at = next_window_open(contact.timezone, window, now)
        elif reason == BACKOFF:
            pass  # next_attempt_at is already in the future
        else:
            # Unknown timezone or similar data problem — hold for a human.
            contact.status = ContactStatus.FAILED
        session.add(contact)

    async def _run_call(self, contact: Contact, campaign: Campaign) -> None:
        try:
            await self._place_call(contact, campaign)
        except Exception:
            logger.exception("Call failed for contact %s", contact.id)
            async with self._sessions() as session:
                await session.execute(
                    update(Contact)
                    .where(Contact.id == contact.id)
                    .values(status=ContactStatus.PENDING, attempts=Contact.attempts + 1)
                )
                await session.commit()
