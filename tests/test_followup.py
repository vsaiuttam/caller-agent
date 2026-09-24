"""Post-call SMS / WhatsApp: what gets sent, and what the record says after.

No Twilio account and no network. Delivery receipts run against a throwaway
SQLite database. Runs standalone (`python tests/test_followup.py`) or under
pytest.
"""

from __future__ import annotations

import asyncio
import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine  # noqa: E402

from src.voiceagent import followup, storage  # noqa: E402
from src.voiceagent.models import Appointment, CallOutcome, Disposition  # noqa: E402

INTERNAL_SUMMARY = "Asha sounded hesitant about the price and may churn."


def _outcome(disposition: Disposition, *, appointment: bool = False) -> CallOutcome:
    return CallOutcome(
        disposition=disposition,
        summary=INTERNAL_SUMMARY,
        needs_human_review=False,
        appointment=(
            Appointment(
                starts_at_local="2026-09-30T15:00:00",
                timezone="Asia/Kolkata",
                duration_minutes=30,
                subject="Cleaning",
            )
            if appointment
            else None
        ),
    )


def _compose(disposition: Disposition, **kwargs):
    return followup.compose_message(
        contact_name="Asha Rao",
        campaign_name="Smile Dental",
        outcome=_outcome(disposition, **kwargs),
    )


# ---------------------------------------------------------------------------


def test_a_booked_call_confirms_the_appointment_without_the_staff_summary() -> None:
    message = _compose(Disposition.COMPLETED, appointment=True)
    assert message is not None
    assert message.text.startswith("Hi Asha, thanks for speaking with Smile Dental")
    assert "Wed 30 Sep, 3:00 PM (Asia/Kolkata)" in message.text, message.text
    assert message.text.endswith("— Smile Dental")
    # The extractor's summary is written for staff, not for the person.
    assert "hesitant" not in message.text


def test_a_missed_call_gets_a_missed_call_note() -> None:
    for disposition in (Disposition.NO_ANSWER, Disposition.VOICEMAIL):
        message = _compose(disposition)
        assert message is not None and "couldn't reach you" in message.detail, disposition


def test_nothing_goes_to_an_opt_out_a_wrong_number_or_a_failure() -> None:
    for disposition in (Disposition.DO_NOT_CALL, Disposition.WRONG_NUMBER, Disposition.FAILED):
        assert _compose(disposition) is None, disposition


def test_template_variables_are_single_lines() -> None:
    # WhatsApp rejects template variables containing newlines.
    message = _compose(Disposition.CALLBACK_REQUESTED, appointment=True)
    assert message is not None
    assert "\n" not in message.detail and "\n" not in message.first_name


def test_a_missing_sender_is_reported_not_raised() -> None:
    saved = {k: os.environ.pop(k, None) for k in ("TWILIO_WHATSAPP_FROM",)}
    try:
        results = asyncio.run(
            followup.send_followups(
                to="+919800000000",
                call_id=None,
                contact_name="Asha Rao",
                campaign_name="Smile Dental",
                outcome=_outcome(Disposition.COMPLETED),
                sms=False,
                whatsapp=True,
            )
        )
    finally:
        for key, value in saved.items():
            if value is not None:
                os.environ[key] = value
    result = results["whatsapp"]
    assert result.status == "failed" and "TWILIO_WHATSAPP_FROM" in (result.error or "")
    columns = followup.followup_columns(results)
    assert columns["whatsapp_status"] == "failed" and "whatsapp" in columns["followup_errors"]


def test_delivery_receipts_only_move_forward_and_only_for_our_message() -> None:
    async def scenario() -> tuple[str | None, str | None, dict | None]:
        path = Path(tempfile.mkdtemp()) / "followup.db"
        engine = create_async_engine(f"sqlite+aiosqlite:///{path.as_posix()}")
        async with engine.begin() as conn:
            await conn.run_sync(storage.Base.metadata.create_all)
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        async with sessions() as session:
            session.add(
                storage.Call(
                    id="call-1",
                    contact_id="contact-1",
                    campaign_id="campaign-1",
                    sms_sid="SM1",
                    sms_status="queued",
                    whatsapp_sid="WA1",
                    whatsapp_status="queued",
                )
            )
            await session.commit()

        real = storage.SessionLocal
        storage.SessionLocal = sessions
        try:
            record = followup.record_delivery_status
            await record(call_id="call-1", channel="sms", message_sid="SM1", status="delivered")
            # A late "sent" must not undo "delivered".
            await record(call_id="call-1", channel="sms", message_sid="SM1", status="sent")
            # Someone else's message SID changes nothing.
            await record(call_id="call-1", channel="sms", message_sid="SMX", status="failed")
            await record(
                call_id="call-1", channel="whatsapp", message_sid="WA1",
                status="undelivered", error_code="63015",
            )
        finally:
            storage.SessionLocal = real

        async with sessions() as session:
            call = await session.get(storage.Call, "call-1")
            result = call.sms_status, call.whatsapp_status, call.followup_errors
        await engine.dispose()
        return result

    sms_status, whatsapp_status, errors = asyncio.run(scenario())
    assert sms_status == "delivered", sms_status
    assert whatsapp_status == "undelivered", whatsapp_status
    assert errors and "Sandbox" in errors["whatsapp"], errors


# ---------------------------------------------------------------------------


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0
    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"pass  {test.__name__}")
    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
