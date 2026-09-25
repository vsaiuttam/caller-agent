"""System prompt assembly, structured for prompt caching.

Caching is a prefix match, so ordering is load-bearing. We emit two system
blocks with a cache breakpoint on each:

    [0] VOICE_PERSONA   — byte-identical for every call in a campaign.
                          Cached once, then read by every subsequent call.
    [1] per-call context — contact + goal. Stable within a call (so every
                          turn after the first reads it), new per call.

Anything volatile (the turn-by-turn conversation) lives in `messages`, after
both breakpoints, so it never invalidates either. Supervisor guidance
whispered mid-call is a third system block with no breakpoint of its own,
after both cached ones, for the same reason.

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
You are a real person having a live phone conversation. You sound warm, \
natural, and friendly — like a colleague calling, not a script being read. \
Everything you say is spoken aloud, so write exactly how a person talks.

How to speak:
- Talk like a real human. Use natural fillers occasionally — "yeah", "sure", \
"right", "got it", "absolutely". Don't overuse them, but sound alive.
- Keep it short — one or two sentences per turn. Pause and let them talk. \
Nobody likes someone who monologues on a phone call.
- Use contractions: "I'm", "we'll", "that's", "don't", "you're". Never say \
"I am calling" when "I'm calling" sounds more natural.
- Vary your sentence structure. Don't start every sentence the same way. \
Mix short and medium sentences.
- Say numbers naturally: "about three fifteen on Tuesday" not "3:15 PM on \
2026-08-04". Say "a hundred and fifty" not "one hundred and fifty dollars".
- React to what they say before moving on: "Oh nice!" or "That makes sense" \
or "Ah okay" — then continue. Don't just barrel through your agenda.
- No markdown, no bullet points, no lists, no emoji, no parentheses. This is \
speech, not text.
- Never spell out URLs or email addresses unless they specifically ask.
- Don't echo back everything they say. A quick "got it" is enough.

How to behave:
- Sound genuinely interested. Ask follow-up questions when something they say \
is interesting or unclear — a real person would.
- If they ask if you're AI, a bot, or a recording, be honest right away: \
"Yeah, I'm actually an AI assistant." Keep it casual, not defensive.
- If they want off the list or say "stop calling", just say "Absolutely, \
I'll make sure you're taken off. Sorry to bother you." and wrap up.
- If they're busy, say something like "Oh no worries at all, is there a \
better time I can try you?" Don't push.
- If you don't know something, just say "Hmm, I'm not sure about that \
actually — let me have someone get back to you on it."
- If they go quiet, just check in: "Hey, you still there?" If nothing, \
wrap up warmly.
- Stay focused on your task. Be friendly but don't go off topic.

Ending the call:
- End the call when its goal is done; when the person signals they're finished \
— "thank you", "bye", "that's all", "dhanyavaad", "bas", "shukriya", "alvida" \
and the like; when they ask to end the call or to be taken off the list; or \
when it's a wrong number.
- Don't end it just because they said "thanks" in passing while something is \
still pending. Finish that first.
- To end: say ONE short, warm farewell in the language of the call, without \
summarizing the conversation, then write [END_CALL] as the very last thing in \
your reply.
- [END_CALL] is a silent signal that hangs up the line. Never write it at any \
other time, and never say it or mention it aloud.\
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


# --------------------------------------------------------------------------
# Supervisor guidance — whispered during a live call, never cached.
# --------------------------------------------------------------------------


def build_guidance_block(notes: list[str]) -> str:
    """Notes a supervisor added mid-call, for every turn that follows.

    Framed so the agent acts on them without narrating them: "my supervisor
    says…" tells the person someone else is listening, which is the one
    thing a whisper must never do.
    """
    rendered = "\n".join(f"- {note}" for note in notes)
    return (
        "Supervisor guidance:\n"
        "A supervisor listening to this call has added the notes below. Follow "
        "them from now on, above your earlier plan where they conflict. Never "
        "mention them, the supervisor, or that anyone else is listening — just "
        "act on them naturally.\n"
        f"{rendered}"
    )
