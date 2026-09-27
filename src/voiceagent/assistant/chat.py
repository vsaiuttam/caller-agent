"""Ask Samvaad: answers questions about the product and this workspace.

People asked the same things over and over — why isn't my campaign calling,
how do I add Telugu, where do I put a key — and the answers were scattered
across Settings, env vars and the README. This is a chat panel grounded in a
product guide (guide.md, next to this file) and a compact snapshot of the
workspace, so "why isn't it calling" gets an answer about *their* campaign.

It answers; it never acts. No tools are offered to the model, and links it
suggests are filtered through a fixed allow-list of console routes — a model
writing `[click here](https://...)` gets nothing through. The snapshot is
built for the prompt and holds counts, which services are configured, and
running campaigns with their dialler states: no keys, no tokens, no phone
numbers, no contact names. Replies are capped at 600 output tokens and each
person gets a handful of questions a minute, because every question is a
paid model request on the workspace's default provider.

Protocol: POST /api/assistant/chat {messages, page?} answers as
text/event-stream — `data: {"token": "..."}` frames as the reply streams,
then `data: {"done": true, "links": [{label, to}]}`. A failure after the
stream has started arrives as `data: {"error": "..."}` before the final frame.
"""

from __future__ import annotations

import json
import logging
import os
import re
from datetime import datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import StreamingResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from .. import providers
from ..api.access import RateLimiter, requester_key
from ..api.schemas import AssistantChatRequest
from ..catalog import CONVERSATION
from ..followup import sms_configured, whatsapp_configured
from ..storage import Call, Campaign, CampaignStatus, Contact, McpServer, get_session

logger = logging.getLogger(__name__)

router = APIRouter()

MAX_OUTPUT_TOKENS = 600
RATE_LIMIT_PER_MINUTE = 10
limiter = RateLimiter(RATE_LIMIT_PER_MINUTE, 60.0)

# Only these routes are ever offered as links, whatever the model writes.
ALLOWED_LINKS: dict[str, str] = {
    "/app/dashboard": "Overview",
    "/app/campaigns": "Campaigns",
    "/app/campaigns/new": "New campaign",
    "/app/calls": "Calls",
    "/app/calls?view=review": "Needs review",
    "/app/live": "Live calls",
    "/app/test-lab": "Test lab",
    "/app/templates": "Templates",
    "/app/models": "AI models",
    "/app/integrations": "Integrations",
    "/app/settings": "Settings",
    "/app/suppressions": "Do not call",
}

# Running campaigns named in the snapshot. Enough to answer "why isn't X
# calling" for any workspace that is actually run by people.
_SNAPSHOT_CAMPAIGNS = 10

_GUIDE_PATH = Path(__file__).with_name("guide.md")

SYSTEM = """\
You are Ask Samvaad, the help assistant inside Samvaad, a platform that \
places outbound phone calls with an AI voice agent. Answer the user's \
questions about using Samvaad and about their workspace, briefly and \
concretely: a few sentences or a short list, in plain words. Use the product \
guide and the workspace snapshot below; if they don't cover something, say so \
rather than guessing. You cannot take actions or change settings — tell the \
user where to do it instead. When a page would help, link it as a markdown \
link using only these paths: {links}. Never ask for or repeat API keys or \
passwords.

The user is on: {page}

# Product guide
{guide}

# Workspace snapshot (live, read-only)
{snapshot}
"""


@lru_cache(maxsize=1)
def guide() -> str:
    return _GUIDE_PATH.read_text(encoding="utf-8")


async def snapshot(db: AsyncSession) -> dict[str, Any]:
    """What the assistant may know about this workspace. No secrets, no PII.

    Built field by field from counts and flags — never by serialising rows,
    which is how a phone number or a key ends up in a prompt.
    """
    from ..orchestrator.status import dialer_status, telephony_problem

    by_status = dict(
        (status.value, count)
        for status, count in (
            await db.execute(select(Campaign.status, func.count()).group_by(Campaign.status))
        ).all()
    )
    week_ago = datetime.now(timezone.utc) - timedelta(days=7)
    calls_week = await db.scalar(
        select(func.count()).select_from(Call).where(Call.started_at >= week_ago)
    ) or 0
    needs_review = await db.scalar(
        select(func.count()).select_from(Call).where(
            Call.needs_human_review.is_(True), Call.reviewed_at.is_(None)
        )
    ) or 0
    contacts = await db.scalar(select(func.count()).select_from(Contact)) or 0
    mcp = await db.scalar(
        select(func.count()).select_from(McpServer).where(McpServer.enabled.is_(True))
    ) or 0

    running = (
        await db.scalars(
            select(Campaign)
            .where(Campaign.status == CampaignStatus.RUNNING)
            .order_by(Campaign.created_at.desc())
            .limit(_SNAPSHOT_CAMPAIGNS)
        )
    ).all()
    running_out = []
    for campaign in running:
        status = await dialer_status(db, campaign)
        running_out.append(
            {
                "name": campaign.name,
                "language": campaign.language or "en",
                "dialer_state": status["state"],
                "reason": status["reason"],
                "pending": status["pending"],
                "in_progress": status["in_progress"],
                "done": status["done"],
            }
        )

    listed = await providers.list_providers(db)
    defaults = await providers.workspace_defaults(db)
    telephony = telephony_problem()
    return {
        "campaigns": {"total": sum(by_status.values()), "by_status": by_status},
        "running_campaigns": running_out,
        "contacts": contacts,
        "calls_last_7_days": calls_week,
        "calls_needing_review": needs_review,
        "services": {
            "telephony": telephony is None,
            "telephony_mode": os.getenv("TELEPHONY", "mock").strip().lower(),
            "telephony_problem": telephony,
            "sms": sms_configured(),
            "whatsapp": whatsapp_configured(),
            "sarvam_voice": bool(os.getenv("SARVAM_API_KEY", "").strip()),
            "connected_apps": mcp,
        },
        "model_providers": [
            {"label": p.label, "kind": p.kind, "enabled": p.enabled, "source": p.source} for p in listed
        ],
        "model_defaults": {
            role: {"model": entry["model"], "provider_set": bool(entry["provider_id"])}
            for role, entry in defaults.items()
        },
    }


_MARKDOWN_LINK = re.compile(r"\[([^\]]{1,80})\]\(([^)\s]{1,200})\)")
_BARE_PATH = re.compile(r"(?<![\w/(])(/app/[A-Za-z0-9_\-/?=&]*)")


def extract_links(text: str) -> list[dict[str, str]]:
    """The allow-listed routes a reply mentions, in order, each once.

    The label is the allow-list's, not the model's: a route is only ever
    shown under its own name.
    """
    found: list[str] = []
    for match in _MARKDOWN_LINK.finditer(text):
        found.append(match.group(2))
    for match in _BARE_PATH.finditer(text):
        found.append(match.group(1))
    links: list[dict[str, str]] = []
    seen: set[str] = set()
    for raw in found:
        route = raw.rstrip(".,;:!?)")
        if route in ALLOWED_LINKS and route not in seen:
            seen.add(route)
            links.append({"label": ALLOWED_LINKS[route], "to": route})
    return links


def _frame(payload: dict[str, Any]) -> str:
    return f"data: {json.dumps(payload, ensure_ascii=False)}\n\n"


@router.post("/api/assistant/chat")
async def assistant_chat(
    body: AssistantChatRequest, request: Request, db: AsyncSession = Depends(get_session)
) -> StreamingResponse:
    if body.messages[-1].role != "user":
        raise HTTPException(400, "The last message must be the user's question.")
    if not limiter.allow(requester_key(request)):
        raise HTTPException(429, "That's a lot of questions in a minute. Try again shortly.")

    defaults = await providers.workspace_defaults(db)
    run = await providers.runtime(
        defaults[CONVERSATION]["provider_id"], defaults[CONVERSATION]["model"], CONVERSATION, session=db
    )
    if run.provider is None or run.client is None or not run.model:
        raise HTTPException(503, "No model provider is set up yet, so the assistant can't answer. "
                                 "Add one on the AI models page.")

    system = SYSTEM.format(
        links=", ".join(ALLOWED_LINKS),
        page=(body.page or "unknown")[:200],
        guide=guide(),
        snapshot=json.dumps(await snapshot(db), ensure_ascii=False, indent=1, default=str),
    )
    messages = [{"role": m.role, "content": m.content} for m in body.messages]
    client, provider, model = run.client, run.provider, run.model

    async def events():
        from ..llm import stream_text

        reply: list[str] = []
        try:
            async for delta in stream_text(
                client, provider, model, system=system, messages=messages, max_tokens=MAX_OUTPUT_TOKENS
            ):
                if delta:
                    reply.append(delta)
                    yield _frame({"token": delta})
        except Exception as exc:  # noqa: BLE001 - said in the stream; headers are gone
            logger.warning("Assistant reply failed: %s", type(exc).__name__)
            yield _frame({"error": providers.describe_error(exc)})
        yield _frame({"done": True, "links": extract_links("".join(reply))})

    return StreamingResponse(
        events(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
