"""Outbound webhooks.

The escape hatch for every integration we haven't built. MCP handles the tools
we know about — calendar, the internal records API — but every customer has one
system nobody has heard of, and "wait for us to build a connector" is not an
answer. A signed POST per completed call is.

Deliberately fire-and-forget with a short timeout: a customer's slow endpoint
must not hold a worker slot open while there are calls waiting to be placed.
Delivery is therefore at-most-once, and the API is the source of truth — the
webhook is a notification, not a replication channel. Anything that must not
be missed should reconcile against `GET /api/calls`.
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os

import httpx

logger = logging.getLogger(__name__)

TIMEOUT_SECONDS = 5.0

# Shared secret for the signature header. Without it we still deliver, but the
# receiver has no way to tell our POST from anyone else's — so we say so, once,
# rather than failing silently.
_SECRET = os.getenv("WEBHOOK_SIGNING_SECRET", "")
_warned = False


def sign(body: bytes) -> str | None:
    if not _SECRET:
        return None
    return hmac.HMAC(_SECRET.encode(), body, hashlib.sha256).hexdigest()


async def fire_webhook(url: str, payload: dict) -> bool:
    """POST `payload` to `url`. Returns whether it was accepted.

    Never raises: a broken customer endpoint is their problem to fix and ours
    to log, not a reason to fail a call that already happened.
    """
    global _warned

    if not url:
        return False

    body = json.dumps(payload, separators=(",", ":")).encode()
    headers = {"Content-Type": "application/json", "User-Agent": "RumikAI-Webhook/1.0"}

    signature = sign(body)
    if signature:
        headers["X-Rumik-Signature"] = f"sha256={signature}"
    elif not _warned:
        logger.warning(
            "WEBHOOK_SIGNING_SECRET is unset — webhooks are being sent unsigned, "
            "so the receiver cannot verify they came from us."
        )
        _warned = True

    try:
        async with httpx.AsyncClient(timeout=TIMEOUT_SECONDS) as client:
            response = await client.post(url, content=body, headers=headers)
        if response.status_code >= 400:
            logger.warning("Webhook to %s returned %s", url, response.status_code)
            return False
        return True
    except Exception as exc:  # noqa: BLE001 - see docstring
        logger.warning("Webhook to %s failed: %s", url, exc)
        return False
