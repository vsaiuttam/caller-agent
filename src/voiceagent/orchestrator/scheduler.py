"""Eligibility and retry policy.

Pure functions — no I/O, no database. Everything here is a decision about
*whether* and *when* a contact may be dialled, which makes it the part of the
system most worth unit-testing exhaustively.

Calling hours are evaluated in the **contact's** local timezone, never the
server's. A worker in Frankfurt dialling a contact in Denver must respect
Denver's clock, and `zoneinfo` handles the DST arithmetic for us.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from ..models import Disposition


@dataclass(frozen=True)
class CallingWindow:
    start_hour: int
    end_hour: int
    allowed_weekdays: frozenset[int]  # ISO weekday, 1=Mon .. 7=Sun

    @classmethod
    def from_campaign(cls, start_hour: int, end_hour: int, days: list[int]) -> "CallingWindow":
        return cls(
            start_hour=start_hour,
            end_hour=end_hour,
            allowed_weekdays=frozenset(days),
        )


class EligibilityReason(str):
    pass


OK = "ok"
SUPPRESSED = "suppressed"
OUTSIDE_HOURS = "outside_calling_hours"
BACKOFF = "in_retry_backoff"
EXHAUSTED = "attempts_exhausted"
BAD_TIMEZONE = "invalid_timezone"


def _local_now(tz_name: str, now_utc: datetime) -> datetime | None:
    try:
        return now_utc.astimezone(ZoneInfo(tz_name))
    except (ZoneInfoNotFoundError, ValueError):
        return None


def is_within_window(tz_name: str, window: CallingWindow, now_utc: datetime) -> bool:
    local = _local_now(tz_name, now_utc)
    if local is None:
        return False
    if local.isoweekday() not in window.allowed_weekdays:
        return False
    return window.start_hour <= local.hour < window.end_hour


def next_window_open(tz_name: str, window: CallingWindow, now_utc: datetime) -> datetime:
    """First moment from `now_utc` at which this contact may be called.

    Walks forward day by day rather than computing directly — the loop is
    bounded at 14 iterations and sidesteps a whole class of DST and
    weekday-wraparound bugs that the closed-form version invites.
    """
    local = _local_now(tz_name, now_utc)
    if local is None:
        # Unknown timezone: defer a day rather than dialling blind.
        return now_utc + timedelta(days=1)

    candidate = local
    for _ in range(14):
        if candidate.isoweekday() in window.allowed_weekdays:
            open_at = candidate.replace(
                hour=window.start_hour, minute=0, second=0, microsecond=0
            )
            close_at = candidate.replace(
                hour=window.end_hour, minute=0, second=0, microsecond=0
            )
            if candidate < open_at:
                return open_at.astimezone(timezone.utc)
            if candidate < close_at:
                return candidate.astimezone(timezone.utc)
        # Next day, at midnight local.
        candidate = (candidate + timedelta(days=1)).replace(
            hour=0, minute=0, second=0, microsecond=0
        )

    return now_utc + timedelta(days=1)


# --------------------------------------------------------------------------
# Retry policy
# --------------------------------------------------------------------------

# How long to wait before the next attempt, by how the last one ended.
# Deliberately conservative: repeatedly dialling someone who didn't pick up is
# the fastest way to generate complaints.
_RETRY_DELAY: dict[Disposition, timedelta | None] = {
    Disposition.NO_ANSWER: timedelta(hours=4),
    Disposition.VOICEMAIL: timedelta(days=1),
    Disposition.FAILED: timedelta(minutes=30),
    Disposition.PARTIAL: timedelta(days=1),
    Disposition.CALLBACK_REQUESTED: timedelta(days=1),
    # Terminal — never retry these.
    Disposition.COMPLETED: None,
    Disposition.DECLINED: None,
    Disposition.DO_NOT_CALL: None,
    Disposition.WRONG_NUMBER: None,
}


def is_terminal(disposition: Disposition) -> bool:
    return _RETRY_DELAY.get(disposition, None) is None


def next_attempt_after(
    disposition: Disposition,
    attempts_so_far: int,
    now_utc: datetime,
) -> datetime | None:
    """When to try again, or None if this contact is done.

    Backoff doubles per attempt so a number that never answers drifts out of
    the pool rather than being hammered daily.
    """
    base = _RETRY_DELAY.get(disposition)
    if base is None:
        return None
    return now_utc + base * (2 ** max(0, attempts_so_far - 1))


# --------------------------------------------------------------------------
# Combined check
# --------------------------------------------------------------------------


def check_eligibility(
    *,
    tz_name: str,
    window: CallingWindow,
    now_utc: datetime,
    attempts: int,
    max_attempts: int,
    next_attempt_at: datetime | None,
    is_suppressed: bool,
) -> str:
    """Return OK, or the reason this contact may not be dialled right now."""
    if is_suppressed:
        return SUPPRESSED
    if attempts >= max_attempts:
        return EXHAUSTED
    if next_attempt_at is not None and now_utc < next_attempt_at:
        return BACKOFF
    if _local_now(tz_name, now_utc) is None:
        return BAD_TIMEZONE
    if not is_within_window(tz_name, window, now_utc):
        return OUTSIDE_HOURS
    return OK
