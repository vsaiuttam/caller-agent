"""The pre-call heads-up: a short message before the campaign calls someone.

Covers docs/v3-spec.md §6 in the campaign runner: when a contact becomes due,
the runner sends the heads-up first, records `precall_sent_at` and
`precall_status` on the contact, and pushes `next_attempt_at` out by the
lead time; the call goes out on a later tick. A retry within 12 hours of a
heads-up gets no second one (after 12 hours it gets a fresh one). A
suppressed number, or someone outside the calling window, gets nothing. The
template fills in {name}, {company} (the campaign name when unset), {minutes}
and {agent}; the default wording says who is calling and how to opt out.

Runs the real `CampaignRunner` on a throwaway SQLite database, one tick at a
time. No Twilio: `followup.send_precall(channel, to, text)` (DEV's seam, looked
up at call time) is replaced by an outbox, and the one test of the real
sender stubs `twilio.rest.Client`. Runs standalone
(`python tests/test_precall.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import inspect
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_api_v2 import _env, _patched, _temp_db  # noqa: E402
from test_campaign_v3 import TWILIO  # noqa: E402

from src.voiceagent import followup, storage  # noqa: E402
from src.voiceagent.orchestrator.runner import CampaignRunner  # noqa: E402
from src.voiceagent.storage import CampaignStatus, ContactStatus  # noqa: E402

PHONE = "+919800000001"
TEMPLATE = "Hi {name}, {agent} from {company} will call you in {minutes} minutes. Reply STOP to opt out."
LEAD = 10


class Outbox:
    """Stands in for `followup.send_precall`; records every heads-up."""

    def __init__(self, status: str = "queued") -> None:
        self.status = status
        self.sent: list[dict] = []

    async def __call__(self, *args, **kwargs):
        message = dict(zip(("channel", "to", "text"), args))
        message.update(kwargs)
        self.sent.append(message)
        return followup.SendResult(message.get("channel", "sms"), self.status, sid=f"SM{len(self.sent)}")


class Dialler:
    """Stands in for the pipeline's `place_call`."""

    def __init__(self) -> None:
        self.placed: list[str] = []

    async def __call__(self, contact, campaign) -> None:
        self.placed.append(contact.id)


def _utc(value: datetime | None) -> datetime | None:
    if value is None:
        return None
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


async def _seed(sessions, *, days=None, message=TEMPLATE, channel="sms", precall=True, **contact) -> None:
    async with sessions() as db:
        db.add(storage.Campaign(
            id="camp-1", name="Smile Dental", goal="Confirm Tuesday.", status=CampaignStatus.RUNNING,
            calling_days=days or [1, 2, 3, 4, 5, 6, 7], calling_hours_start=0, calling_hours_end=24,
            precall_enabled=precall, precall_channel=channel, precall_message=message,
            precall_lead_minutes=LEAD,
        ))
        db.add(storage.Contact(
            id="ct-1", campaign_id="camp-1", full_name="Asha Rao", phone_e164=PHONE,
            timezone="UTC", status=ContactStatus.PENDING, **contact,
        ))
        await db.commit()


async def _contact(sessions):
    async with sessions() as db:
        return await db.get(storage.Contact, "ct-1")


async def _tick(runner: CampaignRunner) -> None:
    """One dispatch pass, then let any call it started finish."""
    await runner._tick()
    tasks = [t for tasks in runner._active.values() for t in tasks]
    if tasks:
        await asyncio.wait_for(asyncio.gather(*tasks, return_exceptions=True), 2)


def _scenario(body, *, outbox: Outbox | None = None):
    """Run `body(runner, sessions, outbox, dialler)` on a fresh database with Twilio configured."""
    outbox = outbox or Outbox()
    dialler = Dialler()

    async def main():
        engine, sessions = await _temp_db()
        try:
            runner = CampaignRunner(sessions, dialler)
            return await body(runner, sessions, outbox, dialler)
        finally:
            await engine.dispose()

    with _env(**TWILIO), _patched(followup, "send_precall", outbox):
        result = asyncio.run(main())
    return result, outbox, dialler


# ---------------------------------------------------------------------------


def test_a_due_contact_gets_a_heads_up_first_and_its_call_waits_for_the_lead_time() -> None:
    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions)
        before = datetime.now(timezone.utc)
        await _tick(runner)
        after = datetime.now(timezone.utc)
        return before, after, await _contact(sessions)

    (before, after, contact), outbox, dialler = _scenario(body)
    assert len(outbox.sent) == 1, outbox.sent
    message = outbox.sent[0]
    assert message["channel"] == "sms" and message["to"] == PHONE, message
    assert dialler.placed == [], "the call must wait for the lead time, not go out with the heads-up"
    sent_at = _utc(contact.precall_sent_at)
    assert sent_at and before - timedelta(seconds=5) <= sent_at <= after + timedelta(seconds=5), sent_at
    assert contact.precall_status == "queued", contact.precall_status
    due = _utc(contact.next_attempt_at)
    lead = timedelta(minutes=LEAD)
    assert due and before + lead - timedelta(seconds=5) <= due <= after + lead + timedelta(seconds=5), due
    assert contact.status == ContactStatus.PENDING, f"the contact must stay dialable: {contact.status}"


def test_the_call_goes_out_on_a_later_tick_without_a_second_heads_up() -> None:
    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions)
        await _tick(runner)
        await _tick(runner)
        placed_before_lead = list(dialler.placed)
        async with sessions() as db:  # the lead time passes
            contact = await db.get(storage.Contact, "ct-1")
            contact.next_attempt_at = datetime.now(timezone.utc) - timedelta(seconds=1)
            await db.commit()
        await _tick(runner)
        return placed_before_lead

    placed_before_lead, outbox, dialler = _scenario(body)
    assert placed_before_lead == [], "called before the lead time was up"
    assert dialler.placed == ["ct-1"], dialler.placed
    assert len(outbox.sent) == 1, f"one heads-up per call, got {len(outbox.sent)}"


def test_a_retry_within_12_hours_gets_no_second_heads_up() -> None:
    now = datetime.now(timezone.utc)

    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions, attempts=1, precall_sent_at=now - timedelta(hours=2), precall_status="delivered",
                    next_attempt_at=now - timedelta(minutes=1))
        await _tick(runner)

    _, outbox, dialler = _scenario(body)
    assert outbox.sent == [], outbox.sent
    assert dialler.placed == ["ct-1"], "a retry inside 12 hours of the heads-up is dialled straight away"


def test_a_retry_after_12_hours_gets_a_fresh_heads_up() -> None:
    now = datetime.now(timezone.utc)

    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions, attempts=1, precall_sent_at=now - timedelta(hours=13), precall_status="delivered",
                    next_attempt_at=now - timedelta(minutes=1))
        await _tick(runner)
        return await _contact(sessions)

    contact, outbox, dialler = _scenario(body)
    assert len(outbox.sent) == 1, outbox.sent
    assert dialler.placed == [], dialler.placed
    assert _utc(contact.precall_sent_at) > now - timedelta(minutes=1), contact.precall_sent_at


def test_a_suppressed_number_gets_no_heads_up_and_no_call() -> None:
    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions)
        async with sessions() as db:
            db.add(storage.Suppression(phone_e164=PHONE, reason="Asked not to be called"))
            await db.commit()
        await _tick(runner)
        return await _contact(sessions)

    contact, outbox, dialler = _scenario(body)
    assert outbox.sent == [] and dialler.placed == [], (outbox.sent, dialler.placed)
    assert contact.status == ContactStatus.SUPPRESSED, contact.status
    assert contact.precall_sent_at is None, contact.precall_sent_at


def test_nobody_gets_a_heads_up_outside_the_calling_window() -> None:
    tomorrow = datetime.now(timezone.utc).isoweekday() % 7 + 1

    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions, days=[tomorrow])
        await _tick(runner)
        return await _contact(sessions)

    contact, outbox, dialler = _scenario(body)
    assert outbox.sent == [] and dialler.placed == [], (outbox.sent, dialler.placed)
    assert contact.precall_sent_at is None, contact.precall_sent_at


def test_the_heads_up_fills_in_name_company_minutes_and_agent() -> None:
    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions)
        await _tick(runner)

    _, outbox, _ = _scenario(body)
    text = outbox.sent[0]["text"]
    assert "Asha" in text and "Smile Dental" in text, text
    assert f"in {LEAD} minutes" in text, text
    assert "{" not in text and "}" not in text, f"a placeholder was left unfilled: {text}"


def test_the_default_heads_up_says_who_is_calling_and_how_to_opt_out() -> None:
    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions, message="")
        await _tick(runner)

    _, outbox, _ = _scenario(body)
    assert len(outbox.sent) == 1, outbox.sent
    text = outbox.sent[0]["text"]
    assert "Smile Dental" in text, text
    assert "STOP" in text, text
    assert "{" not in text, text
    assert len(text) <= 320, f"the default should be short: {len(text)} characters"


def test_whatsapp_heads_ups_go_out_on_the_whatsapp_channel() -> None:
    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions, channel="whatsapp")
        await _tick(runner)

    _, outbox, dialler = _scenario(body)
    assert len(outbox.sent) == 1 and outbox.sent[0]["channel"] == "whatsapp", outbox.sent
    assert outbox.sent[0]["to"].endswith(PHONE), outbox.sent[0]
    assert dialler.placed == []


def test_without_a_heads_up_the_call_goes_out_at_once() -> None:
    async def body(runner, sessions, outbox, dialler):
        await _seed(sessions, precall=False)
        await _tick(runner)
        return await _contact(sessions)

    contact, outbox, dialler = _scenario(body)
    assert outbox.sent == [], outbox.sent
    assert dialler.placed == ["ct-1"], dialler.placed
    assert contact.precall_sent_at is None


def test_the_precall_sender_reports_an_unconfigured_channel_rather_than_raising() -> None:
    assert inspect.iscoroutinefunction(followup.send_precall), "followup.send_precall must be async"
    with _env(TWILIO_ACCOUNT_SID=None, TWILIO_AUTH_TOKEN=None, TWILIO_PHONE_NUMBER=None, TWILIO_WHATSAPP_FROM=None):
        sms = asyncio.run(followup.send_precall("sms", PHONE, "Hi Asha"))
        whatsapp = asyncio.run(followup.send_precall("whatsapp", PHONE, "Hi Asha"))
    assert sms.status == "failed" and "TWILIO" in (sms.error or ""), sms
    assert whatsapp.status == "failed" and "TWILIO" in (whatsapp.error or ""), whatsapp


def test_the_precall_sender_sends_the_text_through_twilio() -> None:
    import twilio.rest

    created: list[dict] = []

    class FakeTwilio:
        def __init__(self, *args, **kwargs) -> None:
            self.messages = SimpleNamespace(create=self._create)

        def _create(self, **kwargs):
            created.append(kwargs)
            return SimpleNamespace(sid="SM-precall", status="queued")

    with _env(**TWILIO), _patched(twilio.rest, "Client", FakeTwilio):
        result = asyncio.run(followup.send_precall("sms", PHONE, "Hi Asha, Smile Dental will call in 10 minutes."))
    assert result.status == "queued" and result.sid == "SM-precall", result
    assert len(created) == 1, created
    assert created[0]["to"] == PHONE and created[0]["from_"] == TWILIO["TWILIO_PHONE_NUMBER"], created[0]
    assert created[0]["body"] == "Hi Asha, Smile Dental will call in 10 minutes.", created[0]


# ---------------------------------------------------------------------------


def _run_all() -> int:
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(errors="backslashreplace")
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
