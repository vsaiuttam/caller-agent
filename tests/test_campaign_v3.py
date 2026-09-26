"""Campaigns in v3: provider, voice and pre-call fields, and "why isn't it calling".

Covers docs/v3-spec.md §1.1, §2.3, §4 and §6 on the campaign: the new columns
(`conversation_provider_id`, `extraction_provider_id`, `voice`, `precall_*`
and `contacts.precall_sent_at` / `precall_status`) are additive with the
documented defaults and round-trip through create, get and patch; the
pre-call lead time is held to 2–240 minutes; and GET
/api/campaigns/{id}/dialer names the dialler's state (draft, paused,
completed, waiting for the calling window and when it opens, dialing, or
blocked with the reasons) with contact counts.

Drives the real app over ASGI on a throwaway SQLite database with the
harness from test_accounts.py; campaigns in a given state are seeded straight
into the database. No network. Runs standalone
(`python tests/test_campaign_v3.py`) or under pytest.
"""

from __future__ import annotations

import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_accounts import _fresh_ip, _run, _show  # noqa: E402
from test_providers_api import ANTHROPIC_DB_KEY, ENV_ANTHROPIC, NO_PROVIDERS, create_provider, get_json  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.orchestrator.scheduler import CallingWindow, next_window_open  # noqa: E402
from src.voiceagent.storage import CampaignStatus, ContactStatus  # noqa: E402

NO_TELEPHONY = dict(
    TELEPHONY="twilio",
    TWILIO_ACCOUNT_SID=None, TWILIO_AUTH_TOKEN=None, TWILIO_PHONE_NUMBER=None, TWILIO_WHATSAPP_FROM=None,
    LIVEKIT_API_KEY=None, LIVEKIT_URL=None, TELNYX_API_KEY=None, TELNYX_PHONE_NUMBER=None,
)
TWILIO = dict(
    NO_TELEPHONY,
    TWILIO_ACCOUNT_SID="AC-test", TWILIO_AUTH_TOKEN="test-token",
    TWILIO_PHONE_NUMBER="+15550000000", TWILIO_WHATSAPP_FROM="+15550000001",
    TWILIO_WHATSAPP_CONTENT_SID=None,
)
READY = dict(ENV_ANTHROPIC, **TWILIO)
NOTHING = dict(ENV_ANTHROPIC, **NO_PROVIDERS, **NO_TELEPHONY)

DIALER_KEYS = {"state", "reason", "next_window_start", "pending", "in_progress", "done", "failed", "blockers"}
ALL_DAYS = [1, 2, 3, 4, 5, 6, 7]
KOLKATA = "Asia/Kolkata"


def _utc(value: datetime) -> datetime:
    return value if value.tzinfo else value.replace(tzinfo=timezone.utc)


def _iso(value: str) -> datetime:
    return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))


async def _seed(sessions, *, status=CampaignStatus.RUNNING, days=None, start=0, end=24,
                contacts=(ContactStatus.PENDING,), tz="UTC") -> str:
    async with sessions() as db:
        db.add(storage.Campaign(
            id="camp-1", name="Smile Dental", goal="Confirm Tuesday.", status=status,
            calling_days=days or ALL_DAYS, calling_hours_start=start, calling_hours_end=end,
        ))
        for n, contact_status in enumerate(contacts):
            db.add(storage.Contact(
                id=f"ct-{n}", campaign_id="camp-1", full_name=f"Person {n}",
                phone_e164=f"+9198000000{n:02d}", timezone=tz, status=contact_status,
            ))
        await db.commit()
    return "camp-1"


async def _dialer(http, campaign_id: str = "camp-1") -> dict:
    body = await get_json(http, f"/api/campaigns/{campaign_id}/dialer")
    assert DIALER_KEYS <= set(body), f"missing {sorted(DIALER_KEYS - set(body))} in {sorted(body)}"
    assert isinstance(body["reason"], str) and body["reason"].strip(), "the state should come with a reason"
    assert isinstance(body["blockers"], list), body
    return body


async def _voices(http, language: str) -> list[str]:
    return [v["id"] for v in await get_json(http, f"/api/voices?language={language}")]


# ---------------------------------------------------------------------------
# Columns
# ---------------------------------------------------------------------------


def test_the_new_columns_exist_and_are_additive() -> None:
    campaign = storage.Campaign.__table__.columns
    contact = storage.Contact.__table__.columns
    for name in ("conversation_provider_id", "extraction_provider_id", "voice"):
        assert name in campaign, f"campaigns.{name} is missing"
        assert campaign[name].nullable, f"campaigns.{name} must be nullable (null = the default)"
    assert campaign["conversation_provider_id"].type.length == 64
    assert campaign["extraction_provider_id"].type.length == 64
    assert campaign["voice"].type.length == 40
    for name in ("precall_enabled", "precall_channel", "precall_message", "precall_lead_minutes"):
        assert name in campaign, f"campaigns.{name} is missing"
    assert campaign["precall_channel"].type.length == 16
    # Added to existing databases by `_add_missing_columns`, so the defaults
    # need literals (FALSE, not 0: Postgres refuses an integer on a boolean).
    assert storage._default_literal(campaign["precall_enabled"]) == "FALSE"
    assert storage._default_literal(campaign["precall_lead_minutes"]) == "10"
    for name in ("precall_sent_at", "precall_status"):
        assert name in contact and contact[name].nullable, f"contacts.{name} is missing or not nullable"
    assert "llm_providers" in storage.Base.metadata.tables, "the llm_providers table is missing"
    providers = storage.Base.metadata.tables["llm_providers"].columns
    for name in ("id", "kind", "label", "base_url", "secret", "enabled", "created_at", "updated_at"):
        assert name in providers, f"llm_providers.{name} is missing"


def test_a_new_campaign_uses_the_workspace_defaults_and_no_precall() -> None:
    async def scenario(http, sessions):
        r = await http.post("/api/campaigns", json={"name": "Smile Dental", "goal": "Confirm Tuesday."})
        assert r.status_code == 201, _show(r)
        return r.json()

    body = _run(scenario, _fresh_ip(), **READY)
    assert body["conversation_provider_id"] is None and body["extraction_provider_id"] is None, body
    assert body["voice"] is None, body
    assert body["precall_enabled"] is False, body
    assert body["precall_lead_minutes"] == 10, body


def test_provider_voice_and_precall_fields_round_trip_through_create_and_get() -> None:
    async def scenario(http, sessions):
        provider = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        voice = (await _voices(http, "te"))[0]
        sent = {
            "name": "Smile Dental", "goal": "Confirm Tuesday.", "language": "te",
            "conversation_provider_id": provider["id"], "conversation_model": "claude-sonnet-5",
            "extraction_provider_id": "env:anthropic", "extraction_model": "claude-opus-5",
            "voice": voice,
            "precall_enabled": True, "precall_channel": "sms",
            "precall_message": "Hi {name}, {agent} from {company} will call in {minutes} minutes. Reply STOP to opt out.",
            "precall_lead_minutes": 15,
        }
        created = await http.post("/api/campaigns", json=sent)
        assert created.status_code == 201, _show(created)
        got = await get_json(http, f"/api/campaigns/{created.json()['id']}")
        listed = await get_json(http, "/api/campaigns")
        return sent, created.json(), got, listed

    sent, created, got, listed = _run(scenario, _fresh_ip(), **READY)
    for field in (
        "conversation_provider_id", "extraction_provider_id", "voice", "language",
        "precall_enabled", "precall_channel", "precall_message", "precall_lead_minutes",
    ):
        assert created[field] == sent[field], (field, created[field])
        assert got[field] == sent[field], (field, got[field])
    assert listed[0]["voice"] == sent["voice"], "the list carries the new fields too"


def test_patch_changes_the_v3_fields_and_leaves_the_rest() -> None:
    async def scenario(http, sessions):
        provider = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        first, second = (await _voices(http, "hi"))[:2]
        created = await http.post("/api/campaigns", json={
            "name": "Smile Dental", "goal": "Confirm Tuesday.", "language": "hi", "voice": first,
            "conversation_provider_id": provider["id"], "conversation_model": "claude-sonnet-5",
            "precall_enabled": True, "precall_channel": "sms", "precall_message": "Hi {name}.",
        })
        assert created.status_code == 201, _show(created)
        url = f"/api/campaigns/{created.json()['id']}"
        patched = await http.patch(url, json={
            "voice": second, "precall_channel": "whatsapp", "precall_lead_minutes": 30,
            "conversation_provider_id": None,
        })
        return second, patched, await get_json(http, url)

    second, patched, got = _run(scenario, _fresh_ip(), **READY)
    assert patched.status_code == 200, _show(patched)
    assert got["voice"] == second, got["voice"]
    assert got["precall_channel"] == "whatsapp" and got["precall_lead_minutes"] == 30, got
    assert got["conversation_provider_id"] is None, "null puts the campaign back on the workspace default"
    assert got["precall_enabled"] is True and got["precall_message"] == "Hi {name}.", "omitted fields changed"


def test_the_precall_lead_time_is_between_2_and_240_minutes() -> None:
    async def scenario(http, sessions):
        base = {"name": "Smile Dental", "goal": "Confirm Tuesday."}
        created = {
            minutes: (await http.post("/api/campaigns", json=dict(base, precall_lead_minutes=minutes))).status_code
            for minutes in (1, 2, 240, 241)
        }
        ok = await http.post("/api/campaigns", json=base)
        url = f"/api/campaigns/{ok.json()['id']}"
        patched = {
            minutes: (await http.patch(url, json={"precall_lead_minutes": minutes})).status_code
            for minutes in (1, 241, 60)
        }
        return created, patched, await get_json(http, url)

    created, patched, got = _run(scenario, _fresh_ip(), **READY)
    assert created[2] == 201 and created[240] == 201, created
    assert created[1] in (400, 422) and created[241] in (400, 422), created
    assert patched[1] in (400, 422) and patched[241] in (400, 422), patched
    assert patched[60] == 200 and got["precall_lead_minutes"] == 60, (patched, got)


def test_the_precall_channel_is_sms_or_whatsapp() -> None:
    async def scenario(http, sessions):
        base = {"name": "Smile Dental", "goal": "Confirm Tuesday.", "precall_enabled": True}
        return {
            channel: (await http.post("/api/campaigns", json=dict(base, precall_channel=channel))).status_code
            for channel in ("sms", "whatsapp", "fax", "email")
        }

    statuses = _run(scenario, _fresh_ip(), **READY)
    assert statuses["sms"] == 201 and statuses["whatsapp"] == 201, statuses
    assert statuses["fax"] in (400, 422) and statuses["email"] in (400, 422), statuses


# ---------------------------------------------------------------------------
# GET /api/campaigns/{id}/dialer
# ---------------------------------------------------------------------------


def test_a_draft_campaign_says_draft() -> None:
    async def scenario(http, sessions):
        await _seed(sessions, status=CampaignStatus.DRAFT)
        return await _dialer(http)

    body = _run(scenario, _fresh_ip(), **READY)
    assert body["state"] == "draft", body


def test_paused_and_completed_campaigns_say_so() -> None:
    async def scenario(http, sessions):
        await _seed(sessions, status=CampaignStatus.PAUSED)
        paused = await _dialer(http)
        async with sessions() as db:
            campaign = await db.get(storage.Campaign, "camp-1")
            campaign.status = CampaignStatus.COMPLETED
            await db.commit()
        return paused, await _dialer(http)

    paused, completed = _run(scenario, _fresh_ip(), **READY)
    assert paused["state"] == "paused", paused
    assert completed["state"] == "completed", completed


def test_a_running_campaign_outside_its_hours_waits_and_says_when_the_window_opens() -> None:
    now = datetime.now(timezone.utc)
    today = now.astimezone(ZoneInfo(KOLKATA)).isoweekday()
    tomorrow = today % 7 + 1
    window = CallingWindow.from_campaign(9, 20, [tomorrow])
    expected = next_window_open(KOLKATA, window, now)

    async def scenario(http, sessions):
        await _seed(sessions, days=[tomorrow], start=9, end=20, tz=KOLKATA,
                    contacts=(ContactStatus.PENDING, ContactStatus.PENDING))
        return await _dialer(http)

    body = _run(scenario, _fresh_ip(), **READY)
    assert body["state"] == "waiting_window", body
    assert body["next_window_start"], body
    assert abs(_iso(body["next_window_start"]) - expected) < timedelta(minutes=1), (body["next_window_start"], expected)
    assert body["blockers"] == [], body
    assert body["pending"] == 2, body


def test_a_running_campaign_in_its_window_with_everything_configured_is_dialing() -> None:
    async def scenario(http, sessions):
        await _seed(sessions)
        return await _dialer(http)

    body = _run(scenario, _fresh_ip(), **READY)
    assert body["state"] == "dialing", body
    assert body["blockers"] == [], body


def test_a_campaign_without_telephony_or_a_model_is_blocked_and_says_why() -> None:
    async def scenario(http, sessions):
        await _seed(sessions)
        return await _dialer(http)

    body = _run(scenario, _fresh_ip(), **NOTHING)
    assert body["state"] == "blocked", body
    blockers = " | ".join(body["blockers"]).lower()
    assert len(body["blockers"]) >= 2, body["blockers"]
    assert "telephony" in blockers, body["blockers"]
    assert "provider" in blockers or "model" in blockers, body["blockers"]


def test_a_campaign_with_telephony_but_no_model_is_blocked_on_the_model_alone() -> None:
    async def scenario(http, sessions):
        await _seed(sessions)
        return await _dialer(http)

    body = _run(scenario, _fresh_ip(), **dict(READY, **NO_PROVIDERS))
    assert body["state"] == "blocked", body
    assert len(body["blockers"]) == 1, body["blockers"]
    assert "telephony" not in body["blockers"][0].lower(), body["blockers"]


def test_the_dialer_counts_contacts_by_state() -> None:
    async def scenario(http, sessions):
        await _seed(sessions, contacts=(
            ContactStatus.PENDING, ContactStatus.PENDING, ContactStatus.IN_PROGRESS,
            ContactStatus.COMPLETED, ContactStatus.FAILED,
        ))
        return await _dialer(http)

    body = _run(scenario, _fresh_ip(), **READY)
    counts = {k: body[k] for k in ("pending", "in_progress", "done", "failed")}
    assert counts == {"pending": 2, "in_progress": 1, "done": 1, "failed": 1}, counts


def test_the_dialer_of_an_unknown_campaign_is_404() -> None:
    async def scenario(http, sessions):
        return await http.get("/api/campaigns/nope/dialer")

    r = _run(scenario, _fresh_ip(), **READY)
    assert r.status_code == 404, _show(r)
    assert "not found" in r.text.lower() and "campaign" in r.text.lower(), r.text


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
