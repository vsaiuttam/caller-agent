"""Model providers as a workspace resource: bring any LLM, never leak its key.

Covers docs/v3-spec.md §1: the preset list; env-configured providers shown
as read-only `env:<kind>` rows that a database row of the same kind
overrides; provider CRUD where the API key goes in once and only its last
four characters ever come back out (not in any response, not in plain text
in the database); owner/admin-only writes; the MCP SSRF guard on an
`openai_compatible` base URL; the one-completion `/test`; custom models with
their own prices; workspace model defaults (and a 409 for deleting one); and
a disabled provider falling back to the workspace default.

Drives the real FastAPI app over ASGI on a throwaway SQLite database with the
harness from test_accounts.py. No network and no real key: every model
client the app builds comes from a patched `make_client` (DEV's seam:
`providers.client_for` builds through it), private hosts resolve through a
patched `socket.getaddrinfo`, and an OpenAI-shaped endpoint is a stub server
on 127.0.0.1. Also home to the fakes the other v3 test files import. Runs
standalone (`python tests/test_providers_api.py`) or under pytest.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
from contextlib import asynccontextmanager, contextmanager
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import httpx  # noqa: E402
from sqlalchemy import text  # noqa: E402
from test_accounts import _bearer, _fresh_ip, _member, _owner, _run, _show  # noqa: E402
from test_mcp_api import _dns  # noqa: E402

from src.voiceagent import catalog, providers  # noqa: E402
from src.voiceagent.models import CallOutcome, Disposition, Sentiment  # noqa: E402

logging.getLogger().setLevel(logging.WARNING)
for _noisy in ("httpx", "httpcore"):
    logging.getLogger(_noisy).setLevel(logging.CRITICAL)

# Every key variable a provider might read, cleared so a developer's shell or
# .env can't change what these tests see.
NO_PROVIDERS = {
    name: None
    for name in (
        "MODEL_PROVIDER", "GEMINI_API_KEY", "ANTHROPIC_API_KEY", "OPENAI_API_KEY",
        "SARVAM_API_KEY", "NVIDIA_API_KEY", "GROQ_API_KEY", "OPENROUTER_API_KEY",
        "DEEPSEEK_API_KEY", "MISTRAL_API_KEY", "TOGETHER_API_KEY", "FIREWORKS_API_KEY",
        "XAI_API_KEY", "AZURE_OPENAI_API_KEY", "AZURE_OPENAI_ENDPOINT",
    )
}
BASE = dict(NO_PROVIDERS, SECRETS_KEY="test-secrets-key-1", MCP_ALLOW_PRIVATE_HOSTS=None)
ENV_KEY = "sk-ant-api03-ENVKEYSECRET-9876"
ENV_ANTHROPIC = dict(BASE, MODEL_PROVIDER="anthropic", ANTHROPIC_API_KEY=ENV_KEY)
LOCAL_DEV = dict(BASE, MCP_ALLOW_PRIVATE_HOSTS="true")

DB_KEY = "sk-proj-DBKEYSECRET-1234"
ANTHROPIC_DB_KEY = "sk-ant-api03-DBANTHROPICSECRET-4321"

KINDS = {
    "openai", "anthropic", "gemini", "sarvam", "groq", "openrouter", "deepseek",
    "mistral", "together", "fireworks", "xai", "nvidia", "azure_openai", "openai_compatible",
}
PRESET_FIELDS = {
    "kind", "label", "default_base_url", "needs_base_url", "key_url",
    "supports_tools", "api_shape", "popular_models",
}
PROVIDER_FIELDS = {
    "id", "kind", "label", "base_url", "source", "enabled", "supports_tools",
    "api_shape", "key_hint", "status", "last_error", "models_count",
}
MODEL_FIELDS = {"id", "name", "input_per_mtok", "output_per_mtok", "roles", "supports_tools", "source"}


# ---------------------------------------------------------------------------
# Fake model clients (shared with the other v3 test files)
# ---------------------------------------------------------------------------

DEFAULT_OUTCOME = CallOutcome(
    disposition=Disposition.COMPLETED,
    summary="Asha confirmed Tuesday at two.",
    needs_human_review=False,
    sentiment=Sentiment.POSITIVE,
)


def _request() -> httpx.Request:
    return httpx.Request("POST", "https://api.anthropic.com/v1/messages")


def overloaded(status: int = 529) -> Exception:
    """Anthropic's overload: 529 is `OverloadedError`, 5xx `InternalServerError`."""
    import anthropic

    cls = anthropic.OverloadedError if status == 529 else anthropic.InternalServerError
    return cls("Overloaded", response=httpx.Response(status, request=_request()), body=None)


def rate_limited() -> Exception:
    import anthropic

    return anthropic.RateLimitError("Rate limited", response=httpx.Response(429, request=_request()), body=None)


def rejected_key(key: str) -> Exception:
    """A 401 whose message quotes the key, the way some providers' errors do."""
    import anthropic

    return anthropic.AuthenticationError(
        f"Error code: 401 - invalid x-api-key {key}", response=httpx.Response(401, request=_request()), body=None
    )


class _Stream:
    """`messages.stream(...)`: an async context manager with `text_stream`."""

    def __init__(self, owner: "FakeModel", kwargs: dict) -> None:
        self._owner, self._kwargs = owner, kwargs

    async def __aenter__(self):
        self._owner._next("messages.stream", self._kwargs)
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    @property
    def text_stream(self):
        async def deltas():
            for piece in self._owner.pieces():
                await asyncio.sleep(0)
                yield piece

        return deltas()

    def __aiter__(self):
        async def events():
            for piece in self._owner.pieces():
                yield SimpleNamespace(type="content_block_delta", index=0,
                                      delta=SimpleNamespace(type="text_delta", text=piece))
            yield SimpleNamespace(type="message_stop")

        return events()

    async def get_final_message(self):
        return self._owner._message(self._kwargs)


class _Messages:
    def __init__(self, owner: "FakeModel") -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner._next("messages.create", kwargs)
        if kwargs.get("stream"):
            return _Stream(self._owner, kwargs).__aiter__()
        return self._owner._message(kwargs)

    def stream(self, **kwargs):
        return _Stream(self._owner, kwargs)

    async def parse(self, **kwargs):
        self._owner._next("messages.parse", kwargs)
        return SimpleNamespace(parsed_output=self._owner.outcome, stop_reason="end_turn", usage=None)


class _Completions:
    def __init__(self, owner: "FakeModel") -> None:
        self._owner = owner

    async def create(self, **kwargs):
        self._owner._next("chat.completions.create", kwargs)
        reply = self._owner.reply
        if kwargs.get("stream"):
            async def chunks():
                for piece in self._owner.pieces():
                    yield SimpleNamespace(
                        choices=[SimpleNamespace(index=0, finish_reason=None,
                                                 delta=SimpleNamespace(content=piece, tool_calls=None, role=None))],
                        usage=None,
                    )
                yield SimpleNamespace(
                    choices=[SimpleNamespace(index=0, finish_reason="stop",
                                             delta=SimpleNamespace(content=None, tool_calls=None, role=None))],
                    usage=None,
                )

            return chunks()
        return SimpleNamespace(
            id="chatcmpl-1",
            model=kwargs.get("model"),
            choices=[SimpleNamespace(
                index=0, finish_reason="stop",
                message=SimpleNamespace(role="assistant", content=reply, tool_calls=None, refusal=None),
            )],
            usage=None,
        )

    async def parse(self, **kwargs):
        self._owner._next("chat.completions.parse", kwargs)
        message = SimpleNamespace(role="assistant", content=None, parsed=self._owner.outcome, refusal=None)
        return SimpleNamespace(choices=[SimpleNamespace(index=0, finish_reason="stop", message=message)], usage=None)


class _Page:
    def __init__(self, ids: list[str]) -> None:
        self.data = [SimpleNamespace(id=i, object="model", owned_by="test") for i in ids]

    def __await__(self):
        async def page():
            return self

        return page().__await__()

    def __aiter__(self):
        async def items():
            for item in self.data:
                yield item

        return items()


class _Models:
    def __init__(self, owner: "FakeModel") -> None:
        self._owner = owner

    def list(self, **kwargs):
        self._owner._next("models.list", kwargs)
        return _Page(self._owner.model_ids)


class FakeModel:
    """A model client of either API shape, scripted per test.

    `failures` are raised by the next requests, in order; `always` is raised by
    every request. Every request is recorded as (method, kwargs). Awaitable,
    so it can stand in for a factory that is sync or async.
    """

    def __init__(
        self,
        reply: str = "Okay.",
        *,
        outcome: CallOutcome | None = None,
        failures: list[Exception] | None = None,
        always: Exception | None = None,
        model_ids: list[str] | None = None,
    ) -> None:
        self.reply = reply
        self.outcome = outcome or DEFAULT_OUTCOME
        self.failures = list(failures or [])
        self.always = always
        self.model_ids = model_ids or []
        self.requests: list[tuple[str, dict]] = []
        self.messages = _Messages(self)
        self.chat = SimpleNamespace(completions=_Completions(self))
        self.models = _Models(self)

    def pieces(self) -> list[str]:
        words = self.reply.split(" ")
        return [w + (" " if i < len(words) - 1 else "") for i, w in enumerate(words)]

    def _next(self, method: str, kwargs: dict) -> None:
        self.requests.append((method, kwargs))
        if self.always is not None:
            raise self.always
        if self.failures:
            raise self.failures.pop(0)

    def _message(self, kwargs: dict):
        return SimpleNamespace(
            id="msg_1",
            type="message",
            role="assistant",
            model=kwargs.get("model"),
            content=[SimpleNamespace(type="text", text=self.reply)],
            stop_reason="end_turn",
            usage=None,
        )

    def calls(self, method: str | None = None) -> int:
        return sum(1 for m, _ in self.requests if method is None or m == method)

    def with_options(self, **kwargs) -> "FakeModel":
        return self

    async def close(self) -> None:
        pass

    def __await__(self):
        async def itself():
            return self

        return itself().__await__()


@contextmanager
def models_from(factory):
    """Every model client the app builds comes from `factory(provider)`.

    Patches `make_client` wherever the package holds it (providers, the app,
    the worker, ...). `providers.client_for` builds through it and keys its
    cache on the factory, so each test's fakes are honoured.
    """
    original = providers.make_client
    holders = [
        module
        for name, module in list(sys.modules.items())
        if name.startswith("src.voiceagent") and getattr(module, "make_client", None) is original
    ]

    def make_client(provider=None, *args, **kwargs):
        return factory(provider)

    for module in holders:
        module.make_client = make_client
    try:
        yield
    finally:
        for module in holders:
            module.make_client = original


@contextmanager
def fake_model(client: FakeModel):
    """Every model client the app builds is `client`."""
    with models_from(lambda provider: client):
        yield client


def by_provider(clients: dict[str, FakeModel], default: FakeModel | None = None):
    """A factory that picks the fake by the provider's id."""

    def factory(provider):
        pid = getattr(provider, "id", None)
        if pid in clients:
            return clients[pid]
        if default is None:
            raise AssertionError(f"no fake model client for provider {pid!r}")
        return default

    return factory


@asynccontextmanager
async def openai_stub(model_ids: tuple[str, ...] = ("llama3.1:8b",)):
    """An OpenAI-shaped endpoint on 127.0.0.1: `/models` and `/chat/completions`."""

    async def handle(reader, writer):
        try:
            data = b""
            while b"\r\n\r\n" not in data:
                chunk = await reader.read(4096)
                if not chunk:
                    return
                data += chunk
            head, _, rest = data.partition(b"\r\n\r\n")
            length = 0
            for line in head.split(b"\r\n")[1:]:
                name, _, value = line.partition(b":")
                if name.strip().lower() == b"content-length":
                    length = int(value.strip() or 0)
            while len(rest) < length:
                rest += await reader.read(4096)
            path = head.split(b" ")[1].decode().split("?")[0]
            if path.endswith("/models"):
                payload = {"object": "list", "data": [{"id": i, "object": "model"} for i in model_ids]}
                status = b"200 OK"
            elif path.endswith("/chat/completions"):
                payload = {
                    "id": "chatcmpl-1", "object": "chat.completion", "model": model_ids[0],
                    "choices": [{"index": 0, "finish_reason": "stop",
                                 "message": {"role": "assistant", "content": "ok"}}],
                    "usage": {"prompt_tokens": 1, "completion_tokens": 1, "total_tokens": 2},
                }
                status = b"200 OK"
            else:
                payload, status = {"error": "not found"}, b"404 Not Found"
            body = json.dumps(payload).encode()
            writer.write(
                b"HTTP/1.1 " + status + b"\r\nContent-Type: application/json\r\n"
                + f"Content-Length: {len(body)}\r\nConnection: close\r\n\r\n".encode() + body
            )
            await writer.drain()
        except ConnectionError:
            pass
        finally:
            writer.close()

    server = await asyncio.start_server(handle, "127.0.0.1", 0)
    try:
        yield f"http://127.0.0.1:{server.sockets[0].getsockname()[1]}/v1"
    finally:
        server.close()


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------


async def create_provider(http, headers: dict | None = None, **body) -> dict:
    """POST /api/providers; asserts 201 and returns the provider."""
    r = await http.post("/api/providers", json=body, headers=headers or {})
    assert r.status_code == 201, f"expected 201 creating a provider: {_show(r)}"
    return r.json()


async def get_json(http, url: str, headers: dict | None = None):
    r = await http.get(url, headers=headers or {})
    assert r.status_code == 200, f"expected 200: {_show(r)}"
    return r.json()


def _by_id(rows: list[dict]) -> dict[str, dict]:
    return {row["id"]: row for row in rows}


async def _stored_secrets(sessions) -> list[str]:
    async with sessions() as db:
        rows = (await db.execute(text("SELECT secret FROM llm_providers"))).all()
    return [row[0] or "" for row in rows]


# ---------------------------------------------------------------------------
# Presets and env rows
# ---------------------------------------------------------------------------


def test_presets_cover_every_documented_kind_in_one_of_two_api_shapes() -> None:
    async def scenario(http, sessions):
        return await get_json(http, "/api/providers/presets")

    presets = _run(scenario, _fresh_ip(), **BASE)
    assert isinstance(presets, list), presets
    by_kind = {p["kind"]: p for p in presets}
    assert KINDS <= set(by_kind), f"missing presets: {sorted(KINDS - set(by_kind))}"
    for kind, preset in by_kind.items():
        assert PRESET_FIELDS <= set(preset), f"{kind} lacks {sorted(PRESET_FIELDS - set(preset))}"
        assert preset["api_shape"] in ("anthropic", "openai"), preset
        assert isinstance(preset["label"], str) and preset["label"].strip(), preset
        assert isinstance(preset["supports_tools"], bool), preset
        assert isinstance(preset["popular_models"], list), preset
    assert by_kind["anthropic"]["api_shape"] == "anthropic"
    assert by_kind["openai"]["api_shape"] == "openai"
    assert by_kind["openai_compatible"]["needs_base_url"] is True
    assert by_kind["azure_openai"]["needs_base_url"] is True
    assert by_kind["openai"]["needs_base_url"] is False
    assert by_kind["anthropic"]["popular_models"], "the anthropic preset lists its catalog models"


def test_an_env_key_is_listed_as_a_read_only_env_row() -> None:
    """ANTHROPIC_API_KEY shows up as `env:anthropic`, source env; PATCH and DELETE get 403."""

    async def scenario(http, sessions):
        listed = await http.get("/api/providers")
        patched = await http.patch("/api/providers/env:anthropic", json={"label": "Mine now"})
        deleted = await http.delete("/api/providers/env:anthropic")
        after = await http.get("/api/providers")
        return listed, patched, deleted, after

    listed, patched, deleted, after = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert listed.status_code == 200, _show(listed)
    rows = _by_id(listed.json())
    assert "env:anthropic" in rows, f"no env row: {sorted(rows)}"
    row = rows["env:anthropic"]
    assert PROVIDER_FIELDS <= set(row), f"missing {sorted(PROVIDER_FIELDS - set(row))}"
    assert row["source"] == "env" and row["kind"] == "anthropic", row
    assert row["api_shape"] == "anthropic" and row["enabled"] is True, row
    assert row["key_hint"] == ENV_KEY[-4:], row["key_hint"]
    assert all(r["source"] == "env" for r in rows.values()), "only env rows exist on a fresh database"
    assert patched.status_code == 403, _show(patched)
    assert deleted.status_code == 403, _show(deleted)
    assert "env:anthropic" in _by_id(after.json())
    for response in (listed, patched, deleted, after):
        assert ENV_KEY not in response.text, "the env key came back out of the API"


def test_without_keys_or_rows_the_provider_list_is_empty() -> None:
    async def scenario(http, sessions):
        return await get_json(http, "/api/providers")

    assert _run(scenario, _fresh_ip(), **BASE) == []


# ---------------------------------------------------------------------------
# CRUD
# ---------------------------------------------------------------------------


def test_a_new_provider_comes_back_with_a_key_hint_never_the_key() -> None:
    async def scenario(http, sessions):
        created = await create_provider(http, kind="openai", api_key=DB_KEY)
        listed = await get_json(http, "/api/providers")
        presets = await get_json(http, "/api/providers/presets")
        return created, listed, presets

    created, listed, presets = _run(scenario, _fresh_ip(), **BASE)
    assert PROVIDER_FIELDS <= set(created), f"missing {sorted(PROVIDER_FIELDS - set(created))}"
    assert not {"api_key", "secret", "key"} & set(created), sorted(created)
    assert created["kind"] == "openai" and created["source"] == "db", created
    assert not created["id"].startswith("env:"), created["id"]
    openai_label = next(p["label"] for p in presets if p["kind"] == "openai")
    assert created["label"] == openai_label, "the label defaults to the preset's"
    assert created["key_hint"] == DB_KEY[-4:], created["key_hint"]
    assert created["api_shape"] == "openai" and created["enabled"] is True, created
    assert created["status"] in ("ok", "untested", "error"), created["status"]
    assert isinstance(created["models_count"], int), created
    assert [r["id"] for r in listed] == [created["id"]], listed


def test_a_providers_key_never_appears_in_any_response_or_in_the_database() -> None:
    new_key = "sk-proj-ROTATEDSECRET-5678"

    async def scenario(http, sessions):
        texts = []
        r = await http.post("/api/providers", json={"kind": "openai", "api_key": DB_KEY, "label": "Team OpenAI"})
        assert r.status_code == 201, _show(r)
        pid = r.json()["id"]
        texts.append(r.text)
        with fake_model(FakeModel("pong", model_ids=["gpt-test"])):
            for method, url, body in [
                ("GET", "/api/providers", None),
                ("GET", f"/api/providers/{pid}/models", None),
                ("POST", f"/api/providers/{pid}/test", None),
                ("PATCH", f"/api/providers/{pid}", {"label": "Renamed"}),
                ("PATCH", f"/api/providers/{pid}", {"api_key": new_key}),
                ("GET", "/api/providers", None),
                ("GET", "/api/model-defaults", None),
                ("GET", "/api/health", None),
                ("GET", "/api/models", None),
            ]:
                texts.append((await http.request(method, url, json=body)).text)
        return texts, await _stored_secrets(sessions)

    texts, stored = _run(scenario, _fresh_ip(), **BASE)
    leaks = [(key, t[:160]) for t in texts for key in (DB_KEY, new_key) if key in t]
    assert not leaks, f"a provider key came back out of the API: {leaks}"
    assert stored and all(DB_KEY not in s and new_key not in s for s in stored), "keys stored in plain text"


def test_a_database_row_takes_precedence_over_the_env_key_of_the_same_kind() -> None:
    async def scenario(http, sessions):
        created = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        return created, await get_json(http, "/api/providers")

    created, listed = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    anthropic_rows = [r for r in listed if r["kind"] == "anthropic"]
    assert [r["id"] for r in anthropic_rows] == [created["id"]], (
        f"the env row should give way to the database row of its kind: {anthropic_rows}"
    )


def test_editing_a_provider_changes_its_label_key_and_enabled_flag() -> None:
    new_key = "sk-proj-SECONDKEY-0042"

    async def scenario(http, sessions):
        created = await create_provider(http, kind="openai", api_key=DB_KEY)
        url = f"/api/providers/{created['id']}"
        renamed = await http.patch(url, json={"label": "Support team key"})
        rekeyed = await http.patch(url, json={"api_key": new_key})
        disabled = await http.patch(url, json={"enabled": False})
        listed = await get_json(http, "/api/providers")
        missing = await http.patch("/api/providers/no-such-provider", json={"label": "x"})
        return renamed, rekeyed, disabled, listed, missing

    renamed, rekeyed, disabled, listed, missing = _run(scenario, _fresh_ip(), **BASE)
    for r in (renamed, rekeyed, disabled):
        assert r.status_code == 200, _show(r)
    assert renamed.json()["label"] == "Support team key", renamed.json()
    assert rekeyed.json()["key_hint"] == new_key[-4:], rekeyed.json()
    assert rekeyed.json()["label"] == "Support team key", "an omitted field was changed"
    assert disabled.json()["enabled"] is False, disabled.json()
    assert listed[0]["enabled"] is False and listed[0]["key_hint"] == "0042", listed
    assert missing.status_code == 404, _show(missing)


def test_a_custom_models_prices_are_listed_with_the_providers_models() -> None:
    custom = [
        {"id": "llama3.1:8b", "name": "Llama 3.1 8B", "input_per_mtok": 0.1, "output_per_mtok": 0.2},
        {"id": "my-finetune", "name": "My finetune", "input_per_mtok": None, "output_per_mtok": None},
    ]

    async def scenario(http, sessions):
        async with openai_stub(("llama3.1:8b",)) as base_url:
            with fake_model(FakeModel(model_ids=["llama3.1:8b"])):
                created = await create_provider(
                    http, kind="openai_compatible", label="Office Ollama",
                    base_url=base_url, api_key="ollama", custom_models=custom,
                )
                models = await get_json(http, f"/api/providers/{created['id']}/models")
        return created, models

    created, models = _run(scenario, _fresh_ip(), **LOCAL_DEV)
    assert created["base_url"] and created["base_url"].startswith("http://127.0.0.1"), created
    by_id = {m["id"]: m for m in models}
    assert {"llama3.1:8b", "my-finetune"} <= set(by_id), sorted(by_id)
    for model in models:
        assert MODEL_FIELDS <= set(model), f"{model.get('id')} lacks {sorted(MODEL_FIELDS - set(model))}"
        assert model["source"] in ("catalog", "custom", "discovered"), model
    assert by_id["my-finetune"]["source"] == "custom", by_id["my-finetune"]
    assert by_id["my-finetune"]["input_per_mtok"] is None, "an unset price is null, never 0"
    assert by_id["my-finetune"]["output_per_mtok"] is None
    assert by_id["llama3.1:8b"]["input_per_mtok"] == 0.1, by_id["llama3.1:8b"]
    assert by_id["llama3.1:8b"]["output_per_mtok"] == 0.2
    assert created["models_count"] >= 2, created


def test_an_env_providers_models_come_from_the_priced_catalog() -> None:
    async def scenario(http, sessions):
        return await get_json(http, "/api/providers/env:anthropic/models")

    models = {m["id"]: m for m in _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)}
    assert catalog.DEFAULT_CONVERSATION_MODEL in models, sorted(models)
    sonnet = models[catalog.DEFAULT_CONVERSATION_MODEL]
    spec = catalog.MODELS_BY_ID[catalog.DEFAULT_CONVERSATION_MODEL]
    assert sonnet["source"] == "catalog", sonnet
    assert sonnet["input_per_mtok"] == spec.input_per_mtok and sonnet["output_per_mtok"] == spec.output_per_mtok
    assert "conversation" in sonnet["roles"], sonnet


def test_bad_provider_bodies_are_refused_and_nothing_is_saved() -> None:
    async def scenario(http, sessions):
        statuses = {}
        for name, body in {
            "unknown kind": {"kind": "skynet", "api_key": DB_KEY},
            "no key": {"kind": "openai"},
            "compatible without a base url": {"kind": "openai_compatible", "api_key": "x"},
            "azure without a base url": {"kind": "azure_openai", "api_key": "x"},
        }.items():
            statuses[name] = (await http.post("/api/providers", json=body)).status_code
        return statuses, await get_json(http, "/api/providers")

    statuses, listed = _run(scenario, _fresh_ip(), **BASE)
    assert all(code in (400, 422) for code in statuses.values()), statuses
    assert listed == [], f"a refused provider was saved: {listed}"


def test_a_private_base_url_is_refused_unless_private_hosts_are_allowed() -> None:
    table = {"llm.example.com": ["93.184.216.34"], "intranet.example.com": ["10.0.0.7"], "localhost": ["127.0.0.1"]}
    unsafe = [
        "https://intranet.example.com/v1",
        "http://127.0.0.1:11434/v1",
        "https://localhost/v1",
        "https://169.254.169.254/latest/",
    ]

    async def refused(http, sessions):
        statuses = {}
        for url in unsafe:
            r = await http.post("/api/providers", json={"kind": "openai_compatible", "base_url": url, "api_key": "x"})
            statuses[url] = (r.status_code, r.text)
        good = await create_provider(http, kind="openai_compatible", base_url="https://llm.example.com/v1", api_key="x")
        moved = await http.patch(f"/api/providers/{good['id']}", json={"base_url": "https://intranet.example.com/v1"})
        return statuses, moved, await get_json(http, "/api/providers")

    async def allowed(http, sessions):
        async with openai_stub() as base_url:
            return await http.post(
                "/api/providers", json={"kind": "openai_compatible", "base_url": base_url, "api_key": "ollama"}
            )

    with _dns(table), fake_model(FakeModel()):
        statuses, moved, listed = _run(refused, _fresh_ip(), **BASE)
        local = _run(allowed, _fresh_ip(), **LOCAL_DEV)
    assert all(code == 400 for code, _ in statuses.values()), statuses
    assert all(body.strip() for _, body in statuses.values()), "a refusal should say why"
    assert moved.status_code == 400, _show(moved)
    assert [r["base_url"] for r in listed] == ["https://llm.example.com/v1"], listed
    assert local.status_code == 201, f"MCP_ALLOW_PRIVATE_HOSTS should allow a local model server: {_show(local)}"


# ---------------------------------------------------------------------------
# Roles
# ---------------------------------------------------------------------------


def test_members_can_list_providers_but_only_owners_and_admins_change_them() -> None:
    async def scenario(http, sessions):
        owner = await _owner(http)
        admin = await _member(http, owner["token"], "admin@example.com", role="admin")
        member = await _member(http, owner["token"], "member@example.com")
        as_owner, as_admin, as_member = (_bearer(u["token"]) for u in (owner, admin, member))

        anonymous = await http.get("/api/providers")
        by_admin = await create_provider(http, as_admin, kind="openai", api_key=DB_KEY)
        pid = by_admin["id"]
        defaults = {
            "conversation": {"provider_id": "env:anthropic", "model": catalog.DEFAULT_CONVERSATION_MODEL},
            "extraction": {"provider_id": "env:anthropic", "model": catalog.DEFAULT_EXTRACTION_MODEL},
        }
        member_reads = [
            (await http.get(url, headers=as_member)).status_code
            for url in ("/api/providers", "/api/providers/presets", "/api/model-defaults")
        ]
        member_writes = [
            (await http.request(method, url, json=body, headers=as_member)).status_code
            for method, url, body in [
                ("POST", "/api/providers", {"kind": "groq", "api_key": "gsk-member"}),
                ("PATCH", f"/api/providers/{pid}", {"label": "Mine"}),
                ("DELETE", f"/api/providers/{pid}", None),
                ("PUT", "/api/model-defaults", defaults),
            ]
        ]
        owner_put = await http.put("/api/model-defaults", json=defaults, headers=as_owner)
        owner_delete = await http.delete(f"/api/providers/{pid}", headers=as_owner)
        return anonymous, member_reads, member_writes, owner_put, owner_delete

    anonymous, reads, writes, owner_put, owner_delete = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert anonymous.status_code == 401, _show(anonymous)
    assert reads == [200, 200, 200], f"members may read providers and defaults: {reads}"
    assert writes == [403, 403, 403, 403], f"member writes must be refused with 403: {writes}"
    assert owner_put.status_code == 200, _show(owner_put)
    assert owner_delete.status_code == 204, _show(owner_delete)


# ---------------------------------------------------------------------------
# /test
# ---------------------------------------------------------------------------


def test_testing_a_provider_runs_one_tiny_completion_and_reports_ok() -> None:
    fake = FakeModel("pong")

    async def scenario(http, sessions):
        created = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        with fake_model(fake):
            r = await http.post(f"/api/providers/{created['id']}/test")
        listed = _by_id(await get_json(http, "/api/providers"))
        return r, listed[created["id"]]

    r, row = _run(scenario, _fresh_ip(), **BASE)
    assert r.status_code == 200, _show(r)
    result = r.json()
    assert result["ok"] is True, result
    assert isinstance(result["latency_ms"], (int, float)) and result["latency_ms"] >= 0, result
    assert isinstance(result["model"], str) and result["model"], result
    assert not result.get("error"), result
    assert fake.calls() == 1, f"one tiny completion, not {fake.requests}"
    method, kwargs = fake.requests[0]
    assert method == "messages.create", method
    assert kwargs.get("max_tokens", 0) <= 50, f"the test completion should be tiny: {kwargs.get('max_tokens')}"
    assert row["status"] == "ok" and not row["last_error"], row


def test_a_failed_provider_test_reports_the_error_without_the_key() -> None:
    async def scenario(http, sessions):
        created = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        with fake_model(FakeModel(always=rejected_key(ANTHROPIC_DB_KEY))):
            r = await http.post(f"/api/providers/{created['id']}/test")
        listed = await http.get("/api/providers")
        return r, listed

    r, listed = _run(scenario, _fresh_ip(), **BASE)
    assert r.status_code == 200, f"a failed test is a result, not a server error: {_show(r)}"
    result = r.json()
    assert result["ok"] is False, result
    assert isinstance(result.get("error"), str) and result["error"].strip(), result
    assert ANTHROPIC_DB_KEY not in r.text and ANTHROPIC_DB_KEY not in listed.text, "the key leaked via the error"
    row = listed.json()[0]
    assert row["status"] == "error" and row["last_error"], row


# ---------------------------------------------------------------------------
# Workspace defaults
# ---------------------------------------------------------------------------


def test_model_defaults_fall_back_to_the_env_provider_when_unset() -> None:
    async def scenario(http, sessions):
        return await get_json(http, "/api/model-defaults")

    defaults = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert defaults == {
        "conversation": {"provider_id": "env:anthropic", "model": catalog.DEFAULT_CONVERSATION_MODEL},
        "extraction": {"provider_id": "env:anthropic", "model": catalog.DEFAULT_EXTRACTION_MODEL},
    }, defaults


def test_model_defaults_round_trip() -> None:
    async def scenario(http, sessions):
        created = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        body = {
            "conversation": {"provider_id": created["id"], "model": "claude-haiku-4-5"},
            "extraction": {"provider_id": created["id"], "model": "claude-opus-5"},
        }
        put = await http.put("/api/model-defaults", json=body)
        return body, put, await get_json(http, "/api/model-defaults")

    body, put, got = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert put.status_code == 200, _show(put)
    assert put.json() == body, put.json()
    assert got == body, got


def test_model_defaults_must_name_a_known_provider_and_a_model_it_offers() -> None:
    async def scenario(http, sessions):
        created = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        good = {"provider_id": created["id"], "model": "claude-opus-5"}
        unknown_provider = await http.put(
            "/api/model-defaults",
            json={"conversation": {"provider_id": "nope", "model": "claude-sonnet-5"}, "extraction": good},
        )
        wrong_model = await http.put(
            "/api/model-defaults",
            json={"conversation": {"provider_id": created["id"], "model": "gemini-3.5-flash"}, "extraction": good},
        )
        return unknown_provider, wrong_model, await get_json(http, "/api/model-defaults")

    unknown_provider, wrong_model, after = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert unknown_provider.status_code in (400, 404, 422), _show(unknown_provider)
    assert wrong_model.status_code in (400, 422), _show(wrong_model)
    assert after["conversation"]["provider_id"] == "env:anthropic", "a refused PUT changed the defaults"


def test_deleting_a_workspace_default_provider_is_refused_with_409() -> None:
    async def scenario(http, sessions):
        created = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        await http.put("/api/model-defaults", json={
            "conversation": {"provider_id": created["id"], "model": "claude-sonnet-5"},
            "extraction": {"provider_id": "env:anthropic", "model": "claude-opus-5"},
        })
        r = await http.delete(f"/api/providers/{created['id']}")
        return created, r, await get_json(http, "/api/providers")

    created, r, listed = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert r.status_code == 409, _show(r)
    assert r.json().get("detail"), "a 409 should say why"
    assert created["id"] in _by_id(listed), "the default provider was deleted anyway"


def test_deleting_a_provider_that_is_not_a_default_removes_it() -> None:
    async def scenario(http, sessions):
        created = await create_provider(http, kind="openai", api_key=DB_KEY)
        r = await http.delete(f"/api/providers/{created['id']}")
        again = await http.delete(f"/api/providers/{created['id']}")
        return r, again, await get_json(http, "/api/providers"), await _stored_secrets(sessions)

    r, again, listed, stored = _run(scenario, _fresh_ip(), **BASE)
    assert r.status_code == 204, _show(r)
    assert again.status_code == 404, _show(again)
    assert listed == [] and stored == [], (listed, stored)


def test_a_disabled_or_deleted_provider_falls_back_to_the_workspace_default() -> None:
    """A campaign pointing at a switched-off provider still calls, on the default, with a warning."""

    class Warnings(logging.Handler):
        def __init__(self) -> None:
            super().__init__(logging.WARNING)
            self.records: list[logging.LogRecord] = []

        def emit(self, record: logging.LogRecord) -> None:
            self.records.append(record)

    async def scenario(http, sessions):
        default = await create_provider(http, kind="anthropic", api_key=ANTHROPIC_DB_KEY)
        other = await create_provider(http, kind="openai", api_key=DB_KEY)
        gone = await create_provider(http, kind="groq", api_key="gsk-GONE-0001")
        r = await http.put("/api/model-defaults", json={
            "conversation": {"provider_id": default["id"], "model": "claude-sonnet-5"},
            "extraction": {"provider_id": default["id"], "model": "claude-opus-5"},
        })
        assert r.status_code == 200, _show(r)
        assert (await http.patch(f"/api/providers/{other['id']}", json={"enabled": False})).status_code == 200
        assert (await http.delete(f"/api/providers/{gone['id']}")).status_code == 204

        handler = Warnings()
        logging.getLogger().addHandler(handler)
        try:
            disabled = await providers.provider_for(other["id"], "conversation")
            deleted = await providers.provider_for(gone["id"], "extraction")
            unset = await providers.provider_for(None, "conversation")
        finally:
            logging.getLogger().removeHandler(handler)
        return default["id"], disabled, deleted, unset, handler.records

    default_id, disabled, deleted, unset, warnings = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert disabled.id == default_id, f"a disabled provider should fall back to the default, got {disabled.id}"
    assert deleted.id == default_id, f"a deleted provider should fall back to the default, got {deleted.id}"
    assert unset.id == default_id, unset.id
    assert len(warnings) >= 2, "each fallback should log a warning"


def test_the_old_models_catalog_still_answers() -> None:
    async def scenario(http, sessions):
        return await get_json(http, "/api/models")

    body = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert body["models"] and body["pricing_as_of"] == catalog.PRICING_AS_OF, body.keys()


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
