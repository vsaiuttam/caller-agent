"""Model catalog, token accounting, and cost estimation.

Picking a model for a calling platform is not a preference — it's a tradeoff
between three things that pull against each other:

  - **Latency.** On the in-call path, every 100ms of time-to-first-audio is
    felt by the person on the line. Nothing else in the system matters if the
    agent sounds like it's buffering.
  - **Correctness.** On the post-call path, latency is free and being wrong is
    expensive: extraction output is written into a calendar and a customer
    record with no human in between.
  - **Cost.** At thousands of calls a day the per-call delta between models
    compounds into real money, so the choice deserves a number rather than a
    vibe.

Most platforms hide this behind "AI powered" and give you no lever. This module
is the lever: it publishes what each model costs, which role it suits, and what
a campaign of N calls will actually spend before you dial anybody.

Prices are USD per million tokens, first-party Anthropic API rates. They are
cached values with a date on them, not a live feed — treat estimates as
estimates, and re-check `PRICING_AS_OF` against the pricing page before
quoting a customer.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field

from .providers import active_id

PRICING_AS_OF = "2026-09-04"

# Prompt-cache multipliers against the base input rate. A 5-minute cache write
# costs 1.25x input; a read costs 0.1x. The whole point of the two-breakpoint
# prompt layout in prompts.py is to land on that 0.1x for the persona block on
# every call after the first.
CACHE_WRITE_MULTIPLIER = 1.25
CACHE_READ_MULTIPLIER = 0.10


@dataclass(frozen=True)
class ModelSpec:
    id: str
    name: str
    family: str
    context_tokens: int
    input_per_mtok: float
    output_per_mtok: float
    # "fastest" | "fast" | "balanced" | "deliberate" — relative time-to-first
    # -token, which is what the in-call path actually cares about.
    speed: str
    # Which jobs this model is offerable for in the UI.
    roles: tuple[str, ...]
    tagline: str
    # Which provider serves this id. Only models belonging to the active
    # provider are offered or resolvable — see `resolve()`.
    provider: str = "anthropic"
    strengths: tuple[str, ...] = ()
    watch_out: str = ""
    note: str = ""
    recommended_for: tuple[str, ...] = ()

    @property
    def cache_write_per_mtok(self) -> float:
        return round(self.input_per_mtok * CACHE_WRITE_MULTIPLIER, 4)

    @property
    def cache_read_per_mtok(self) -> float:
        return round(self.input_per_mtok * CACHE_READ_MULTIPLIER, 4)

    def to_dict(self) -> dict:
        data = asdict(self)
        data["strengths"] = list(self.strengths)
        data["roles"] = list(self.roles)
        data["recommended_for"] = list(self.recommended_for)
        data["cache_write_per_mtok"] = self.cache_write_per_mtok
        data["cache_read_per_mtok"] = self.cache_read_per_mtok
        return data


CONVERSATION = "conversation"
EXTRACTION = "extraction"


MODELS: list[ModelSpec] = [
    ModelSpec(
        id="claude-haiku-4-5",
        name="Claude Haiku 4.5",
        family="Haiku",
        context_tokens=200_000,
        input_per_mtok=1.00,
        output_per_mtok=5.00,
        speed="fastest",
        roles=(CONVERSATION,),
        tagline="Cheapest and quickest on the line. Best for short, scripted calls.",
        strengths=(
            "Lowest time-to-first-audio of any model here",
            "Roughly a third the cost of Sonnet per conversation",
            "Plenty for confirm-a-detail and reminder calls",
        ),
        watch_out=(
            "Loses the thread on long, meandering calls and handles objections "
            "less gracefully. Not offered for extraction — a wrong appointment "
            "costs far more than the few cents saved."
        ),
        recommended_for=("Appointment reminders", "Delivery confirmations", "Short surveys"),
    ),
    ModelSpec(
        id="claude-sonnet-5",
        name="Claude Sonnet 5",
        family="Sonnet",
        context_tokens=1_000_000,
        input_per_mtok=3.00,
        output_per_mtok=15.00,
        speed="fast",
        roles=(CONVERSATION, EXTRACTION),
        tagline="The default for live conversation. Near-Opus quality at low effort.",
        strengths=(
            "Handles interruptions, objections, and topic changes naturally",
            "Low effort keeps it quick without flattening the conversation",
            "Good multilingual register — Hindi and Urdu sound spoken, not translated",
        ),
        watch_out=(
            "At high effort it thinks longer than a phone call tolerates. Keep "
            "it on low or medium for the in-call role."
        ),
        note="Introductory pricing runs through 2026-08-31; list rate shown.",
        recommended_for=("Lead qualification", "Renewals", "Anything open-ended"),
    ),
    ModelSpec(
        id="claude-opus-5",
        name="Claude Opus 5",
        family="Opus",
        context_tokens=1_000_000,
        input_per_mtok=5.00,
        output_per_mtok=25.00,
        speed="balanced",
        roles=(CONVERSATION, EXTRACTION),
        tagline="The default for extraction. Use in-call only when the call is high-stakes.",
        strengths=(
            "Best at resolving 'actually, make it Thursday' from a messy transcript",
            "Most reliable at admitting it is unsure instead of guessing",
            "High effort is affordable off the call path — pennies per extraction",
        ),
        watch_out=(
            "On the in-call path it is noticeably more deliberate. Worth it for "
            "a call closing real money; wasteful for a reminder."
        ),
        recommended_for=("Post-call extraction", "Complex negotiations", "Regulated calls"),
    ),
    ModelSpec(
        id="claude-fable-5",
        name="Claude Fable 5",
        family="Fable",
        context_tokens=1_000_000,
        input_per_mtok=10.00,
        output_per_mtok=50.00,
        speed="deliberate",
        roles=(EXTRACTION,),
        tagline="Most capable, most expensive. Reserve for transcripts you cannot get wrong.",
        strengths=(
            "Highest ceiling on ambiguous or multi-party transcripts",
            "Worth it when a wrong extraction has legal or financial weight",
        ),
        watch_out=(
            "Twice Opus pricing. Not offered for the in-call role — it is the "
            "wrong shape for a real-time conversation."
        ),
        recommended_for=("Medical intake", "Financial disclosures", "Dispute handling"),
    ),
    # ---- Google Gemini ---------------------------------------------------
    # Added for multilingual reach rather than price, though it is also
    # cheaper: the Live API lists 97 languages including Hindi *and* Urdu,
    # and native-audio models switch language mid-conversation without being
    # told to — which is what a Hinglish call actually is.
    ModelSpec(
        id="gemini-3.8-flash",
        name="Gemini 3.8 Flash",
        family="Gemini",
        provider="gemini",
        context_tokens=1_048_576,
        input_per_mtok=0.75,
        output_per_mtok=3.75,
        speed="fast",
        roles=(CONVERSATION, EXTRACTION),
        tagline="The default on Gemini for both roles. Broadest language coverage here.",
        strengths=(
            "Hindi, Urdu, and code-mixed Hinglish without a language setting",
            "A fifth of Sonnet's input price at comparable conversational quality",
            "Structured extraction lands the nested appointment schema reliably",
        ),
        watch_out=(
            "Thinking tokens are billed as output and are not included in the "
            "reported completion count, so the ledger derives them from the "
            "total. Expect output charges above what the transcript suggests."
        ),
        note="Introductory pricing runs through 2026-12-31; doubles after.",
        recommended_for=("Hindi and Urdu campaigns", "Hinglish", "Cost-sensitive volume"),
    ),
    ModelSpec(
        id="gemini-3.1-flash-lite",
        name="Gemini 3.1 Flash Lite",
        family="Gemini",
        provider="gemini",
        context_tokens=1_048_576,
        input_per_mtok=0.25,
        output_per_mtok=1.50,
        speed="fastest",
        roles=(CONVERSATION,),
        tagline="The default on the line. Cheapest and quickest to first audio here.",
        strengths=(
            "Measured at ~1.6s to first token against ~5s on 3.7 Flash",
            "A third of Flash's input price",
            "Its own free-tier quota pool, separate from the Flash models",
        ),
        watch_out=(
            "Thinks less, which is the point in-call and a liability off it. Not "
            "offered for extraction — a lightly-considered appointment written "
            "into a calendar costs more than the tenth of a cent it saves."
        ),
        recommended_for=("The in-call path", "Reminders", "High-volume campaigns"),
    ),
    ModelSpec(
        id="gemini-3.5-flash-lite",
        name="Gemini 3.5 Flash Lite",
        family="Gemini",
        provider="gemini",
        context_tokens=1_048_576,
        input_per_mtok=0.30,
        output_per_mtok=2.50,
        speed="fast",
        roles=(CONVERSATION,),
        tagline="A second Lite tier, useful when 3.1's quota is exhausted.",
        strengths=("Another separate quota pool", "Same language coverage"),
        watch_out="Measured slower than 3.1 Flash Lite (~3.1s) and priced higher.",
        recommended_for=("A fallback when 3.1 Lite is rate limited",),
    ),
    ModelSpec(
        id="gemini-3.6-flash",
        name="Gemini 3.6 Flash",
        family="Gemini",
        provider="gemini",
        context_tokens=1_048_576,
        input_per_mtok=0.75,
        output_per_mtok=3.75,
        speed="fast",
        roles=(CONVERSATION, EXTRACTION),
        tagline="The default extractor on Gemini. Reads a reversal correctly for Flash money.",
        strengths=(
            "Verified on a mid-call reschedule: took Thursday, not the Tuesday "
            "that was agreed first, and resolved the date against the call day",
            "Half the price of 3.5 Flash for the same result",
            "Quota that the newest model does not always have",
        ),
        watch_out=(
            "A generation behind 3.8. Worth re-checking against it whenever the "
            "newer model has quota to spare."
        ),
        recommended_for=("Post-call extraction",),
    ),
    ModelSpec(
        id="gemini-3.5-flash",
        name="Gemini 3.5 Flash",
        family="Gemini",
        provider="gemini",
        context_tokens=1_048_576,
        input_per_mtok=1.50,
        output_per_mtok=9.00,
        speed="fast",
        roles=(CONVERSATION, EXTRACTION),
        tagline="The previous Flash generation. Keep a campaign on it for comparability.",
        strengths=(
            "Same language coverage as 3.8",
            "Useful as a fixed baseline while tuning prompts against a newer model",
        ),
        watch_out="Twice the price of 3.8 Flash with no advantage on these calls.",
        recommended_for=("A/B baselines",),
    ),
    ModelSpec(
        id="gemini-3.1-pro-preview",
        name="Gemini 3.1 Pro",
        family="Gemini",
        provider="gemini",
        context_tokens=1_048_576,
        input_per_mtok=2.00,
        output_per_mtok=12.00,
        speed="deliberate",
        roles=(EXTRACTION,),
        tagline="Gemini's careful reader. For transcripts where the booking must be right.",
        strengths=(
            "Best Gemini option at resolving reversals late in a transcript",
            "Still under half of Opus 5 per extraction",
        ),
        watch_out=(
            "No free-tier quota — a key without billing enabled gets a 429 on "
            "the first call. Enable billing before assigning it to a campaign."
        ),
        recommended_for=("Post-call extraction once billing is on",),
    ),
]

MODELS_BY_ID = {m.id: m for m in MODELS}


# --------------------------------------------------------------------------
# Effort
# --------------------------------------------------------------------------

# Effort controls how much the model thinks before answering. It is the single
# biggest lever on both latency and output-token spend, so it is a first-class
# setting rather than a constant buried in the client.
#
# `output_multiplier` is a working heuristic used *only* for the estimator; the
# ledger on real calls records actual token counts from the API.
EFFORTS: list[dict] = [
    {
        "value": "low",
        "label": "Low",
        "output_multiplier": 1.0,
        "description": "Answers immediately. The only sensible setting for live conversation.",
    },
    {
        "value": "medium",
        "label": "Medium",
        "output_multiplier": 1.8,
        "description": "Thinks briefly. Tolerable in-call on a fast model; better for extraction.",
    },
    {
        "value": "high",
        "label": "High",
        "output_multiplier": 3.2,
        "description": "Thinks properly. Right for extraction; too slow to sit on a phone call.",
    },
]

EFFORT_MULTIPLIER = {e["value"]: e["output_multiplier"] for e in EFFORTS}

DEFAULT_CONVERSATION_MODEL = "claude-sonnet-5"
DEFAULT_CONVERSATION_EFFORT = "low"
DEFAULT_EXTRACTION_MODEL = "claude-opus-5"
DEFAULT_EXTRACTION_EFFORT = "high"

DEFAULTS = {
    "conversation_model": DEFAULT_CONVERSATION_MODEL,
    "conversation_effort": DEFAULT_CONVERSATION_EFFORT,
    "extraction_model": DEFAULT_EXTRACTION_MODEL,
    "extraction_effort": DEFAULT_EXTRACTION_EFFORT,
}

# Per-provider defaults. The constants above stay as they are because they are
# baked into database column defaults and request schemas; these are what a
# running process actually picks when nothing was chosen explicitly.
#
# Gemini extracts on Flash rather than Pro deliberately: 3.1 Pro has no
# free-tier quota, so defaulting to it would make the first extraction of a
# fresh key fail with a 429 — a bad first impression for a setting nobody
# asked to change.
PROVIDER_DEFAULTS: dict[str, dict[str, str]] = {
    "anthropic": DEFAULTS,
    # Split across two models on purpose, and it buys three things at once.
    # Lite is the fastest to first audio we measured (~1.6s against ~5s), it is
    # a third of the price on the path that runs eight times per call, and —
    # on a free tier — it draws from a different quota pool than the extraction
    # model, so a long conversation cannot rate-limit its own extraction.
    "gemini": {
        "conversation_model": "gemini-3.1-flash-lite",
        "conversation_effort": "low",
        "extraction_model": "gemini-3.6-flash",
        "extraction_effort": "high",
    },
}


def active_defaults() -> dict[str, str]:
    """Defaults for whichever provider this process is configured for."""
    return PROVIDER_DEFAULTS.get(active_id(), DEFAULTS)


def default_model(role: str) -> str:
    key = "conversation_model" if role == CONVERSATION else "extraction_model"
    return active_defaults()[key]


def models_for_active() -> list[ModelSpec]:
    """The catalog, narrowed to what the configured key can actually call."""
    provider = active_id()
    return [m for m in MODELS if m.provider == provider] if provider else MODELS


def resolve(model_id: str | None, role: str) -> str:
    """Return a usable model id for `role`, falling back to the role default.

    A model removed from the catalog, assigned to a role it isn't offered
    for, or belonging to a provider this deployment has no key for must not
    take the call path down — a stale id in a campaign row falls back rather
    than raising at dial time.

    That last case is what makes switching providers safe. Campaigns created
    against Anthropic still hold `claude-sonnet-5`; pointing .env at Gemini
    resolves them onto Gemini's default instead of failing at connect time,
    with no migration and no edit to any campaign.
    """
    spec = MODELS_BY_ID.get(model_id or "")
    provider = active_id()
    if spec and role in spec.roles and (not provider or spec.provider == provider):
        return spec.id
    return default_model(role)


def resolve_for_pricing(model_id: str | None, role: str) -> str:
    """The model an *estimate* should price. Deliberately not provider-aware.

    `resolve()` answers "what will actually run", so it has to route around a
    provider we hold no key for. This answers "what would this cost", and the
    Models page uses it to rank models against each other — routing around the
    inactive ones there would make every row on the page show an identical
    number, which is the one outcome that makes a comparison tool useless.
    """
    spec = MODELS_BY_ID.get(model_id or "")
    if spec and role in spec.roles:
        return spec.id
    return default_model(role)


def resolve_effort(effort: str | None, role: str) -> str:
    if effort in EFFORT_MULTIPLIER:
        return effort
    return DEFAULT_CONVERSATION_EFFORT if role == CONVERSATION else DEFAULT_EXTRACTION_EFFORT


# --------------------------------------------------------------------------
# Token accounting
# --------------------------------------------------------------------------


@dataclass
class TokenUsage:
    """Running token totals for one call, across every model it touched.

    Kept per-model because a call bills two different rates: the conversational
    model per turn, and the extraction model once at the end.
    """

    by_model: dict[str, dict[str, int]] = field(default_factory=dict)

    def add(
        self,
        model: str,
        *,
        input_tokens: int = 0,
        output_tokens: int = 0,
        cache_read_tokens: int = 0,
        cache_write_tokens: int = 0,
    ) -> None:
        bucket = self.by_model.setdefault(
            model,
            {"input": 0, "output": 0, "cache_read": 0, "cache_write": 0},
        )
        bucket["input"] += input_tokens
        bucket["output"] += output_tokens
        bucket["cache_read"] += cache_read_tokens
        bucket["cache_write"] += cache_write_tokens

    def add_response_usage(self, model: str, usage) -> None:
        """Fold in an SDK usage object, from either API shape.

        Anthropic reports `input_tokens` / `output_tokens`; the OpenAI shape
        reports `prompt_tokens` / `completion_tokens`. Field names have also
        moved across API versions, so read defensively: a missing cache
        counter should cost us a slightly low estimate, not an AttributeError
        on the call path.

        The `total_tokens` clause is not redundant. Gemini bills thinking as
        output but leaves it out of `completion_tokens` — on a real extraction
        we measured 233 completion tokens against a 936-token total. Taking
        the larger of the two keeps the ledger honest instead of under-billing
        by the size of the reasoning, which on a thinking model is most of it.
        """
        if usage is None:
            return

        def field(*names: str) -> int:
            for name in names:
                value = getattr(usage, name, None)
                if value:
                    return int(value)
            return 0

        prompt = field("input_tokens", "prompt_tokens")
        completion = field("output_tokens", "completion_tokens")
        total = field("total_tokens")
        if total > prompt + completion:
            completion = total - prompt

        # OpenAI-shaped providers nest the cache counter; Gemini's compatible
        # endpoint omits the block entirely, so cached reads read as zero and
        # the reported cost is a ceiling rather than a floor there.
        details = getattr(usage, "prompt_tokens_details", None)
        cached = getattr(details, "cached_tokens", 0) or 0 if details else 0

        self.add(
            model,
            input_tokens=prompt,
            output_tokens=completion,
            cache_read_tokens=field("cache_read_input_tokens") or cached,
            cache_write_tokens=field("cache_creation_input_tokens"),
        )

    def merge(self, other: "TokenUsage") -> None:
        for model, bucket in other.by_model.items():
            self.add(
                model,
                input_tokens=bucket["input"],
                output_tokens=bucket["output"],
                cache_read_tokens=bucket["cache_read"],
                cache_write_tokens=bucket["cache_write"],
            )

    @property
    def input_tokens(self) -> int:
        return sum(b["input"] for b in self.by_model.values())

    @property
    def output_tokens(self) -> int:
        return sum(b["output"] for b in self.by_model.values())

    @property
    def cache_read_tokens(self) -> int:
        return sum(b["cache_read"] for b in self.by_model.values())

    @property
    def cache_write_tokens(self) -> int:
        return sum(b["cache_write"] for b in self.by_model.values())

    @property
    def cache_hit_rate(self) -> float:
        """Share of prompt input served from cache. The prompt layout's KPI."""
        total = self.input_tokens + self.cache_read_tokens + self.cache_write_tokens
        return round(self.cache_read_tokens / total, 4) if total else 0.0

    def cost_usd(self) -> float:
        total = 0.0
        for model, bucket in self.by_model.items():
            spec = MODELS_BY_ID.get(model)
            if spec is None:
                continue
            total += (
                bucket["input"] * spec.input_per_mtok
                + bucket["output"] * spec.output_per_mtok
                + bucket["cache_read"] * spec.cache_read_per_mtok
                + bucket["cache_write"] * spec.cache_write_per_mtok
            ) / 1_000_000
        return round(total, 6)

    def to_dict(self) -> dict:
        return {
            "input_tokens": self.input_tokens,
            "output_tokens": self.output_tokens,
            "cache_read_tokens": self.cache_read_tokens,
            "cache_write_tokens": self.cache_write_tokens,
            "cache_hit_rate": self.cache_hit_rate,
            "cost_usd": self.cost_usd(),
            "by_model": self.by_model,
        }


# --------------------------------------------------------------------------
# Estimation
# --------------------------------------------------------------------------

# Token shape of a typical call, measured against the prompt layout in
# prompts.py. These are averages, and the estimator says so — the point is to
# tell the difference between a $40 campaign and a $900 one before dialling,
# not to predict a single call to the cent.
_PERSONA_TOKENS = 620       # frozen VOICE_PERSONA block — cached after call #1
_CONTEXT_TOKENS = 320       # per-campaign context block — cached within a campaign
_TOKENS_PER_TURN = 42       # one side of one exchange
_AGENT_OUTPUT_TOKENS = 55   # the agent's spoken reply, before effort multiplier
_EXTRACTION_SYSTEM_TOKENS = 430
_EXTRACTION_OUTPUT_TOKENS = 320


def estimate_call(
    *,
    conversation_model: str,
    conversation_effort: str,
    extraction_model: str,
    extraction_effort: str,
    exchanges: int = 8,
    cache_hit: bool = True,
) -> dict:
    """Estimated cost of one call, broken down by phase.

    `exchanges` is round-trips: one agent turn plus one person turn. Eight is a
    typical qualification call; a reminder is three or four.

    `cache_hit` models the steady state — the first call of a campaign pays the
    cache-write premium, every call after it reads. Over a campaign of any size
    the steady state is what the bill looks like.
    """
    conv = MODELS_BY_ID.get(resolve_for_pricing(conversation_model, CONVERSATION))
    extract = MODELS_BY_ID.get(resolve_for_pricing(extraction_model, EXTRACTION))
    assert conv and extract  # resolution never returns an unknown id

    conv_mult = EFFORT_MULTIPLIER.get(resolve_effort(conversation_effort, CONVERSATION), 1.0)
    extract_mult = EFFORT_MULTIPLIER.get(resolve_effort(extraction_effort, EXTRACTION), 1.0)

    prefix = _PERSONA_TOKENS + _CONTEXT_TOKENS

    # Each turn resends the whole conversation so far. The cached prefix is
    # billed at the read rate; the growing transcript is billed at full rate.
    fresh_input = 0
    for turn in range(exchanges):
        fresh_input += turn * 2 * _TOKENS_PER_TURN

    cached_input = prefix * exchanges if cache_hit else 0
    uncached_input = fresh_input + (0 if cache_hit else prefix * exchanges)
    conv_output = int(_AGENT_OUTPUT_TOKENS * conv_mult) * exchanges

    conversation_cost = (
        uncached_input * conv.input_per_mtok
        + cached_input * conv.cache_read_per_mtok
        + conv_output * conv.output_per_mtok
    ) / 1_000_000

    transcript_tokens = exchanges * 2 * _TOKENS_PER_TURN
    extraction_input = _EXTRACTION_SYSTEM_TOKENS + transcript_tokens
    extraction_output = int(_EXTRACTION_OUTPUT_TOKENS * extract_mult)
    extraction_cost = (
        extraction_input * extract.input_per_mtok
        + extraction_output * extract.output_per_mtok
    ) / 1_000_000

    return {
        "conversation_model": conv.id,
        "extraction_model": extract.id,
        "exchanges": exchanges,
        "conversation_cost_usd": round(conversation_cost, 6),
        "extraction_cost_usd": round(extraction_cost, 6),
        "cost_per_call_usd": round(conversation_cost + extraction_cost, 6),
        "input_tokens": uncached_input + cached_input + extraction_input,
        "output_tokens": conv_output + extraction_output,
        "assumes_cache_hit": cache_hit,
    }


def estimate_campaign(
    *,
    contacts: int,
    connect_rate: float = 0.55,
    **call_kwargs,
) -> dict:
    """Project a whole campaign.

    Unconnected dials are not free but they are cheap: a voicemail or no-answer
    still runs extraction on an empty transcript, which short-circuits before
    any model call. We bill those at zero and say so, rather than quietly
    inflating the estimate by 45%.
    """
    per_call = estimate_call(**call_kwargs)
    connected = round(contacts * max(0.0, min(1.0, connect_rate)))
    total = per_call["cost_per_call_usd"] * connected

    return {
        **per_call,
        "contacts": contacts,
        "connect_rate": connect_rate,
        "connected_calls": connected,
        "total_cost_usd": round(total, 4),
        "cost_per_connected_call_usd": per_call["cost_per_call_usd"],
    }


def catalog_dict() -> dict:
    """The catalog as the UI sees it.

    Only the active provider's models are listed. Showing an Opus card to a
    deployment holding a Gemini key would be an invitation to pick something
    that cannot run.
    """
    from .providers import active

    spec = active()
    return {
        "models": [m.to_dict() for m in models_for_active()],
        "efforts": EFFORTS,
        "defaults": active_defaults(),
        "pricing_as_of": PRICING_AS_OF,
        "roles": [CONVERSATION, EXTRACTION],
        "provider": spec.id if spec else "",
        "provider_label": spec.label if spec else "",
    }
