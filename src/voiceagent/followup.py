"""Post-call follow-up messages: SMS and WhatsApp, both through Twilio.

After a call the person gets a short text on each channel the campaign has
switched on — a thank-you with any appointment that was booked, or a
missed-call note if nobody picked up. Delivery receipts come back through
`record_delivery_status`, so the call record says whether the message
actually arrived, not just that we asked Twilio to send it.

The message is composed here from the outcome rather than by a model, and
deliberately leaves out the extractor's `summary`. That summary is written
for staff skimming a review queue ("seemed hesitant about price") and is not
something to send to the person it describes.

Env vars:
    TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN   — both channels
    TWILIO_PHONE_NUMBER                     — SMS sender (same as the calls)
    TWILIO_WHATSAPP_FROM                    — WhatsApp sender, e.g. +14155238886
                                              for the Twilio Sandbox
    TWILIO_WHATSAPP_CONTENT_SID             — optional approved template (HX...),
                                              required for business-initiated
                                              WhatsApp outside the Sandbox
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from dataclasses import asdict, dataclass
from datetime import datetime

from .models import CallOutcome, Disposition

logger = logging.getLogger(__name__)

SMS = "sms"
WHATSAPP = "whatsapp"
CHANNELS = (SMS, WHATSAPP)

# A missed call gets one note, not one per retry.
MISSED = {Disposition.NO_ANSWER, Disposition.VOICEMAIL}

# Twilio's statuses in the order a message moves through them. Callbacks can
# arrive out of order, and a late "sent" must not overwrite "delivered".
_STATUS_RANK = {
    "accepted": 0,
    "scheduled": 0,
    "queued": 0,
    "sending": 1,
    "sent": 2,
    "delivered": 3,
    "read": 4,
    "undelivered": 5,
    "failed": 5,
    "canceled": 5,
}

# The errors people actually hit setting this up, in words that say what to do.
_ERROR_HINTS = {
    "21211": "The 'To' number is not a valid phone number.",
    "21408": "SMS to this country is not enabled — turn it on under Messaging > Geo permissions in the Twilio console.",
    "21608": "Twilio trial accounts can only message verified numbers — verify it in the console or upgrade.",
    "21610": "The recipient has replied STOP to this sender.",
    "21614": "The 'To' number is not a mobile number.",
    "30003": "The handset is unreachable (switched off or out of coverage).",
    "30005": "Unknown destination handset.",
    "30006": "The destination is a landline or cannot receive messages.",
    "30007": "Filtered by the carrier.",
    "30008": "Delivery failed for an unknown reason on the carrier side.",
    "63007": "TWILIO_WHATSAPP_FROM is not a WhatsApp sender on this Twilio account.",
    "63015": "The Sandbox can only message numbers that have joined it — send the join code from WhatsApp first.",
    "63016": "Outside WhatsApp's 24-hour window — set TWILIO_WHATSAPP_CONTENT_SID to an approved template.",
}


@dataclass
class SendResult:
    channel: str
    status: str  # a Twilio status ("queued", "sent", …), or "failed"
    sid: str | None = None
    error: str | None = None

    def as_dict(self) -> dict:
        return asdict(self)


@dataclass
class FollowUpMessage:
    first_name: str
    campaign_name: str
    detail: str  # one line: what happened, and any appointment

    @property
    def text(self) -> str:
        return f"Hi {self.first_name}, {self.detail}\n— {self.campaign_name}"


# --------------------------------------------------------------------------
# Configuration
# --------------------------------------------------------------------------


def _credentials() -> tuple[str, str] | None:
    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    return (sid, token) if sid and token else None


def sms_configured() -> bool:
    return bool(_credentials() and os.getenv("TWILIO_PHONE_NUMBER"))


def whatsapp_configured() -> bool:
    return bool(_credentials() and os.getenv("TWILIO_WHATSAPP_FROM"))


def _whatsapp_address(number: str) -> str:
    number = number.strip()
    return number if number.startswith("whatsapp:") else f"whatsapp:{number}"


def _status_callback(call_id: str | None, channel: str) -> str | None:
    """Where Twilio reports delivery, or None when we have no public URL."""
    base = os.getenv("TWILIO_WEBHOOK_URL") or os.getenv("RENDER_EXTERNAL_URL") or ""
    if not call_id or not base.startswith("https://"):
        return None
    return f"{base.rstrip('/')}/twilio/message-status/{call_id}/{channel}"


# --------------------------------------------------------------------------
# Composing
# --------------------------------------------------------------------------


def compose_message(
    *, contact_name: str, campaign_name: str, outcome: CallOutcome
) -> FollowUpMessage | None:
    """The message for this outcome, or None when nothing should be sent.

    Nothing goes to a wrong number (it isn't the person we meant), after a
    technical failure, or after an opt-out — honouring "don't contact me"
    includes not texting to confirm it.
    """
    first_name = contact_name.split()[0] if contact_name.strip() else "there"
    disposition = outcome.disposition

    if disposition in (Disposition.COMPLETED, Disposition.PARTIAL):
        detail = f"thanks for speaking with {campaign_name} today."
    elif disposition is Disposition.CALLBACK_REQUESTED:
        detail = f"thanks for speaking with {campaign_name}. We'll call you back as you asked."
    elif disposition is Disposition.DECLINED:
        detail = "thanks for your time today. We've noted your preference."
    elif disposition in MISSED:
        detail = f"we tried to call you from {campaign_name} but couldn't reach you. We'll try again soon."
    else:
        return None

    if outcome.appointment and disposition not in MISSED:
        detail += f" Your appointment: {_format_appointment(outcome.appointment)}."

    return FollowUpMessage(first_name=first_name, campaign_name=campaign_name, detail=detail)


def _format_appointment(appointment) -> str:
    when = appointment.starts_at_local
    try:
        parsed = datetime.fromisoformat(when)
        when = parsed.strftime("%a %d %b, %I:%M %p").replace(" 0", " ")
    except ValueError:
        pass
    return f"{when} ({appointment.timezone})"


# --------------------------------------------------------------------------
# Sending
# --------------------------------------------------------------------------


async def send_followups(
    *,
    to: str,
    call_id: str | None,
    contact_name: str,
    campaign_name: str,
    outcome: CallOutcome,
    sms: bool,
    whatsapp: bool,
) -> dict[str, SendResult]:
    """Send the follow-up on each requested channel, concurrently.

    Never raises: a message is an enhancement to a call that has already
    happened, and a failure is recorded on the result rather than thrown.
    """
    message = compose_message(contact_name=contact_name, campaign_name=campaign_name, outcome=outcome)
    if message is None:
        logger.debug("No follow-up for disposition %s", outcome.disposition.value)
        return {}

    jobs = []
    if sms:
        jobs.append(_send(SMS, to, message, call_id))
    if whatsapp:
        jobs.append(_send(WHATSAPP, to, message, call_id))
    results = await asyncio.gather(*jobs)
    return {result.channel: result for result in results}


async def _send(channel: str, to: str, message: FollowUpMessage, call_id: str | None) -> SendResult:
    credentials = _credentials()
    if channel == SMS and not sms_configured():
        return SendResult(SMS, "failed", error="SMS needs TWILIO_ACCOUNT_SID, TWILIO_AUTH_TOKEN and TWILIO_PHONE_NUMBER.")
    if channel == WHATSAPP and not whatsapp_configured():
        return SendResult(WHATSAPP, "failed", error="WhatsApp needs TWILIO_WHATSAPP_FROM (and the Twilio credentials).")

    if channel == SMS:
        kwargs: dict = {"to": to, "from_": os.environ["TWILIO_PHONE_NUMBER"], "body": message.text}
    else:
        kwargs = {
            "to": _whatsapp_address(to),
            "from_": _whatsapp_address(os.environ["TWILIO_WHATSAPP_FROM"]),
        }
        content_sid = os.getenv("TWILIO_WHATSAPP_CONTENT_SID", "").strip()
        if content_sid:
            # WhatsApp only allows business-initiated messages from an
            # approved template. Expected shape: "Hi {{1}}, {{2}} — {{3}}".
            kwargs["content_sid"] = content_sid
            kwargs["content_variables"] = json.dumps(
                {"1": message.first_name, "2": message.detail, "3": message.campaign_name}
            )
        else:
            kwargs["body"] = message.text

    callback = _status_callback(call_id, channel)
    if callback:
        kwargs["status_callback"] = callback

    try:
        from twilio.rest import Client

        client = Client(*credentials)
        sent = await asyncio.to_thread(client.messages.create, **kwargs)
    except Exception as exc:  # noqa: BLE001 - reported on the result instead
        code = str(getattr(exc, "code", "") or "")
        error = _ERROR_HINTS.get(code) or str(getattr(exc, "msg", "") or exc)
        logger.warning("%s follow-up to %s…. failed: %s", channel, to[:6], error)
        return SendResult(channel, "failed", error=f"{code}: {error}" if code else error)

    logger.info("%s follow-up sent to %s…. (SID %s)", channel, to[:6], sent.sid)
    return SendResult(channel, str(sent.status or "queued"), sid=sent.sid)


def followup_columns(results: dict[str, SendResult]) -> dict:
    """Call-row values for a set of send results."""
    values: dict = {}
    errors: dict[str, str] = {}
    for channel, result in results.items():
        values[f"{channel}_sid"] = result.sid
        values[f"{channel}_status"] = result.status
        if result.error:
            errors[channel] = result.error
    if results:
        values["followup_errors"] = errors or None
    return values


# --------------------------------------------------------------------------
# Delivery receipts
# --------------------------------------------------------------------------


async def record_delivery_status(
    *, call_id: str, channel: str, message_sid: str, status: str, error_code: str = ""
) -> None:
    """Apply a Twilio status callback to the call it belongs to.

    Only moves a status forward, and only for the message SID we stored, so a
    forged or stray callback can't rewrite another call's record.
    """
    if channel not in CHANNELS or status not in _STATUS_RANK or not message_sid:
        return

    from .storage import Call, SessionLocal

    async with SessionLocal() as session:
        call = await session.get(Call, call_id)
        if call is None or getattr(call, f"{channel}_sid") != message_sid:
            return
        current = getattr(call, f"{channel}_status")
        if _STATUS_RANK.get(current or "", -1) >= _STATUS_RANK[status]:
            return

        setattr(call, f"{channel}_status", status)
        if error_code:
            errors = dict(call.followup_errors or {})
            errors[channel] = f"{error_code}: {_ERROR_HINTS.get(error_code, 'see the Twilio console')}"
            call.followup_errors = errors
        await session.commit()
    logger.info("%s follow-up for call %s: %s", channel, call_id, status)
