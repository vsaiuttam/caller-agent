"""Insert SYNTHETIC call records so every UI state is visible without an API key.

⚠️ These are fabricated rows written straight to the database — no calls were
placed and no model produced these transcripts. They exist purely so you can
evaluate the interface before wiring up telephony. Delete voiceagent.db to
clear them.

    python seed_demo_calls.py
"""

from __future__ import annotations

import asyncio
import uuid
from datetime import datetime, timedelta, timezone

from sqlalchemy import select

from src.voiceagent.catalog import TokenUsage
from src.voiceagent.storage import (
    Call,
    CallStatus,
    Campaign,
    Contact,
    ContactStatus,
    SessionLocal,
    Suppression,
    engine,
    init_db,
)


def turn(role: str, text: str, offset: int, base: datetime) -> dict:
    return {
        "role": role,
        "text": text,
        "started_at": (base + timedelta(seconds=offset)).isoformat(),
    }


def build_scenarios(base: datetime) -> list[dict]:
    """One scenario per UI state worth looking at."""
    return [
        # 1. Clean success — appointment booked, everything written.
        {
            "disposition": "completed",
            "summary": (
                "Confirmed the existing appointment no longer worked and rescheduled to "
                "Tuesday at 2pm. Collected a contact email for the confirmation."
            ),
            "needs_review": False,
            "transcript": [
                ("assistant", "Hi Dana, this is an AI assistant calling on behalf of Appointment confirmations. Do you have a moment?"),
                ("user", "Yeah, sure, I've got a minute."),
                ("assistant", "Great. I'm calling about your service appointment this Thursday at ten. Does that still work for you?"),
                ("user", "Actually no, Tuesday afternoon would be much better if you have anything."),
                ("assistant", "I can do Tuesday. Would two o'clock suit?"),
                ("user", "Two o'clock is perfect."),
                ("assistant", "Booked. What's the best email for the confirmation?"),
                ("user", "dana.whitfield at gmail dot com."),
                ("assistant", "Got it. You're all set for Tuesday at two. Thanks for your time, and have a great day."),
            ],
            "outcome": {
                "disposition": "completed",
                "summary": "Rescheduled to Tuesday 2pm and captured contact email.",
                "collected": [
                    {"name": "Whether the existing appointment still works", "value": "No — Thursday 10am did not work", "verbatim": True},
                    {"name": "Preferred day and time if rescheduling", "value": "Tuesday 2:00 PM", "verbatim": True},
                    {"name": "Best contact email for the confirmation", "value": "dana.whitfield@gmail.com", "verbatim": True},
                ],
                "appointment": {
                    "starts_at_local": "2026-08-18T14:00:00",
                    "timezone": "America/Los_Angeles",
                    "duration_minutes": 60,
                    "subject": "Service appointment — Dana Whitfield",
                    "notes": "Rescheduled from Thursday 10am at customer request.",
                },
                "needs_human_review": False,
                "review_reason": "",
            },
            "dispatch": {
                "suppressed": False,
                "calendar_event_id": "mock-event-9f21c4a8",
                "fields_written": 3,
                "queued_for_review": False,
                "errors": [],
            },
            "duration": 74,
        },
        # 2. Ambiguous time — held for review, nothing written.
        {
            "disposition": "partial",
            "summary": (
                "Wanted to move the appointment but gave an ambiguous time. Said "
                "'next Thursday' during a week where that could mean two different dates."
            ),
            "needs_review": True,
            "review_reason": "Could not confidently resolve 'next Thursday' — the call was placed on a Thursday, so it may mean tomorrow week or the day itself.",
            "transcript": [
                ("assistant", "Hi Marcus, this is an AI assistant calling on behalf of Appointment confirmations. Do you have a moment?"),
                ("user", "Go ahead."),
                ("assistant", "I'm calling about your appointment on the twentieth. Does that still work?"),
                ("user", "Move it to next Thursday if you can."),
                ("assistant", "I'll get that noted. Is the morning or afternoon better?"),
                ("user", "Morning. Look, I have to run, sorry."),
                ("assistant", "No problem at all. Thanks for your time, and goodbye."),
            ],
            "outcome": {
                "disposition": "partial",
                "summary": "Requested a move to 'next Thursday' morning; exact date unresolved.",
                "collected": [
                    {"name": "Whether the existing appointment still works", "value": "No — wants to move it", "verbatim": True},
                    {"name": "Preferred day and time if rescheduling", "value": "Thursday morning (date ambiguous)", "verbatim": False},
                ],
                "appointment": None,
                "needs_human_review": True,
                "review_reason": "Could not confidently resolve 'next Thursday' — the call was placed on a Thursday, so it may mean tomorrow week or the day itself.",
            },
            "dispatch": {
                "suppressed": False,
                "calendar_event_id": None,
                "fields_written": 0,
                "queued_for_review": True,
                "errors": [],
            },
            "duration": 51,
        },
        # 3. Opt-out — suppressed immediately, not gated behind review.
        {
            "disposition": "do_not_call",
            "summary": "Asked to be removed from the calling list. Suppressed across all campaigns.",
            "needs_review": False,
            "transcript": [
                ("assistant", "Hi Priya, this is an AI assistant calling on behalf of Appointment confirmations. Do you have a moment?"),
                ("user", "How did you get this number? Please take me off your list."),
                ("assistant", "Of course — I've removed you, and you won't get any further calls from us. Sorry for the interruption, and goodbye."),
            ],
            "outcome": {
                "disposition": "do_not_call",
                "summary": "Requested removal from the list.",
                "collected": [],
                "appointment": None,
                "needs_human_review": False,
                "review_reason": "",
            },
            "dispatch": {
                "suppressed": True,
                "calendar_event_id": None,
                "fields_written": 0,
                "queued_for_review": False,
                "errors": [],
            },
            "duration": 19,
        },
        # 4. Voicemail — will be retried tomorrow.
        {
            "disposition": "voicemail",
            "summary": "Reached voicemail. No message left; scheduled for retry.",
            "needs_review": False,
            "transcript": [],
            "outcome": {
                "disposition": "voicemail",
                "summary": "Reached voicemail.",
                "collected": [],
                "appointment": None,
                "needs_human_review": False,
                "review_reason": "",
            },
            "dispatch": {
                "suppressed": False,
                "calendar_event_id": None,
                "fields_written": 0,
                "queued_for_review": False,
                "errors": [],
            },
            "duration": None,
        },
        # 5. Downstream failure — extraction fine, calendar write failed.
        {
            "disposition": "completed",
            "summary": "Confirmed the existing appointment. Calendar write failed and was queued for review.",
            "needs_review": True,
            "review_reason": "Calendar API returned 503 during dispatch; the outcome is correct but nothing was written.",
            "transcript": [
                ("assistant", "Hi Alina, this is an AI assistant calling on behalf of Appointment confirmations. Do you have a moment?"),
                ("user", "Yes, briefly."),
                ("assistant", "Just confirming your appointment on the nineteenth at eleven. Does that still work?"),
                ("user", "That's fine, keep it."),
                ("assistant", "Perfect, you're confirmed. Thanks for your time, and have a good day."),
            ],
            "outcome": {
                "disposition": "completed",
                "summary": "Existing appointment confirmed, no changes needed.",
                "collected": [
                    {"name": "Whether the existing appointment still works", "value": "Yes — keeping the 19th at 11am", "verbatim": True},
                ],
                "appointment": None,
                "needs_human_review": True,
                "review_reason": "Calendar API returned 503 during dispatch; the outcome is correct but nothing was written.",
            },
            "dispatch": {
                "suppressed": False,
                "calendar_event_id": None,
                "fields_written": 1,
                "queued_for_review": True,
                "errors": ["calendar: HTTP 503 Service Unavailable"],
            },
            "duration": 38,
        },
    ]


async def main() -> None:
    await init_db()
    now = datetime.now(timezone.utc)

    async with SessionLocal() as session:
        campaign = await session.scalar(select(Campaign).limit(1))
        if campaign is None:
            print("No campaign found. Run `python seed_demo.py` first.")
            await engine.dispose()
            return

        contacts = (
            await session.execute(
                select(Contact).where(Contact.campaign_id == campaign.id)
            )
        ).scalars().all()
        if not contacts:
            print("Campaign has no contacts. Run `python seed_demo.py` first.")
            await engine.dispose()
            return

        scenarios = build_scenarios(now)

        for i, scenario in enumerate(scenarios):
            contact = contacts[i % len(contacts)]
            started = now - timedelta(minutes=90 - i * 17)

            # Fabricated token counts, in the same shape a real call produces:
            # the persona prefix served from cache, a little fresh input per
            # turn, and one extraction pass. Scaled off the turn count so the
            # cost-per-call figure on the dashboard is at least plausible.
            turns = len(scenario["transcript"])
            usage = TokenUsage()
            if turns:
                usage.add(
                    campaign.conversation_model or "claude-sonnet-5",
                    input_tokens=turns * 90,
                    output_tokens=turns * 55,
                    cache_read_tokens=turns * 940,
                    cache_write_tokens=940 if i == 0 else 0,
                )
                usage.add(
                    campaign.extraction_model or "claude-opus-5",
                    input_tokens=430 + turns * 42,
                    output_tokens=900,
                )

            session.add(
                Call(
                    input_tokens=usage.input_tokens,
                    output_tokens=usage.output_tokens,
                    cache_read_tokens=usage.cache_read_tokens,
                    cache_write_tokens=usage.cache_write_tokens,
                    cost_usd=usage.cost_usd(),
                    conversation_model=campaign.conversation_model,
                    extraction_model=campaign.extraction_model,
                    id=str(uuid.uuid4()),
                    contact_id=contact.id,
                    campaign_id=campaign.id,
                    status=CallStatus.COMPLETED,
                    started_at=started,
                    connected_at=started + timedelta(seconds=6),
                    ended_at=started
                    + timedelta(seconds=6 + (scenario["duration"] or 0)),
                    provider_call_sid=f"demo-sid-{uuid.uuid4().hex[:8]}",
                    transcript=[
                        turn(role, text, n * 7, started)
                        for n, (role, text) in enumerate(scenario["transcript"])
                    ],
                    disposition=scenario["disposition"],
                    summary=scenario["summary"],
                    outcome=scenario["outcome"],
                    needs_human_review=scenario["needs_review"],
                    review_reason=scenario.get("review_reason"),
                    dispatch_result=scenario["dispatch"],
                )
            )
            campaign.spend_usd = (campaign.spend_usd or 0.0) + usage.cost_usd()

            # Mirror the real pipeline's contact-state transitions.
            if scenario["disposition"] == "do_not_call":
                contact.status = ContactStatus.SUPPRESSED
                if not await session.scalar(
                    select(Suppression).where(
                        Suppression.phone_e164 == contact.phone_e164
                    )
                ):
                    session.add(
                        Suppression(
                            phone_e164=contact.phone_e164,
                            reason="Requested during call.",
                        )
                    )
            elif scenario["disposition"] == "voicemail":
                contact.status = ContactStatus.PENDING
                contact.attempts = 1
                contact.next_attempt_at = now + timedelta(hours=20)
            else:
                contact.status = ContactStatus.COMPLETED
                contact.attempts = 1

        await session.commit()

    print(f"Inserted {len(build_scenarios(now))} synthetic calls.")
    print("These are fabricated records — no calls were placed.")
    print("Open http://127.0.0.1:8000 to view.")
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
