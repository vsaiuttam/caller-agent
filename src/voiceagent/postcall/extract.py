"""Post-call extraction: transcript in, CallOutcome out.

This runs off the call, so latency doesn't matter and correctness does. Its
output writes into a calendar and an internal system, and a wrong appointment
time is a real-world failure with a real-world cost — so this path uses Opus 5
at high effort rather than the cheap conversational model. At a few cents per
call the delta is not worth optimizing against a single bad booking.

Extracting from the full transcript at the end is also more reliable than
tracking state turn-by-turn during the call: the model sees corrections,
reversals, and "actually, make it Thursday" in context, instead of committing
to the first thing it heard.
"""

from __future__ import annotations

import logging

from ..catalog import (
    DEFAULT_EXTRACTION_EFFORT,
    DEFAULT_EXTRACTION_MODEL,
    EXTRACTION,
    TokenUsage,
    resolve,
    resolve_effort,
)
from ..models import CallContext, CallOutcome, Contact, Disposition, Turn
from ..providers import ANTHROPIC_API, active

logger = logging.getLogger(__name__)

# Fallbacks. The model is a per-campaign setting — see catalog.py for why the
# extraction role gets a different default from the conversation role.
MODEL = DEFAULT_EXTRACTION_MODEL
EFFORT = DEFAULT_EXTRACTION_EFFORT

EXTRACTION_SYSTEM = """\
You are extracting a structured record from a completed phone call transcript.

Report only what the transcript supports. If something was discussed but never \
settled, it was not settled — do not resolve ambiguity in favour of a tidier \
record. An incomplete record that is flagged for review is far more useful than \
a complete one that is wrong, because this output is written directly into a \
calendar and a customer system without a human reading it first.

Specific rules:
- Set `appointment` only when a specific date and time were actually agreed. \
"Sometime next week" or "I'll check and get back to you" is not an appointment.
- Resolve relative times ("next Tuesday", "tomorrow afternoon") against the \
call's date and the person's timezone, both given below. If you cannot resolve \
one confidently, leave `appointment` null and flag for review.
- Mark `verbatim` false on any collected field you inferred rather than heard \
stated.
- Set `needs_human_review` true if: the person disputed something, a \
commitment was made that falls outside the stated goal, you resolved a time \
you are not confident about, or the transcript is too garbled to trust.
- If the person asked not to be contacted again, the disposition is \
do_not_call, regardless of whatever else was accomplished on the call.
- Set `sentiment` to the person's overall attitude on the call — positive, \
neutral or negative — judged from what they said and how, not from whether \
the goal was met: a friendly "no thanks" is neutral or positive, a booking \
made through gritted teeth is negative. Put a short phrase from the call that \
shows it in `sentiment_reason`.\
"""

SCORING_RULES = """\

Scoring:
You are also given a list of criteria this call is assessed against. Return one \
entry in `scores` for every criterion, using its name exactly as written.

- `rating`: 0 if the criterion never came up on the call, 1 if they clearly \
fall short, 2 if they partially meet it, 3 if they meet it, 4 if they clearly \
exceed it.
- `met`: true only when the transcript actually shows they meet it. A criterion \
that never came up is not met — rate it 0 and set met to false. This is not a \
judgement about the person; it means the call did not establish it.
- `evidence`: a short quote or close paraphrase from the transcript. Leave it \
empty when the criterion never came up. Do not write evidence you cannot point \
at in the transcript.

Rate only what was said. Do not infer that a candidate probably has a skill \
because of an adjacent one, and do not give credit for an answer they were \
never asked for.

If a criterion refers to a standard you were not given — a required number of \
years, a budget band, a specific location — you cannot judge it. Rate it 0, set \
`met` to false, and leave `evidence` empty. Do not assume the standard was met \
because nothing contradicted it. "The transcript does not establish this" is a \
correct and useful answer; a confident pass on a threshold nobody told you is \
not.\
"""


def _render_scorecard(context: CallContext) -> str:
    if not context.scorecard:
        return ""
    lines = [
        f"- {c.name}" + (f": {c.description.strip()}" if c.description.strip() else "")
        for c in context.scorecard
    ]
    # Weights and knockout flags are deliberately withheld. The extractor rates
    # each criterion on its own evidence; what any of them is worth is decided
    # afterwards in scoring.py, so a heavily-weighted criterion can't pull the
    # model's rating of it upward.
    return "\n\nCriteria to score against:\n" + "\n".join(lines)


def _render_transcript(turns: list[Turn]) -> str:
    speaker = {"assistant": "Agent", "user": "Person"}
    return "\n".join(f"{speaker.get(t.role, t.role)}: {t.text}" for t in turns)


async def extract_outcome(
    client,
    contact: Contact,
    context: CallContext,
    turns: list[Turn],
    call_started_at_iso: str,
    *,
    model: str | None = None,
    effort: str | None = None,
    usage: TokenUsage | None = None,
) -> CallOutcome:
    """Extract a structured outcome. Never raises on model-side failure.

    On refusal, malformed output, or an API error this returns a FAILED
    outcome flagged for review rather than propagating — one bad extraction
    must not take down the batch, and a human needs to see it either way.

    `usage` is the call's shared ledger; token counts are folded into it so
    the per-call cost covers both the conversation and this.
    """
    model_id = resolve(model, EXTRACTION)
    effort_level = resolve_effort(effort, EXTRACTION)

    if not turns:
        # Short-circuits before any model call: a no-answer costs nothing to
        # "extract", and billing it would quietly inflate every campaign's
        # cost-per-contact by the share of dials that never connect.
        return CallOutcome(
            disposition=Disposition.NO_ANSWER,
            summary="No conversation took place.",
            needs_human_review=False,
        )

    user_content = f"""\
Call placed at: {call_started_at_iso}
Person's timezone: {contact.timezone}
Goal of the call: {context.goal}
Information the call was meant to collect: {", ".join(context.fields_to_collect) or "none specified"}\
{_render_scorecard(context)}

Transcript:
{_render_transcript(turns)}\
"""

    system = EXTRACTION_SYSTEM + (SCORING_RULES if context.scorecard else "")

    spec = active()
    anthropic_path = spec is None or spec.api == ANTHROPIC_API

    try:
        if anthropic_path:
            outcome = await _extract_anthropic(
                client, model_id, effort_level, system, user_content, usage
            )
        else:
            outcome = await _extract_openai(
                client, model_id, effort_level, system, user_content, usage
            )
    except _Refused as refusal:
        logger.warning("Extraction refused for contact %s", contact.contact_id)
        return _needs_review(str(refusal))
    except Exception:
        logger.exception("Extraction failed for contact %s", contact.contact_id)
        return _needs_review("Extraction call failed; transcript preserved for manual review.")

    if outcome is None:
        logger.warning("Extraction produced no parsed output for %s", contact.contact_id)
        return _needs_review("Extraction returned malformed output.")

    return outcome


class _Refused(Exception):
    """The model declined rather than failed. A different thing to report."""


async def _extract_anthropic(
    client, model_id: str, effort: str, system: str, user_content: str, usage: TokenUsage | None
) -> CallOutcome | None:
    response = await client.messages.parse(
        model=model_id,
        max_tokens=2048,
        output_config={"effort": effort},
        system=system,
        messages=[{"role": "user", "content": user_content}],
        output_format=CallOutcome,
    )

    if usage is not None:
        usage.add_response_usage(model_id, getattr(response, "usage", None))

    # Opus 5 runs safety classifiers and can decline with a 200 + refusal.
    # Unlikely on a call transcript, but check before reading content.
    if response.stop_reason == "refusal":
        raise _Refused("Extraction was declined by content classifiers.")

    return response.parsed_output


async def _extract_openai(
    client, model_id: str, effort: str, system: str, user_content: str, usage: TokenUsage | None
) -> CallOutcome | None:
    """Structured extraction on the `chat/completions` shape.

    `parse()` hands the Pydantic model straight to the provider as a JSON
    schema, which matters here because `CallOutcome` nests an optional
    `Appointment` — the exact shape a strict schema layer tends to reject.
    Verified against Gemini: the nested optional round-trips, and relative
    times ("Thursday morning") resolve correctly against the call date.
    """
    response = await client.chat.completions.parse(
        model=model_id,
        max_tokens=4096,
        reasoning_effort=effort,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_content},
        ],
        response_format=CallOutcome,
    )

    if usage is not None:
        usage.add_response_usage(model_id, getattr(response, "usage", None))

    message = response.choices[0].message
    if getattr(message, "refusal", None):
        raise _Refused("Extraction was declined by content classifiers.")

    return message.parsed


def _needs_review(reason: str) -> CallOutcome:
    return CallOutcome(
        disposition=Disposition.FAILED,
        summary=reason,
        needs_human_review=True,
        review_reason=reason,
    )
