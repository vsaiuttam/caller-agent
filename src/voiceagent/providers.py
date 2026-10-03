"""Which model provider this deployment talks to.

There are two API shapes here, not five. Anthropic has its own Messages API;
everyone else worth using — Google Gemini, OpenAI, Sarvam, NVIDIA — speaks
the OpenAI `chat/completions` shape and differs only in a base URL and which
environment variable holds the key. So adding a provider is a row in the
table below, not a new code path, and comparing two of them is one line in
`.env`.

That matters more than it sounds. "Which model is best for Hindi?" is not a
question anyone should answer from a benchmark page — it is a question you
answer by running your own campaign past the same difficult persona on two
providers and listening. This module is what makes that a config change.

Selection is deliberate rather than magical: `MODEL_PROVIDER` names one
explicitly, and with it unset we take the first provider below that holds a
usable key. "Usable" excludes the placeholders that ship in `.env.example` —
a key of `sk-ant-...` reads as configured to a naive presence check and then
fails on the first real call, which is a confusing way to find out you never
set a key.

v3 makes providers a workspace resource as well. `PRESETS` lists every
provider the console can connect (still two API shapes); rows in
`llm_providers` hold a preset, a sealed key and an optional base URL; and a
campaign names one per role. `runtime()` turns that choice into a client —
cached per provider until its row changes — with a fallback to the
workspace default, then to the env provider above, so a deleted or
disabled provider degrades a call rather than failing it.
"""

from __future__ import annotations

import asyncio
import logging
import os
import time
from dataclasses import dataclass, field, replace
from typing import Any

logger = logging.getLogger(__name__)

ANTHROPIC_API = "anthropic"
OPENAI_API = "openai"


@dataclass(frozen=True)
class ProviderSpec:
    id: str
    label: str
    # Which client library speaks to it. Only two values exist by design.
    api: str
    key_env: str
    # None means the SDK's own default host.
    base_url: str | None = None
    console: str = ""
    note: str = ""
    # Whether its models can call tools (the user's MCP apps) mid-call.
    # Off where the endpoint either rejects `tools` or accepts and ignores
    # them — the second is worse, a model saying "let me check" and never
    # checking.
    supports_tools: bool = False
    # Where to go for a key, shown next to the key field.
    key_url: str = ""
    # True where there is no default host: every account has its own
    # (Azure) or the server is the user's own (Ollama, vLLM, LM Studio).
    needs_base_url: bool = False
    # Env var holding the base URL for an env-configured row of a preset
    # that needs one.
    base_url_env: str = ""
    # The OpenAI shape is shared, not identical. OpenAI's own reasoning
    # models refuse `max_tokens` and want `max_completion_tokens`; Mistral
    # refuses unknown fields such as `stream_options`.
    max_tokens_param: str = "max_tokens"
    stream_usage: bool = True

    @property
    def kind(self) -> str:
        """The preset id. A ProviderSpec *is* its preset; see `Provider`."""
        return self.id


# Order is the auto-detection order when MODEL_PROVIDER is unset. Anthropic
# sits below Gemini because this project started on Anthropic and its
# placeholder key is still in most .env files — a real Gemini key is a
# stronger signal of intent than a leftover Anthropic line.
PROVIDERS: list[ProviderSpec] = [
    ProviderSpec(
        id="gemini",
        label="Google Gemini",
        api=OPENAI_API,
        key_env="GEMINI_API_KEY",
        base_url="https://generativelanguage.googleapis.com/v1beta/openai/",
        console="https://aistudio.google.com",
        note="97 languages on the Live API, Hindi and Urdu included.",
        supports_tools=True,
    ),
    ProviderSpec(
        id="anthropic",
        label="Anthropic",
        api=ANTHROPIC_API,
        key_env="ANTHROPIC_API_KEY",
        console="https://console.anthropic.com",
        note="Prompt caching with two breakpoints; the original path here.",
        supports_tools=True,
    ),
    ProviderSpec(
        id="openai",
        label="OpenAI",
        api=OPENAI_API,
        key_env="OPENAI_API_KEY",
        console="https://platform.openai.com",
        note="Realtime speech-to-speech and SIP telephony from the same key.",
        supports_tools=True,
    ),
    ProviderSpec(
        id="sarvam",
        label="Sarvam AI",
        api=OPENAI_API,
        key_env="SARVAM_API_KEY",
        base_url="https://api.sarvam.ai/v1",
        console="https://dashboard.sarvam.ai",
        note="Indic-first; the strongest option for code-mixed Hinglish.",
    ),
    ProviderSpec(
        id="nvidia",
        label="NVIDIA NIM",
        api=OPENAI_API,
        key_env="NVIDIA_API_KEY",
        base_url="https://integrate.api.nvidia.com/v1",
        console="https://build.nvidia.com",
        note="Free evaluation credits, ~40 requests/minute, variable latency. Nemotron Lightning on the call (thinking off), Ultra after it. No tool calls.",
    ),
]

PROVIDERS_BY_ID = {p.id: p for p in PROVIDERS}

OPENAI_COMPATIBLE = "openai_compatible"

# Every provider a workspace can connect from the console. The five above
# stay the env auto-detection list — adding a preset here must not change
# which vendor an existing deployment silently talks to — and the rest are
# reached by adding them on the AI models page (or by their env key, which
# lists them as a read-only row). Base URLs per docs/research.md §6.4.
PRESETS: list[ProviderSpec] = [
    replace(PROVIDERS_BY_ID["openai"], key_url="https://platform.openai.com/api-keys",
            max_tokens_param="max_completion_tokens"),
    replace(PROVIDERS_BY_ID["anthropic"], key_url="https://console.anthropic.com/settings/keys"),
    replace(PROVIDERS_BY_ID["gemini"], key_url="https://aistudio.google.com/apikey"),
    replace(PROVIDERS_BY_ID["sarvam"], key_url="https://dashboard.sarvam.ai"),
    ProviderSpec(
        id="groq",
        label="Groq",
        api=OPENAI_API,
        key_env="GROQ_API_KEY",
        base_url="https://api.groq.com/openai/v1",
        console="https://console.groq.com",
        key_url="https://console.groq.com/keys",
        note="The lowest time-to-first-token for Llama and Qwen models.",
        supports_tools=True,
    ),
    ProviderSpec(
        id="openrouter",
        label="OpenRouter",
        api=OPENAI_API,
        key_env="OPENROUTER_API_KEY",
        base_url="https://openrouter.ai/api/v1",
        console="https://openrouter.ai",
        key_url="https://openrouter.ai/keys",
        note="Hundreds of models behind one key, billed at the underlying price.",
        supports_tools=True,
    ),
    ProviderSpec(
        id="deepseek",
        label="DeepSeek",
        api=OPENAI_API,
        key_env="DEEPSEEK_API_KEY",
        base_url="https://api.deepseek.com",
        console="https://platform.deepseek.com",
        key_url="https://platform.deepseek.com/api_keys",
        note="Peak and off-peak pricing; the off-peak rate is half.",
        supports_tools=True,
    ),
    ProviderSpec(
        id="mistral",
        label="Mistral AI",
        api=OPENAI_API,
        key_env="MISTRAL_API_KEY",
        base_url="https://api.mistral.ai/v1",
        console="https://console.mistral.ai",
        key_url="https://console.mistral.ai/api-keys",
        note="Mostly OpenAI-compatible; test tool use before relying on it.",
        supports_tools=True,
        stream_usage=False,
    ),
    ProviderSpec(
        id="together",
        label="Together AI",
        api=OPENAI_API,
        key_env="TOGETHER_API_KEY",
        base_url="https://api.together.xyz/v1",
        console="https://api.together.ai",
        key_url="https://api.together.ai/settings/api-keys",
        note="Open-weight models (Llama, Qwen, DeepSeek) on shared hosting.",
        supports_tools=True,
    ),
    ProviderSpec(
        id="fireworks",
        label="Fireworks AI",
        api=OPENAI_API,
        key_env="FIREWORKS_API_KEY",
        base_url="https://api.fireworks.ai/inference/v1",
        console="https://fireworks.ai",
        key_url="https://fireworks.ai/account/api-keys",
        note="Open-weight models tuned for low latency.",
        supports_tools=True,
    ),
    ProviderSpec(
        id="xai",
        label="xAI",
        api=OPENAI_API,
        key_env="XAI_API_KEY",
        base_url="https://api.x.ai/v1",
        console="https://console.x.ai",
        key_url="https://console.x.ai",
        note="Grok models.",
        supports_tools=True,
    ),
    replace(PROVIDERS_BY_ID["nvidia"], key_url="https://build.nvidia.com"),
    ProviderSpec(
        id="azure_openai",
        label="Azure OpenAI",
        api=OPENAI_API,
        key_env="AZURE_OPENAI_API_KEY",
        base_url_env="AZURE_OPENAI_BASE_URL",
        console="https://ai.azure.com",
        key_url="https://portal.azure.com",
        note="Use the v1 endpoint, https://<resource>.openai.azure.com/openai/v1/, "
        "and your deployment name as the model.",
        supports_tools=True,
        needs_base_url=True,
        max_tokens_param="max_completion_tokens",
    ),
    ProviderSpec(
        id=OPENAI_COMPATIBLE,
        label="OpenAI-compatible",
        api=OPENAI_API,
        key_env="OPENAI_COMPATIBLE_API_KEY",
        base_url_env="OPENAI_COMPATIBLE_BASE_URL",
        note="Ollama, vLLM, LM Studio, or any other server that speaks "
        "chat/completions. Tools stay off: many such servers accept them and "
        "then ignore them.",
        needs_base_url=True,
    ),
]

PRESETS_BY_KIND = {p.id: p for p in PRESETS}


def _is_placeholder(value: str) -> bool:
    """Whether a key is one of the dummy values that ship in .env.example.

    Checked because `os.getenv("ANTHROPIC_API_KEY")` being truthy is not the
    same as having a key, and the difference only shows up as an opaque 401
    on the first call — after the UI has spent a screen telling you
    everything is configured.
    """
    stripped = value.strip()
    low = stripped.lower()
    return (
        not stripped
        or "..." in stripped
        or low in {"changeme", "your-key-here"}
        or ("your-" in low and "-key-here" in low)
    )


def api_key(spec: ProviderSpec) -> str | None:
    """The configured key for this provider, or None if it isn't really set."""
    value = os.getenv(spec.key_env, "")
    return None if _is_placeholder(value) else value.strip()


def configured() -> list[ProviderSpec]:
    return [spec for spec in PROVIDERS if api_key(spec)]


def active() -> ProviderSpec | None:
    """The provider this process will use, or None if none is usable."""
    named = os.getenv("MODEL_PROVIDER", "").strip().lower()
    if named:
        # An explicit choice with no usable key resolves to nothing rather
        # than falling through to auto-detection. Quietly calling a different
        # vendor than the one someone named — on their key, at their cost — is
        # worse than refusing and saying why.
        spec = PROVIDERS_BY_ID.get(named)
        return spec if spec and api_key(spec) else None
    return next(iter(configured()), None)


def active_id() -> str:
    spec = active()
    return spec.id if spec else ""


def missing_key_message() -> str:
    """What to tell a human when nothing is usable. Names the actual problem."""
    named = os.getenv("MODEL_PROVIDER", "").strip().lower()
    if named:
        spec = PROVIDERS_BY_ID.get(named)
        if spec is None:
            known = ", ".join(p.id for p in PROVIDERS)
            return (
                f"MODEL_PROVIDER is set to {named!r}, which is not a provider this "
                f"build knows about. Known providers: {known}."
            )
        return (
            f"MODEL_PROVIDER selects {spec.label}, but {spec.key_env} does not hold a "
            f"real key. Set it in .env and restart, or unset MODEL_PROVIDER to use "
            f"whichever key is configured."
        )

    options = ", ".join(f"{p.key_env} ({p.label})" for p in PROVIDERS)
    return (
        "No model provider is configured, so there is nothing to talk to. "
        f"Set one of these in .env and restart the server: {options}."
    )


def make_client(spec: ProviderSpec | None = None):
    """An async client for `spec`, already carrying its key and base URL.

    Returns `AsyncAnthropic` or `AsyncOpenAI`. Both are closed with
    `await client.close()`, which is the only part of their surface this
    codebase relies on being identical.
    """
    spec = spec or active()
    if spec is None:
        raise RuntimeError(missing_key_message())

    if isinstance(spec, Provider):
        # A resolved provider carries its own key and address: a database
        # row's sealed key, or the env key it was built from. Local servers
        # (Ollama) take no key, but the SDK insists on one.
        key, base_url = spec.secret or "not-needed", spec.base_url
    else:
        key, base_url = api_key(spec), spec.base_url
        if key is None:
            raise RuntimeError(
                f"{spec.label} is selected but {spec.key_env} is not set to a real key."
            )

    if spec.api == ANTHROPIC_API:
        from anthropic import AsyncAnthropic

        if base_url:
            return AsyncAnthropic(api_key=key, base_url=base_url)
        return AsyncAnthropic(api_key=key)

    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=key, base_url=base_url)


# --------------------------------------------------------------------------
# Workspace providers: rows in `llm_providers`, plus the env keys
# --------------------------------------------------------------------------
#
# A campaign names a provider by id and gets a client for exactly that
# provider. Env keys keep working with no rows at all: each preset whose key
# is set appears as a read-only provider with id `env:<kind>`, and a database
# row of the same kind is listed ahead of it.

ENV_PREFIX = "env:"


class NoModelProvider(RuntimeError):
    """No provider is usable for a call: none configured, or all disabled.

    Raised before dialling. The runner puts the contact back without
    spending an attempt, since nothing was dialled.
    """

CONVERSATION_ROLE = "conversation"
EXTRACTION_ROLE = "extraction"
MODEL_DEFAULTS_KEY = "model_defaults"


@dataclass(frozen=True)
class Provider:
    """A provider ready to call: its preset's behaviour plus a key and host.

    Shaped like `ProviderSpec` where the rest of the code reads it (`api`,
    `supports_tools`, `label`, `kind`), so the model paths take either.
    """

    id: str
    kind: str
    label: str
    api: str
    base_url: str | None
    supports_tools: bool
    source: str  # "db" | "env"
    enabled: bool = True
    custom_models: tuple[dict[str, Any], ...] = ()
    # Never logged, never serialised: repr=False keeps it out of tracebacks.
    secret: str = field(default="", repr=False)
    # Changes whenever the row does; part of the client cache key.
    stamp: str = ""
    max_tokens_param: str = "max_tokens"
    stream_usage: bool = True
    console: str = ""
    # Whether the stored key could be read with the current SECRETS_KEY.
    key_readable: bool = True

    @property
    def preset(self) -> ProviderSpec | None:
        return PRESETS_BY_KIND.get(self.kind)

    @property
    def key_hint(self) -> str:
        return key_hint(self.secret)

    def custom_model(self, model_id: str) -> dict[str, Any] | None:
        return next((m for m in self.custom_models if m.get("id") == model_id), None)


def key_hint(key: str | None) -> str:
    """The last four characters of a key, the only part ever shown again.

    Nothing for keys too short to spare four characters of.
    """
    key = (key or "").strip()
    return key[-4:] if len(key) >= 8 else ""


def env_provider(kind: str) -> Provider | None:
    """The read-only provider an env key configures, or None when unset."""
    spec = PRESETS_BY_KIND.get(kind)
    if spec is None:
        return None
    key = api_key(spec)
    base_url = spec.base_url
    if spec.base_url_env:
        base_url = os.getenv(spec.base_url_env, "").strip() or None
    if key is None or (spec.needs_base_url and not base_url):
        return None
    return Provider(
        id=ENV_PREFIX + kind,
        kind=kind,
        label=spec.label,
        api=spec.api,
        base_url=base_url,
        supports_tools=spec.supports_tools,
        source="env",
        secret=key,
        stamp="env",
        max_tokens_param=spec.max_tokens_param,
        stream_usage=spec.stream_usage,
        console=spec.console,
    )


def env_providers() -> list[Provider]:
    return [p for p in (env_provider(spec.id) for spec in PRESETS) if p is not None]


def from_row(row) -> Provider:
    """A `storage.LlmProvider` row as a Provider. An unreadable key reads as empty.

    A key sealed under a SECRETS_KEY that has since changed cannot be
    recovered; the provider stays listed, fails its test with a message
    asking for the key again, and nothing else on the page breaks.
    """
    from .mcp.secrets import SecretsUnavailable, unseal

    spec = PRESETS_BY_KIND.get(row.kind) or PRESETS_BY_KIND[OPENAI_COMPATIBLE]
    readable = True
    try:
        secret = str(unseal(row.secret).get("api_key") or "") if row.secret else ""
    except SecretsUnavailable:
        secret, readable = "", False
    updated = getattr(row, "updated_at", None)
    return Provider(
        id=row.id,
        kind=row.kind,
        label=row.label or spec.label,
        api=spec.api,
        base_url=(row.base_url or None) or spec.base_url,
        supports_tools=spec.supports_tools,
        source="db",
        enabled=bool(row.enabled),
        custom_models=tuple(row.custom_models or ()),
        secret=secret,
        stamp=updated.isoformat() if updated else "",
        max_tokens_param=spec.max_tokens_param,
        stream_usage=spec.stream_usage,
        console=spec.console,
        key_readable=readable,
    )


def _session_factory():
    # Looked up on the module at call time, not imported by name, so
    # whatever database the app is using right now (a test's) is the one asked.
    from . import storage

    return storage.SessionLocal


async def _with_session(session, work):
    if session is not None:
        return await work(session)
    async with _session_factory()() as db:
        return await work(db)


async def list_providers(session=None) -> list[Provider]:
    """Every provider the workspace can use: rows first, then env keys."""
    from sqlalchemy import select

    from .storage import LlmProvider

    async def load(db) -> list[Provider]:
        rows = (await db.scalars(select(LlmProvider).order_by(LlmProvider.created_at))).all()
        return [from_row(row) for row in rows]

    rows = await _with_session(session, load)
    # A row of the same kind replaces the env key's entry: the one managed
    # from the console is the one people mean.
    kinds = {row.kind for row in rows}
    return [*rows, *(p for p in env_providers() if p.kind not in kinds)]


async def get_provider(provider_id: str | None, session=None) -> Provider | None:
    """One provider by id, enabled or not, or None if there is no such thing."""
    if not provider_id:
        return None
    if provider_id.startswith(ENV_PREFIX):
        return env_provider(provider_id[len(ENV_PREFIX):])

    from .storage import LlmProvider

    async def load(db):
        row = await db.get(LlmProvider, provider_id)
        return from_row(row) if row is not None else None

    return await _with_session(session, load)


def usable(provider: Provider | None) -> bool:
    """Enabled and holding a key (local OpenAI-compatible servers need none)."""
    return (
        provider is not None
        and provider.enabled
        and provider.key_readable
        and bool(provider.secret or provider.kind == OPENAI_COMPATIBLE)
    )


async def workspace_defaults(session=None) -> dict[str, dict[str, str | None]]:
    """`{"conversation": {provider_id, model}, "extraction": {...}}` as stored.

    Values may be None: unset means "the active env provider and its catalog
    default", which `provider_for` and the model resolver fill in. Kept in
    the same settings row as the pre-v3 flat defaults, which it leaves alone.
    """
    from .storage import Setting

    async def load(db):
        return await db.get(Setting, MODEL_DEFAULTS_KEY)

    row = await _with_session(session, load)
    stored = row.value if row is not None and isinstance(row.value, dict) else {}
    result: dict[str, dict[str, str | None]] = {}
    for role in (CONVERSATION_ROLE, EXTRACTION_ROLE):
        entry = stored.get(role) if isinstance(stored.get(role), dict) else {}
        result[role] = {
            "provider_id": entry.get("provider_id") or None,
            "model": entry.get("model") or None,
        }
    return result


def fallback_provider() -> Provider | None:
    """Today's behaviour: the env provider this process auto-detects."""
    spec = active()
    return env_provider(spec.id) if spec else None


async def provider_for(
    provider_id: str | None, role: str = CONVERSATION_ROLE, session=None
) -> Provider | None:
    """The provider a campaign's role runs on.

    Its own, when set and usable; else the workspace default for the role;
    else the env provider. A campaign whose provider was deleted or disabled
    falls back rather than failing the call, and the log says so — the
    person being dialled should never be the one who finds out.
    """
    if provider_id:
        chosen = await get_provider(provider_id, session)
        if usable(chosen):
            return chosen
        logger.warning(
            "Provider %s is %s; using the workspace default for %s",
            provider_id,
            "unusable" if chosen is not None else "gone",
            role,
        )

    default_id = (await workspace_defaults(session))[role]["provider_id"]
    if default_id and default_id != provider_id:
        chosen = await get_provider(default_id, session)
        if usable(chosen):
            return chosen
        logger.warning("Workspace default provider %s is unusable; using the env provider", default_id)
    return await default_provider(session)


async def default_provider(session=None) -> Provider | None:
    """The provider used when nothing names one: today's env provider, as
    GET /api/model-defaults reports it; with no env key at all, the first
    usable console row, so a workspace set up entirely from the console
    works without also choosing defaults."""
    env = fallback_provider()
    if env is not None:
        return env
    rows = [p for p in await list_providers(session) if p.source == "db" and usable(p)]
    return rows[0] if rows else None


# Clients per provider. Building one costs a TLS handshake on its first
# request, so a call reuses whatever the last call built until the row
# changes. Keyed by the running loop too: an httpx pool belongs to the loop
# that opened it.
_clients: dict[str, tuple[tuple, Any]] = {}


def _fingerprint(provider: Provider) -> tuple:
    try:
        loop = id(asyncio.get_running_loop())
    except RuntimeError:
        loop = 0
    # `make_client` is part of the key so a stand-in factory (a test's) is
    # honoured rather than answered from the cache.
    return (provider.stamp, provider.base_url, hash(provider.secret), loop, id(make_client))


def invalidate(provider_id: str | None = None) -> None:
    """Forget cached clients: one provider's after its row changes, or all."""
    if provider_id is None:
        dropped = list(_clients.values())
        _clients.clear()
    else:
        entry = _clients.pop(provider_id, None)
        dropped = [entry] if entry else []
    for _, client in dropped:
        _close_later(client)


def _close_later(client) -> None:
    close = getattr(client, "close", None)
    if close is None:
        return
    try:
        asyncio.get_running_loop().create_task(close())
    except RuntimeError:
        pass  # no loop: the process is exiting, and the pool with it


def cached_client(provider: Provider):
    """A client for `provider`, shared across calls until its row changes.

    Callers must not close it.
    """
    key = _fingerprint(provider)
    entry = _clients.get(provider.id)
    if entry is not None and entry[0] == key:
        return entry[1]
    client = make_client(provider)
    _clients[provider.id] = (key, client)
    if entry is not None and entry[1] is not client:
        _close_later(entry[1])
    return client


async def client_for(provider_id: str | None, role: str = CONVERSATION_ROLE, session=None):
    """The cached client for a campaign's provider, with `provider_for`'s fallback.

    Raises RuntimeError with a readable message when nothing is usable.
    """
    provider = await provider_for(provider_id, role, session)
    if provider is None:
        raise RuntimeError(missing_key_message())
    return cached_client(provider)


@dataclass
class Runtime:
    """What one role of one call runs on: a client, its provider, the model."""

    client: Any
    provider: Provider | None
    model: str | None


async def choice(
    provider_id: str | None, model: str | None, role: str = CONVERSATION_ROLE, session=None
) -> tuple[Provider | None, str | None]:
    """(provider, model) a campaign's role will actually run on. See `runtime`."""
    from .catalog import resolve

    provider = await provider_for(provider_id, role, session)
    if provider is None:
        return None, model
    resolved = resolve(model, role, provider)
    if resolved != model:
        default = (await workspace_defaults(session))[role]
        if default["model"] and default["provider_id"] in (None, provider.id):
            resolved = resolve(default["model"], role, provider)
    return provider, resolved


async def runtime(
    provider_id: str | None,
    model: str | None,
    role: str = CONVERSATION_ROLE,
    *,
    default_client=None,
    session=None,
) -> Runtime:
    """Resolve a campaign's (provider, model) choice for `role` into a Runtime.

    The model is kept when the provider can run it. When it can't — the
    campaign names no provider and the workspace default is another vendor,
    or its provider fell back — the workspace default model is used if it
    belongs to the provider that won, and the provider's catalog default
    otherwise.

    `default_client` is the process's own client for the env provider (the
    worker builds one at start). It is reused whenever that is the provider
    that won, so a deployment with no provider rows runs exactly as before.
    """
    provider, resolved = await choice(provider_id, model, role, session)
    if provider is None:
        return Runtime(default_client, None, model)

    env = fallback_provider()
    if default_client is not None and env is not None and provider.id == env.id:
        return Runtime(default_client, provider, resolved)
    return Runtime(cached_client(provider), provider, resolved)


async def extraction_fallback(primary: Runtime, *, default_client=None, session=None) -> Runtime | None:
    """The workspace's default extractor, when it is a different provider.

    Where extraction goes after its own provider has been retried and is
    still overloaded. None when there is nowhere different to go.
    """
    default = (await workspace_defaults(session))[EXTRACTION_ROLE]
    provider = await provider_for(default["provider_id"], EXTRACTION_ROLE, session)
    if provider is None or (primary.provider is not None and provider.id == primary.provider.id):
        return None
    from .catalog import default_model, resolve

    model = resolve(default["model"], EXTRACTION_ROLE, provider) if default["model"] else default_model(
        EXTRACTION_ROLE, provider
    )
    env = fallback_provider()
    if default_client is not None and env is not None and provider.id == env.id:
        return Runtime(default_client, provider, model)
    return Runtime(cached_client(provider), provider, model)


def chat_params(provider, model: str, *, max_tokens: int, effort: str | None) -> dict[str, Any]:
    """The provider-specific part of a `chat/completions` request.

    With no provider (the pre-v3 path) the request is as it always was.
    Otherwise `reasoning_effort` goes only to models that take it — sent to
    a non-reasoning model it is a 400 on OpenAI and refused by strict
    servers — and the token cap uses the field the provider accepts.
    """
    from .catalog import MODELS_BY_ID

    spec = MODELS_BY_ID.get(model)
    if provider is None:
        params: dict[str, Any] = {"max_tokens": max_tokens}
        if effort and not (spec is not None and spec.thinking_toggle):
            params["reasoning_effort"] = effort
    else:
        params = {getattr(provider, "max_tokens_param", "max_tokens"): max_tokens}
        reasons = spec.reasoning if spec is not None else getattr(provider, "kind", "") == "gemini"
        if effort and reasons:
            params["reasoning_effort"] = effort
    if spec is not None and spec.thinking_toggle:
        # Models that think unless the chat template says otherwise. The
        # OpenAI SDK passes extra_body through to the request JSON.
        params["extra_body"] = {"chat_template_kwargs": {"enable_thinking": False}}
    return params


def stream_params(provider) -> dict[str, Any]:
    """`stream_options` where the provider accepts it (usage on the last chunk)."""
    if provider is None or getattr(provider, "stream_usage", True):
        return {"stream_options": {"include_usage": True}}
    return {}


async def test_provider(provider: Provider, model: str | None = None) -> dict[str, Any]:
    """One tiny completion against `provider`: `{ok, latency_ms, model, error?}`.

    A fresh client rather than the cached one, so the key just typed in is
    the key tested. The error is a sentence with nothing of the key in it.
    """
    from .catalog import CONVERSATION, default_model

    model = model or default_model(CONVERSATION, provider)
    if not provider.key_readable:
        return {"ok": False, "latency_ms": 0, "model": model,
                "error": "This key was saved under a different SECRETS_KEY. Enter it again."}
    if not model:
        return {"ok": False, "latency_ms": 0, "model": None,
                "error": "No model to test with. Add a custom model to this provider first."}
    started = time.monotonic()
    client = None
    try:
        client = make_client(provider)
        if provider.api == ANTHROPIC_API:
            await client.messages.create(
                model=model, max_tokens=8, messages=[{"role": "user", "content": "Say OK."}]
            )
        else:
            await client.chat.completions.create(
                model=model,
                messages=[{"role": "user", "content": "Say OK."}],
                **chat_params(provider, model, max_tokens=8, effort=None),
            )
    except Exception as exc:  # noqa: BLE001 - reported, not raised
        return {
            "ok": False,
            "latency_ms": int((time.monotonic() - started) * 1000),
            "model": model,
            "error": _scrub(describe_error(exc), provider.secret),
        }
    finally:
        close = getattr(client, "close", None)
        if close is not None:
            try:
                await close()
            except Exception:  # noqa: BLE001
                pass
    return {"ok": True, "latency_ms": int((time.monotonic() - started) * 1000), "model": model}


def describe_error(exc: Exception) -> str:
    """A provider error in a sentence, whichever SDK raised it."""
    if isinstance(exc, auth_error_types()):
        return "The key was rejected. Check it is complete and still active."
    if isinstance(exc, rate_limit_error_types()):
        return "Rate limited, or this key has no quota for that model."
    if isinstance(exc, overloaded_error_types()):
        return "The provider is overloaded right now. Try again in a minute."
    message = str(getattr(exc, "message", "") or exc) or type(exc).__name__
    return message[:300]


def _scrub(text: str, secret: str) -> str:
    return text.replace(secret, "••••") if secret and len(secret) >= 4 else text


def retryable_error_types() -> tuple[type[Exception], ...]:
    """Worth another try in a few seconds: overload, rate limits, dropped connections."""
    types: list[type[Exception]] = [*overloaded_error_types(), *rate_limit_error_types()]
    try:
        from anthropic import APIConnectionError as AnthropicConnection

        types.append(AnthropicConnection)
    except ImportError:  # pragma: no cover
        pass
    try:
        from openai import APIConnectionError as OpenAIConnection

        types.append(OpenAIConnection)
    except ImportError:  # pragma: no cover
        pass
    return tuple(types)


def auth_error_types() -> tuple[type[Exception], ...]:
    """Exception types meaning "the key was rejected", across both SDKs.

    Collected in one place because the two paths raise different classes for
    the same operator mistake, and the fix — go and check your key — is the
    same either way.
    """
    types: list[type[Exception]] = []
    try:
        from anthropic import AuthenticationError as AnthropicAuthError

        types.append(AnthropicAuthError)
    except ImportError:  # pragma: no cover - anthropic is a hard dependency
        pass
    try:
        from openai import AuthenticationError as OpenAIAuthError
        from openai import PermissionDeniedError

        types.extend([OpenAIAuthError, PermissionDeniedError])
    except ImportError:  # pragma: no cover
        pass
    return tuple(types)


def overloaded_error_types() -> tuple[type[Exception], ...]:
    """Exception types meaning "the provider is busy, this would have worked".

    Separated from a generic failure because the response is different: a 503
    is worth retrying in a minute, and on a shared free tier it says nothing
    at all about your configuration. Told plainly, it stops someone rewriting
    working code to chase a capacity problem.
    """
    types: list[type[Exception]] = []
    try:
        from anthropic import InternalServerError as AnthropicOverloaded

        types.append(AnthropicOverloaded)
        # Anthropic's 529 "overloaded" is its own class, not a subclass of
        # InternalServerError — missing it sent busy-hour extractions
        # straight to review instead of retrying them.
        from anthropic import OverloadedError as AnthropicOverloaded529

        types.append(AnthropicOverloaded529)
    except ImportError:  # pragma: no cover
        pass
    try:
        from openai import InternalServerError as OpenAIOverloaded

        types.append(OpenAIOverloaded)
    except ImportError:  # pragma: no cover
        pass
    return tuple(types)


def rate_limit_error_types() -> tuple[type[Exception], ...]:
    """Exception types meaning "slow down, or you are out of quota".

    Worth distinguishing from a generic failure: on a free tier this is the
    single most likely thing to go wrong, and "you have no quota for this
    model" is actionable in a way that "the call failed" is not.
    """
    types: list[type[Exception]] = []
    try:
        from anthropic import RateLimitError as AnthropicRateLimit

        types.append(AnthropicRateLimit)
    except ImportError:  # pragma: no cover
        pass
    try:
        from openai import RateLimitError as OpenAIRateLimit

        types.append(OpenAIRateLimit)
    except ImportError:  # pragma: no cover
        pass
    return tuple(types)
