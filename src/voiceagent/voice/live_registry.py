"""Calls in progress in this process, for the live console.

The operator's "End call" and "whisper" buttons need the running
`CallSession` itself, not a row in the database, so live calls are tracked
here, in memory. Single-process by design, like the event bus: a call is
controllable from the process that placed it. A call placed by a separate
worker process is not listed by the API process — the same boundary the
in-process bus already draws.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from .session import CallSession


@dataclass
class LiveCall:
    call_id: str
    session: CallSession
    room_name: str
    campaign_id: str | None
    contact_name: str
    is_test: bool
    started_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    # Last state the session reported: speaking | listening | thinking | ended.
    state: str = "connected"

    @property
    def turns(self) -> int:
        """Turns recorded so far."""
        return len(self.session.transcript)

    def to_dict(self) -> dict[str, Any]:
        return {
            "call_id": self.call_id,
            "room_name": self.room_name,
            "campaign_id": self.campaign_id,
            "contact_name": self.contact_name,
            "started_at": self.started_at.isoformat(),
            "state": self.state,
            "is_test": self.is_test,
            "turns": self.turns,
        }


_calls: dict[str, LiveCall] = {}


def register(
    call_id: str,
    *,
    session: CallSession,
    room_name: str,
    campaign_id: str | None,
    contact_name: str,
    is_test: bool,
) -> LiveCall:
    call = LiveCall(
        call_id=call_id,
        session=session,
        room_name=room_name,
        campaign_id=campaign_id,
        contact_name=contact_name,
        is_test=is_test,
    )
    _calls[call_id] = call
    return call


def unregister(call_id: str) -> None:
    _calls.pop(call_id, None)


def get(call_id: str) -> LiveCall | None:
    return _calls.get(call_id)


def all() -> list[LiveCall]:  # noqa: A001 - the registry's public name
    """Every live call, oldest first."""
    return sorted(_calls.values(), key=lambda call: call.started_at)


def set_state(call_id: str, state: str) -> None:
    call = _calls.get(call_id)
    if call is not None:
        call.state = state
