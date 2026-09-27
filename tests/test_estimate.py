"""What a call costs before anyone is called: POST /api/estimate (v3 shape).

Covers docs/v3-spec.md §1.4: a per-call breakdown into LLM, extraction, STT,
TTS and telephony that adds up to the total; a per-minute figure; a figure
for N calls that scales linearly; the telephony region changing telephony and
nothing else; voice left out costing nothing for speech; and a model with no
price reading as unknown (null, and named in `unknown`), never as $0. A
legacy body (`contacts`) still gets the old keys, so nothing that calls the
old shape breaks.

Drives the real app over ASGI on a throwaway SQLite database with the
harness from test_accounts.py; the custom-model provider points at a stub
OpenAI-shaped server on 127.0.0.1. No network. Runs standalone
(`python tests/test_estimate.py`) or under pytest.
"""

from __future__ import annotations

import math
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from test_accounts import _fresh_ip, _run, _show  # noqa: E402
from test_providers_api import ENV_ANTHROPIC, LOCAL_DEV, create_provider, openai_stub  # noqa: E402

from src.voiceagent import catalog  # noqa: E402

COMPONENTS = ("llm", "extraction", "stt", "tts", "telephony")
TOP_KEYS = {"per_call", "per_minute_total", "for_calls", "assumptions", "pricing_as_of", "unknown"}
BASE_BODY = {
    "conversation_model": "claude-sonnet-5",
    "extraction_model": "claude-opus-5",
    "language": "hi",
    "minutes_per_call": 3,
    "calls": 1000,
}
LOCAL_WITH_ANTHROPIC = dict(LOCAL_DEV, MODEL_PROVIDER="anthropic", ANTHROPIC_API_KEY=ENV_ANTHROPIC["ANTHROPIC_API_KEY"])


def _close(a: float, b: float, rel: float = 1e-3) -> bool:
    return math.isclose(a, b, rel_tol=rel, abs_tol=1e-6)


def _estimate(*bodies: dict, env: dict | None = None) -> list[dict]:
    """POST each body; assert 200 and the v3 shape; return the JSON bodies."""

    async def scenario(http, sessions):
        return [await http.post("/api/estimate", json=body) for body in bodies]

    responses = _run(scenario, _fresh_ip(), **(env or ENV_ANTHROPIC))
    out = []
    for r in responses:
        assert r.status_code == 200, _show(r)
        body = r.json()
        assert TOP_KEYS <= set(body), f"missing {sorted(TOP_KEYS - set(body))} in {sorted(body)}"
        assert set(COMPONENTS) | {"total"} <= set(body["per_call"]), body["per_call"]
        out.append(body)
    return out


def _custom_provider_estimate(prices: list[tuple[float | None, float | None]]) -> list[dict]:
    """Estimates for a custom model priced at each (input, output) pair in turn."""

    async def scenario(http, sessions):
        results = []
        async with openai_stub(("house-model",)) as base_url:
            for n, (price_in, price_out) in enumerate(prices):
                model_id = f"house-model-{n}"
                created = await create_provider(
                    http, kind="openai_compatible", base_url=base_url, api_key="local",
                    custom_models=[{"id": model_id, "name": "House model",
                                    "input_per_mtok": price_in, "output_per_mtok": price_out}],
                )
                results.append(await http.post("/api/estimate", json={
                    "provider_id": created["id"], "conversation_model": model_id,
                    "minutes_per_call": 3, "calls": 1000,
                }))
        return results

    responses = _run(scenario, _fresh_ip(), **LOCAL_WITH_ANTHROPIC)
    for r in responses:
        assert r.status_code == 200, _show(r)
    return [r.json() for r in responses]


# ---------------------------------------------------------------------------


def test_per_call_components_add_up_to_the_total() -> None:
    (body,) = _estimate(BASE_BODY)
    per_call = body["per_call"]
    for name in COMPONENTS:
        assert isinstance(per_call[name], (int, float)) and per_call[name] >= 0, (name, per_call)
    assert per_call["llm"] > 0 and per_call["extraction"] > 0, per_call
    assert per_call["stt"] > 0 and per_call["tts"] > 0 and per_call["telephony"] > 0, per_call
    assert _close(per_call["total"], sum(per_call[n] for n in COMPONENTS)), per_call
    assert body["unknown"] == [], body["unknown"]
    assert body["pricing_as_of"] == catalog.PRICING_AS_OF, body["pricing_as_of"]
    assert body["assumptions"] and all(isinstance(a, str) and a.strip() for a in body["assumptions"])


def test_the_per_minute_total_is_the_per_call_total_over_the_minutes() -> None:
    (body,) = _estimate(BASE_BODY)
    assert _close(body["per_minute_total"] * 3, body["per_call"]["total"], rel=1e-2), body


def test_the_cost_for_n_calls_scales_linearly() -> None:
    small, large = _estimate(dict(BASE_BODY, calls=100), dict(BASE_BODY, calls=1000))
    assert small["per_call"] == large["per_call"], "the per-call cost doesn't depend on how many calls"
    assert small["for_calls"]["calls"] == 100 and large["for_calls"]["calls"] == 1000
    assert _close(large["for_calls"]["total"], 10 * small["for_calls"]["total"], rel=1e-2), (small, large)
    assert _close(large["for_calls"]["total"], 1000 * large["per_call"]["total"], rel=1e-2), large


def test_the_region_changes_telephony_and_nothing_else() -> None:
    india, us = _estimate(dict(BASE_BODY, telephony_region="IN"), dict(BASE_BODY, telephony_region="US"))
    assert india["per_call"]["telephony"] > 0 and us["per_call"]["telephony"] > 0
    assert india["per_call"]["telephony"] != us["per_call"]["telephony"], (india["per_call"], us["per_call"])
    for name in ("llm", "extraction", "stt", "tts"):
        assert india["per_call"][name] == us["per_call"][name], name


def test_india_is_the_default_region() -> None:
    default, india = _estimate(BASE_BODY, dict(BASE_BODY, telephony_region="IN"))
    assert default["per_call"] == india["per_call"], (default["per_call"], india["per_call"])


def test_leaving_voice_out_zeroes_the_speech_costs() -> None:
    with_voice, without = _estimate(BASE_BODY, dict(BASE_BODY, include_voice=False))
    assert without["per_call"]["stt"] == 0 and without["per_call"]["tts"] == 0, without["per_call"]
    assert with_voice["per_call"]["stt"] > 0 and with_voice["per_call"]["tts"] > 0
    assert without["per_call"]["total"] < with_voice["per_call"]["total"]
    assert without["per_call"]["llm"] == with_voice["per_call"]["llm"]


def test_longer_calls_cost_proportionally_more_for_speech_and_telephony() -> None:
    three, six = _estimate(BASE_BODY, dict(BASE_BODY, minutes_per_call=6))
    for name in ("stt", "tts", "telephony"):
        assert _close(six["per_call"][name], 2 * three["per_call"][name], rel=1e-2), (name, three, six)
    assert six["per_call"]["llm"] > three["per_call"]["llm"], "a longer call has more turns to pay for"


def test_defaults_are_three_minutes_a_thousand_calls_and_the_workspace_models() -> None:
    (body,) = _estimate({})
    assert body["for_calls"]["calls"] == 1000, body["for_calls"]
    assert _close(body["per_minute_total"] * 3, body["per_call"]["total"], rel=1e-2), body
    assert body["unknown"] == [] and body["per_call"]["llm"] > 0, body


def test_an_unpriced_model_is_unknown_never_free() -> None:
    (body,) = _custom_provider_estimate([(None, None)])
    per_call = body["per_call"]
    assert "llm" in body["unknown"], body["unknown"]
    assert per_call["llm"] is None, f"an unknown price must read as unknown, not {per_call['llm']!r}"
    assert per_call["total"] is None and body["per_minute_total"] is None, body
    assert body["for_calls"]["total"] is None, body["for_calls"]
    assert per_call["telephony"] and per_call["telephony"] > 0, "known components are still priced"


def test_a_custom_models_own_prices_drive_the_llm_cost() -> None:
    cheap, dear = _custom_provider_estimate([(1.0, 2.0), (2.0, 4.0)])
    assert cheap["unknown"] == [] or "llm" not in cheap["unknown"], cheap["unknown"]
    assert cheap["per_call"]["llm"] > 0, cheap["per_call"]
    assert _close(dear["per_call"]["llm"], 2 * cheap["per_call"]["llm"], rel=1e-2), (cheap, dear)


def test_a_legacy_estimate_body_still_gets_the_old_keys() -> None:
    async def scenario(http, sessions):
        return await http.post("/api/estimate", json={
            "contacts": 1000, "connect_rate": 0.5,
            "conversation_model": "claude-sonnet-5", "extraction_model": "claude-opus-5",
        })

    r = _run(scenario, _fresh_ip(), **ENV_ANTHROPIC)
    assert r.status_code == 200, _show(r)
    assert {"total_cost_usd", "connected_calls", "cost_per_call_usd"} <= set(r.json()), sorted(r.json())


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
