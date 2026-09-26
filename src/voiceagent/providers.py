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
"""

from __future__ import annotations

import os
from dataclasses import dataclass

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
        note="Free evaluation credits, 40 requests/minute. Not for campaigns.",
    ),
]

PROVIDERS_BY_ID = {p.id: p for p in PROVIDERS}


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

    key = api_key(spec)
    if key is None:
        raise RuntimeError(
            f"{spec.label} is selected but {spec.key_env} is not set to a real key."
        )

    if spec.api == ANTHROPIC_API:
        from anthropic import AsyncAnthropic

        return AsyncAnthropic(api_key=key)

    from openai import AsyncOpenAI

    return AsyncOpenAI(api_key=key, base_url=spec.base_url)


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
