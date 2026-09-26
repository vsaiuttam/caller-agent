"""HTTP + WebSocket API.

Serves the built frontend in production and proxies nothing in development —
Vite handles that side. The WebSocket at /api/events is the live feed backing
the dashboard's call monitor.
"""

from __future__ import annotations

import asyncio
import csv
import io
import json
import logging
import os
import re
import statistics
import time
import uuid
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

from fastapi import (
    Depends,
    FastAPI,
    File,
    HTTPException,
    Query,
    Request,
    UploadFile,
    WebSocket,
    WebSocketDisconnect,
)
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, Response
from fastapi.staticfiles import StaticFiles
from sqlalchemy import func, select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from .. import storage
from ..catalog import (
    CONVERSATION,
    EFFORT_MULTIPLIER,
    EXTRACTION,
    MODELS_BY_ID,
    TokenUsage,
    catalog_dict,
    estimate_campaign,
)
from ..catalog import active_defaults, resolve
from ..followup import followup_columns, send_followups, sms_configured, whatsapp_configured
from ..llm import ConversationLLM
from ..mcp.client import (
    AUTO,
    BUILTIN,
    McpUnavailable,
    discover_transport,
    host_of,
    is_builtin,
)
from ..mcp.client import discover as discover_tools
from ..mcp.guard import UnsafeUrl, check_url
from ..mcp.ids import server_prefix, tool_id, unique_slug
from ..mcp.secrets import REENTER_MESSAGE, SecretsUnavailable, seal, sealing_enabled, unseal
from ..mcp.toolbox import CallToolbox, ToolLog, call_tools
from ..models import CallContext, CallOutcome, Disposition
from ..models import Contact as ContactModel
from ..models import ScoreCriterion
from ..orchestrator.events import (
    CALL_CONNECTED,
    CALL_ENDED,
    CALL_EXTRACTED,
    CALL_FAILED,
    CALL_STARTED,
    CALL_WHISPER,
    Event,
    bus,
)
from ..postcall.extract import extract_outcome
from ..postcall.mcp_actions import run_for_call
from ..providers import (
    active as active_provider,
)
from ..providers import (
    auth_error_types,
    configured,
    make_client,
    missing_key_message,
    overloaded_error_types,
    rate_limit_error_types,
)
from ..scoring import qualify_outcome
from ..storage import (
    Call,
    CallStatus,
    Campaign,
    CampaignStatus,
    Contact,
    ContactStatus,
    Invite,
    McpServer,
    Setting,
    Suppression,
    User,
    get_session,
    init_db,
)
from ..templates import CATEGORIES, LANGUAGES, TEMPLATES, language_instruction
from ..voice import live_registry
from ..voice.live_feed import CallFeed
from ..voice.phrases import phrases_for
from ..voice.pipeline import dial_failure_message, prepare_telephony
from ..voice.session import CallNotPlaced, CallSession
from . import auth
from .schemas import (
    DEFAULT_GREETING,
    BulkResult,
    CallDetail,
    CallSetupRequest,
    CallSummary,
    CampaignCreate,
    CampaignOut,
    CampaignUpdate,
    ContactBulkCreate,
    ContactOut,
    DashboardStats,
    EstimateRequest,
    FollowupResend,
    HourBucket,
    InviteCreate,
    InviteOut,
    LiveCallRequest,
    LoginRequest,
    McpCatalogTool,
    McpServerCreate,
    McpServerOut,
    McpServerUpdate,
    McpToolOut,
    McpToolTest,
    McpToolTestResult,
    ModelDefaults,
    RegisterRequest,
    ReviewDecision,
    SimulationRequest,
    SuppressionCreate,
    SuppressionOut,
    TeamUserOut,
    TeamUserUpdate,
    TestCallRequest,
    WhisperRequest,
)

logger = logging.getLogger(__name__)

# Configure logging early so all modules benefit.
logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)-7s %(name)s: %(message)s",
)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Startup/shutdown lifecycle for the API server."""
    await init_db()
    logger.info("Database initialized")
    # Before serving: whether anyone has registered decides whether the
    # console is locked, and tokens must verify from the first request.
    await auth.load_accounts()
    yield
    from ..storage import engine
    await engine.dispose()
    logger.info("Database connections closed")


app = FastAPI(title="Samvaad API", version="1.0.0", lifespan=lifespan)

# Opt-in; a no-op until someone registers or ADMIN_PASSWORD is set. See auth.py.
app.add_middleware(auth.AuthMiddleware)

# Added after the auth gate, so it runs before it: a 401 still carries the
# CORS headers the console needs to read it, and preflights never need a
# token. Dev only otherwise: Vite serves the UI on 5173 and calls us on 8000.
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("CORS_ORIGINS", "http://localhost:5173").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def mask(phone: str) -> str:
    return phone[:-4] + "••••" if len(phone) > 4 else "••••"


# --------------------------------------------------------------------------
# Templates & languages (static product content, no DB)
# --------------------------------------------------------------------------


@app.get("/api/templates")
async def list_templates() -> dict:
    return {
        "categories": CATEGORIES,
        "templates": [t.to_dict() for t in TEMPLATES],
    }


@app.get("/api/languages")
async def list_languages() -> list[dict]:
    return [
        {"code": lang.code, "name": lang.name, "native_name": lang.native_name}
        for lang in LANGUAGES
    ]


# --------------------------------------------------------------------------
# Models, defaults, and cost
# --------------------------------------------------------------------------

_MODEL_DEFAULTS_KEY = "model_defaults"


async def _model_defaults(db: AsyncSession) -> dict:
    """Workspace defaults, falling back to the catalog's.

    Stored values are merged over the catalog rather than replacing it, so a
    setting saved before a new field existed still resolves.
    """
    row = await db.get(Setting, _MODEL_DEFAULTS_KEY)
    stored = row.value if row and isinstance(row.value, dict) else {}
    return {
        **active_defaults(),
        **{k: v for k, v in stored.items() if _still_usable(k, v)},
    }


def _still_usable(field: str, value) -> bool:
    """Whether a saved default survives the provider this process is using.

    A workspace that picked Opus for extraction and later switched its key to
    Gemini must not go on being handed an Opus id. `resolve()` already routes
    around it at call time, but the Models page would otherwise keep claiming
    a setting that isn't in effect — and a setting that lies is worse than no
    setting at all.
    """
    if not value:
        return False
    if not field.endswith("_model"):
        return True
    spec = MODELS_BY_ID.get(value)
    provider = active_provider()
    return bool(spec and provider and spec.provider == provider.id)


def _validate_assignment(model_id: str, role: str, effort: str) -> None:
    """Reject a model/role pairing the catalog does not offer.

    Enforced server-side, not just in the picker: Fable on the in-call path
    would produce a call that sounds broken, and Haiku on extraction would
    write confident wrong appointments into a calendar. Neither is a mistake
    the API should accept just because someone bypassed the UI.
    """
    spec = MODELS_BY_ID.get(model_id)
    if spec is None:
        raise HTTPException(400, f"Unknown model: {model_id}")
    if role not in spec.roles:
        raise HTTPException(
            400,
            f"{spec.name} is not available for the {role} role. "
            f"Offered for: {', '.join(spec.roles)}.",
        )
    if effort not in EFFORT_MULTIPLIER:
        raise HTTPException(400, f"Unknown effort level: {effort}")


@app.get("/api/models")
async def list_models(db: AsyncSession = Depends(get_session)) -> dict:
    return {**catalog_dict(), "defaults": await _model_defaults(db)}


@app.get("/api/settings/models", response_model=ModelDefaults)
async def get_model_defaults(db: AsyncSession = Depends(get_session)) -> ModelDefaults:
    return ModelDefaults(**await _model_defaults(db))


@app.put("/api/settings/models", response_model=ModelDefaults)
async def set_model_defaults(
    body: ModelDefaults, db: AsyncSession = Depends(get_session)
) -> ModelDefaults:
    """Set the defaults new campaigns inherit.

    Deliberately does *not* rewrite existing campaigns. Silently changing the
    model under a campaign that is mid-flight would make its cost history
    unreadable and its results incomparable.
    """
    _validate_assignment(body.conversation_model, CONVERSATION, body.conversation_effort)
    _validate_assignment(body.extraction_model, EXTRACTION, body.extraction_effort)

    row = await db.get(Setting, _MODEL_DEFAULTS_KEY)
    if row is None:
        row = Setting(key=_MODEL_DEFAULTS_KEY, value={})
        db.add(row)
    row.value = body.model_dump()
    await db.commit()
    return body


@app.post("/api/estimate")
async def estimate(body: EstimateRequest) -> dict:
    """Project what a campaign will cost before any of it is spent."""
    _validate_assignment(body.conversation_model, CONVERSATION, body.conversation_effort)
    _validate_assignment(body.extraction_model, EXTRACTION, body.extraction_effort)

    return estimate_campaign(
        contacts=body.contacts,
        connect_rate=body.connect_rate,
        conversation_model=body.conversation_model,
        conversation_effort=body.conversation_effort,
        extraction_model=body.extraction_model,
        extraction_effort=body.extraction_effort,
        exchanges=body.exchanges,
    )


# --------------------------------------------------------------------------
# Health / readiness
# --------------------------------------------------------------------------


@app.get("/api/health")
async def health(db: AsyncSession = Depends(get_session)) -> dict:
    """What is actually wired up, named honestly.

    A platform that looks fully operational while running entirely on mocks is
    how a demo becomes a production incident. Every integration reports whether
    it holds real credentials, and the UI shows it on every screen.
    """
    provider = active_provider()
    checks = {
        # Named for the role, not the vendor: which vendor fills it is now a
        # setting, and `provider` below says which one won.
        "model_provider": provider is not None,
        "telephony": bool(
            (os.getenv("LIVEKIT_API_KEY") and os.getenv("LIVEKIT_URL"))
            or (os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN") and os.getenv("TWILIO_PHONE_NUMBER"))
            or (os.getenv("TELNYX_API_KEY") and os.getenv("TELNYX_PHONE_NUMBER"))
        ),
        "twilio": bool(os.getenv("TWILIO_ACCOUNT_SID") and os.getenv("TWILIO_AUTH_TOKEN")),
        "sms": sms_configured(),
        "whatsapp": whatsapp_configured(),
        "speech_to_text": bool(os.getenv("DEEPGRAM_API_KEY") or os.getenv("TWILIO_ACCOUNT_SID") or os.getenv("SARVAM_API_KEY")),
        "text_to_speech": bool(os.getenv("CARTESIA_API_KEY") or os.getenv("TWILIO_ACCOUNT_SID") or os.getenv("SARVAM_API_KEY")),
        "calendar": bool(os.getenv("GOOGLE_CALENDAR_CREDENTIALS") or os.getenv("BUILTIN_CALENDAR")),
        "records_api": bool(os.getenv("RECORDS_API_URL") or os.getenv("BUILTIN_RECORDS")),
        "webhook_signing": bool(os.getenv("WEBHOOK_SIGNING_SECRET")),
    }

    mcp_servers = 0
    try:
        await db.execute(select(func.count()).select_from(Campaign))
        checks["database"] = True
        mcp_servers = await db.scalar(
            select(func.count()).select_from(McpServer).where(McpServer.enabled.is_(True))
        ) or 0
    except Exception:  # noqa: BLE001
        logger.exception("Health check: database unreachable")
        checks["database"] = False

    live = [k for k, ok in checks.items() if ok]
    mocked = [k for k, ok in checks.items() if not ok]

    return {
        "ok": checks["database"],
        "checks": checks,
        "live": live,
        "mocked": mocked,
        # The one that decides whether anything real can happen at all.
        "can_place_calls": checks["model_provider"] and checks["telephony"],
        "can_run_simulations": checks["model_provider"],
        "provider": provider.id if provider else "",
        "provider_label": provider.label if provider else "",
        "providers_configured": [p.id for p in configured()],
        "telephony_mode": os.getenv("TELEPHONY", "mock"),
        # Said on every screen when false: anyone with the link can dial.
        "auth_enabled": auth.auth_enabled(),
        # Connected apps: how many are switched on, whether this provider's
        # models can use them at all, and whether their credentials are
        # encrypted at rest (false until SECRETS_KEY or AUTH_SECRET is set).
        "mcp_servers": mcp_servers,
        "provider_supports_tools": bool(provider and provider.supports_tools),
        "secrets_sealed": sealing_enabled(),
        # Said plainly because the distinction bites: these check that a
        # credential is *present*, not that it works. Placeholder keys are the
        # one exception — `sk-ant-...` is recognised as unset rather than
        # counted as configured, because it is the single most common way to
        # spend a screen believing you have a key you don't have.
        "note": "Credentials are checked for presence, not validity.",
    }


# --------------------------------------------------------------------------
# Access control and accounts (opt-in; see auth.py)
# --------------------------------------------------------------------------


_login_throttle = auth.LoginThrottle()
# Separate counters, so fumbling one form costs nothing on the other. On
# register, a failure is a wrong setup code, an unusable invite code, or an
# email that is taken — the answers worth guessing at.
_register_throttle = auth.LoginThrottle()

# One answer for an unknown email and a wrong password alike.
LOGIN_FAILED = "Wrong email or password."


def _client(request: Request) -> str:
    return auth.client_address(request.headers, request.client.host if request.client else None)


def _public_user(user: User) -> dict:
    return {"id": user.id, "email": user.email, "name": user.name, "role": user.role}


async def _any_users(db: AsyncSession) -> bool:
    """Whether anyone has registered, per the in-process flag, else per the
    database — which also catches the flag up when another worker process
    registered the first user."""
    if auth.users_exist():
        return True
    try:
        found = await db.scalar(select(User.id).limit(1)) is not None
    except Exception:  # noqa: BLE001
        logger.exception("Accounts: could not read the users table")
        return False
    if found:
        auth.set_users_exist(True)
    return found


@app.post("/api/auth/login")
async def login(body: LoginRequest, request: Request, db: AsyncSession = Depends(get_session)) -> dict:
    """Trade an email and password — or the admin password — for a token."""
    if not auth.auth_enabled():
        raise HTTPException(
            400, "Access control is off — register the owner account, or set ADMIN_PASSWORD, to turn it on."
        )

    client = _client(request)
    if _login_throttle.blocked(client):
        raise HTTPException(429, "Too many wrong passwords. Try again in a few minutes.")

    email = auth.normalize_email(body.email or "")
    if not email:
        if not auth.check_password(body.password):
            _login_throttle.failed(client)
            raise HTTPException(401, "That password is not right.")
        _login_throttle.succeeded(client)
        token, expires_at = auth.issue_token()
        return {"token": token, "expires_at": expires_at.isoformat(), "user": auth.BREAK_GLASS_USER}

    user = await db.scalar(select(User).where(User.email == email))
    # Checked even when there is no such user, so both failures cost the same
    # time. In a thread: scrypt would otherwise stall live call audio.
    matches = await asyncio.to_thread(
        auth.check_password_hash,
        body.password,
        user.password_hash if user is not None else auth.stand_in_hash(),
    )
    if user is None or not matches:
        _login_throttle.failed(client)
        raise HTTPException(401, LOGIN_FAILED)
    # Only said to someone who knew the password, so it reveals nothing.
    if user.disabled:
        raise HTTPException(403, "This account is disabled")

    _login_throttle.succeeded(client)
    user.last_login_at = datetime.now(timezone.utc)
    await db.commit()
    token, expires_at = auth.issue_token(subject=user.id, role=user.role)
    return {"token": token, "expires_at": expires_at.isoformat(), "user": _public_user(user)}


@app.post("/api/auth/register", status_code=201)
async def register(
    body: RegisterRequest, request: Request, db: AsyncSession = Depends(get_session)
) -> dict:
    """Create an account and sign it in.

    The first account is the owner, and creating it is what locks the
    console; with ADMIN_PASSWORD set it must present that as `setup_code`,
    so a stranger who finds a public deploy first can't claim it. After
    that, REGISTRATION_MODE decides: an invite code, anyone, or nobody.
    """
    client = _client(request)
    if _register_throttle.blocked(client):
        raise HTTPException(429, "Too many attempts. Try again in a few minutes.")

    # The database, not the in-process flag: this decides who becomes owner.
    bootstrap = await db.scalar(select(User.id).limit(1)) is None
    mode = "owner" if bootstrap else auth.registration_mode()
    if mode == "closed":
        raise HTTPException(403, "Registration is closed. Ask your workspace owner for access.")

    email = auth.normalize_email(body.email)
    name = body.name.strip() or email.split("@")[0]
    problem = auth.email_problem(email) or auth.password_problem(body.password, email)
    if problem is None and len(name) > auth.MAX_NAME_LENGTH:
        problem = f"Use at most {auth.MAX_NAME_LENGTH} characters for your name."
    if problem:
        raise HTTPException(400, problem)

    now = datetime.now(timezone.utc)
    invite: Invite | None = None
    if mode == "owner":
        role = "owner"
        if auth.admin_password_set() and not auth.check_password(body.setup_code or ""):
            _register_throttle.failed(client)
            raise HTTPException(
                403,
                "That setup code is not right." if body.setup_code
                else "Enter the setup code (this deploy's ADMIN_PASSWORD) to create the owner account.",
            )
    else:
        code = (body.invite_code or "").strip()
        if not code and mode == "invite":
            raise HTTPException(403, "An invite code is required to join this workspace.")
        role = "member"
        if code:
            # Honoured in open mode too: it is how someone joins as an admin.
            invite = await db.scalar(select(Invite).where(Invite.code_hash == auth.invite_code_hash(code)))
            refusal = _invite_refusal(invite, email, now)
            if refusal:
                _register_throttle.failed(client)
                raise HTTPException(403, refusal)
            role = invite.role

    # After the code checks, so without a valid invite nobody can use this
    # to find out which emails have accounts.
    if await db.scalar(select(User.id).where(User.email == email)) is not None:
        _register_throttle.failed(client)
        raise HTTPException(409, "An account with this email already exists. Sign in instead.")

    user = User(
        id=str(uuid.uuid4()),
        email=email,
        name=name,
        password_hash=await asyncio.to_thread(auth.hash_password, body.password),
        role=role,
        disabled=False,
        created_at=now,
    )
    try:
        db.add(user)
        if invite is not None:
            # Claimed conditionally, in the same transaction as the new user:
            # two people racing one code can't both get in.
            claimed = await db.execute(
                update(Invite)
                .where(Invite.id == invite.id, Invite.used_at.is_(None), Invite.revoked.is_(False))
                .values(used_at=now, used_by=user.id)
            )
            if claimed.rowcount != 1:
                await db.rollback()
                raise HTTPException(403, "This invite has already been used. Ask for a new one.")
        await db.commit()
    except IntegrityError:
        # Lost a race: the same email registered a moment ago, or (on a
        # fresh deploy) someone else became the owner first — the database
        # allows exactly one.
        await db.rollback()
        raise HTTPException(
            409,
            "The owner account was created a moment ago. Sign in, or ask the owner for an invite."
            if bootstrap else "An account with this email already exists. Sign in instead.",
        ) from None

    if not auth.users_exist():
        auth.set_users_exist(True)
    token, expires_at = auth.issue_token(subject=user.id, role=user.role)
    return {"token": token, "expires_at": expires_at.isoformat(), "user": _public_user(user)}


def _invite_refusal(invite: Invite | None, email: str, now: datetime) -> str | None:
    """Why this invite can't admit `email`, in words, or None if it can."""
    if invite is None:
        return "That invite code isn't valid. Check the link, or ask for a new invite."
    if invite.revoked:
        return "This invite has been revoked. Ask for a new one."
    if invite.used_at is not None:
        return "This invite has already been used. Ask for a new one."
    if _utc(invite.expires_at) <= now:
        return "This invite has expired. Ask for a new one."
    if invite.email and invite.email != email:
        return "This invite is for a different email address."
    return None


@app.get("/api/auth/status")
async def auth_status(request: Request, db: AsyncSession = Depends(get_session)) -> dict:
    """Whether the console must sign in first, whether this request has and
    as whom, and how someone new can register.

    `authenticated` means "may use the API": always true while access control
    is off.
    """
    has_users = await _any_users(db)
    enabled = auth.auth_enabled()
    claims = await auth.authenticate(auth.request_token(request.scope)) if enabled else None

    if enabled and not has_users:
        # Only ADMIN_PASSWORD is configured: answer in exactly the
        # pre-accounts shape, which tests/test_auth.py pins with ==. This
        # hides `user` and `registration` (mode "owner", setup code required)
        # in the one state where the register page needs them; dropping this
        # branch gives the full answer, at the cost of those assertions.
        return {"auth_enabled": True, "authenticated": claims is not None}

    user = None
    if claims is not None:
        user = await _principal(db, claims)
        if user is None:  # disabled or removed since the token was checked
            claims = None
    return {
        "auth_enabled": enabled,
        "authenticated": not enabled or claims is not None,
        "user": user,
        "registration": {
            "mode": auth.registration_mode() if has_users else "owner",
            "setup_code_required": not has_users and auth.admin_password_set(),
        },
    }


async def _principal(db: AsyncSession, claims: dict) -> dict | None:
    """Who a verified token speaks for, as `{id, email, name, role}`: the
    break-glass owner, or the user as they are now (their role may have
    changed since the token was issued)."""
    if claims["sub"] == auth.LEGACY_SUBJECT:
        return dict(auth.BREAK_GLASS_USER)
    user = await db.get(User, claims["sub"])
    if user is None or user.disabled:
        return None
    return _public_user(user)


async def _socket_allowed(ws: WebSocket) -> bool:
    """With auth on, a socket needs a valid `?token=`, else it closes with 4401.

    Accepted first and then closed: a browser only sees the close code of a
    socket that opened, and a refused handshake reaches it as a bare 1006.
    """
    if not auth.auth_enabled() or await auth.authenticate(ws.query_params.get("token", "")):
        return True
    await ws.accept()
    await ws.close(code=4401)
    return False


# --------------------------------------------------------------------------
# Dashboard
# --------------------------------------------------------------------------


UNREACHED = {"no_answer", "voicemail"}


def _connect_rate(breakdown: dict[str, int]) -> tuple[float, int, int]:
    """Returns (rate, reached, total). 'Reached' = a person actually picked up."""
    total = sum(breakdown.values())
    reached = total - sum(breakdown.get(d, 0) for d in UNREACHED)
    return (reached / total if total else 0.0), reached, total


def _delta(current: float, previous: float) -> float | None:
    """Fractional change, or None when there's no baseline.

    A delta against zero is meaningless — reporting '+100%' because yesterday
    had no calls is noise, so the UI shows '—' instead.
    """
    if previous == 0:
        return None
    return round((current - previous) / previous, 4)


# Simulated calls run the same code and land in the same table, which is what
# makes them worth trusting — but they are rehearsals. Every aggregate on this
# page filters them out, or a morning of prompt-tuning would show up as a great
# day of calling.
REAL_CALLS = Call.is_simulation.is_(False)


@dataclass
class WindowStats:
    breakdown: dict[str, int]
    total_calls: int
    avg_duration: int
    spend_usd: float
    cache_read_tokens: int
    billable_input_tokens: int


async def _window_stats(db: AsyncSession, start: datetime, end: datetime) -> WindowStats:
    in_window = (Call.started_at >= start, Call.started_at < end, REAL_CALLS)

    rows = (
        await db.execute(
            select(Call.disposition, func.count())
            .where(*in_window, Call.disposition.is_not(None))
            .group_by(Call.disposition)
        )
    ).all()
    breakdown = {d: c for d, c in rows}

    total_calls = await db.scalar(
        select(func.count()).select_from(Call).where(*in_window)
    )

    totals = (
        await db.execute(
            select(
                func.coalesce(func.sum(Call.cost_usd), 0.0),
                func.coalesce(func.sum(Call.cache_read_tokens), 0),
                func.coalesce(func.sum(Call.input_tokens), 0),
                func.coalesce(func.sum(Call.cache_write_tokens), 0),
            ).where(*in_window)
        )
    ).one()
    spend, cache_read, fresh_input, cache_write = totals

    # Average talk time over calls that actually connected and ended.
    durations = (
        await db.execute(
            select(Call.connected_at, Call.ended_at).where(
                *in_window,
                Call.connected_at.is_not(None),
                Call.ended_at.is_not(None),
            )
        )
    ).all()
    spans = [(e - c).total_seconds() for c, e in durations if e > c]
    avg_duration = int(sum(spans) / len(spans)) if spans else 0

    return WindowStats(
        breakdown=breakdown,
        total_calls=total_calls or 0,
        avg_duration=avg_duration,
        spend_usd=float(spend or 0.0),
        cache_read_tokens=int(cache_read or 0),
        billable_input_tokens=int((fresh_input or 0) + (cache_write or 0)),
    )


@app.get("/api/stats", response_model=DashboardStats)
async def stats(db: AsyncSession = Depends(get_session)) -> DashboardStats:
    now = datetime.now(timezone.utc)
    window_start = now - timedelta(hours=24)
    prior_start = now - timedelta(hours=48)

    current = await _window_stats(db, window_start, now)
    prior = await _window_stats(db, prior_start, window_start)

    breakdown = current.breakdown
    rate_now, reached, total = _connect_rate(breakdown)
    rate_prev, _, _ = _connect_rate(prior.breakdown)
    completed = breakdown.get("completed", 0)

    cached = current.cache_read_tokens
    cache_hit_rate = (
        round(cached / (cached + current.billable_input_tokens), 4)
        if (cached + current.billable_input_tokens)
        else 0.0
    )

    running = await db.scalar(
        select(func.count())
        .select_from(Campaign)
        .where(Campaign.status == CampaignStatus.RUNNING)
    )
    in_progress = await db.scalar(
        select(func.count())
        .select_from(Call)
        .where(Call.status.in_([CallStatus.DIALING, CallStatus.CONNECTED]), REAL_CALLS)
    )
    pending_review = await db.scalar(
        select(func.count())
        .select_from(Call)
        .where(Call.needs_human_review.is_(True), Call.reviewed_at.is_(None), REAL_CALLS)
    )
    suppressed = await db.scalar(select(func.count()).select_from(Suppression))

    return DashboardStats(
        campaigns_running=running or 0,
        calls_today=current.total_calls,
        calls_in_progress=in_progress or 0,
        connect_rate=round(rate_now, 3),
        completion_rate=round(completed / reached, 3) if reached else 0.0,
        avg_duration_seconds=current.avg_duration,
        pending_review=pending_review or 0,
        suppressed_total=suppressed or 0,
        disposition_breakdown=breakdown,
        sentiment_breakdown=await _sentiment_breakdown(db, window_start, now),
        calls_delta=_delta(current.total_calls, prior.total_calls),
        connect_rate_delta=_delta(rate_now, rate_prev),
        avg_duration_delta=_delta(current.avg_duration, prior.avg_duration),
        spend_usd=round(current.spend_usd, 4),
        spend_delta=_delta(current.spend_usd, prior.spend_usd),
        cost_per_connected_call_usd=(
            round(current.spend_usd / reached, 4) if reached else 0.0
        ),
        cache_hit_rate=cache_hit_rate,
        volume_by_hour=await _volume_by_hour(db, window_start, now),
    )


async def _sentiment_breakdown(db: AsyncSession, start: datetime, end: datetime) -> dict[str, int]:
    rows = (
        await db.execute(
            select(Call.sentiment, func.count())
            .where(
                Call.started_at >= start,
                Call.started_at < end,
                REAL_CALLS,
                Call.sentiment.is_not(None),
            )
            .group_by(Call.sentiment)
        )
    ).all()
    return {sentiment: count for sentiment, count in rows}


async def _volume_by_hour(db: AsyncSession, start: datetime, end: datetime):
    """24 hourly buckets, zero-filled.

    Bucketing happens in Python rather than SQL: date-truncation syntax differs
    between SQLite and Postgres, and at 24h of calls the row count is small
    enough that the round-trip isn't worth a dialect branch.
    """
    rows = (
        await db.execute(
            select(Call.started_at, Call.disposition).where(
                Call.started_at >= start, Call.started_at < end, REAL_CALLS
            )
        )
    ).all()

    buckets: dict[datetime, dict[str, int]] = {}
    cursor = start.replace(minute=0, second=0, microsecond=0)
    while cursor <= end:
        buckets[cursor] = {"total": 0, "connected": 0}
        cursor += timedelta(hours=1)

    for started_at, disposition in rows:
        if started_at.tzinfo is None:  # SQLite round-trips naive datetimes
            started_at = started_at.replace(tzinfo=timezone.utc)
        key = started_at.replace(minute=0, second=0, microsecond=0)
        bucket = buckets.get(key)
        if bucket is None:
            continue
        bucket["total"] += 1
        if disposition and disposition not in UNREACHED:
            bucket["connected"] += 1

    return [
        HourBucket(
            hour=hour.isoformat(),
            label=hour.strftime("%H:%M"),
            total=counts["total"],
            connected=counts["connected"],
        )
        for hour, counts in sorted(buckets.items())
    ]


# --------------------------------------------------------------------------
# Campaigns
# --------------------------------------------------------------------------


async def _campaign_out(db: AsyncSession, campaign: Campaign) -> CampaignOut:
    defaults = active_defaults()
    counts = dict(
        (
            await db.execute(
                select(Contact.status, func.count())
                .where(Contact.campaign_id == campaign.id)
                .group_by(Contact.status)
            )
        ).all()
    )
    needs_review = await db.scalar(
        select(func.count()).select_from(Call).where(
            Call.campaign_id == campaign.id,
            Call.needs_human_review.is_(True),
            Call.reviewed_at.is_(None),
        )
    )
    return CampaignOut(
        id=campaign.id,
        name=campaign.name,
        goal=campaign.goal,
        scorecard=campaign.scorecard or [],
        greeting=campaign.greeting,
        fields_to_collect=campaign.fields_to_collect or [],
        constraints=campaign.constraints or [],
        extra_instructions=campaign.extra_instructions or "",
        language=campaign.language or "en",
        template_id=campaign.template_id,
        calling_hours_start=campaign.calling_hours_start,
        calling_hours_end=campaign.calling_hours_end,
        calling_days=campaign.calling_days or [],
        max_concurrent_calls=campaign.max_concurrent_calls,
        max_attempts=campaign.max_attempts,
        # Reported as what will actually run, not as what the row happens to
        # hold. A campaign created under Anthropic still stores
        # `claude-sonnet-5`; under a Gemini key it dials on Gemini, and a
        # screen that kept showing the Anthropic id would be describing a call
        # that never happens.
        conversation_model=resolve(
            campaign.conversation_model or defaults["conversation_model"], CONVERSATION
        ),
        conversation_effort=campaign.conversation_effort or defaults["conversation_effort"],
        extraction_model=resolve(
            campaign.extraction_model or defaults["extraction_model"], EXTRACTION
        ),
        extraction_effort=campaign.extraction_effort or defaults["extraction_effort"],
        budget_usd=campaign.budget_usd,
        sms_followup=getattr(campaign, "sms_followup", False) or False,
        whatsapp_followup=getattr(campaign, "whatsapp_followup", False) or False,
        webhook_url=campaign.webhook_url,
        mcp_tools=campaign.mcp_tools or [],
        mcp_post_call_tools=campaign.mcp_post_call_tools or [],
        mcp_post_call_instructions=campaign.mcp_post_call_instructions or "",
        status=campaign.status.value,
        created_at=campaign.created_at,
        total_contacts=sum(counts.values()),
        pending=counts.get(ContactStatus.PENDING, 0),
        completed=counts.get(ContactStatus.COMPLETED, 0),
        needs_review=needs_review or 0,
        spend_usd=round(campaign.spend_usd or 0.0, 4),
    )


@app.get("/api/campaigns", response_model=list[CampaignOut])
async def list_campaigns(db: AsyncSession = Depends(get_session)):
    campaigns = (
        await db.execute(select(Campaign).order_by(Campaign.created_at.desc()))
    ).scalars().all()
    return [await _campaign_out(db, c) for c in campaigns]


@app.post("/api/campaigns", response_model=CampaignOut, status_code=201)
async def create_campaign(body: CampaignCreate, db: AsyncSession = Depends(get_session)):
    if body.calling_hours_end <= body.calling_hours_start:
        raise HTTPException(400, "calling_hours_end must be after calling_hours_start")

    # A campaign created without an explicit choice inherits the workspace
    # default rather than the code default, so changing it once on the Models
    # page actually takes effect.
    fields = body.model_dump()
    for key, value in (await _model_defaults(db)).items():
        if not fields.get(key):
            fields[key] = value

    _validate_assignment(
        fields["conversation_model"], CONVERSATION, fields["conversation_effort"]
    )
    _validate_assignment(fields["extraction_model"], EXTRACTION, fields["extraction_effort"])
    await _check_tool_ids(db, fields["mcp_tools"], fields["mcp_post_call_tools"])

    campaign = Campaign(id=str(uuid.uuid4()), **fields)
    db.add(campaign)
    await db.commit()
    return await _campaign_out(db, campaign)


@app.get("/api/campaigns/{campaign_id}", response_model=CampaignOut)
async def get_campaign(campaign_id: str, db: AsyncSession = Depends(get_session)):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")
    return await _campaign_out(db, campaign)


@app.patch("/api/campaigns/{campaign_id}", response_model=CampaignOut)
async def update_campaign(
    campaign_id: str, body: CampaignUpdate, db: AsyncSession = Depends(get_session)
):
    """Partial update.

    Editable while running: a campaign whose opening line is landing badly
    should be fixable without tearing it down and re-importing the list.
    Changes apply to calls placed after the edit; calls already in flight keep
    the configuration they started with.
    """
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    changes = body.model_dump(exclude_unset=True)

    start = changes.get("calling_hours_start", campaign.calling_hours_start)
    end = changes.get("calling_hours_end", campaign.calling_hours_end)
    if end <= start:
        raise HTTPException(400, "calling_hours_end must be after calling_hours_start")

    if "calling_days" in changes and not changes["calling_days"]:
        raise HTTPException(400, "At least one calling day is required")

    if {"conversation_model", "conversation_effort"} & changes.keys():
        _validate_assignment(
            changes.get("conversation_model", campaign.conversation_model),
            CONVERSATION,
            changes.get("conversation_effort", campaign.conversation_effort),
        )
    if {"extraction_model", "extraction_effort"} & changes.keys():
        _validate_assignment(
            changes.get("extraction_model", campaign.extraction_model),
            EXTRACTION,
            changes.get("extraction_effort", campaign.extraction_effort),
        )

    # Sent as null, the tool fields mean "none", like on rows made before them.
    for field, empty in (("mcp_tools", []), ("mcp_post_call_tools", []), ("mcp_post_call_instructions", "")):
        if field in changes and changes[field] is None:
            changes[field] = empty
    await _check_tool_ids(db, changes.get("mcp_tools"), changes.get("mcp_post_call_tools"))

    for field, value in changes.items():
        setattr(campaign, field, value)

    await db.commit()
    return await _campaign_out(db, campaign)


@app.post("/api/campaigns/{campaign_id}/status", response_model=CampaignOut)
async def set_campaign_status(
    campaign_id: str,
    action: str = Query(pattern="^(start|pause|complete)$"),
    db: AsyncSession = Depends(get_session),
):
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    # Restarting a campaign that stopped on its spend cap would immediately
    # stop again after one more call. Refuse, and say what to change — this is
    # a guard rail, not a speed bump to be tapped through.
    if (
        action == "start"
        and campaign.budget_usd is not None
        and (campaign.spend_usd or 0.0) >= campaign.budget_usd
    ):
        raise HTTPException(
            409,
            f"Campaign has spent its ${campaign.budget_usd:.2f} budget "
            f"(${campaign.spend_usd:.2f} used). Raise or clear the budget to resume.",
        )

    campaign.status = {
        "start": CampaignStatus.RUNNING,
        "pause": CampaignStatus.PAUSED,
        "complete": CampaignStatus.COMPLETED,
    }[action]
    await db.commit()
    return await _campaign_out(db, campaign)


# --------------------------------------------------------------------------
# Contacts
# --------------------------------------------------------------------------


@app.get("/api/campaigns/{campaign_id}/contacts", response_model=list[ContactOut])
async def list_contacts(
    campaign_id: str,
    status: str | None = None,
    limit: int = Query(default=100, le=1000),
    offset: int = 0,
    db: AsyncSession = Depends(get_session),
):
    stmt = select(Contact).where(Contact.campaign_id == campaign_id)
    if status:
        stmt = stmt.where(Contact.status == ContactStatus(status))
    rows = (
        await db.execute(stmt.order_by(Contact.created_at).limit(limit).offset(offset))
    ).scalars().all()
    return [
        ContactOut(
            id=c.id,
            full_name=c.full_name,
            phone_masked=mask(c.phone_e164),
            timezone=c.timezone,
            status=c.status.value,
            attempts=c.attempts,
            next_attempt_at=c.next_attempt_at,
        )
        for c in rows
    ]


@app.post("/api/campaigns/{campaign_id}/contacts", response_model=BulkResult, status_code=201)
async def add_contacts(
    campaign_id: str,
    body: ContactBulkCreate,
    db: AsyncSession = Depends(get_session),
):
    """Bulk import. Suppressed numbers are dropped at ingest, not at dial time.

    Filtering here rather than later means an opt-out can never be undone by
    someone re-uploading last month's spreadsheet.
    """
    campaign = await db.get(Campaign, campaign_id)
    if not campaign:
        raise HTTPException(404, "Campaign not found")

    incoming = {c.phone_e164 for c in body.contacts}

    suppressed = set(
        (
            await db.execute(
                select(Suppression.phone_e164).where(Suppression.phone_e164.in_(incoming))
            )
        ).scalars().all()
    )
    existing = set(
        (
            await db.execute(
                select(Contact.phone_e164).where(
                    Contact.campaign_id == campaign_id,
                    Contact.phone_e164.in_(incoming),
                )
            )
        ).scalars().all()
    )

    created = 0
    for item in body.contacts:
        if item.phone_e164 in suppressed or item.phone_e164 in existing:
            continue
        existing.add(item.phone_e164)  # de-dupe within the upload itself
        db.add(
            Contact(
                id=str(uuid.uuid4()),
                campaign_id=campaign_id,
                full_name=item.full_name,
                phone_e164=item.phone_e164,
                timezone=item.timezone,
                attributes=item.attributes,
            )
        )
        created += 1

    await db.commit()
    return BulkResult(
        created=created,
        skipped_suppressed=len(incoming & suppressed),
        skipped_duplicate=len(body.contacts) - created - len(incoming & suppressed),
    )


# Default country dialling codes, by the language the campaign runs in. A bare
# 10-digit number is ambiguous — it is a valid local number in dozens of
# countries — so the campaign's language is the best signal available at
# import time. Getting this wrong dials the wrong country entirely.
_LANGUAGE_DIAL_CODE = {
    "hi": "91",     # India
    "hi-en": "91",
    "ur": "92",     # Pakistan
    "en": "1",      # US/Canada
}


@app.post("/api/parse-contacts")
async def parse_contacts(
    file: UploadFile = File(...),
    language: str = Query(default="en", description="Campaign language; picks the default dial code."),
    country_code: str | None = Query(
        default=None, description="Explicit dial code without '+', e.g. 91. Overrides language."
    ),
) -> dict:
    """Parse an uploaded .xlsx/.xls/.csv into contact rows without saving them.

    Server-side rather than in the browser because Excel parsing needs a real
    library, and openpyxl already handles the format's edge cases — merged
    header cells, numeric-typed phone columns that lose their leading zero,
    dates masquerading as strings.

    Returns rows for the UI to preview and confirm; nothing is written here.
    """
    raw = await file.read()
    if len(raw) > 10 * 1024 * 1024:
        raise HTTPException(413, "File is larger than 10 MB")

    name = (file.filename or "").lower()

    try:
        if name.endswith((".xlsx", ".xlsm", ".xls")):
            rows = _rows_from_excel(raw)
        else:
            rows = _rows_from_csv(raw)
    except HTTPException:
        raise
    except Exception as exc:
        logger.exception("Contact file parse failed")
        raise HTTPException(400, f"Could not read the file: {exc}") from exc

    dial = (country_code or _LANGUAGE_DIAL_CODE.get(language, "1")).lstrip("+")
    return _rows_to_contacts(rows, dial)


def _rows_from_excel(raw: bytes) -> list[list[str]]:
    try:
        from openpyxl import load_workbook
    except ImportError as exc:
        raise HTTPException(
            400, "Excel support needs openpyxl — run: pip install openpyxl"
        ) from exc

    workbook = load_workbook(io.BytesIO(raw), read_only=True, data_only=True)
    sheet = workbook.active
    rows: list[list[str]] = []
    for row in sheet.iter_rows(values_only=True):
        if row is None:
            continue
        cells = ["" if v is None else str(v).strip() for v in row]
        if any(cells):
            rows.append(cells)
    workbook.close()
    return rows


def _rows_from_csv(raw: bytes) -> list[list[str]]:
    # Excel on Windows commonly exports cp1252, not UTF-8. Try the strict
    # decode first and fall back rather than mangling accented names.
    for encoding in ("utf-8-sig", "cp1252", "latin-1"):
        try:
            text = raw.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    else:
        raise HTTPException(400, "Could not decode the file's text encoding")

    return [row for row in csv.reader(io.StringIO(text)) if any(c.strip() for c in row)]


_NAME_HEADERS = {"name", "full_name", "fullname", "contact", "customer", "client"}
_PHONE_HEADERS = {"phone", "phone_e164", "number", "mobile", "telephone", "contact_number"}
_TZ_HEADERS = {"timezone", "tz", "time_zone"}


def _rows_to_contacts(rows: list[list[str]], dial_code: str) -> dict:
    if len(rows) < 2:
        raise HTTPException(400, "The file needs a header row and at least one contact")

    headers = [h.strip().lower() for h in rows[0]]

    def find(candidates: set[str]) -> int:
        return next((i for i, h in enumerate(headers) if h in candidates), -1)

    name_at, phone_at, tz_at = find(_NAME_HEADERS), find(_PHONE_HEADERS), find(_TZ_HEADERS)
    if name_at < 0 or phone_at < 0:
        raise HTTPException(
            400,
            "Could not find a name and a phone column. "
            f"Found: {', '.join(headers) or '(no headers)'}",
        )

    contacts: list[dict] = []
    rejected: list[dict] = []

    for offset, row in enumerate(rows[1:], start=2):
        cell = lambda i: (row[i].strip() if 0 <= i < len(row) else "")  # noqa: E731

        full_name = cell(name_at)
        phone = _normalise_phone(cell(phone_at), dial_code)

        if not full_name:
            rejected.append({"line": offset, "reason": "No name"})
            continue
        if not phone:
            rejected.append(
                {
                    "line": offset,
                    "reason": f"Unrecognised phone number: {cell(phone_at) or '(empty)'}",
                }
            )
            continue

        attributes = {
            headers[i]: cell(i)
            for i in range(len(headers))
            if i not in {name_at, phone_at, tz_at} and cell(i)
        }

        contacts.append(
            {
                "full_name": full_name,
                "phone_e164": phone,
                "timezone": cell(tz_at) or "America/New_York",
                "attributes": attributes,
            }
        )

    return {
        "contacts": contacts,
        "rejected": rejected,
        "attribute_columns": [
            headers[i]
            for i in range(len(headers))
            if i not in {name_at, phone_at, tz_at} and headers[i]
        ],
    }


def _normalise_phone(raw: str, dial_code: str = "1") -> str | None:
    """Coerce a spreadsheet cell to E.164, or return None if unusable.

    Numbers already in +E.164 are taken as-is. Bare local numbers are prefixed
    with `dial_code`, which the caller derives from the campaign's language —
    a 10-digit number is a valid local number in dozens of countries, and
    assuming one silently is how a campaign ends up dialling the wrong
    continent.
    """
    value = raw.strip()
    if not value:
        return None

    # Excel stores phone columns as numbers often enough to matter: a cell
    # holding 14155550142 arrives as "14155550142.0".
    if value.endswith(".0"):
        value = value[:-2]

    digits = re.sub(r"[^\d+]", "", value)

    if digits.startswith("+"):
        return digits if re.fullmatch(r"\+[1-9]\d{6,14}", digits) else None

    # Local trunk prefix ("0" before the subscriber number) is common in
    # Indian, Pakistani, and UK exports and is dropped when going international.
    digits = digits.lstrip("0")

    if not digits:
        return None

    # Already carries the country code.
    if digits.startswith(dial_code) and len(digits) > len(dial_code) + 6:
        candidate = f"+{digits}"
    else:
        candidate = f"+{dial_code}{digits}"

    return candidate if re.fullmatch(r"\+[1-9]\d{6,14}", candidate) else None


# --------------------------------------------------------------------------
# Calls
# --------------------------------------------------------------------------


def _call_summary(call: Call, contact_name: str, phone: str) -> CallSummary:
    duration = None
    if call.connected_at and call.ended_at:
        duration = int((call.ended_at - call.connected_at).total_seconds())
    return CallSummary(
        id=call.id,
        campaign_id=call.campaign_id,
        contact_id=call.contact_id,
        contact_name=contact_name,
        phone_masked=mask(phone),
        status=call.status.value,
        disposition=call.disposition,
        summary=call.summary,
        needs_human_review=call.needs_human_review,
        review_reason=call.review_reason,
        started_at=call.started_at,
        ended_at=call.ended_at,
        duration_seconds=duration,
        cost_usd=round(call.cost_usd or 0.0, 6),
        is_simulation=bool(call.is_simulation),
        score=call.score,
        qualification_band=call.qualification_band,
        sentiment=call.sentiment,
    )


def _calls_query(
    campaign_id: str | None,
    disposition: str | None,
    needs_review: bool | None,
    include_simulations: bool,
    band: str | None = None,
    min_score: int | None = None,
    sort: str = "recent",
):
    stmt = select(Call, Contact).join(Contact, Call.contact_id == Contact.id)
    if campaign_id:
        stmt = stmt.where(Call.campaign_id == campaign_id)
    if disposition:
        stmt = stmt.where(Call.disposition == disposition)
    if not include_simulations:
        stmt = stmt.where(REAL_CALLS)
    if needs_review is not None:
        stmt = stmt.where(Call.needs_human_review.is_(needs_review))
        if needs_review:
            stmt = stmt.where(Call.reviewed_at.is_(None))
    if band:
        stmt = stmt.where(Call.qualification_band == band)
    if min_score is not None:
        stmt = stmt.where(Call.score >= min_score)

    if sort == "score":
        # Unscored calls sort last. The extra key is not decoration: Postgres
        # treats NULL as largest and would put every unscored call above the
        # best candidate under DESC, while SQLite treats it as smallest and
        # would not. Sorting on `is_(None)` first gives the same answer on
        # both without a dialect branch.
        return stmt.order_by(
            Call.score.is_(None), Call.score.desc(), Call.started_at.desc()
        )
    return stmt.order_by(Call.started_at.desc())


@app.get("/api/calls", response_model=list[CallSummary])
async def list_calls(
    campaign_id: str | None = None,
    disposition: str | None = None,
    needs_review: bool | None = None,
    include_simulations: bool = False,
    band: str | None = Query(
        default=None, description="strong | possible | weak | disqualified | not_assessed"
    ),
    min_score: int | None = Query(default=None, ge=0, le=100),
    sort: str = Query(default="recent", pattern="^(recent|score)$"),
    limit: int = Query(default=50, le=500),
    offset: int = 0,
    db: AsyncSession = Depends(get_session),
):
    """Call history, and — with `sort=score` — the ranked queue.

    Ranking is the reason scoring exists: 'we called 300 people' is not a
    result, 'here are the 14 worth an interview, best first' is.
    """
    stmt = _calls_query(
        campaign_id, disposition, needs_review, include_simulations, band, min_score, sort
    )
    rows = (await db.execute(stmt.limit(limit).offset(offset))).all()
    return [_call_summary(c, ct.full_name, ct.phone_e164) for c, ct in rows]


# Declared before /api/calls/{call_id}, which would otherwise take "live" for
# an id.
@app.get("/api/calls/live")
async def live_calls() -> list[dict]:
    """Calls in progress in this process, for the live console."""
    return [call.to_dict() for call in live_registry.all()]


# Columns are fixed and explicit rather than derived from the model, so a
# schema change can't silently start leaking a new field into an export that
# someone emails around.
_EXPORT_COLUMNS = [
    "call_id",
    "started_at",
    "campaign_id",
    "contact_name",
    "phone_masked",
    "disposition",
    "duration_seconds",
    "score",
    "qualification_band",
    "needs_human_review",
    "review_reason",
    "summary",
    "appointment_starts_at",
    "collected",
    "conversation_model",
    "extraction_model",
    "cost_usd",
]


@app.get("/api/calls/export.csv")
async def export_calls(
    campaign_id: str | None = None,
    disposition: str | None = None,
    needs_review: bool | None = None,
    include_simulations: bool = False,
    band: str | None = None,
    min_score: int | None = Query(default=None, ge=0, le=100),
    sort: str = Query(default="recent", pattern="^(recent|score)$"),
    limit: int = Query(default=5000, le=50_000),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Download results as CSV.

    Phone numbers stay masked here exactly as they are in the API. An export
    is the single most likely thing to end up in an inbox or a shared drive,
    which makes it the worst place to relax that rule.
    """
    stmt = _calls_query(
        campaign_id, disposition, needs_review, include_simulations, band, min_score, sort
    )
    rows = (await db.execute(stmt.limit(limit))).all()

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(_EXPORT_COLUMNS)

    for call, contact in rows:
        outcome = call.outcome or {}
        appointment = outcome.get("appointment") or {}
        collected = "; ".join(
            f"{f.get('name')}={f.get('value')}" for f in outcome.get("collected") or []
        )
        duration = (
            int((call.ended_at - call.connected_at).total_seconds())
            if call.connected_at and call.ended_at
            else ""
        )
        writer.writerow(
            [
                call.id,
                call.started_at.isoformat() if call.started_at else "",
                call.campaign_id,
                contact.full_name,
                mask(contact.phone_e164),
                call.disposition or "",
                duration,
                "" if call.score is None else call.score,
                call.qualification_band or "",
                "yes" if call.needs_human_review else "no",
                (call.review_reason or "").replace("\n", " "),
                (call.summary or "").replace("\n", " "),
                appointment.get("starts_at_local", ""),
                collected,
                call.conversation_model or "",
                call.extraction_model or "",
                f"{call.cost_usd or 0:.6f}",
            ]
        )

    # utf-8-sig: Excel opens a plain UTF-8 CSV as cp1252 and mangles every
    # non-ASCII name. The BOM is what makes Hindi and Urdu columns readable.
    return Response(
        content=buffer.getvalue().encode("utf-8-sig"),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="calls.csv"'},
    )


@app.get("/api/calls/{call_id}", response_model=CallDetail)
async def get_call(call_id: str, db: AsyncSession = Depends(get_session)):
    row = (
        await db.execute(
            select(Call, Contact)
            .join(Contact, Call.contact_id == Contact.id)
            .where(Call.id == call_id)
        )
    ).first()
    if not row:
        raise HTTPException(404, "Call not found")

    call, contact = row
    base = _call_summary(call, contact.full_name, contact.phone_e164)
    return CallDetail(
        **base.model_dump(),
        transcript=call.transcript or [],
        outcome=call.outcome,
        scores=call.scores or [],
        qualification=call.qualification,
        dispatch_result=call.dispatch_result,
        input_tokens=call.input_tokens or 0,
        output_tokens=call.output_tokens or 0,
        cache_read_tokens=call.cache_read_tokens or 0,
        cache_write_tokens=call.cache_write_tokens or 0,
        conversation_model=call.conversation_model,
        extraction_model=call.extraction_model,
        recording_url=getattr(call, "recording_url", None),
        recording_sid=getattr(call, "recording_sid", None),
        recording_duration=getattr(call, "recording_duration", None),
        amd_result=getattr(call, "amd_result", None),
        sms_sid=getattr(call, "sms_sid", None),
        sms_status=getattr(call, "sms_status", None),
        whatsapp_sid=getattr(call, "whatsapp_sid", None),
        whatsapp_status=getattr(call, "whatsapp_status", None),
        followup_errors=getattr(call, "followup_errors", None),
        tool_calls=call.tool_calls or [],
    )


@app.get("/api/calls/{call_id}/recording")
async def get_recording(call_id: str, db: AsyncSession = Depends(get_session)):
    """Proxy the Twilio recording audio so the browser can play it without
    needing Twilio credentials. Returns the MP3 stream."""
    call = await db.get(Call, call_id)
    if not call:
        raise HTTPException(404, "Call not found")

    recording_url = getattr(call, "recording_url", None)
    if not recording_url:
        raise HTTPException(404, "No recording available for this call")

    # Twilio recording URLs need auth and .mp3 suffix
    import httpx

    sid = os.getenv("TWILIO_ACCOUNT_SID", "")
    token = os.getenv("TWILIO_AUTH_TOKEN", "")
    mp3_url = f"{recording_url}.mp3"

    try:
        async with httpx.AsyncClient() as client:
            resp = await client.get(mp3_url, auth=(sid, token), follow_redirects=True)
            resp.raise_for_status()
            return Response(
                content=resp.content,
                media_type="audio/mpeg",
                headers={
                    "Content-Disposition": f'inline; filename="recording-{call_id}.mp3"',
                    "Cache-Control": "private, max-age=3600",
                },
            )
    except Exception as exc:
        logger.exception("Failed to fetch recording for call %s", call_id)
        raise HTTPException(502, f"Could not fetch recording: {exc}") from exc


@app.get("/api/calls/{call_id}/transcript")
async def export_transcript(
    call_id: str,
    fmt: str = Query(default="txt", alias="format", description="txt | json"),
    db: AsyncSession = Depends(get_session),
) -> Response:
    """Download one conversation, as readable text or as JSON.

    Works mid-call too: the transcript is saved after every turn, so this is
    everything said so far.
    """
    if fmt not in ("txt", "json"):
        raise HTTPException(400, "format must be txt or json")

    call = await db.get(Call, call_id)
    if call is None:
        raise HTTPException(404, "Call not found")
    contact = await db.get(Contact, call.contact_id)
    campaign = await db.get(Campaign, call.campaign_id)
    contact_name = contact.full_name if contact else "Contact"

    if fmt == "json":
        payload = {
            "call_id": call.id,
            "contact_name": contact_name,
            "campaign_id": call.campaign_id,
            "started_at": _utc(call.started_at).isoformat() if call.started_at else None,
            "disposition": call.disposition,
            "summary": call.summary,
            "sentiment": call.sentiment,
            "turns": call.transcript or [],
        }
        content = json.dumps(payload, ensure_ascii=False, indent=2)
        media_type = "application/json"
    else:
        content = _transcript_text(call, contact_name, campaign.name if campaign else call.campaign_id)
        media_type = "text/plain; charset=utf-8"

    return Response(
        content=content.encode("utf-8"),
        media_type=media_type,
        headers={"Content-Disposition": f'attachment; filename="transcript-{call.id}.{fmt}"'},
    )


def _transcript_text(call: Call, contact_name: str, campaign_name: str) -> str:
    """A header, then one `[mm:ss] Speaker: text` line per turn."""
    turns = call.transcript or []
    started = _utc(call.started_at).isoformat() if call.started_at else "—"
    lines = [
        f"Contact: {contact_name}",
        f"Campaign: {campaign_name}",
        f"Started: {started}",
        f"Disposition: {call.disposition or '—'}",
        f"Summary: {call.summary or '—'}",
        "",
    ]
    first = _turn_time(turns[0]) if turns else None
    for turn in turns:
        speaker = "Agent" if turn.get("role") == "assistant" else contact_name
        lines.append(f"[{_offset(first, _turn_time(turn))}] {speaker}: {turn.get('text', '')}")
    return "\n".join(lines) + "\n"


def _turn_time(turn: dict) -> datetime | None:
    try:
        return _utc(datetime.fromisoformat(str(turn.get("started_at"))))
    except ValueError:
        return None


def _offset(first: datetime | None, at: datetime | None) -> str:
    seconds = int((at - first).total_seconds()) if first and at else 0
    minutes, seconds = divmod(max(0, seconds), 60)
    return f"{minutes:02d}:{seconds:02d}"


def _utc(moment: datetime) -> datetime:
    # SQLite round-trips naive datetimes; everything stored is UTC.
    return moment if moment.tzinfo else moment.replace(tzinfo=timezone.utc)


@app.post("/api/calls/{call_id}/hangup", status_code=202)
async def hangup_call(call_id: str) -> dict:
    """End a live call politely: the agent says goodbye, then hangs up."""
    live = live_registry.get(call_id)
    if live is None:
        raise HTTPException(404, "That call is not live on this server.")
    live.session.request_end()
    return {"call_id": call_id, "status": "ending"}


@app.post("/api/calls/{call_id}/whisper", status_code=202)
async def whisper(call_id: str, body: WhisperRequest) -> dict:
    """Steer a live call: guidance the agent follows but never mentions."""
    live = live_registry.get(call_id)
    if live is None:
        raise HTTPException(404, "That call is not live on this server.")
    live.session.llm.add_guidance(body.text)
    await bus.publish(Event(CALL_WHISPER, {"call_id": call_id, "text": body.text}))
    return {"call_id": call_id, "status": "accepted"}


@app.post("/api/calls/{call_id}/followup")
async def resend_followup(
    call_id: str, body: FollowupResend, db: AsyncSession = Depends(get_session)
) -> dict:
    """Send (or re-send) the post-call SMS / WhatsApp for a finished call.

    For when the first attempt failed for a fixable reason — a number that
    hadn't joined the WhatsApp Sandbox yet, a trial account's unverified
    number — without placing the call again.
    """
    if not (body.sms or body.whatsapp):
        raise HTTPException(400, "Choose SMS, WhatsApp, or both.")
    row = (
        await db.execute(
            select(Call, Contact, Campaign)
            .join(Contact, Call.contact_id == Contact.id)
            .join(Campaign, Call.campaign_id == Campaign.id)
            .where(Call.id == call_id)
        )
    ).first()
    if not row:
        raise HTTPException(404, "Call not found")
    call, contact, campaign = row
    if not call.outcome:
        raise HTTPException(409, "This call has no extracted outcome to follow up on yet.")

    results = await send_followups(
        to=contact.phone_e164,
        call_id=call.id,
        contact_name=contact.full_name,
        campaign_name=campaign.name,
        outcome=CallOutcome.model_validate(call.outcome),
        sms=body.sms,
        whatsapp=body.whatsapp,
    )
    if not results:
        raise HTTPException(409, "Nothing is sent for this call's outcome.")
    columns = followup_columns(results)
    # Keep the other channel's error when only one channel was re-sent.
    columns["followup_errors"] = {
        **{k: v for k, v in (call.followup_errors or {}).items() if k not in results},
        **(columns.get("followup_errors") or {}),
    } or None
    for column, value in columns.items():
        setattr(call, column, value)
    await db.commit()
    return {channel: result.as_dict() for channel, result in results.items()}


@app.post("/api/calls/{call_id}/review", response_model=CallSummary)
async def review_call(
    call_id: str, body: ReviewDecision, db: AsyncSession = Depends(get_session)
):
    row = (
        await db.execute(
            select(Call, Contact)
            .join(Contact, Call.contact_id == Contact.id)
            .where(Call.id == call_id)
        )
    ).first()
    if not row:
        raise HTTPException(404, "Call not found")

    call, contact = row
    call.reviewed_at = datetime.now(timezone.utc)
    if body.note:
        call.review_reason = f"{call.review_reason or ''}\n[reviewer] {body.note}".strip()
    await db.commit()
    return _call_summary(call, contact.full_name, contact.phone_e164)


# --------------------------------------------------------------------------
# Rehearsal — try a campaign out without dialling anybody
# --------------------------------------------------------------------------


@dataclass
class _CallSetup:
    """A rehearsal request resolved down to what one call actually runs on."""

    campaign: Campaign | None
    contact: ContactModel
    context: CallContext
    greeting: str
    conversation_model: str
    conversation_effort: str
    extraction_model: str
    extraction_effort: str
    language_name: str
    language: str = "en"


def _as_criteria(raw) -> list[ScoreCriterion]:
    """Coerce a scorecard from either the request or the campaign row.

    It arrives as pydantic models from one and plain dicts from the other; a
    malformed row is dropped rather than raised on, because a bad criterion
    should cost a campaign its scoring, not its ability to make calls.
    """
    criteria: list[ScoreCriterion] = []
    for entry in raw or []:
        try:
            criteria.append(
                ScoreCriterion.model_validate(
                    entry if isinstance(entry, dict) else entry.model_dump()
                )
            )
        except Exception:  # noqa: BLE001
            logger.warning("Skipping unusable scorecard entry: %r", entry)
    return criteria


async def _resolve_call_setup(db: AsyncSession, body: CallSetupRequest) -> _CallSetup:
    """Resolve a rehearsal request against its campaign and the workspace.

    Request wins, then the campaign, then the workspace default — and the same
    resolution for a scripted persona and a live microphone, so the two are
    genuinely rehearsing the same configuration rather than two that happen to
    look alike.
    """
    campaign = await db.get(Campaign, body.campaign_id) if body.campaign_id else None
    if body.campaign_id and campaign is None:
        raise HTTPException(404, "Campaign not found")

    settings = await _model_defaults(db)

    def pick(field: str, fallback=None):
        value = getattr(body, field, None)
        if value not in (None, ""):
            return value
        if campaign is not None:
            value = getattr(campaign, field, None)
            if value not in (None, ""):
                return value
        return settings.get(field, fallback)

    goal = pick("goal")
    if not goal:
        raise HTTPException(400, "A goal is required — either pass one or pick a campaign.")

    language = pick("language", "en") or "en"
    conversation_model = pick("conversation_model")
    conversation_effort = pick("conversation_effort")
    extraction_model = pick("extraction_model")
    extraction_effort = pick("extraction_effort")
    _validate_assignment(conversation_model, CONVERSATION, conversation_effort)
    _validate_assignment(extraction_model, EXTRACTION, extraction_effort)

    campaign_name = campaign.name if campaign else "our team"
    greeting_template = pick("greeting", DEFAULT_GREETING)
    first_name = body.contact_name.split()[0] if body.contact_name.strip() else "there"
    try:
        greeting = greeting_template.format(
            first_name=first_name,
            full_name=body.contact_name,
            campaign_name=campaign_name,
        )
    except (KeyError, IndexError, ValueError) as exc:
        # Surfaced rather than swallowed: catching a bad placeholder here is
        # the entire point of rehearsing before the call.
        raise HTTPException(400, f"The greeting has an unknown placeholder: {exc}") from exc

    return _CallSetup(
        campaign=campaign,
        contact=ContactModel(
            contact_id="rehearsal",
            full_name=body.contact_name or "Alex Morgan",
            phone_e164="+10000000000",
            timezone=body.contact_timezone,
            attributes=body.contact_attributes,
        ),
        context=CallContext(
            campaign_id=campaign.id if campaign else "rehearsal",
            goal=goal,
            scorecard=_as_criteria(pick("scorecard")),
            fields_to_collect=pick("fields_to_collect") or [],
            constraints=pick("constraints") or [],
            extra_instructions=pick("extra_instructions") or "",
            language_instruction=language_instruction(language),
        ),
        greeting=greeting,
        conversation_model=conversation_model,
        conversation_effort=conversation_effort,
        extraction_model=extraction_model,
        extraction_effort=extraction_effort,
        language_name=next(
            (lang.name for lang in LANGUAGES if lang.code == language), "English"
        ),
        language=language,
    )


def _campaign_tools(setup: _CallSetup) -> list[str]:
    """The in-call tool ids of the campaign a rehearsal or test call runs on."""
    return (setup.campaign.mcp_tools or []) if setup.campaign else []


def _bad_key_message() -> str:
    provider = active_provider()
    if provider is None:
        return missing_key_message()
    return (
        f"{provider.label} rejected the key in {provider.key_env}. It is set, "
        f"but it is not valid — check for a placeholder or an expired key at "
        f"{provider.console}."
    )


def _quota_message(model_id: str) -> str:
    provider = active_provider()
    label = provider.label if provider else "The provider"
    return (
        f"{label} refused the request for {model_id}: rate limited, or no quota "
        "on this key for that model. Free tiers commonly allow the Flash-class "
        "models and nothing else — pick a different model on the Models page, "
        "or enable billing."
    )


def _busy_message(model_id: str) -> str:
    provider = active_provider()
    label = provider.label if provider else "The provider"
    return (
        f"{label} is under load and turned {model_id} away. Nothing is wrong "
        "with the configuration — try again in a minute. Free tiers share "
        "capacity, so this is common there and rare on a paid key."
    )


@app.get("/api/personas")
async def list_personas() -> list[dict]:
    from ..simulate import PERSONAS

    return [p.to_dict() for p in PERSONAS]


@app.post("/api/simulate")
async def simulate(body: SimulationRequest, db: AsyncSession = Depends(get_session)) -> dict:
    """Run one call against a simulated person and return everything it produced.

    Synchronous on purpose. A simulation takes seconds, the caller is a human
    staring at the screen waiting for it, and a job queue for something nobody
    walks away from is machinery with no user.
    """
    if active_provider() is None:
        raise HTTPException(503, missing_key_message())

    from ..simulate import PERSONAS_BY_ID, simulate_call

    if body.persona not in PERSONAS_BY_ID:
        raise HTTPException(400, f"Unknown persona: {body.persona}")

    setup = await _resolve_call_setup(db, body)

    # A rehearsal uses the campaign's tools for real, like a call would —
    # that is what makes it a rehearsal of the call rather than of the prompt.
    tools = ToolLog()

    async def on_tool(event: dict) -> None:
        tools.add(event)

    client = make_client()
    try:
        async with call_tools(storage.SessionLocal, _campaign_tools(setup), on_event=on_tool) as toolbox:
            result = await simulate_call(
                client,
                contact=setup.contact,
                context=setup.context,
                greeting=setup.greeting,
                persona_id=body.persona,
                language_name=setup.language_name,
                conversation_model=setup.conversation_model,
                conversation_effort=setup.conversation_effort,
                extraction_model=setup.extraction_model,
                extraction_effort=setup.extraction_effort,
                max_exchanges=body.max_exchanges,
                toolbox=toolbox,
            )
        result.tool_calls = tools.entries
    except auth_error_types() as exc:
        # Distinguished from a generic failure because the fix is completely
        # different: health reports whether a key is *present*, and a present
        # but wrong key otherwise surfaces as an opaque 502.
        logger.warning("Simulation rejected: bad API key")
        raise HTTPException(401, _bad_key_message()) from exc
    except rate_limit_error_types() as exc:
        # On a free tier this is the likeliest failure of all, and "you have no
        # quota for this model" is actionable in a way that "it failed" isn't.
        logger.warning("Simulation rate limited or out of quota")
        raise HTTPException(429, _quota_message(setup.conversation_model)) from exc
    except overloaded_error_types() as exc:
        logger.warning("Simulation hit provider capacity")
        raise HTTPException(503, _busy_message(setup.conversation_model)) from exc
    except Exception as exc:  # noqa: BLE001
        logger.exception("Simulation failed")
        raise HTTPException(502, f"The simulation could not run: {exc}") from exc
    finally:
        await client.close()

    payload = result.to_dict()
    payload["greeting"] = setup.greeting

    if body.save and setup.campaign is not None:
        payload["call_id"] = await _save_simulation(db, setup.campaign, result)

    return payload


async def _save_simulation(
    db: AsyncSession,
    campaign: Campaign,
    result,
    *,
    started_at: datetime | None = None,
    ended_at: datetime | None = None,
) -> str:
    """Persist a rehearsal as a call row, flagged so aggregates skip it.

    Used by both the persona simulator and the live microphone — a mic test is
    a rehearsal too, and it must no more reach the dashboard than a scripted
    one does.

    It needs a contact row to join against, so a single reusable placeholder
    contact per campaign is created in SUPPRESSED state — a status the runner
    will never dial, which is the safety property that matters here.

    A simulation has no wall-clock duration worth reporting and passes neither
    timestamp; a live call took as long as it took and passes both.
    """
    placeholder_phone = "+10000000000"
    contact = await db.scalar(
        select(Contact).where(
            Contact.campaign_id == campaign.id,
            Contact.phone_e164 == placeholder_phone,
        )
    )
    if contact is None:
        contact = Contact(
            id=str(uuid.uuid4()),
            campaign_id=campaign.id,
            full_name="Simulated contact",
            phone_e164=placeholder_phone,
            timezone="UTC",
            status=ContactStatus.SUPPRESSED,
            attributes={"simulation": "true"},
        )
        db.add(contact)
        await db.flush()

    now = datetime.now(timezone.utc)
    call = Call(
        id=str(uuid.uuid4()),
        contact_id=contact.id,
        campaign_id=campaign.id,
        status=CallStatus.COMPLETED,
        started_at=started_at or now,
        connected_at=started_at or now,
        ended_at=ended_at or now,
        transcript=[t.model_dump(mode="json") for t in result.transcript],
        tool_calls=result.tool_calls or None,
        disposition=result.outcome.disposition.value,
        sentiment=result.outcome.sentiment.value,
        summary=result.outcome.summary,
        outcome=result.outcome.model_dump(mode="json"),
        needs_human_review=result.outcome.needs_human_review,
        review_reason=result.outcome.review_reason or None,
        scores=[s.model_dump(mode="json") for s in result.outcome.scores],
        qualification=(
            result.qualification.model_dump(mode="json") if result.qualification else None
        ),
        score=result.qualification.score if result.qualification else None,
        qualification_band=result.qualification.band.value if result.qualification else None,
        input_tokens=result.usage.input_tokens,
        output_tokens=result.usage.output_tokens,
        cache_read_tokens=result.usage.cache_read_tokens,
        cache_write_tokens=result.usage.cache_write_tokens,
        cost_usd=result.usage.cost_usd(),
        conversation_model=result.conversation_model,
        extraction_model=result.extraction_model,
        is_simulation=True,
    )
    db.add(call)
    await db.commit()
    return call.id


# --------------------------------------------------------------------------
# Test call — place a real phone call from the simulator
# --------------------------------------------------------------------------


def _followup_choice(body: TestCallRequest, campaign: Campaign | None) -> tuple[bool, bool]:
    """(sms, whatsapp) for a test call: the request's choice, else the campaign's."""

    def pick(requested: bool | None, field: str) -> bool:
        if requested is not None:
            return requested
        return bool(getattr(campaign, field, False)) if campaign else False

    return pick(body.send_sms, "sms_followup"), pick(body.send_whatsapp, "whatsapp_followup")


@app.post("/api/test-call", status_code=202)
async def test_call(body: TestCallRequest, db: AsyncSession = Depends(get_session)) -> dict:
    """Place a real phone call to test a campaign, and return at once.

    The call runs in the background: it lasts minutes, and an HTTP request
    held open that long is one proxy timeout away from losing the result.
    Everything that happens is streamed on /api/events under the returned
    `call_id` — call.connected, then call.state and call.turn as the
    conversation goes, then call.ended and call.extracted (carrying the full
    result), or call.failed. The transcript is saved after every turn.

    Anything wrong with the request itself still fails here, synchronously.
    """
    if active_provider() is None:
        raise HTTPException(503, missing_key_message())

    telephony_mode = os.getenv("TELEPHONY", "mock").lower()
    if telephony_mode not in ("twilio", "telnyx"):
        raise HTTPException(
            400,
            "Test calls require TELEPHONY=twilio or TELEPHONY=telnyx. Current mode: "
            f"{telephony_mode}. Set it in .env and restart.",
        )

    setup = await _resolve_call_setup(db, body)

    call_id = str(uuid.uuid4())
    room_name = f"test-{call_id}"
    await _create_test_call_row(call_id, room_name, body, setup)

    task = asyncio.create_task(_run_test_call(call_id, room_name, body, setup))
    # The event loop only holds tasks weakly; this is what keeps a call alive.
    _test_calls.add(task)
    task.add_done_callback(_test_calls.discard)
    return {"call_id": call_id, "status": "dialing"}


_test_calls: set[asyncio.Task] = set()


def _test_call_telephony():
    """The telephony adapter a test call dials through, per TELEPHONY."""
    mode = os.getenv("TELEPHONY", "mock").lower()
    try:
        if mode == "telnyx":
            from ..voice.telnyx_adapter import TelnyxTelephony

            return TelnyxTelephony()
        from ..voice.twilio_adapter import TwilioTelephony

        return TwilioTelephony()
    except KeyError as exc:
        raise RuntimeError(f"TELEPHONY={mode}, but {exc.args[0]} is not set.") from exc


async def _create_test_call_row(
    call_id: str, room_name: str, body: TestCallRequest, setup: _CallSetup
) -> None:
    """The row a test call reports into, written before anything is dialled.

    It needs a contact to join against, so one placeholder contact per
    campaign and number is reused, in SUPPRESSED state — a status the runner
    will never dial. Without a campaign there is nothing to hang a row on, so
    the call runs and streams unsaved, as campaign-less test calls always have.

    Its own database session rather than the request's: committing the
    request's session would expire the campaign the background call still
    reads from.
    """
    if setup.campaign is None:
        return

    async with storage.SessionLocal() as db:
        contact = await db.scalar(
            select(Contact).where(
                Contact.campaign_id == setup.campaign.id,
                Contact.phone_e164 == body.phone_number,
            )
        )
        if contact is None:
            contact = Contact(
                id=str(uuid.uuid4()),
                campaign_id=setup.campaign.id,
                full_name=body.contact_name or "Test call contact",
                phone_e164=body.phone_number,
                timezone="UTC",
                status=ContactStatus.SUPPRESSED,
                attributes={"test_call": "true"},
            )
            db.add(contact)
            await db.flush()

        db.add(
            Call(
                id=call_id,
                contact_id=contact.id,
                campaign_id=setup.campaign.id,
                status=CallStatus.DIALING,
                room_name=room_name,
                conversation_model=resolve(setup.conversation_model, CONVERSATION),
                extraction_model=resolve(setup.extraction_model, EXTRACTION),
                is_simulation=True,
            )
        )
        await db.commit()


async def _update_call_row(call_id: str, **values) -> None:
    """Write to a test call's row. A no-op for a call that has none."""
    async with storage.SessionLocal() as db:
        await db.execute(update(Call).where(Call.id == call_id).values(**values))
        await db.commit()


async def _run_test_call(
    call_id: str, room_name: str, body: TestCallRequest, setup: _CallSetup
) -> None:
    """Dial, converse, extract, report: the background half of a test call.

    Never raises. Whatever goes wrong — the dial refused, nobody answering,
    the model failing — marks the row failed and is said on the feed as
    call.failed, in words the operator can act on.
    """
    feed = CallFeed(call_id, storage.SessionLocal)
    campaign_id = setup.campaign.id if setup.campaign else None
    await feed.publish(
        CALL_STARTED,
        campaign_id=campaign_id,
        contact_name=setup.contact.full_name,
        phone=mask(body.phone_number),
        is_test=True,
    )

    usage = TokenUsage()
    client = control = None
    session_started = False
    try:
        telephony = _test_call_telephony()
        prepare_telephony(telephony, room_name, language=setup.language, greeting=setup.greeting)
        # Open while the phone rings, closed the moment the call is over.
        async with call_tools(
            storage.SessionLocal, _campaign_tools(setup), on_event=feed.on_tool
        ) as toolbox:
            listener, speaker, control, call_sid = await telephony.dial(
                phone_e164=body.phone_number, room_name=room_name
            )
            connected_at = datetime.now(timezone.utc)
            await _update_call_row(
                call_id,
                status=CallStatus.CONNECTED,
                connected_at=connected_at,
                provider_call_sid=call_sid,
            )
            await feed.publish(CALL_CONNECTED)

            client = make_client()
            session = CallSession(
                llm=ConversationLLM(
                    client,
                    contact=setup.contact,
                    context=setup.context,
                    model=setup.conversation_model,
                    effort=setup.conversation_effort,
                    usage=usage,
                    toolbox=toolbox,
                ),
                listener=listener,
                speaker=speaker,
                control=control,
                greeting=setup.greeting,
                max_duration_seconds=600,
                phrases=phrases_for(setup.language),
                on_event=feed.on_event,
            )
            live_registry.register(
                call_id,
                session=session,
                room_name=room_name,
                campaign_id=campaign_id,
                contact_name=setup.contact.full_name,
                is_test=True,
            )
            try:
                session_started = True  # from here on, run() hangs up whatever happens
                transcript = await session.run()
            finally:
                live_registry.unregister(call_id)
        await feed.drain()

        if session.error is not None:
            await _fail_test_call(feed, session.error, body, setup, usage)
            return

        state = telephony.get_call_state(room_name) if hasattr(telephony, "get_call_state") else None
        await _complete_test_call(
            feed,
            client,
            usage,
            body,
            setup,
            transcript=transcript,
            call_sid=call_sid,
            connected_at=connected_at,
            recording=state,
        )
    except Exception as exc:  # noqa: BLE001 - reported on the feed instead
        logger.exception("Test call %s failed", call_id)
        if control is not None and not session_started:
            with _suppress_all():
                await control.hangup()
        await feed.drain()
        await _fail_test_call(feed, exc, body, setup, usage)
    finally:
        if client is not None:
            await client.close()


async def _complete_test_call(
    feed: CallFeed,
    client,
    usage: TokenUsage,
    body: TestCallRequest,
    setup: _CallSetup,
    *,
    transcript: list,
    call_sid: str,
    connected_at: datetime,
    recording,
) -> None:
    """Extract, score and follow up on a finished test call, then report it."""
    outcome = await extract_outcome(
        client,
        contact=setup.contact,
        context=setup.context,
        turns=transcript,
        call_started_at_iso=connected_at.isoformat(),
        model=setup.extraction_model,
        effort=setup.extraction_effort,
        usage=usage,
    )
    qualification = qualify_outcome(setup.context, outcome) if setup.context.scorecard else None

    # Written back into the user's apps like a campaign call's, about the
    # number actually called rather than the rehearsal placeholder.
    after_call, mcp_dispatch = await run_for_call(
        client,
        storage.SessionLocal,
        model=setup.extraction_model,
        effort=setup.extraction_effort,
        campaign=setup.campaign,
        contact=setup.contact.model_copy(update={"phone_e164": body.phone_number}),
        outcome=outcome,
        usage=usage,
    )

    # Follow-ups to the number just called.
    send_sms, send_whatsapp = _followup_choice(body, setup.campaign)
    followups = {}
    if send_sms or send_whatsapp:
        followups = await send_followups(
            to=body.phone_number,
            call_id=feed.call_id,
            contact_name=setup.contact.full_name,
            campaign_name=setup.campaign.name if setup.campaign else "our team",
            outcome=outcome,
            sms=send_sms,
            whatsapp=send_whatsapp,
        )

    tool_calls = [*feed.tool_calls, *after_call]
    ended_at = datetime.now(timezone.utc)
    values = dict(
        status=CallStatus.COMPLETED,
        ended_at=ended_at,
        transcript=[t.model_dump(mode="json") for t in transcript],
        tool_calls=tool_calls or None,
        dispatch_result=mcp_dispatch or None,
        disposition=outcome.disposition.value,
        sentiment=outcome.sentiment.value,
        summary=outcome.summary,
        outcome=outcome.model_dump(mode="json"),
        needs_human_review=outcome.needs_human_review,
        review_reason=outcome.review_reason or None,
        scores=[s.model_dump(mode="json") for s in outcome.scores],
        qualification=qualification.model_dump(mode="json") if qualification else None,
        score=qualification.score if qualification else None,
        qualification_band=qualification.band.value if qualification else None,
        input_tokens=usage.input_tokens,
        output_tokens=usage.output_tokens,
        cache_read_tokens=usage.cache_read_tokens,
        cache_write_tokens=usage.cache_write_tokens,
        cost_usd=usage.cost_usd(),
        **followup_columns(followups),
    )
    # Normally the recording arrives after the call is gone and the webhook
    # stores it itself; only write it here if it beat us to it.
    if recording is not None and recording.recording_url:
        values.update(
            recording_url=recording.recording_url,
            recording_sid=recording.recording_sid,
            recording_duration=recording.recording_duration,
        )
    await _update_call_row(feed.call_id, **values)

    # On a real call the per-turn figure is the wait from the person
    # finishing to the reply being ready, measured by the session.
    latencies = [t.latency_ms for t in transcript if t.latency_ms is not None]
    result = {
        "call_id": feed.call_id,
        "conversation_model": resolve(setup.conversation_model, CONVERSATION),
        "extraction_model": resolve(setup.extraction_model, EXTRACTION),
        "ended_because": "call completed",
        "greeting": setup.greeting,
        "call_sid": call_sid,
        # Masked: this travels on the shared event feed, not just back to
        # whoever placed the call.
        "phone_number": mask(body.phone_number),
        "turns": [
            {"role": t.role, "text": t.text, "first_chunk_ms": t.latency_ms, "total_ms": None}
            for t in transcript
        ],
        "median_first_chunk_ms": int(statistics.median(latencies)) if latencies else None,
        "outcome": outcome.model_dump(mode="json"),
        "qualification": qualification.model_dump(mode="json") if qualification else None,
        "usage": usage.to_dict(),
        "recording_url": values.get("recording_url"),
        "recording_sid": values.get("recording_sid"),
        "followups": {channel: r.as_dict() for channel, r in followups.items()},
        "tool_calls": tool_calls,
    }

    await feed.publish(
        CALL_ENDED,
        turns=len(transcript),
        duration_seconds=max(0, int((ended_at - connected_at).total_seconds())),
    )
    await feed.publish(
        CALL_EXTRACTED,
        disposition=outcome.disposition.value,
        summary=outcome.summary,
        needs_review=outcome.needs_human_review,
        cost_usd=values["cost_usd"],
        sentiment=outcome.sentiment.value,
        result=result,
    )


async def _fail_test_call(
    feed: CallFeed, exc: Exception, body: TestCallRequest, setup: _CallSetup, usage: TokenUsage
) -> None:
    error = _test_call_error(exc, body, setup)
    unanswered = isinstance(exc, ConnectionError) and not isinstance(exc, CallNotPlaced)
    try:
        await _update_call_row(
            feed.call_id,
            status=CallStatus.FAILED,
            ended_at=datetime.now(timezone.utc),
            disposition=(Disposition.NO_ANSWER if unanswered else Disposition.FAILED).value,
            summary=error,
            input_tokens=usage.input_tokens,
            output_tokens=usage.output_tokens,
            cache_read_tokens=usage.cache_read_tokens,
            cache_write_tokens=usage.cache_write_tokens,
            cost_usd=usage.cost_usd(),
        )
    except Exception:  # noqa: BLE001 - the feed still hears about it
        logger.exception("Could not mark test call %s failed", feed.call_id)
    await feed.publish(CALL_FAILED, error=error)


def _test_call_error(exc: Exception, body: TestCallRequest, setup: _CallSetup) -> str:
    """What went wrong, for the operator: plain words and a masked number."""
    if isinstance(exc, ConnectionError):
        return dial_failure_message(exc, body.phone_number)
    if isinstance(exc, auth_error_types()):
        return _bad_key_message()
    if isinstance(exc, rate_limit_error_types()):
        return _quota_message(setup.conversation_model)
    if isinstance(exc, overloaded_error_types()):
        return _busy_message(setup.conversation_model)
    reason = str(exc).replace(body.phone_number, mask(body.phone_number)) or type(exc).__name__
    return f"The test call failed: {reason}"


# --------------------------------------------------------------------------
# Live microphone — take the call yourself
# --------------------------------------------------------------------------


class _SocketTransport:
    """A FastAPI WebSocket, in the shape `live.LiveCall` expects."""

    def __init__(self, ws: WebSocket) -> None:
        self._ws = ws

    async def send(self, message: dict) -> None:
        await self._ws.send_json(message)

    async def receive(self) -> dict:
        return await self._ws.receive_json()


@app.websocket("/api/live")
async def live(ws: WebSocket) -> None:
    """Talk to the agent yourself, over the browser's microphone.

    The browser owns the audio — speech recognition in, speech synthesis out —
    and this owns the model, the transcript, and the barge-in rules. The
    conversation model, prompt, greeting, and extractor are the real ones; the
    person on the other end is you.

    Database sessions are opened around the setup read and the final save
    rather than held for the length of the call. A call lasts minutes, and a
    SQLite connection parked in an open transaction for that long will block
    the worker's contact claims.
    """
    if not await _socket_allowed(ws):
        return
    await ws.accept()

    try:
        opening = await ws.receive_json()
    except Exception:  # noqa: BLE001 - closed before saying anything
        return

    try:
        body = LiveCallRequest.model_validate(opening or {})
    except Exception as exc:  # noqa: BLE001 - pydantic validation
        await _refuse(ws, f"That call setup was not usable: {exc}")
        return

    if active_provider() is None:
        await _refuse(ws, missing_key_message())
        return

    try:
        async with storage.SessionLocal() as db:
            setup = await _resolve_call_setup(db, body)
    except HTTPException as exc:
        await _refuse(ws, str(exc.detail))
        return

    from ..live import LiveCall

    client = make_client()
    call = LiveCall(
        client,
        contact=setup.contact,
        context=setup.context,
        greeting=setup.greeting,
        conversation_model=setup.conversation_model,
        conversation_effort=setup.conversation_effort,
        extraction_model=setup.extraction_model,
        extraction_effort=setup.extraction_effort,
    )
    started_at = datetime.now(timezone.utc)

    try:
        await ws.send_json(
            {
                "type": "ready",
                "greeting": setup.greeting,
                "conversation_model": call.conversation_model,
                "language": body.language or (setup.campaign.language if setup.campaign else "en"),
            }
        )
        await call.run(_SocketTransport(ws))

        # A dropped tab gets no extraction: it costs real money and there is
        # nobody left to read it.
        if call.disconnected or not call.transcript:
            return

        await ws.send_json({"type": "extracting"})
        result = await call.extract()
        payload = result.to_dict()
        payload["greeting"] = setup.greeting

        if body.save and setup.campaign is not None:
            async with storage.SessionLocal() as db:
                campaign = await db.get(Campaign, setup.campaign.id)
                if campaign is not None:
                    payload["call_id"] = await _save_simulation(
                        db,
                        campaign,
                        result,
                        started_at=started_at,
                        ended_at=datetime.now(timezone.utc),
                    )

        await ws.send_json({"type": "outcome", "result": payload})

    except auth_error_types():
        # Same distinction the simulator draws: health reports whether a key is
        # present, and a present-but-wrong key otherwise reads as a mystery.
        logger.warning("Live call rejected: bad API key")
        await _refuse(ws, _bad_key_message())
    except rate_limit_error_types():
        logger.warning("Live call rate limited or out of quota")
        await _refuse(ws, _quota_message(call.conversation_model))
    except overloaded_error_types():
        logger.warning("Live call hit provider capacity")
        await _refuse(ws, _busy_message(call.conversation_model))
    except WebSocketDisconnect:
        logger.info("Live call: browser disconnected")
    except Exception as exc:  # noqa: BLE001
        logger.exception("Live call failed")
        await _refuse(ws, f"The call failed: {exc}")
    finally:
        await client.close()
        with _suppress_all():
            await ws.close()


async def _refuse(ws: WebSocket, message: str) -> None:
    """Tell the browser why, in words a person can act on, then leave."""
    with _suppress_all():
        await ws.send_json({"type": "error", "message": message, "fatal": True})


# --------------------------------------------------------------------------
# Suppression
# --------------------------------------------------------------------------


@app.get("/api/suppressions", response_model=list[SuppressionOut])
async def list_suppressions(
    limit: int = Query(default=100, le=1000), db: AsyncSession = Depends(get_session)
):
    rows = (
        await db.execute(
            select(Suppression).order_by(Suppression.created_at.desc()).limit(limit)
        )
    ).scalars().all()
    return [
        SuppressionOut(
            phone_masked=mask(s.phone_e164), reason=s.reason, created_at=s.created_at
        )
        for s in rows
    ]


@app.post("/api/suppressions", response_model=SuppressionOut, status_code=201)
async def add_suppression(
    body: SuppressionCreate, db: AsyncSession = Depends(get_session)
):
    existing = await db.scalar(
        select(Suppression).where(Suppression.phone_e164 == body.phone_e164)
    )
    if existing:
        return SuppressionOut(
            phone_masked=mask(existing.phone_e164),
            reason=existing.reason,
            created_at=existing.created_at,
        )

    entry = Suppression(phone_e164=body.phone_e164, reason=body.reason)
    db.add(entry)

    # Stop any pending attempts against this number across every campaign.
    contacts = (
        await db.execute(select(Contact).where(Contact.phone_e164 == body.phone_e164))
    ).scalars().all()
    for contact in contacts:
        contact.status = ContactStatus.SUPPRESSED

    await db.commit()
    return SuppressionOut(
        phone_masked=mask(entry.phone_e164), reason=entry.reason, created_at=entry.created_at
    )


# --------------------------------------------------------------------------
# Connected apps (MCP servers)
# --------------------------------------------------------------------------
#
# A server's URL and headers are sealed on the way in and never come back
# out: responses carry its host and its header *names*, enough to tell which
# app and which credentials without being able to reuse either.


def _header_names(server: McpServer) -> list[str] | None:
    """The server's header names, or None when its secrets can't be opened."""
    try:
        return list(unseal(server.secrets or "").get("headers") or {})
    except SecretsUnavailable:
        return None


def _server_out(server: McpServer) -> McpServerOut:
    header_names = _header_names(server)
    readable = header_names is not None
    return McpServerOut(
        id=server.id,
        name=server.name,
        slug=server.slug,
        transport=server.transport,
        host=server.host or "",
        header_names=header_names or [],
        enabled=bool(server.enabled),
        # Said now, not at the next refresh: a changed key breaks the server
        # the moment it changes.
        status=server.status if readable else "error",
        last_error=server.last_error if readable else REENTER_MESSAGE,
        checked_at=server.checked_at,
        tools=[
            McpToolOut(
                id=tool_id(server.slug, tool["name"]),
                name=tool["name"],
                description=tool.get("description") or "",
                input_schema=tool.get("input_schema") or {},
            )
            for tool in server.tools or []
        ],
    )


async def _checked_url(url: str) -> str:
    """`url`, or a 400 saying why it can't be connected to."""
    url = url.strip()
    try:
        # In a thread: it resolves the host, and DNS must not stall live calls.
        await asyncio.to_thread(check_url, url)
    except UnsafeUrl as exc:
        raise HTTPException(400, str(exc)) from exc
    return url


async def _discover(server: McpServer, *, detect_transport: bool) -> None:
    """Re-read a server's tools and record how that went. Never raises.

    A failure keeps the tools already known, so campaigns that use them
    still save while the app is briefly down; calls skip it until it is ok.
    """
    try:
        tools = await (discover_transport(server) if detect_transport else discover_tools(server))
    except McpUnavailable as exc:
        server.status, server.last_error = "error", str(exc)
    else:
        server.status, server.last_error, server.tools = "ok", None, tools
    server.checked_at = datetime.now(timezone.utc)


async def _server_or_404(db: AsyncSession, server_id: str) -> McpServer:
    server = await db.get(McpServer, server_id)
    if server is None:
        raise HTTPException(404, "No such server.")
    return server


@app.get("/api/mcp/servers", response_model=list[McpServerOut])
async def list_mcp_servers(db: AsyncSession = Depends(get_session)):
    servers = (await db.execute(select(McpServer).order_by(McpServer.created_at))).scalars().all()
    return [_server_out(server) for server in servers]


@app.post("/api/mcp/servers", response_model=McpServerOut, status_code=201)
async def create_mcp_server(body: McpServerCreate, db: AsyncSession = Depends(get_session)):
    """Connect an app, and discover its tools straight away.

    A server whose discovery fails is still saved, with the reason, so the
    URL or key can be fixed rather than typed in again. An unsafe URL is
    refused outright.
    """
    url = await _checked_url(body.url)
    taken = set((await db.execute(select(McpServer.slug))).scalars().all())
    server = McpServer(
        id=str(uuid.uuid4()),
        name=body.name,
        slug=unique_slug(body.name, taken),
        transport=BUILTIN if is_builtin(url) else body.transport,
        host=host_of(url),
        secrets=seal({"url": url, "headers": body.headers}),
        enabled=True,
        status="unchecked",
        tools=[],
    )
    await _discover(server, detect_transport=server.transport == AUTO)
    db.add(server)
    await db.commit()
    return _server_out(server)


@app.patch("/api/mcp/servers/{server_id}", response_model=McpServerOut)
async def update_mcp_server(
    server_id: str, body: McpServerUpdate, db: AsyncSession = Depends(get_session)
):
    """Rename, pause, or re-point a server. New URL or headers are re-discovered.

    The slug stays: campaigns hold tool ids made from it.
    """
    server = await _server_or_404(db, server_id)
    url = await _checked_url(body.url) if body.url is not None else None

    if url is not None or body.headers is not None:
        try:
            current = unseal(server.secrets or "")
        except SecretsUnavailable:
            if url is None:
                raise HTTPException(400, REENTER_MESSAGE) from None
            current = {}
        url = url or current["url"]
        headers = body.headers if body.headers is not None else current.get("headers") or {}
        server.secrets = seal({"url": url, "headers": headers})
        server.host = host_of(url)
        if body.url is not None:
            server.transport = BUILTIN if is_builtin(url) else AUTO
        await _discover(server, detect_transport=server.transport == AUTO)

    if body.name is not None:
        server.name = body.name
    if body.enabled is not None:
        server.enabled = body.enabled
    await db.commit()
    return _server_out(server)


@app.delete("/api/mcp/servers/{server_id}", status_code=204)
async def delete_mcp_server(server_id: str, db: AsyncSession = Depends(get_session)) -> Response:
    """Disconnect an app, and take its tools off every campaign that chose them."""
    server = await _server_or_404(db, server_id)
    prefix = server_prefix(server.slug)
    for campaign in (await db.execute(select(Campaign))).scalars().all():
        for field in ("mcp_tools", "mcp_post_call_tools"):
            chosen = getattr(campaign, field) or []
            kept = [tid for tid in chosen if not tid.startswith(prefix)]
            if kept != chosen:
                setattr(campaign, field, kept)
    await db.delete(server)
    await db.commit()
    return Response(status_code=204)


@app.post("/api/mcp/servers/{server_id}/refresh", response_model=McpServerOut)
async def refresh_mcp_server(server_id: str, db: AsyncSession = Depends(get_session)):
    server = await _server_or_404(db, server_id)
    await _discover(server, detect_transport=False)
    await db.commit()
    return _server_out(server)


@app.post("/api/mcp/servers/{server_id}/tools/{name}/test", response_model=McpToolTestResult)
async def test_mcp_tool(
    server_id: str, name: str, body: McpToolTest, db: AsyncSession = Depends(get_session)
):
    """Run one tool once, as a call would, for the console's "Try it" panel."""
    server = await _server_or_404(db, server_id)
    if not any(tool.get("name") == name for tool in server.tools or []):
        raise HTTPException(404, f"{server.name} has no tool called {name}.")

    toolbox = CallToolbox.for_server(server, phase="test")
    started = time.perf_counter()
    try:
        result = await toolbox.call(tool_id(server.slug, name), body.arguments)
    finally:
        await toolbox.aclose()
    return McpToolTestResult(
        ok=result.ok, text=result.text, duration_ms=int((time.perf_counter() - started) * 1000)
    )


@app.get("/api/mcp/tools", response_model=list[McpCatalogTool])
async def list_mcp_tools(db: AsyncSession = Depends(get_session)):
    """Every tool a call could use right now: enabled, healthy servers only."""
    servers = (
        await db.execute(
            select(McpServer)
            .where(McpServer.enabled.is_(True), McpServer.status == "ok")
            .order_by(McpServer.created_at)
        )
    ).scalars().all()
    return [
        McpCatalogTool(server_id=server.id, server_name=server.name, **tool.model_dump())
        for server in servers
        if _header_names(server) is not None  # a call couldn't open it
        for tool in _server_out(server).tools
    ]


async def _check_tool_ids(db: AsyncSession, *lists: list[str] | None) -> None:
    """400 unless every id names a tool some connected server has.

    Checked against every server, healthy or not: one briefly failing must
    not stop a campaign that uses it from being saved.
    """
    wanted = {tid for ids in lists for tid in ids or []}
    if not wanted:
        return
    servers = (await db.execute(select(McpServer))).scalars().all()
    known = {tool_id(s.slug, t["name"]) for s in servers for t in s.tools or [] if t.get("name")}
    unknown = sorted(wanted - known)
    if unknown:
        raise HTTPException(
            400,
            f"Unknown tools: {', '.join(unknown)}. Pick tools from a connected app "
            "under Integrations, or refresh the app if it has changed.",
        )


# --------------------------------------------------------------------------
# Live feed
# --------------------------------------------------------------------------


@app.websocket("/api/events")
async def events(ws: WebSocket) -> None:
    if not await _socket_allowed(ws):
        return
    await ws.accept()
    try:
        async for event in bus.subscribe():
            await ws.send_json(event.to_dict())
    except WebSocketDisconnect:
        pass
    except Exception:
        logger.exception("Event stream failed")
    finally:
        with _suppress_all():
            await ws.close()


class _suppress_all:
    """Swallow any exception. Used around socket cleanup where failure is normal."""
    def __enter__(self):
        return self
    def __exit__(self, *exc):
        return True


# --------------------------------------------------------------------------
# Twilio webhook routes (mounted on main app so they work on single-port hosts)
# --------------------------------------------------------------------------

try:
    from ..voice.twilio_adapter import _build_webhook_app as _build_twilio_app
    _twilio_app = _build_twilio_app()
    # Routes inside already have /twilio/ prefix, so mount at root
    app.mount("", _twilio_app)
    logger.info("Twilio webhook routes mounted")
except Exception:
    logger.debug("Twilio webhook routes not mounted (twilio adapter not available)")


# --------------------------------------------------------------------------
# Static frontend (production). Mounted last so /api/* wins.
# --------------------------------------------------------------------------

_dist = Path(__file__).resolve().parents[3] / "frontend" / "dist"

if _dist.is_dir():
    # Hashed build assets are served directly.
    app.mount("/assets", StaticFiles(directory=str(_dist / "assets")), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    async def spa(path: str) -> FileResponse:
        """Serve index.html for any non-API path so client-side routes work.

        A plain StaticFiles mount only resolves index.html for directory
        requests, so deep links like /campaigns 404 on refresh. React Router
        needs the document served for every route it owns.
        """
        if path.startswith("api/"):
            raise HTTPException(404, "Not found")

        # Real files (favicon, manifest) still win over the SPA fallback.
        candidate = (_dist / path).resolve()
        if path and candidate.is_file() and candidate.is_relative_to(_dist.resolve()):
            return FileResponse(candidate)

        return FileResponse(_dist / "index.html")
