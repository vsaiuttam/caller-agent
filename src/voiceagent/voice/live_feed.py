"""One call's live feed: what the session reports, relayed as it happens.

A `CallFeed` is the `on_event` observer for a `CallSession`. Each state
change and turn goes out on the event bus (the live console follows a call by
its `call_id`), each state change updates the live registry, and each turn is
saved to the call's row — so a call that crashes, or a process that dies
mid-call, still leaves everything said so far on disk.

The save is deliberately off the call's hot path. The session awaits its
observer between the person finishing and the reply starting, and a database
round trip there is dead air on the line. Saves are coalesced instead: at
most one runs at a time, and it always writes the newest transcript, so a
slow database costs extra writes, never extra latency.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from sqlalchemy import update

from ..orchestrator.events import CALL_STATE, CALL_TURN, Event, bus
from ..storage import Call
from . import live_registry

logger = logging.getLogger(__name__)


class CallFeed:
    def __init__(self, call_id: str, session_factory) -> None:
        self.call_id = call_id
        self._sessions = session_factory
        self._turns: list[dict[str, Any]] = []
        self._unsaved = False
        self._saving: asyncio.Task | None = None

    async def publish(self, event_type: str, **payload: Any) -> None:
        """Put a call.* event on the bus, tagged with this call's id."""
        await bus.publish(Event(event_type, {"call_id": self.call_id, **payload}))

    async def on_event(self, kind: str, payload: dict[str, Any]) -> None:
        """`CallSession`'s observer."""
        if kind == "state":
            live_registry.set_state(self.call_id, payload["state"])
            await self.publish(CALL_STATE, **payload)
        elif kind == "turn":
            # The stored shape of a `Turn`, so the row reads the same mid-call
            # as it does once the call has finished.
            self._turns.append(
                {
                    "role": payload["role"],
                    "text": payload["text"],
                    "started_at": payload["at"],
                    "latency_ms": payload["latency_ms"],
                }
            )
            self._save_soon()
            await self.publish(CALL_TURN, **payload)

    async def drain(self) -> None:
        """Wait out any save in flight, so it can't land after a later write."""
        if self._saving is not None:
            await self._saving

    def _save_soon(self) -> None:
        self._unsaved = True
        if self._saving is None or self._saving.done():
            self._saving = asyncio.create_task(self._save())

    async def _save(self) -> None:
        while self._unsaved:
            self._unsaved = False
            snapshot = list(self._turns)
            try:
                async with self._sessions() as db:
                    await db.execute(
                        update(Call).where(Call.id == self.call_id).values(transcript=snapshot)
                    )
                    await db.commit()
            except Exception:  # noqa: BLE001 - the final save still writes it
                logger.exception("Saving the transcript of call %s mid-call failed", self.call_id)
