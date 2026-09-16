"""Seed a demo campaign so you can watch the whole loop run end to end.

    python seed_demo.py

Creates a campaign with a handful of contacts spread across timezones, already
set to RUNNING. Start the worker with TELEPHONY=mock and calls begin
immediately — assuming the local time falls inside the calling window, which
is deliberately wide here so the demo works whenever you run it.
"""

from __future__ import annotations

import asyncio
import uuid

from src.voiceagent.storage import (
    Campaign,
    CampaignStatus,
    Contact,
    SessionLocal,
    engine,
    init_db,
)

CONTACTS = [
    ("Dana Whitfield", "+14155550142", "America/Los_Angeles", {"account": "AC-2291", "last_visit": "March 4"}),
    ("Marcus Oyelaran", "+12125550188", "America/New_York", {"account": "AC-3310", "last_visit": "February 19"}),
    ("Priya Raghunathan", "+13125550176", "America/Chicago", {"account": "AC-1877", "last_visit": "April 2"}),
    ("Tom Ferreira", "+16175550119", "America/New_York", {"account": "AC-4402", "last_visit": "March 28"}),
    ("Alina Kovacs", "+13035550163", "America/Denver", {"account": "AC-5019", "last_visit": "January 30"}),
]


async def main() -> None:
    await init_db()

    campaign = Campaign(
        id=str(uuid.uuid4()),
        name="Appointment confirmations",
        goal=(
            "Confirm the customer still wants their upcoming service appointment. "
            "If the existing time no longer works, agree a new one."
        ),
        fields_to_collect=[
            "Whether the existing appointment still works",
            "Preferred day and time if rescheduling",
            "Best contact email for the confirmation",
        ],
        constraints=[
            "Never quote a price or discuss billing",
            "Do not offer discounts, credits, or refunds",
            "Do not confirm anything outside normal business hours",
        ],
        # Wide window so the demo dials whenever you happen to run it.
        calling_hours_start=0,
        calling_hours_end=24,
        calling_days=[1, 2, 3, 4, 5, 6, 7],
        max_concurrent_calls=3,
        max_attempts=2,
        status=CampaignStatus.RUNNING,
    )

    async with SessionLocal() as session:
        session.add(campaign)
        for name, phone, tz, attributes in CONTACTS:
            session.add(
                Contact(
                    id=str(uuid.uuid4()),
                    campaign_id=campaign.id,
                    full_name=name,
                    phone_e164=phone,
                    timezone=tz,
                    attributes=attributes,
                )
            )
        await session.commit()

    print(f"Seeded campaign {campaign.id} with {len(CONTACTS)} contacts.")
    print("Start the worker (TELEPHONY=mock) and open http://localhost:5173")

    # Without this the connection pool keeps non-daemon threads alive and the
    # process hangs after main() returns instead of exiting.
    await engine.dispose()


if __name__ == "__main__":
    asyncio.run(main())
