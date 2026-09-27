"""Who may change workspace settings, and per-person rate limits.

Workspace resources added in v3 — model providers and the default models —
are readable by every teammate and writable by the owner and admins only.
The rule is the team page's, applied to a dependency rather than repeated
in each handler.

With the gate off (nobody has registered and there is no ADMIN_PASSWORD)
there is nobody to ask: the console is open, as it is for campaigns and
connected apps, and writes are allowed. A fresh deploy has to be able to
add its first provider before anyone has an account.
"""

from __future__ import annotations

import time
from collections import deque

from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession

from ..storage import User, get_session
from . import auth

WRITE_ROLES = ("owner", "admin")


async def current_actor(request: Request, db: AsyncSession) -> dict | None:
    """`{id, role}` for a signed-in request; None with the gate off.

    The role comes from the database, not the token, so a demotion applies
    to sessions already open. The admin password counts as the owner.
    """
    if not auth.auth_enabled():
        return None
    claims = await auth.authenticate(auth.request_token(request.scope))
    if claims is None:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    if claims["sub"] == auth.LEGACY_SUBJECT:
        return {"id": auth.LEGACY_SUBJECT, "role": "owner"}
    user = await db.get(User, claims["sub"])
    if user is None or user.disabled:
        raise HTTPException(401, "Authentication required", headers={"WWW-Authenticate": "Bearer"})
    return {"id": user.id, "role": user.role}


async def workspace_writer(
    request: Request, db: AsyncSession = Depends(get_session)
) -> dict | None:
    """Dependency: the owner or an admin, or nobody when the gate is off."""
    actor = await current_actor(request, db)
    if actor is not None and actor["role"] not in WRITE_ROLES:
        raise HTTPException(403, "Only the owner or an admin can change this.")
    return actor


def requester_key(request: Request) -> str:
    """Who a rate limit counts against: the signed-in subject, else the client address."""
    claims = auth.token_claims(auth.request_token(request.scope) or "")
    if claims is not None:
        return f"user:{claims['sub']}"
    peer = request.client.host if request.client else None
    return "ip:" + auth.client_address(request.headers, peer)


class RateLimiter:
    """At most `limit` events per `window` seconds per key, in memory.

    Per process, which is the deployment shape here (one API process). It
    bounds spend on the endpoints that cost a model or TTS request, not a
    security boundary.
    """

    def __init__(self, limit: int, window: float = 60.0) -> None:
        self.limit = limit
        self.window = window
        self._events: dict[str, deque[float]] = {}

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        events = self._events.setdefault(key, deque())
        while events and now - events[0] >= self.window:
            events.popleft()
        if len(events) >= self.limit:
            return False
        events.append(now)
        return True

    def reset(self) -> None:
        self._events.clear()
