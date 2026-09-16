"""System prompt assembly, structured for prompt caching.

Caching is a prefix match, so ordering is load-bearing. We emit two system
blocks with a cache breakpoint on each:

    [0] VOICE_PERSONA   — byte-identical for every call in a campaign.
                          Cached once, then read by every subsequent call.
    [1] per-call context — contact + goal. Stable within a call (so every
                          turn after the first reads it), new per call.

Anything volatile (the turn-by-turn conversation) lives in `messages`, after
both breakpoints, so it never invalidates either.

The persona must contain no timestamps, no contact data, and no campaign
data — a single varying byte at position 0 costs us the shared cache across
every call in flight.
"""

from __future__ import annotations

from .models import CallContext, Contact

# --------------------------------------------------------------------------
# Block 0 — frozen across all calls. Do not interpolate anything into this.
# --------------------------------------------------------------------------

VOICE_PERSONA = """\
You are having a live phone conversation. Everything you produce is converted \
to speech and heard, not read.

How to speak:
- Keep turns to one or two sentences. This is a conversation, not a briefing. \
If you need to convey several things, say one and let them respond.
- Write plain spoken prose. No markdown, no bullet points, no numbered lists, \
no headings, no emoji, no parenthetical asides — all of it gets read aloud \
literally and sounds wrong.
- Write numbers, dates, and times the way a person says them: "three fifteen \
on Tuesday the fourth", not "3:15 PM on 2026-08-04".
- Never spell out a URL or an email address unless they ask for it.
- Don't restate what they just told you back to them as confirmation on every \
turn. Confirm once, at the point it matters.

How to behave:
- If you are asked whether you are a person, an AI, a bot, or a recording, say \
plainly and immediately that you are an AI assistant. Never imply otherwise, \
and never deflect the question.
- If they ask to be removed from the list, ask not to be called again, or say \
any equivalent of "stop calling me", acknowledge it in one sentence, do not \
argue or attempt to continue the task, and end the call.
- If they sound busy or say it is a bad time, offer to call back and end. Do \
not push.
- If they ask something you do not know, say you don't know and offer to have \
someone follow up. Never invent a fact, a price, a policy, or an availability.
- If the line is silent or the response is garbled, ask once whether they are \
still there. If there's no answer after that, close politely and end.
- Stay on the task you were given. Do not agree to anything outside it, and \
do not make commitments on the caller's behalf.

Ending the call:
- When the task is done, or when it's clear it will not be, close warmly in \
one sentence and stop. Do not keep the person on the line to summarize.\
"""


# --------------------------------------------------------------------------
# Block 1 — per call. Stable for the duration of one call.
# --------------------------------------------------------------------------


def _render_attributes(attributes: dict[str, str]) -> str:
    if not attributes:
        return "  (none on file)"
    # Sorted so the rendered bytes are deterministic — an unsorted dict would
    # produce a different prefix on every process and never cache.
    return "\n".join(f"  {k}: {v}" for k, v in sorted(attributes.items()))


def _render_list(items: list[str], empty: str) -> str:
    if not items:
        return f"  {empty}"
    return "\n".join(f"  - {item}" for item in items)


def _render_scorecard(context: CallContext) -> str:
    """What the call is judged on, phrased for the agent rather than the scorer.

    The agent is told what matters and asked to find out about it in
    conversation — deliberately *not* told the weights or that anything is a
    knockout. Someone who knows which answer disqualifies them can hear it in
    how the question is asked, and a caller who senses a trapdoor stops
    answering straight. The scoring happens afterwards, on what they actually
    said.
    """
    if not context.scorecard:
        return ""

    lines = []
    for criterion in context.scorecard:
        detail = f" — {criterion.description.strip()}" if criterion.description.strip() else ""
        lines.append(f"  - {criterion.name}{detail}")

    return (
        "\n\nWhat this call is assessing:\n"
        + "\n".join(lines)
        + "\nFind out enough about each of these to be judged fairly on it. Ask "
        "conversationally and follow up when an answer is vague — 'soon' and "
        "'competitive' are not answers. Never say that they are being scored, "
        "and never tell them what a good answer would be."
    )


def build_call_context_block(contact: Contact, context: CallContext) -> str:
    extra = ""
    if context.extra_instructions.strip():
        extra = f"\n\nAdditional guidance for this campaign:\n{context.extra_instructions.strip()}"

    scorecard = _render_scorecard(context)

    return f"""\
Language:
  {context.language_instruction}

Who you are calling:
  Name: {contact.full_name}
  Local timezone: {contact.timezone}
On file about them:
{_render_attributes(contact.attributes)}

What this call is for:
  {context.goal}

What you need to come away with:
{_render_list(context.fields_to_collect, "Nothing specific — this is informational.")}

Boundaries for this call:
{_render_list(context.constraints, "None beyond your general rules.")}

Ask for the items above conversationally, as they fit the flow. Do not read \
them out as a checklist or work through them in order — if the conversation \
covers one naturally, take it and move on.{scorecard}{extra}\
"""


def build_system_blocks(contact: Contact, context: CallContext) -> list[dict]:
    """Return the `system` array with cache breakpoints on both blocks.

    Two breakpoints rather than one: the first gives every call in the
    campaign a shared read of the persona; the second gives every turn after
    the first a read of this call's context.

    Anthropic-shaped. Providers on the `chat/completions` path take
    `build_system_text` instead.
    """
    return [
        {
            "type": "text",
            "text": VOICE_PERSONA,
            "cache_control": {"type": "ephemeral"},
        },
        {
            "type": "text",
            "text": build_call_context_block(contact, context),
            "cache_control": {"type": "ephemeral"},
        },
    ]


def build_system_text(contact: Contact, context: CallContext) -> str:
    """The same prompt as one string, for providers without explicit breakpoints.

    The ordering above is still load-bearing here even though nothing marks
    it: Gemini and OpenAI both cache on a matching prefix automatically, so
    the frozen persona leading and the per-call context trailing is what
    earns the discount. Only the ability to *place* the breakpoint is lost,
    not the reason for the layout.
    """
    return f"{VOICE_PERSONA}\n\n{build_call_context_block(contact, context)}"
