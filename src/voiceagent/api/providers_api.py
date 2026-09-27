"""Model providers, workspace model defaults, and greeting translation (v3).

Providers used to be one env var per deployment. Now a workspace connects
as many as it likes from the console, and each campaign picks one per role.
Env keys still work: they are listed as read-only rows (`env:<kind>`) and
nothing that ran before needs a row to keep running.

Keys go in and never come out. The API seals them on the way in
(mcp/secrets.py), and every response carries only the last four characters,
which is enough to tell two keys apart and useless to anyone else. A base
URL the user types is checked by the same SSRF guard as an MCP server's,
because the backend will connect to it and relay what comes back.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Response
from sqlalchemy.ext.asyncio import AsyncSession

from .. import providers
from ..catalog import (
    CONVERSATION,
    EXTRACTION,
    MODELS_BY_ID,
    default_model,
    models_for_kind,
    resolve,
)
from ..mcp.guard import UnsafeUrl, check_url
from ..mcp.secrets import seal
from ..storage import LlmProvider, Setting, get_session
from ..templates import LANGUAGES
from .access import workspace_writer
from .schemas import (
    ProviderCreate,
    ProviderOut,
    ProviderTestResult,
    ProviderUpdate,
    TranslateRequest,
    WorkspaceModelDefaults,
)

logger = logging.getLogger(__name__)

router = APIRouter()

# Test results for env rows, which have no database row to hold them.
_env_status: dict[str, tuple[str, str | None]] = {}

# Models discovered from a provider's own /models list: at most this many,
# and no longer than this to answer. The model browser is still usable
# without them.
_DISCOVERY_LIMIT = 500
_DISCOVERY_TIMEOUT = 4.0


# --------------------------------------------------------------------------
# Shapes
# --------------------------------------------------------------------------


def _catalog_entry(spec, source: str = "catalog") -> dict[str, Any]:
    return {
        "id": spec.id,
        "name": spec.name,
        "input_per_mtok": spec.input_per_mtok,
        "output_per_mtok": spec.output_per_mtok,
        "speed": spec.speed,
        "roles": list(spec.roles),
        "supports_tools": providers.PRESETS_BY_KIND[spec.provider].supports_tools
        if spec.provider in providers.PRESETS_BY_KIND
        else False,
        "source": source,
    }


def _custom_entry(model: dict[str, Any], provider: providers.Provider) -> dict[str, Any]:
    return {
        "id": model.get("id"),
        "name": model.get("name") or model.get("id"),
        "input_per_mtok": model.get("input_per_mtok"),
        "output_per_mtok": model.get("output_per_mtok"),
        "speed": None,
        "roles": [CONVERSATION, EXTRACTION],
        "supports_tools": provider.supports_tools,
        "source": "custom",
    }


def _models_count(provider: providers.Provider) -> int:
    catalog_ids = {m.id for m in models_for_kind(provider.kind)}
    custom = {m.get("id") for m in provider.custom_models} - catalog_ids
    return len(catalog_ids) + len(custom)


def _out(provider: providers.Provider, row: LlmProvider | None = None) -> ProviderOut:
    if row is not None:
        status, error = row.status or "untested", row.last_error
    else:
        status, error = _env_status.get(provider.id, ("untested", None))
    if not provider.key_readable:
        status, error = "error", "This key was saved under a different SECRETS_KEY. Enter it again."
    return ProviderOut(
        id=provider.id,
        kind=provider.kind,
        label=provider.label,
        base_url=provider.base_url,
        source=provider.source,  # type: ignore[arg-type]
        enabled=provider.enabled,
        supports_tools=provider.supports_tools,
        api_shape=provider.api,
        key_hint=provider.key_hint,
        status=status if status in ("ok", "untested", "error") else "untested",  # type: ignore[arg-type]
        last_error=error,
        models_count=_models_count(provider),
        custom_models=list(provider.custom_models),
    )


async def _check_base_url(url: str) -> str:
    url = url.strip()
    try:
        # Resolves DNS, so off the event loop.
        await asyncio.to_thread(check_url, url)
    except UnsafeUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    return url


async def _row_or_error(db: AsyncSession, provider_id: str) -> LlmProvider:
    if provider_id.startswith(providers.ENV_PREFIX):
        raise HTTPException(
            403,
            "This provider comes from an environment variable. Change or remove it there, "
            "or add the same provider here to manage it from the console.",
        )
    row = await db.get(LlmProvider, provider_id)
    if row is None:
        raise HTTPException(404, "No such provider.")
    return row


# --------------------------------------------------------------------------
# Providers
# --------------------------------------------------------------------------


@router.get("/api/providers", response_model=list[ProviderOut])
async def list_providers(db: AsyncSession = Depends(get_session)) -> list[ProviderOut]:
    rows = {row.id: row for row in (await db.scalars(_select_rows())).all()}
    return [_out(p, rows.get(p.id)) for p in await providers.list_providers(db)]


def _select_rows():
    from sqlalchemy import select

    return select(LlmProvider).order_by(LlmProvider.created_at)


@router.get("/api/providers/presets")
async def list_presets() -> list[dict[str, Any]]:
    return [
        {
            "kind": spec.id,
            "label": spec.label,
            "default_base_url": spec.base_url,
            "needs_base_url": spec.needs_base_url,
            "key_url": spec.key_url or spec.console,
            "supports_tools": spec.supports_tools,
            "api_shape": spec.api,
            "note": spec.note,
            "popular_models": [_catalog_entry(m) for m in models_for_kind(spec.id)],
        }
        for spec in providers.PRESETS
    ]


@router.post("/api/providers", response_model=ProviderOut, status_code=201)
async def create_provider(
    body: ProviderCreate,
    _actor: dict | None = Depends(workspace_writer),
    db: AsyncSession = Depends(get_session),
) -> ProviderOut:
    spec = providers.PRESETS_BY_KIND.get(body.kind)
    if spec is None:
        known = ", ".join(providers.PRESETS_BY_KIND)
        raise HTTPException(400, f"Unknown provider kind {body.kind!r}. Known: {known}.")
    base_url = (body.base_url or "").strip() or None
    if spec.needs_base_url and not base_url:
        raise HTTPException(400, f"{spec.label} needs a base URL.")
    if base_url:
        base_url = await _check_base_url(base_url)
    key = (body.api_key or "").strip()
    if not key and body.kind != providers.OPENAI_COMPATIBLE:
        raise HTTPException(400, f"{spec.label} needs an API key.")

    row = LlmProvider(
        id=str(uuid.uuid4()),
        kind=body.kind,
        label=(body.label or "").strip() or spec.label,
        base_url=base_url,
        secret=seal({"api_key": key}),
        enabled=True,
        custom_models=[m.model_dump() for m in body.custom_models],
        status="untested",
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return _out(providers.from_row(row), row)


@router.patch("/api/providers/{provider_id}", response_model=ProviderOut)
async def update_provider(
    provider_id: str,
    body: ProviderUpdate,
    _actor: dict | None = Depends(workspace_writer),
    db: AsyncSession = Depends(get_session),
) -> ProviderOut:
    row = await _row_or_error(db, provider_id)
    spec = providers.PRESETS_BY_KIND.get(row.kind)
    changes = body.model_dump(exclude_unset=True)

    if "label" in changes and changes["label"] is not None:
        row.label = changes["label"].strip() or (spec.label if spec else row.kind)
    if "base_url" in changes:
        base_url = (changes["base_url"] or "").strip() or None
        if spec is not None and spec.needs_base_url and not base_url:
            raise HTTPException(400, f"{spec.label} needs a base URL.")
        row.base_url = await _check_base_url(base_url) if base_url else None
        row.status, row.last_error = "untested", None
    if changes.get("api_key"):
        # Blank means "keep the key": the form never has the old one to send.
        row.secret = seal({"api_key": changes["api_key"].strip()})
        row.status, row.last_error = "untested", None
    if changes.get("enabled") is not None:
        row.enabled = changes["enabled"]
    if changes.get("custom_models") is not None:
        row.custom_models = [m.model_dump() for m in body.custom_models or []]

    await db.commit()
    await db.refresh(row)
    providers.invalidate(row.id)
    return _out(providers.from_row(row), row)


@router.delete("/api/providers/{provider_id}", status_code=204)
async def delete_provider(
    provider_id: str,
    _actor: dict | None = Depends(workspace_writer),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Remove a provider. Campaigns that named it fall back to the default.

    Refused while it *is* a default: that would leave every campaign
    without an explicit choice pointing at nothing.
    """
    row = await _row_or_error(db, provider_id)
    defaults = await providers.workspace_defaults(db)
    roles = [role for role, entry in defaults.items() if entry["provider_id"] == row.id]
    if roles:
        raise HTTPException(
            409,
            f"This provider is the workspace default for {' and '.join(roles)}. "
            "Choose another default first.",
        )
    await db.delete(row)
    await db.commit()
    providers.invalidate(provider_id)
    return Response(status_code=204)


@router.post("/api/providers/{provider_id}/test", response_model=ProviderTestResult)
async def test_provider(
    provider_id: str,
    _actor: dict | None = Depends(workspace_writer),
    db: AsyncSession = Depends(get_session),
) -> ProviderTestResult:
    """One tiny completion, and remember whether it worked."""
    provider = await providers.get_provider(provider_id, db)
    if provider is None:
        raise HTTPException(404, "No such provider.")
    # Through the module, so it can be stood in for.
    result = await providers.test_provider(provider)
    status = "ok" if result.get("ok") else "error"
    error = None if result.get("ok") else result.get("error")
    if provider.source == "env":
        _env_status[provider.id] = (status, error)
    else:
        row = await db.get(LlmProvider, provider_id)
        if row is not None:
            row.status, row.last_error = status, error
            await db.commit()
    return ProviderTestResult(**result)


@router.get("/api/providers/{provider_id}/models")
async def provider_models(
    provider_id: str, discover: bool = True, db: AsyncSession = Depends(get_session)
) -> list[dict[str, Any]]:
    """What this provider can run: catalog models, its custom ones, and — for
    OpenAI-shaped providers — whatever its own /models list adds."""
    provider = await providers.get_provider(provider_id, db)
    if provider is None:
        raise HTTPException(404, "No such provider.")

    entries = [_catalog_entry(m) for m in models_for_kind(provider.kind)]
    seen = {e["id"] for e in entries}
    for model in provider.custom_models:
        if model.get("id") and model["id"] not in seen:
            entries.append(_custom_entry(model, provider))
            seen.add(model["id"])

    if discover and provider.api == providers.OPENAI_API and providers.usable(provider):
        for model_id in await _discover(provider):
            if model_id not in seen:
                seen.add(model_id)
                entries.append(
                    {
                        "id": model_id,
                        "name": model_id,
                        "input_per_mtok": None,
                        "output_per_mtok": None,
                        "speed": None,
                        "roles": [CONVERSATION, EXTRACTION],
                        "supports_tools": provider.supports_tools,
                        "source": "discovered",
                    }
                )
    return entries


async def _discover(provider: providers.Provider) -> list[str]:
    """Model ids from GET {base_url}/models. Empty on any failure."""
    try:
        if provider.kind == providers.OPENAI_COMPATIBLE and provider.base_url:
            # Checked again at use: a DNS record repointed after saving.
            await asyncio.to_thread(check_url, provider.base_url)
        client = providers.cached_client(provider)

        async def fetch() -> list[str]:
            page = await client.models.list()
            ids: list[str] = []
            async for model in page:
                ids.append(str(getattr(model, "id", "")))
                if len(ids) >= _DISCOVERY_LIMIT:
                    break
            return [i for i in ids if i]

        return await asyncio.wait_for(fetch(), timeout=_DISCOVERY_TIMEOUT)
    except Exception as exc:  # noqa: BLE001 - the list works without these
        logger.info("Model discovery for %s failed: %s", provider.label, type(exc).__name__)
        return []


# --------------------------------------------------------------------------
# Workspace defaults
# --------------------------------------------------------------------------


async def effective_defaults(db: AsyncSession) -> WorkspaceModelDefaults:
    """The stored defaults, with unset parts filled as today's behaviour:
    the env provider and its catalog defaults."""
    stored = await providers.workspace_defaults(db)
    fallback = providers.fallback_provider()
    result: dict[str, dict[str, str | None]] = {}
    for role in (CONVERSATION, EXTRACTION):
        provider_id = stored[role]["provider_id"] or (fallback.id if fallback else None)
        model = stored[role]["model"]
        if not model:
            provider = await providers.get_provider(provider_id, db) if provider_id else None
            model = default_model(role, provider) if provider else None
        result[role] = {"provider_id": provider_id, "model": model or None}
    return WorkspaceModelDefaults(**result)


@router.get("/api/model-defaults", response_model=WorkspaceModelDefaults)
async def get_model_defaults(db: AsyncSession = Depends(get_session)) -> WorkspaceModelDefaults:
    return await effective_defaults(db)


@router.put("/api/model-defaults", response_model=WorkspaceModelDefaults)
async def put_model_defaults(
    body: WorkspaceModelDefaults,
    _actor: dict | None = Depends(workspace_writer),
    db: AsyncSession = Depends(get_session),
) -> WorkspaceModelDefaults:
    """Set which provider and model each role uses when a campaign doesn't say.

    Existing campaigns that name their own provider are untouched; those
    that don't pick this up on their next call.
    """
    for role in (CONVERSATION, EXTRACTION):
        entry = getattr(body, role)
        if entry.provider_id:
            provider = await providers.get_provider(entry.provider_id, db)
            if provider is None:
                raise HTTPException(400, f"No such provider for {role}: {entry.provider_id}")
            if entry.model:
                _check_model(entry.model, role, provider)

    row = await db.get(Setting, providers.MODEL_DEFAULTS_KEY)
    if row is None:
        row = Setting(key=providers.MODEL_DEFAULTS_KEY, value={})
        db.add(row)
    # The pre-v3 flat keys in this row are left as they are.
    row.value = {**(row.value or {}), **body.model_dump()}
    await db.commit()
    return body


def _check_model(model: str, role: str, provider: providers.Provider) -> None:
    """Refuse a catalog model that belongs to another provider or role.

    A model id the catalog doesn't know is allowed: custom and discovered
    models are the provider's to vouch for.
    """
    spec = MODELS_BY_ID.get(model)
    if spec is None:
        return
    if spec.provider != provider.kind:
        raise HTTPException(400, f"{spec.name} is not served by {provider.label}.")
    if role not in spec.roles:
        raise HTTPException(400, f"{spec.name} is not offered for the {role} role.")


async def check_campaign_choice(
    db: AsyncSession, provider_id: str | None, model: str | None, role: str
) -> None:
    """Validate a campaign's provider id (and its model against it) on save."""
    if not provider_id:
        return
    provider = await providers.get_provider(provider_id, db)
    if provider is None:
        raise HTTPException(400, f"No such provider: {provider_id}")
    if model:
        _check_model(model, role, provider)


# --------------------------------------------------------------------------
# Translation (the campaign builder's "Translate greeting")
# --------------------------------------------------------------------------

_TRANSLATE_SYSTEM = """\
You translate the opening line of an outbound phone call. Translate the \
user's text into {language}, in the spoken register a caller would actually \
use on the phone — {instruction} Keep every placeholder in curly braces, such \
as {{first_name}} and {{campaign_name}}, exactly as written. Reply with the \
translated line only: no quotes, no notes.\
"""


@router.post("/api/translate")
async def translate(body: TranslateRequest, db: AsyncSession = Depends(get_session)) -> dict:
    """Translate a greeting with the workspace default conversation model.

    For the builder only: the result is shown for editing and saved as the
    campaign's greeting. Nothing is ever translated at call time.
    """
    language = next((lang for lang in LANGUAGES if lang.code == body.to), None)
    if language is None:
        raise HTTPException(400, f"Unknown language: {body.to}")

    defaults = await providers.workspace_defaults(db)
    run = await providers.runtime(
        defaults[CONVERSATION]["provider_id"], defaults[CONVERSATION]["model"], CONVERSATION, session=db
    )
    if run.provider is None or run.client is None:
        raise HTTPException(503, providers.missing_key_message())

    from ..llm import complete_text

    system = _TRANSLATE_SYSTEM.format(language=language.name, instruction=language.instruction)
    try:
        text = await complete_text(
            run.client, run.provider, resolve(run.model, CONVERSATION, run.provider),
            system=system, user=body.text, max_tokens=400,
        )
    except Exception as exc:  # noqa: BLE001
        raise model_http_error(exc, run.provider) from exc
    if not text:
        raise HTTPException(502, "The model returned an empty translation. Try again.")
    return {"text": text, "language": language.code}


def model_http_error(exc: Exception, provider) -> HTTPException:
    """An HTTP error for a failed model request, in words that name the fix."""
    label = getattr(provider, "label", "The provider")
    if isinstance(exc, providers.auth_error_types()):
        return HTTPException(401, f"{label} rejected its API key. Check it on the AI models page.")
    if isinstance(exc, providers.rate_limit_error_types()):
        return HTTPException(429, f"{label} is rate limiting this key. Try again in a minute.")
    if isinstance(exc, providers.overloaded_error_types()):
        return HTTPException(503, f"{label} is overloaded right now. Try again in a minute.")
    logger.exception("Model request failed")
    return HTTPException(502, f"The model request failed: {providers.describe_error(exc)}")


