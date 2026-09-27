"""Why a campaign is or isn't dialling right now.

"No campaign I created is calling" had four different causes, and the
console showed none of them: no phone line configured, no model provider,
every contact outside its calling window, or nobody left to call. This
module turns the campaign row, its contacts and the deployment's config into
one state and one sentence — the answer to "why isn't it calling" — plus the
blockers that must be fixed before it can.

Read-only and cheap: one grouped count and one bounded read of pending
contacts. The eligibility rules are the runner's own (scheduler.py), so the
answer here is the decision the dialler would make, not an approximation.
"""

from __future__ import annotations

import os
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import func, select

from .. import providers
from ..storage import Campaign, CampaignStatus, Contact, ContactStatus
from .scheduler import BACKOFF, OK, OUTSIDE_HOURS, CallingWindow, check_eligibility, next_window_open

# Pending contacts looked at to find the next window. The earliest opening
# among a few hundred is the campaign's in practice.
_SCAN_LIMIT = 500


def telephony_problem() -> str | None:
    """Why no real call can be placed, or None when a phone line is set up."""
    mode = os.getenv("TELEPHONY", "mock").strip().lower()
    if mode == "twilio":
        missing = [
            name
            for name in ("TWILIO_ACCOUNT_SID", "TWILIO_AUTH_TOKEN", "TWILIO_PHONE_NUMBER")
            if not os.getenv(name, "").strip()
        ]
        if missing:
            return f"No telephony configured: set {', '.join(missing)} to call through Twilio."
        return None
    if mode == "telnyx":
        if not (os.getenv("TELNYX_API_KEY") and os.getenv("TELNYX_PHONE_NUMBER")):
            return "No telephony configured: set TELNYX_API_KEY and TELNYX_PHONE_NUMBER."
        return None
    if mode == "livekit":
        if not (os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_URL")):
            return "No telephony configured: set LIVEKIT_URL and LIVEKIT_API_KEY."
        return None
    return "No telephony configured: TELEPHONY is 'mock', so no real calls are placed. Set up Twilio."


async def blockers(session, campaign: Campaign, total_contacts: int) -> list[str]:
    """What must be fixed before this campaign can place a real call."""
    found: list[str] = []
    problem = telephony_problem()
    if problem:
        found.append(problem)
    provider = await providers.provider_for(
        getattr(campaign, "conversation_provider_id", None), providers.CONVERSATION_ROLE, session
    )
    if provider is None:
        found.append("No model provider: add one on the AI models page.")
    if total_contacts == 0:
        found.append("No contacts to call: add some on the Contacts step.")
    return found


def _when(moment: datetime, tz_name: str) -> str:
    try:
        local = moment.astimezone(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        local, tz_name = moment.astimezone(timezone.utc), "UTC"
    return f"{local.strftime('%a %H:%M')} ({tz_name})"


async def dialer_status(session, campaign: Campaign, now: datetime | None = None) -> dict:
    """`{state, reason, next_window_start, pending, in_progress, done, failed, blockers}`."""
    now = now or datetime.now(timezone.utc)
    counts = dict(
        (
            await session.execute(
                select(Contact.status, func.count())
                .where(Contact.campaign_id == campaign.id)
                .group_by(Contact.status)
            )
        ).all()
    )
    pending = counts.get(ContactStatus.PENDING, 0) + counts.get(ContactStatus.QUEUED, 0)
    in_progress = counts.get(ContactStatus.IN_PROGRESS, 0)
    done = counts.get(ContactStatus.COMPLETED, 0) + counts.get(ContactStatus.EXHAUSTED, 0)
    failed = counts.get(ContactStatus.FAILED, 0)
    # Placeholder rows for test calls and rehearsals are SUPPRESSED and never
    # dialled; they are not "contacts to call".
    callable_total = pending + in_progress + done + failed

    found = await blockers(session, campaign, callable_total)
    result = {
        "state": "",
        "reason": "",
        "next_window_start": None,
        "pending": pending,
        "in_progress": in_progress,
        "done": done,
        "failed": failed,
        "blockers": found,
    }

    def say(state: str, reason: str, next_start: datetime | None = None) -> dict:
        result.update(state=state, reason=reason, next_window_start=next_start)
        return result

    status = campaign.status
    if status is CampaignStatus.DRAFT:
        if found:
            return say("draft", "Draft. Before launching: " + " ".join(found))
        return say("draft", "Draft. Ready to launch.")
    if status is CampaignStatus.COMPLETED:
        return say("completed", "This campaign is complete; nobody else will be called.")
    if status is CampaignStatus.PAUSED:
        budget = campaign.budget_usd
        if budget is not None and (campaign.spend_usd or 0.0) >= budget:
            return say("paused", f"Paused: it reached its ${budget:.2f} spend cap. Raise the cap to resume.")
        return say("paused", "Paused. Resume it to carry on calling.")

    # Running.
    if found:
        return say("blocked", "Not calling: " + " ".join(found))
    if pending == 0:
        if in_progress:
            return say("dialing", f"{in_progress} call{'s' if in_progress != 1 else ''} in progress; nobody else is waiting.")
        return say("completed", "Everyone has been called. Mark the campaign complete when you're ready.")

    window = CallingWindow.from_campaign(
        campaign.calling_hours_start, campaign.calling_hours_end, campaign.calling_days or []
    )
    contacts = (
        await session.execute(
            select(Contact.timezone, Contact.attempts, Contact.next_attempt_at)
            .where(Contact.campaign_id == campaign.id, Contact.status == ContactStatus.PENDING)
            .limit(_SCAN_LIMIT)
        )
    ).all()
    if not contacts:  # only QUEUED: being dialled this moment
        return say("dialing", "Dialling now.")

    earliest: tuple[datetime, str, str] | None = None
    for tz_name, attempts, next_attempt_at in contacts:
        if next_attempt_at is not None and next_attempt_at.tzinfo is None:
            next_attempt_at = next_attempt_at.replace(tzinfo=timezone.utc)
        reason = check_eligibility(
            tz_name=tz_name,
            window=window,
            now_utc=now,
            attempts=attempts,
            max_attempts=campaign.max_attempts,
            next_attempt_at=next_attempt_at,
            is_suppressed=False,
        )
        if reason == OK:
            return say("dialing", "Dialling: contacts are due and inside their calling hours.")
        if reason == BACKOFF and next_attempt_at is not None:
            candidate = (next_attempt_at, tz_name, "retry")
        elif reason == OUTSIDE_HOURS:
            candidate = (next_window_open(tz_name, window, now), tz_name, "window")
        else:
            continue
        if earliest is None or candidate[0] < earliest[0]:
            earliest = candidate

    if earliest is None:
        return say("waiting_window", "Waiting: no pending contact can be called yet.")
    moment, tz_name, why = earliest
    if why == "retry":
        return say("waiting_window", f"Waiting to retry — next attempt {_when(moment, tz_name)}", moment)
    return say("waiting_window", f"Outside calling hours — next window {_when(moment, tz_name)}", moment)
