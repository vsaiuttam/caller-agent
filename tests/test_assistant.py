""""Ask Samvaad": the in-app help assistant.

Covers docs/v3-spec.md §7: POST /api/assistant/chat streams the model's reply
as server-sent events (`data: {"token": ...}` frames) and ends with
`{done: true, links: [{label, to}]}`; links only ever come from the fixed
allow-list of console routes, whatever the model writes; the workspace
snapshot it is grounded in names running campaigns but carries no keys,
tokens, phone numbers or contact names; replies are capped at 600 output
tokens and use no tools (it answers, it doesn't act); it is rate-limited per
user; and the product guide it reads exists.

Drives the real app over ASGI with the harness from test_accounts.py. The
model is a fake handed out by a patched `make_client` (see
test_providers_api.py), which records every request, so the prompt the
model saw can be checked for secrets. No network. Runs standalone
(`python tests/test_assistant.py`) or under pytest.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_accounts import _bearer, _fresh_ip, _member, _owner, _run, _show  # noqa: E402
from test_campaign_v3 import TWILIO  # noqa: E402
from test_providers_api import ANTHROPIC_DB_KEY, ENV_ANTHROPIC, ENV_KEY, FakeModel, create_provider, fake_model  # noqa: E402

from src.voiceagent import storage  # noqa: E402
from src.voiceagent.storage import CampaignStatus, ContactStatus  # noqa: E402

try:  # imported before any test patches SessionLocal, so it never binds a throwaway one
    from src.voiceagent.assistant import chat  # noqa: E402
except ImportError:  # not built yet; the tests that need it fail on the lookup
    chat = None

GUIDE = Path(__file__).resolve().parents[1] / "src" / "voiceagent" / "assistant" / "guide.md"
REPLY = "Open Campaigns, pick Telugu as the language, then choose a voice."
PHONE = "+919812345678"
CONTACT = "Asha Raghunathan"
SECRETS = {
    "TWILIO_AUTH_TOKEN": "twilio-token-SECRET-777",
    "SARVAM_API_KEY": "sarvam-SECRET-key-888",
    "SECRETS_KEY": "secrets-key-SECRET-999",
    "WEBHOOK_SIGNING_SECRET": "whsec-SECRET-000",
}
ENV = dict(ENV_ANTHROPIC, **TWILIO)
SECRET_ENV = dict(ENV, **SECRETS)
QUESTION = {"messages": [{"role": "user", "content": "How do I call people in Telugu?"}], "page": "/app/campaigns"}


def _events(body: str) -> list[dict]:
    """The JSON payloads of a text/event-stream body, in order."""
    events = []
    for block in body.replace("\r\n", "\n").split("\n\n"):
        data = "\n".join(line[5:].strip() for line in block.split("\n") if line.startswith("data:"))
        if data:
            events.append(json.loads(data))
    return events


def _chat_module():
    assert chat is not None, "src/voiceagent/assistant/chat.py is missing"
    return chat


def _allowed() -> set[str]:
    """The allow-list's routes, whatever shape ALLOWED_LINKS takes."""
    raw = _chat_module().ALLOWED_LINKS
    if isinstance(raw, dict):
        items = list(raw.keys()) + [v for v in raw.values() if isinstance(v, str)]
    else:
        items = list(raw)
    routes = set()
    for item in items:
        if isinstance(item, str):
            routes.add(item)
        elif isinstance(item, dict):
            routes.add(item.get("to"))
        else:
            routes.update(part for part in item if isinstance(part, str) and part.startswith("/"))
    return {r for r in routes if isinstance(r, str) and r.startswith("/")}


async def _seed(sessions) -> None:
    async with sessions() as db:
        db.add(storage.Campaign(
            id="camp-1", name="Smile Dental", goal="Confirm Tuesday.", status=CampaignStatus.RUNNING,
            calling_days=[1, 2, 3, 4, 5, 6, 7], calling_hours_start=0, calling_hours_end=24,
        ))
        db.add(storage.Contact(
            id="ct-1", campaign_id="camp-1", full_name=CONTACT, phone_e164=PHONE,
            timezone="Asia/Kolkata", status=ContactStatus.PENDING,
        ))
        await db.commit()


def _ask(model: FakeModel, body: dict = QUESTION, env: dict = ENV):
    async def scenario(http, sessions):
        await _seed(sessions)
        with fake_model(model):
            return await http.post("/api/assistant/chat", json=body)

    return _run(scenario, _fresh_ip(), **env)


# ---------------------------------------------------------------------------


def test_the_assistant_streams_tokens_and_ends_with_done_and_links() -> None:
    model = FakeModel(REPLY)
    r = _ask(model)
    assert r.status_code == 200, _show(r)
    assert r.headers["content-type"].startswith("text/event-stream"), r.headers["content-type"]
    events = _events(r.text)
    assert len(events) >= 3, f"expected streamed tokens then a final frame: {events}"
    final = events[-1]
    assert final.get("done") is True, final
    assert isinstance(final.get("links"), list), final
    tokens = events[:-1]
    assert all(isinstance(e.get("token"), str) for e in tokens), tokens
    assert "".join(e["token"] for e in tokens).strip() == REPLY, "".join(e["token"] for e in tokens)
    assert model.calls() == 1, model.requests


def test_links_come_only_from_the_allow_list() -> None:
    reply = (
        "See [Campaigns](/app/campaigns) and [AI models](/app/models). "
        "Also [your keys](https://evil.example.com/steal) and [admin](/admin/secret) "
        "and [escape](/app/../../etc/passwd)."
    )
    r = _ask(FakeModel(reply))
    assert r.status_code == 200, _show(r)
    links = _events(r.text)[-1]["links"]
    allowed = _allowed()
    assert allowed, "ALLOWED_LINKS is empty"
    for link in links:
        assert isinstance(link.get("label"), str) and link["label"].strip(), link
        assert link.get("to") in allowed, f"{link} is not on the allow-list"
    text = json.dumps(links)
    assert "evil.example.com" not in text and "/admin" not in text and ".." not in text, links


def test_the_workspace_snapshot_has_no_secrets_or_phone_numbers() -> None:
    async def scenario(http, sessions):
        await _seed(sessions)
        await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        async with sessions() as db:
            snapshot = await _chat_module().snapshot(db)
        model = FakeModel(REPLY)
        with fake_model(model):
            r = await http.post("/api/assistant/chat", json=QUESTION)
        return snapshot, model, r

    snapshot, model, r = _run(scenario, _fresh_ip(), **SECRET_ENV)
    assert isinstance(snapshot, dict), type(snapshot)
    assert r.status_code == 200, _show(r)
    seen_by_model = json.dumps([kwargs for _, kwargs in model.requests], default=str, ensure_ascii=False)
    dumped = json.dumps(snapshot, default=str, ensure_ascii=False)
    forbidden = [ENV_KEY, ANTHROPIC_DB_KEY, *SECRETS.values(), PHONE, PHONE[3:], PHONE[-10:], CONTACT]
    for where, text in (("snapshot", dumped), ("model prompt", seen_by_model), ("reply", r.text)):
        leaks = [s for s in forbidden if s in text]
        assert not leaks, f"the {where} leaks {leaks}"
    assert "Smile Dental" in dumped, "the snapshot should name running campaigns"
    assert "Smile Dental" in seen_by_model, "the model should be given the snapshot"


def test_replies_are_capped_at_600_tokens_and_use_no_tools() -> None:
    model = FakeModel(REPLY)
    r = _ask(model)
    assert r.status_code == 200, _show(r)
    _, kwargs = model.requests[0]
    cap = kwargs.get("max_tokens") or kwargs.get("max_completion_tokens")
    assert cap is not None and cap <= 600, f"output must be capped at 600 tokens, got {cap}"
    assert not kwargs.get("tools"), "the assistant answers questions; it takes no actions"


def test_the_assistant_is_rate_limited_per_user() -> None:
    limit = getattr(_chat_module(), "RATE_LIMIT_PER_MINUTE", 10)

    async def scenario(http, sessions):
        owner = await _owner(http)
        member = await _member(http, owner["token"], "member@example.com")
        with fake_model(FakeModel(REPLY)):
            within = [
                (await http.post("/api/assistant/chat", json=QUESTION, headers=_bearer(owner["token"]))).status_code
                for _ in range(limit)
            ]
            over = await http.post("/api/assistant/chat", json=QUESTION, headers=_bearer(owner["token"]))
            other = await http.post("/api/assistant/chat", json=QUESTION, headers=_bearer(member["token"]))
        return within, over, other

    within, over, other = _run(scenario, _fresh_ip(), **ENV)
    assert within == [200] * limit, within
    assert over.status_code == 429, _show(over)
    assert other.status_code == 200, f"one user's limit must not block another: {_show(other)}"


def test_an_empty_conversation_is_refused() -> None:
    model = FakeModel(REPLY)
    r = _ask(model, body={"messages": []})
    assert r.status_code in (400, 422), _show(r)
    assert model.calls() == 0, "nothing to answer, so no model call"


def test_the_assistant_needs_a_login_when_access_control_is_on() -> None:
    async def scenario(http, sessions):
        owner = await _owner(http)
        with fake_model(FakeModel(REPLY)):
            anonymous = await http.post("/api/assistant/chat", json=QUESTION)
            signed_in = await http.post("/api/assistant/chat", json=QUESTION, headers=_bearer(owner["token"]))
        return anonymous, signed_in

    anonymous, signed_in = _run(scenario, _fresh_ip(), **ENV)
    assert anonymous.status_code == 401, _show(anonymous)
    assert signed_in.status_code == 200, _show(signed_in)


def test_the_product_guide_covers_what_people_ask_about() -> None:
    assert GUIDE.is_file(), f"{GUIDE} is missing"
    guide = GUIDE.read_text(encoding="utf-8").lower()
    assert len(guide) > 2000, "the guide should cover the product, not a paragraph"
    for topic in ("provider", "telephony", "twilio", "mcp", "telugu", "voice", ("heads-up", "pre-call"), "cost", "review"):
        alternatives = topic if isinstance(topic, tuple) else (topic,)
        assert any(word in guide for word in alternatives), f"the guide never mentions {topic!r}"


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
