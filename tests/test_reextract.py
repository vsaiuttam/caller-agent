"""Post-call extraction that survives a busy provider, and a way to re-run it.

Covers docs/v3-spec.md §8. Ten of twelve recent calls ended "Extraction call
failed" after provider overload. Now extraction retries overload and
rate-limit errors with backoff (3 attempts over about 20 s, Anthropic's 529
`OverloadedError` included), other errors are not retried, a given fallback
(the workspace extraction default on a different provider) is tried next,
and only then is the call marked for review. POST
/api/calls/{id}/reextract (owners and admins) re-runs extraction on the saved
transcript and returns the updated call.

`extract_outcome` is driven directly with fake clients and the backoff
patched to zero (`postcall.extract.RETRY_DELAYS`); the endpoint runs on the
real app over ASGI with the harness from test_accounts.py and model clients
from a patched `make_client`. No network, no waiting. Runs standalone
(`python tests/test_reextract.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import contextmanager
from datetime import timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_accounts import _bearer, _env, _fresh_ip, _member, _owner, _run, _show  # noqa: E402
from test_api_v2 import T0, _patched  # noqa: E402
from test_providers_api import (  # noqa: E402
    ANTHROPIC_DB_KEY, DEFAULT_OUTCOME, ENV_ANTHROPIC, FakeModel, by_provider, create_provider,
    fake_model, get_json, models_from, overloaded, rate_limited,
)

from src.voiceagent import providers, storage  # noqa: E402
from src.voiceagent.models import CallContext, CallOutcome, Contact, Disposition, Sentiment, Turn  # noqa: E402
from src.voiceagent.postcall import extract  # noqa: E402

# Failed attempts are logged with a traceback; expected here, so kept quiet.
logging.getLogger(extract.__name__).setLevel(logging.CRITICAL)

FAILED_REASON = "Extraction call failed; transcript preserved for manual review."
FALLBACK_OUTCOME = CallOutcome(
    disposition=Disposition.CALLBACK_REQUESTED,
    summary="Asha asked to be called back on Friday.",
    needs_human_review=False,
    sentiment=Sentiment.NEUTRAL,
)
TURNS = [
    Turn(role="assistant", text="Hi Asha, it's Smile Dental calling.", started_at=T0),
    Turn(role="user", text="Hi! Yes, Tuesday works.", started_at=T0 + timedelta(seconds=5)),
    Turn(role="assistant", text="Perfect, see you Tuesday.", started_at=T0 + timedelta(seconds=9)),
]


@contextmanager
def _no_backoff():
    with _patched(extract, "RETRY_DELAYS", (0.0, 0.0)):
        yield


def _extract(client: FakeModel, **kwargs) -> CallOutcome:
    contact = Contact(contact_id="ct-1", full_name="Asha Rao", phone_e164="+15555550100", timezone="Asia/Kolkata")
    context = CallContext(campaign_id="camp-1", goal="Confirm Tuesday.")

    async def main():
        return await extract.extract_outcome(client, contact, context, TURNS, T0.isoformat(), **kwargs)

    with _env(**ENV_ANTHROPIC), _no_backoff():
        return asyncio.run(main())


async def _seed_failed_call(sessions, **campaign) -> None:
    async with sessions() as db:
        db.add(storage.Campaign(id="camp-1", name="Smile Dental", goal="Confirm Tuesday.", **campaign))
        db.add(storage.Contact(id="ct-1", campaign_id="camp-1", full_name="Asha Rao", phone_e164="+15555550100"))
        db.add(storage.Call(
            id="call-1", contact_id="ct-1", campaign_id="camp-1",
            status=storage.CallStatus.COMPLETED, started_at=T0, connected_at=T0, ended_at=T0 + timedelta(seconds=12),
            transcript=[t.model_dump(mode="json") for t in TURNS],
            disposition="failed", summary=FAILED_REASON, needs_human_review=True, review_reason=FAILED_REASON,
            outcome={"disposition": "failed", "summary": FAILED_REASON, "needs_human_review": True},
        ))
        await db.commit()


# ---------------------------------------------------------------------------
# Retries inside extract_outcome
# ---------------------------------------------------------------------------


def test_the_retries_back_off_over_about_twenty_seconds() -> None:
    delays = tuple(extract.RETRY_DELAYS)
    assert len(delays) == 2, f"3 attempts means 2 waits, got {delays}"
    assert all(d > 0 for d in delays) and delays[1] >= delays[0], delays
    assert 10 <= sum(delays) <= 40, f"about 20 s in all, got {sum(delays)}"


def test_extraction_retries_an_overloaded_provider_and_then_succeeds() -> None:
    client = FakeModel(failures=[overloaded(529), overloaded(529)])
    outcome = _extract(client)
    assert client.calls("messages.parse") == 3, [m for m, _ in client.requests]
    assert outcome.disposition == Disposition.COMPLETED and not outcome.needs_human_review, outcome


def test_a_5xx_from_the_provider_is_retried_too() -> None:
    client = FakeModel(failures=[overloaded(503)])
    outcome = _extract(client)
    assert client.calls("messages.parse") == 2, [m for m, _ in client.requests]
    assert outcome.summary == DEFAULT_OUTCOME.summary, outcome


def test_a_rate_limited_provider_is_retried() -> None:
    client = FakeModel(failures=[rate_limited()])
    outcome = _extract(client)
    assert client.calls("messages.parse") == 2, [m for m, _ in client.requests]
    assert outcome.disposition == Disposition.COMPLETED, outcome


def test_three_overloaded_attempts_with_no_fallback_mark_the_call_for_review() -> None:
    client = FakeModel(always=overloaded(529))
    outcome = _extract(client)
    assert client.calls("messages.parse") == 3, f"3 attempts, then stop: {client.calls()}"
    assert outcome.disposition == Disposition.FAILED and outcome.needs_human_review, outcome


def test_errors_other_than_overload_are_not_retried() -> None:
    client = FakeModel(always=ValueError("schema mismatch"))
    outcome = _extract(client)
    assert client.calls("messages.parse") == 1, [m for m, _ in client.requests]
    assert outcome.needs_human_review, outcome


def test_after_three_overloads_the_fallback_provider_gets_a_try() -> None:
    primary = FakeModel(always=overloaded(529))
    backup = FakeModel(outcome=FALLBACK_OUTCOME)
    outcome = _extract(primary, fallback=(backup, providers.PROVIDERS_BY_ID["anthropic"], "claude-opus-5"))
    assert primary.calls("messages.parse") == 3, primary.calls()
    assert backup.calls("messages.parse") == 1, backup.calls()
    assert backup.requests[0][1]["model"] == "claude-opus-5", backup.requests[0][1].get("model")
    assert outcome.summary == FALLBACK_OUTCOME.summary and not outcome.needs_human_review, outcome


# ---------------------------------------------------------------------------
# POST /api/calls/{id}/reextract
# ---------------------------------------------------------------------------


def test_reextract_reruns_extraction_and_returns_the_updated_call() -> None:
    model = FakeModel()

    async def scenario(http, sessions):
        await _seed_failed_call(sessions)
        with fake_model(model), _no_backoff():
            r = await http.post("/api/calls/call-1/reextract")
        return r, await get_json(http, "/api/calls/call-1")

    r, detail = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert r.status_code == 200, _show(r)
    body = r.json()
    for call in (body, detail):
        assert call["id"] == "call-1", call
        assert call["disposition"] == "completed", call["disposition"]
        assert call["summary"] == DEFAULT_OUTCOME.summary, call["summary"]
        assert call["needs_human_review"] is False, call
        assert call["sentiment"] == "positive", call["sentiment"]
        assert call["outcome"]["summary"] == DEFAULT_OUTCOME.summary, call["outcome"]
    assert detail["transcript"] == body["transcript"] and len(detail["transcript"]) == 3, "the transcript is kept"
    prompt = json.dumps(model.requests[0][1], default=str)
    assert "Tuesday works" in prompt, "extraction should run on the saved transcript"


def test_reextract_falls_back_to_the_workspace_default_provider() -> None:
    async def scenario(http, sessions):
        busy = await create_provider(http, kind="anthropic", label="Busy", api_key=ANTHROPIC_DB_KEY)
        default = await create_provider(http, kind="anthropic", label="Default", api_key="sk-ant-api03-DEFAULT-2222")
        r = await http.put("/api/model-defaults", json={
            "conversation": {"provider_id": default["id"], "model": "claude-sonnet-5"},
            "extraction": {"provider_id": default["id"], "model": "claude-opus-5"},
        })
        assert r.status_code == 200, _show(r)
        await _seed_failed_call(sessions, extraction_provider_id=busy["id"], extraction_model="claude-opus-5")
        busy_model = FakeModel(always=overloaded(529))
        default_model = FakeModel(outcome=FALLBACK_OUTCOME)
        with models_from(by_provider({busy["id"]: busy_model, default["id"]: default_model})), _no_backoff():
            r = await http.post("/api/calls/call-1/reextract")
        return r, busy_model, default_model

    r, busy_model, default_model = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert r.status_code == 200, _show(r)
    assert busy_model.calls("messages.parse") == 3, f"the campaign's provider gets 3 tries: {busy_model.calls()}"
    assert default_model.calls("messages.parse") == 1, "then the workspace default gets one"
    body = r.json()
    assert body["disposition"] == "callback_requested" and body["summary"] == FALLBACK_OUTCOME.summary, body
    assert body["needs_human_review"] is False, body


def test_only_owners_and_admins_can_reextract() -> None:
    async def scenario(http, sessions):
        owner = await _owner(http)
        admin = await _member(http, owner["token"], "admin@example.com", role="admin")
        member = await _member(http, owner["token"], "member@example.com")
        await _seed_failed_call(sessions)
        with fake_model(FakeModel()), _no_backoff():
            anonymous = await http.post("/api/calls/call-1/reextract")
            by_member = await http.post("/api/calls/call-1/reextract", headers=_bearer(member["token"]))
            by_admin = await http.post("/api/calls/call-1/reextract", headers=_bearer(admin["token"]))
        return anonymous, by_member, by_admin

    anonymous, by_member, by_admin = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert anonymous.status_code == 401, _show(anonymous)
    assert by_member.status_code == 403, _show(by_member)
    assert by_admin.status_code == 200, _show(by_admin)


def test_reextracting_an_unknown_call_is_404() -> None:
    async def scenario(http, sessions):
        with fake_model(FakeModel()):
            return await http.post("/api/calls/no-such-call/reextract")

    r = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert r.status_code == 404, _show(r)
    assert "call" in r.text.lower(), r.text


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
