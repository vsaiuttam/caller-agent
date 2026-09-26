"""In-process event bus for the live UI feed.

Single-process only. When you scale past one API node, swap `EventBus` for a
Redis pub/sub implementation behind the same two methods — every publisher and
subscriber in the codebase goes through this interface precisely so that swap
is a one-file change.

Subscribers get a bounded queue and are dropped on overflow rather than
allowed to apply backpressure. A stalled browser tab must never slow down call
dispatch.
"""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any

logger = logging.getLogger(__name__)

_QUEUE_MAXSIZE = 200


@dataclass
class Event:
    type: str
    payload: dict[str, Any] = field(default_factory=dict)
    at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


class EventBus:
    def __init__(self) -> None:
        self._subscribers: set[asyncio.Queue[Event]] = set()

    async def publish(self, event: Event) -> None:
        dead: list[asyncio.Queue[Event]] = []
        for queue in self._subscribers:
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                # Slow consumer. Drop it rather than block dispatch.
                dead.append(queue)
        for queue in dead:
            self._subscribers.discard(queue)
            logger.warning("Dropped a slow event subscriber")

    async def subscribe(self) -> AsyncIterator[Event]:
        queue: asyncio.Queue[Event] = asyncio.Queue(maxsize=_QUEUE_MAXSIZE)
        self._subscribers.add(queue)
        try:
            while True:
                yield await queue.get()
        finally:
            self._subscribers.discard(queue)

    @property
    def subscriber_count(self) -> int:
        return len(self._subscribers)


bus = EventBus()


# Event type constants — keep in sync with the frontend's union type. Every
# call.* payload carries `call_id`, so a console can follow one call on a
# feed shared by all of them.
CALL_STARTED = "call.started"
CALL_CONNECTED = "call.connected"
CALL_TRANSCRIPT = "call.transcript"
CALL_STATE = "call.state"  # speaking | listening | thinking | working | ended
CALL_TURN = "call.turn"  # one recorded turn, as it happens
CALL_TOOL = "call.tool"  # a tool call starting or finishing (mcp/toolbox.py)
CALL_WHISPER = "call.whisper"  # supervisor guidance added mid-call
CALL_ENDED = "call.ended"
CALL_EXTRACTED = "call.extracted"
CALL_FAILED = "call.failed"  # with a human-readable `error`
CAMPAIGN_UPDATED = "campaign.updated"
