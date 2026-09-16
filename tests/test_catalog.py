"""Tests for model selection and cost accounting.

These cover the two ways the model layer can fail quietly rather than loudly:
a stale model id in a campaign row taking the call path down at dial time, and
a cost figure that is wrong in a direction nobody notices until the invoice.

Runs standalone (`python tests/test_catalog.py`) or under pytest. No API key
and no network.
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

# Pin the provider before anything reads it. Model resolution is now
# provider-aware, so without this the suite would pass or fail depending on
# which vendor's key the developer happens to have in .env — a test that
# depends on local credentials is not testing what it claims to.
os.environ["MODEL_PROVIDER"] = "anthropic"
os.environ.setdefault("ANTHROPIC_API_KEY", "test-key-not-used-no-network")

from src.voiceagent.catalog import (  # noqa: E402
    CONVERSATION,
    DEFAULT_CONVERSATION_MODEL,
    DEFAULT_EXTRACTION_MODEL,
    EXTRACTION,
    MODELS_BY_ID,
    TokenUsage,
    default_model,
    estimate_call,
    estimate_campaign,
    resolve,
    resolve_effort,
)


def test_resolve_falls_back_rather_than_raising() -> None:
    """A campaign row holding a removed model id must not break the call.

    Campaigns outlive catalog entries. If a model is retired, every campaign
    still pointing at it has to keep dialling — degraded to the default, never
    failing at connect time.
    """
    assert resolve("claude-does-not-exist", CONVERSATION) == DEFAULT_CONVERSATION_MODEL
    assert resolve(None, EXTRACTION) == DEFAULT_EXTRACTION_MODEL
    assert resolve("", CONVERSATION) == DEFAULT_CONVERSATION_MODEL


def test_resolve_rejects_a_model_in_the_wrong_role() -> None:
    """Fable is extraction-only; Haiku is conversation-only.

    Assigning either to the other role is not a preference to be honoured —
    Fable on the in-call path sounds broken, and Haiku on extraction writes
    confident wrong appointments into a calendar.
    """
    assert resolve("claude-fable-5", CONVERSATION) == DEFAULT_CONVERSATION_MODEL
    assert resolve("claude-fable-5", EXTRACTION) == "claude-fable-5"

    assert resolve("claude-haiku-4-5", EXTRACTION) == DEFAULT_EXTRACTION_MODEL
    assert resolve("claude-haiku-4-5", CONVERSATION) == "claude-haiku-4-5"


def test_resolve_routes_around_a_provider_we_hold_no_key_for() -> None:
    """Switching provider must not require editing a single campaign row.

    Campaigns created against Anthropic still hold `claude-sonnet-5`. Pointing
    .env at Gemini has to keep them dialling on a Gemini model rather than
    failing at connect time — otherwise trying a different vendor means a
    migration, and nobody tries a different vendor.
    """
    os.environ["MODEL_PROVIDER"] = "gemini"
    os.environ.setdefault("GEMINI_API_KEY", "test-key-not-used-no-network")
    try:
        # Asserted against the resolved default rather than a literal id: which
        # model that is, is a tuning decision that will change again. What must
        # not change is that a foreign id lands on *something Gemini can run*.
        for stale, role in (("claude-sonnet-5", CONVERSATION), ("claude-opus-5", EXTRACTION)):
            landed = resolve(stale, role)
            assert landed == default_model(role)
            assert MODELS_BY_ID[landed].provider == "gemini"
            assert role in MODELS_BY_ID[landed].roles

        # A model the active provider does own is left alone.
        assert resolve("gemini-3.8-flash", EXTRACTION) == "gemini-3.8-flash"
    finally:
        os.environ["MODEL_PROVIDER"] = "anthropic"


def test_estimates_price_the_model_asked_about_not_the_active_one() -> None:
    """Pricing and routing are different questions.

    The Models page ranks models against each other, including ones this
    deployment holds no key for. If the estimator substituted the active
    provider's default the way the call path does, every row on that page
    would show an identical number.
    """
    os.environ["MODEL_PROVIDER"] = "gemini"
    try:
        common = {
            "conversation_effort": "low",
            "extraction_model": "claude-opus-5",
            "extraction_effort": "high",
        }
        haiku = estimate_call(conversation_model="claude-haiku-4-5", **common)
        opus = estimate_call(conversation_model="claude-opus-5", **common)

        assert haiku["conversation_model"] == "claude-haiku-4-5"
        assert haiku["conversation_cost_usd"] < opus["conversation_cost_usd"]
    finally:
        os.environ["MODEL_PROVIDER"] = "anthropic"


class _OpenAIShapedUsage:
    """Real numbers from one Gemini extraction through the compat endpoint."""

    prompt_tokens = 146
    completion_tokens = 233
    total_tokens = 936
    prompt_tokens_details = None


def test_thinking_tokens_are_billed_even_when_not_reported_as_completion() -> None:
    """Gemini bills thinking as output but omits it from completion_tokens.

    Measured, not assumed: 146 prompt, 233 completion, 936 total on a real
    transcript. Taking completion_tokens at face value under-bills by 557
    tokens — most of the turn — and the gap grows with how hard it thought.
    """
    usage = TokenUsage()
    usage.add_response_usage("gemini-3.8-flash", _OpenAIShapedUsage())

    assert usage.input_tokens == 146
    assert usage.output_tokens == 936 - 146
    assert usage.cost_usd() > 0


def test_resolve_effort_defaults_differ_by_role() -> None:
    # Low in-call for latency; high off-call for correctness. Getting these
    # the wrong way round is the single most expensive misconfiguration here.
    assert resolve_effort(None, CONVERSATION) == "low"
    assert resolve_effort(None, EXTRACTION) == "high"
    assert resolve_effort("nonsense", CONVERSATION) == "low"
    assert resolve_effort("medium", CONVERSATION) == "medium"


def test_cost_is_summed_per_model_at_that_model_s_rate() -> None:
    """One call bills two models. Rates must not be cross-applied."""
    usage = TokenUsage()
    usage.add("claude-sonnet-5", input_tokens=1_000_000)
    usage.add("claude-opus-5", output_tokens=1_000_000)

    sonnet = MODELS_BY_ID["claude-sonnet-5"]
    opus = MODELS_BY_ID["claude-opus-5"]
    expected = sonnet.input_per_mtok + opus.output_per_mtok

    assert abs(usage.cost_usd() - expected) < 1e-6


def test_cached_input_is_an_order_of_magnitude_cheaper() -> None:
    """The prompt layout only pays off if cache reads are billed as reads.

    If this ever regresses to the full input rate, the two cache breakpoints in
    prompts.py stop being worth their complexity — and nothing else in the
    system would notice.
    """
    fresh = TokenUsage()
    fresh.add("claude-sonnet-5", input_tokens=1_000_000)

    cached = TokenUsage()
    cached.add("claude-sonnet-5", cache_read_tokens=1_000_000)

    assert cached.cost_usd() * 9 < fresh.cost_usd()


def test_unknown_model_contributes_nothing_rather_than_crashing() -> None:
    """Accounting runs on the call path. It must never raise there."""
    usage = TokenUsage()
    usage.add("some-retired-model", input_tokens=500_000, output_tokens=500_000)
    assert usage.cost_usd() == 0.0
    # The tokens are still counted — only the price is unknown.
    assert usage.input_tokens == 500_000


def test_cache_hit_rate_is_reads_over_all_prompt_input() -> None:
    usage = TokenUsage()
    usage.add("claude-sonnet-5", input_tokens=250, cache_read_tokens=750)
    assert usage.cache_hit_rate == 0.75

    assert TokenUsage().cache_hit_rate == 0.0  # no division by zero on an empty ledger


def test_merge_accumulates_across_ledgers() -> None:
    a = TokenUsage()
    a.add("claude-sonnet-5", input_tokens=100, output_tokens=10)
    b = TokenUsage()
    b.add("claude-sonnet-5", input_tokens=50, output_tokens=5)
    b.add("claude-opus-5", output_tokens=200)

    a.merge(b)
    assert a.by_model["claude-sonnet-5"]["input"] == 150
    assert a.by_model["claude-opus-5"]["output"] == 200


def test_cheaper_model_estimates_cheaper() -> None:
    """The estimator's whole job is ranking options. Ordering must hold."""
    common = {
        "extraction_model": "claude-opus-5",
        "extraction_effort": "high",
        "conversation_effort": "low",
        "exchanges": 8,
    }
    haiku = estimate_call(conversation_model="claude-haiku-4-5", **common)
    sonnet = estimate_call(conversation_model="claude-sonnet-5", **common)
    opus = estimate_call(conversation_model="claude-opus-5", **common)

    assert (
        haiku["conversation_cost_usd"]
        < sonnet["conversation_cost_usd"]
        < opus["conversation_cost_usd"]
    )


def test_higher_effort_costs_more() -> None:
    low = estimate_call(
        conversation_model="claude-sonnet-5",
        conversation_effort="low",
        extraction_model="claude-opus-5",
        extraction_effort="low",
    )
    high = estimate_call(
        conversation_model="claude-sonnet-5",
        conversation_effort="high",
        extraction_model="claude-opus-5",
        extraction_effort="high",
    )
    assert high["cost_per_call_usd"] > low["cost_per_call_usd"]


def test_campaign_estimate_bills_connected_calls_only() -> None:
    """Unconnected dials cost nothing: extraction short-circuits on an empty
    transcript, so counting them would inflate every projection."""
    kwargs = {
        "conversation_model": "claude-sonnet-5",
        "conversation_effort": "low",
        "extraction_model": "claude-opus-5",
        "extraction_effort": "high",
        "exchanges": 8,
    }
    half = estimate_campaign(contacts=1000, connect_rate=0.5, **kwargs)
    full = estimate_campaign(contacts=1000, connect_rate=1.0, **kwargs)

    assert half["connected_calls"] == 500
    assert abs(full["total_cost_usd"] - half["total_cost_usd"] * 2) < 0.01


def test_cache_hit_assumption_lowers_the_projection() -> None:
    kwargs = {
        "conversation_model": "claude-sonnet-5",
        "conversation_effort": "low",
        "extraction_model": "claude-opus-5",
        "extraction_effort": "high",
        "exchanges": 8,
    }
    assert (
        estimate_call(cache_hit=True, **kwargs)["conversation_cost_usd"]
        < estimate_call(cache_hit=False, **kwargs)["conversation_cost_usd"]
    )


if __name__ == "__main__":
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith("test_") and callable(fn):
            try:
                fn()
                print(f"  ok   {name}")
            except AssertionError as exc:
                failures += 1
                print(f"  FAIL {name}: {exc}")
    print("\nAll passed." if not failures else f"\n{failures} failed.")
    sys.exit(1 if failures else 0)
