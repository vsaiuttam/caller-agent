"""Real integration clients: Google Calendar, your internal API, suppression.

Each implements one of the protocols in `postcall.actions`, so swapping any of
them for a mock (or a different vendor) touches nothing else.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from ..models import CallOutcome
from ..storage import Contact, ContactStatus, Suppression

logger = logging.getLogger(__name__)


class GoogleCalendarClient:
    """Creates events on a service-account-owned calendar.

    Uses a service account with domain-wide delegation rather than per-user
    OAuth: the agent books on a shared operational calendar, so there's no
    end user to run a consent flow.
    """

    def __init__(self, calendar_id: str, credentials_path: str) -> None:
        self._calendar_id = calendar_id
        self._credentials_path = credentials_path
        self._service = None

    def _client(self):
        if self._service is None:
            from google.oauth2 import service_account  # imported lazily
            from googleapiclient.discovery import build

            creds = service_account.Credentials.from_service_account_file(
                self._credentials_path,
                scopes=["https://www.googleapis.com/auth/calendar.events"],
            )
            self._service = build("calendar", "v3", credentials=creds, cache_discovery=False)
        return self._service

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
        import asyncio

        start = datetime.fromisoformat(starts_at_local)
        end = start + timedelta(minutes=duration_minutes)

        body = {
            "summary": subject,
            "description": f"Booked by voice agent for {attendee_name}.\n\n{notes}".strip(),
            "start": {"dateTime": start.isoformat(), "timeZone": timezone},
            "end": {"dateTime": end.isoformat(), "timeZone": timezone},
        }

        # The Google client is synchronous; keep it off the event loop.
        def _insert() -> str:
            created = (
                self._client()
                .events()
                .insert(calendarId=self._calendar_id, body=body)
                .execute()
            )
            return created["id"]

        return await asyncio.to_thread(_insert)


class HttpRecordsClient:
    """Writes call outcomes to an internal HTTP API.

    Endpoints assumed (override via env if yours differ):
        POST {base}/calls          — full outcome record
        PATCH {base}/contacts/{id} — collected field updates
    """

    def __init__(self, base_url: str, api_key: str, timeout: float = 10.0) -> None:
        self._base = base_url.rstrip("/")
        self._headers = {"Authorization": f"Bearer {api_key}"}
        self._timeout = timeout

    async def log_call(self, *, contact_id: str, outcome: CallOutcome) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.post(
                f"{self._base}/calls",
                headers=self._headers,
                json={"contact_id": contact_id, **outcome.model_dump(mode="json")},
            )
            response.raise_for_status()

    async def upsert_fields(self, *, contact_id: str, fields: dict[str, str]) -> None:
        async with httpx.AsyncClient(timeout=self._timeout) as client:
            response = await client.patch(
                f"{self._base}/contacts/{contact_id}",
                headers=self._headers,
                json=fields,
            )
            response.raise_for_status()


class DbSuppressionList:
    """Do-not-call list backed by the platform database.

    Writes the suppression *and* halts every pending contact row sharing that
    number in the same transaction — a suppression that leaves a queued call
    behind is worse than no suppression at all.
    """

    def __init__(self, session_factory: async_sessionmaker) -> None:
        self._sessions = session_factory

    async def suppress(self, *, contact_id: str, reason: str) -> None:
        async with self._sessions() as session:
            contact = await session.get(Contact, contact_id)
            if contact is None:
                logger.error("Suppression requested for unknown contact %s", contact_id)
                return

            already = await session.scalar(
                select(Suppression).where(Suppression.phone_e164 == contact.phone_e164)
            )
            if already is None:
                session.add(Suppression(phone_e164=contact.phone_e164, reason=reason))

            siblings = (
                await session.execute(
                    select(Contact).where(Contact.phone_e164 == contact.phone_e164)
                )
            ).scalars().all()
            for sibling in siblings:
                sibling.status = ContactStatus.SUPPRESSED
                sibling.next_attempt_at = None

            await session.commit()
            logger.info("Suppressed %s across %d campaign rows", contact_id, len(siblings))


# --------------------------------------------------------------------------
# Construction from environment
# --------------------------------------------------------------------------


def build_calendar():
    calendar_id = os.getenv("GOOGLE_CALENDAR_ID")
    creds = os.getenv("GOOGLE_CREDENTIALS_PATH")
    if calendar_id and creds:
        return GoogleCalendarClient(calendar_id, creds)

    from .mocks import MockCalendar

    logger.warning("GOOGLE_CALENDAR_ID/CREDENTIALS not set — using mock calendar")
    return MockCalendar()


def build_records():
    base = os.getenv("RECORDS_API_URL")
    key = os.getenv("RECORDS_API_KEY")
    if base and key:
        return HttpRecordsClient(base, key)

    from .mocks import MockRecords

    logger.warning("RECORDS_API_URL/KEY not set — using mock records client")
    return MockRecords()
