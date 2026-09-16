"""SMS follow-up via Twilio.

Sends a summary/confirmation text message after each call. Uses the same
Twilio number that places the call, so it arrives from a familiar sender.

Required env vars (same as voice calling):
    TWILIO_ACCOUNT_SID
    TWILIO_AUTH_TOKEN
    TWILIO_PHONE_NUMBER
"""

from __future__ import annotations

import logging
import os

logger = logging.getLogger(__name__)


def _twilio_configured() -> bool:
    return bool(
        os.getenv("TWILIO_ACCOUNT_SID")
        and os.getenv("TWILIO_AUTH_TOKEN")
        and os.getenv("TWILIO_PHONE_NUMBER")
    )


async def send_sms_followup(
    *,
    to: str,
    contact_name: str,
    campaign_name: str,
    disposition: str,
    summary: str,
    appointment_text: str | None = None,
) -> str | None:
    """Send a post-call SMS summary. Returns the message SID or None on failure.

    Skips silently when Twilio is not configured — SMS is an enhancement, not a
    gate, and a missing credential must not break the call pipeline.
    """
    if not _twilio_configured():
        logger.debug("SMS skipped: Twilio not configured")
        return None

    first_name = contact_name.split()[0] if contact_name else "there"

    # Build a concise, human-friendly message
    lines = [f"Hi {first_name}, thanks for speaking with us."]

    if disposition == "completed":
        lines.append(f"Summary: {summary}")
    elif disposition == "callback_requested":
        lines.append("We'll call you back as requested.")
    elif disposition == "partial":
        lines.append(f"Quick recap: {summary}")
    elif disposition in ("declined", "do_not_call"):
        lines.append("We've noted your preference. You won't be contacted again.")
    else:
        # voicemail, no_answer, failed — don't send an SMS for these
        logger.debug("SMS skipped for disposition: %s", disposition)
        return None

    if appointment_text:
        lines.append(f"Appointment: {appointment_text}")

    lines.append(f"— {campaign_name}")

    body = "\n".join(lines)

    # Truncate to SMS-friendly length (160 chars for single segment, 1600 max)
    if len(body) > 1600:
        body = body[:1597] + "..."

    try:
        import asyncio
        from twilio.rest import Client

        client = Client(
            os.environ["TWILIO_ACCOUNT_SID"],
            os.environ["TWILIO_AUTH_TOKEN"],
        )
        message = await asyncio.to_thread(
            client.messages.create,
            to=to,
            from_=os.environ["TWILIO_PHONE_NUMBER"],
            body=body,
        )
        logger.info("SMS sent to %s....: SID %s", to[:6], message.sid)
        return message.sid
    except Exception:
        logger.exception("SMS send failed for %s", to[:6])
        return None
