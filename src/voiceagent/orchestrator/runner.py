"""Campaign runner: decides who gets dialled next, and how many at once.

One runner per process; several processes may run against the same database.
Contacts are therefore claimed with a conditional UPDATE — a worker only wins
a contact if its status is still PENDING when the write lands. Two workers
racing for the same row means one of them updates zero rows and moves on.

The runner does not place calls itself. It hands a claimed contact to an
injected `place_call` coroutine, which keeps this loop testable without
LiveKit, a phone line, or an Anthropic key.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Awaitable, Callable
from datetime import datetime, timezone

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..storage import Campaign, CampaignStatus, Contact, ContactStatus, Suppression
from .events import CAMPAIGN_UPDATED, Event, bus
from .scheduler import OK, CallingWindow, check_eligibility, next_window_open

logger = logging.getLogger(__name__)

PlaceCall = Callable[[Contact, Campaign], Awaitable[None]]

# How long to sleep when there's nothing eligible to dial. Short enough that
# a campaign resuming at 9am local starts promptly, long enough not to spin.
_IDLE_SLEEP_SECONDS = 15


class CampaignRunner:
    def __init__(
        self,
        session_factory: async_sessionmaker,
        place_call: PlaceCall,
        *,
        poll_batch_size: int = 50,
    ) -> None:
        self._sessions = session_factory
        self._place_call = place_call
        self._batch_size = poll_batch_size
        self._active: dict[str, set[asyncio.Task]] = {}
        self._stopping = asyncio.Event()

    # -- lifecycle ---------------------------------------------------------

    async def run_forever(self) -> None:
        logger.info("Campaign runner started")
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
                    next_attempt_at=contact.next_attempt_at,
                    is_suppressed=contact.phone_e164 in suppressed,
                )

                if reason != OK:
                    await self._defer(session, contact, reason, window, now)
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
