"""Dry-run a call before dialling anybody.

The gap this fills: everywhere else in this product, the only way to find out
whether a prompt works is to call a real person with it. That is an expensive
and irreversible way to discover that your opening line sounds like a scam, or
that the agent folds the moment somebody says "I'm in a meeting".

So: Claude plays the person, the *real* `ConversationLLM` plays the agent, and
the *real* extractor reads the transcript afterwards. Only the phone line is
fake. Everything that could be wrong about a campaign — the greeting, the
goal, the constraints, the language, the model choice, the effort level — is
exercised exactly as it would be on a live call.

Two things this measures that you cannot get from a live call:

  - **Time to first chunk**, per turn. This is what the person on the line
    actually experiences as "is it broken?". Recorded here without audio in
    the way, so it isolates model latency from telephony.
  - **Behaviour against a difficult person.** You can run the same script past
    a cooperative persona and a hostile one back to back. Nobody gets called
    twice, and the comparison is free.

Simulated calls are written to the same `calls` table with `is_simulation`
set, so they are inspectable in the UI alongside real ones — and excluded from
every aggregate, because a rehearsal is not a result.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import TYPE_CHECKING, Any

from .catalog import CONVERSATION, EXTRACTION, TokenUsage, resolve, resolve_effort
from .llm import ConversationLLM, ToolPause
from .models import CallContext, CallOutcome, Contact, Qualification, Turn
from .postcall.extract import extract_outcome
from .providers import ANTHROPIC_API, active
from .scoring import qualify_outcome
from .voice.session import _is_closing

if TYPE_CHECKING:
    from .mcp.toolbox import Toolbox

logger = logging.getLogger(__name__)

# The persona runs on the cheapest capable model each provider offers. It is
# scaffolding, not the thing under test, and paying Opus rates to role-play a
# reluctant customer would make the feature too expensive to use casually —
# which would defeat the point of having it.
PERSONA_MODELS = {
    "anthropic": "claude-haiku-4-5",
    # Lite, and not the model under test: the persona is scaffolding, and
    # sharing a quota pool with the agent would have a long rehearsal rate-limit
    # itself halfway through.
    "gemini": "gemini-3.5-flash-lite",
}
PERSONA_MODEL = PERSONA_MODELS["anthropic"]
PERSONA_MAX_TOKENS = 200


def persona_model() -> str:
    return PERSONA_MODELS.get((active().id if active() else ""), PERSONA_MODEL)

# A simulated call cannot hang up on itself, and a model happily talking to a
# model will keep going indefinitely. This is the stop.
DEFAULT_MAX_EXCHANGES = 10


@dataclass(frozen=True)
class Persona:
    id: str
    name: str
    description: str
    behaviour: str

    def to_dict(self) -> dict:
        return {"id": self.id, "name": self.name, "description": self.description}


PERSONAS: list[Persona] = [
    Persona(
        id="cooperative",
        name="Cooperative",
        description="Has time, answers straight, agrees to reasonable next steps.",
        behaviour=(
            "You are willing to talk and you answer questions directly. You are "
            "not suspiciously eager — you still ask what this is about early on "
            "— but once satisfied you cooperate and give real answers."
        ),
    ),
    Persona(
        id="busy",
        name="Busy",
        description="Answers mid-something. Short, clipped, wants it wrapped up.",
        behaviour=(
            "You picked up while doing something else. Your replies are short "
            "and slightly impatient. You interrupt with 'sorry, what is this "
            "about?' early. You will engage if the caller gets to the point "
            "within a sentence or two; if they waffle, you say you have to go."
        ),
    ),
    Persona(
        id="skeptical",
        name="Skeptical",
        description="Assumes it's a scam. Pushes back, asks how you got the number.",
        behaviour=(
            "You assume unsolicited calls are scams. You ask how they got your "
            "number and whether this is a recording. You do not volunteer "
            "personal information and you object to anything that sounds like a "
            "sales pitch. You can be won over by a straight, specific answer, "
            "but you never hand over sensitive details on an inbound cold call."
        ),
    ),
    Persona(
        id="confused",
        name="Confused",
        description="Doesn't recall the context. Mishears, needs things repeated.",
        behaviour=(
            "You do not remember the thing the caller is referring to. You "
            "mishear one detail and repeat it back wrong. You ask them to say "
            "things again. You are not hostile, just genuinely unclear, and you "
            "correct yourself partway through — including changing your mind "
            "about a time you already agreed to."
        ),
    ),
    Persona(
        id="opt_out",
        name="Opts out",
        description="Asks to be removed from the list. Tests the suppression path.",
        behaviour=(
            "You are annoyed to be called. Within the first two exchanges you "
            "clearly say you do not want to be contacted again and ask to be "
            "removed from their list. You do not soften it. If the agent keeps "
            "pitching after that, you get firmer and end the call."
        ),
    ),
    Persona(
        id="wrong_person",
        name="Wrong number",
        description="Not the person on the list. Tests misidentification handling.",
        behaviour=(
            "You are not the person the caller asked for and you have never "
            "heard of them. This number was reassigned. You say so plainly and "
            "you are mildly irritated at being asked to confirm details that "
            "are not yours."
        ),
    ),
]

PERSONAS_BY_ID = {p.id: p for p in PERSONAS}


PERSONA_SYSTEM = """\
You are role-playing a member of the public who has just answered an unexpected \
phone call. You are NOT an assistant. Never break character, never mention that \
you are an AI, and never help the caller do their job.

Who you are:
{who}

How you behave on this call:
{behaviour}

Rules for your replies:
- Reply with spoken words only. No stage directions, no narration, no quotation \
marks, no name prefix.
- One or two sentences. This is a phone call, not an essay. Real people on the \
phone are briefer than they are in writing.
- Use natural spoken register in {language}: contractions, false starts, \
"um" and "hang on" where a real person would.
- Do not invent an elaborate backstory. Stay consistent with the facts above and \
be vague about anything else, as a real person would be.
- When you would genuinely put the phone down, reply with exactly [HANGUP] and \
nothing else.\
"""


@dataclass
class SimulatedTurn:
    role: str
    text: str
    # Milliseconds from "the agent started generating" to "the first speakable
    # chunk was ready". Null on the person's turns and on the scripted greeting.
    first_chunk_ms: int | None = None
    total_ms: int | None = None


@dataclass
class SimulationResult:
    transcript: list[Turn]
    turns: list[SimulatedTurn]
    outcome: CallOutcome
    usage: TokenUsage = field(default_factory=TokenUsage)
    conversation_model: str = ""
    extraction_model: str = ""
    persona: str = ""
    ended_because: str = ""
    # Derived from the outcome's per-criterion ratings, not asked of the model.
    # None when the campaign scores nothing.
    qualification: Qualification | None = None
    # The campaign's tools the agent used, as `Call.tool_calls` stores them.
    tool_calls: list[dict[str, Any]] = field(default_factory=list)

    @property
    def median_first_chunk_ms(self) -> int | None:
        """Median, not mean — one slow cold start should not define the number."""
        values = sorted(t.first_chunk_ms for t in self.turns if t.first_chunk_ms is not None)
        if not values:
            return None
        mid = len(values) // 2
        if len(values) % 2:
            return values[mid]
        return (values[mid - 1] + values[mid]) // 2

    def to_dict(self) -> dict:
        return {
            "persona": self.persona,
            "conversation_model": self.conversation_model,
            "extraction_model": self.extraction_model,
            "ended_because": self.ended_because,
            "turns": [
                {
                    "role": t.role,
                    "text": t.text,
                    "first_chunk_ms": t.first_chunk_ms,
                    "total_ms": t.total_ms,
                }
                for t in self.turns
            ],
            "outcome": self.outcome.model_dump(mode="json"),
            "qualification": (
                self.qualification.model_dump(mode="json") if self.qualification else None
            ),
            "usage": self.usage.to_dict(),
            "median_first_chunk_ms": self.median_first_chunk_ms,
            "tool_calls": self.tool_calls,
        }


async def simulate_call(
    client,
    *,
    contact: Contact,
    context: CallContext,
    greeting: str,
    persona_id: str = "cooperative",
    language_name: str = "English",
    conversation_model: str | None = None,
    conversation_effort: str | None = None,
    extraction_model: str | None = None,
    extraction_effort: str | None = None,
    max_exchanges: int = DEFAULT_MAX_EXCHANGES,
    toolbox: Toolbox | None = None,
) -> SimulationResult:
    """Run one call end to end against a simulated person.

    With a `toolbox` the agent uses the campaign's tools for real, as on a
    call; the caller owns it, and records what it did.
    """
    persona = PERSONAS_BY_ID.get(persona_id) or PERSONAS[0]
    usage = TokenUsage()

    agent = ConversationLLM(
        client,
        contact=contact,
        context=context,
        model=conversation_model,
        effort=conversation_effort,
        usage=usage,
        toolbox=toolbox,
    )

    persona_system = PERSONA_SYSTEM.format(
        who=_describe(contact),
        behaviour=persona.behaviour,
        language=language_name,
    )

    # A simulation has no wall-clock duration worth reporting, but the
    # extractor resolves "next Tuesday" against the call's timestamp — so it
    # gets a real one, and the turns get plausible spacing.
    clock = datetime.now(timezone.utc)
    transcript: list[Turn] = []
    turns: list[SimulatedTurn] = []

    def record(role: str, text: str) -> None:
        nonlocal clock
        turn = Turn(role=role, text=text, started_at=clock)
        transcript.append(turn)
        agent.record(turn)
        clock += timedelta(seconds=6)

    record("assistant", greeting)
    turns.append(SimulatedTurn(role="assistant", text=greeting))

    ended_because = "hit the exchange limit"

    for _ in range(max_exchanges):
        person_text = await _persona_reply(client, persona_system, transcript, usage)

        if not person_text or "[HANGUP]" in person_text:
            ended_because = "the person hung up"
            break

        record("user", person_text)
        turns.append(SimulatedTurn(role="user", text=person_text))

        started = time.perf_counter()
        first_chunk_at: float | None = None
        chunks: list[str] = []

        async for chunk in agent.generate():
            if isinstance(chunk, ToolPause):
                continue  # no line to cover here; the tool just runs
            if first_chunk_at is None:
                first_chunk_at = time.perf_counter()
            chunks.append(chunk)

        agent_text = " ".join(c.strip() for c in chunks if c.strip())
        if not agent_text:
            ended_because = (
                "the agent closed the call" if agent.end_requested else "the agent produced nothing"
            )
            break

        record("assistant", agent_text)
        turns.append(
            SimulatedTurn(
                role="assistant",
                text=agent_text,
                first_chunk_ms=(
                    int((first_chunk_at - started) * 1000) if first_chunk_at else None
                ),
                total_ms=int((time.perf_counter() - started) * 1000),
            )
        )

        # Same rule the live session uses, so the simulation ends the way a
        # real call would rather than on a rule invented for the test.
        if agent.end_requested or _is_closing(agent_text):
            ended_because = "the agent closed the call"
            break

    outcome = await extract_outcome(
        client,
        contact=contact,
        context=context,
        turns=transcript,
        call_started_at_iso=datetime.now(timezone.utc).isoformat(),
        model=extraction_model,
        effort=extraction_effort,
        usage=usage,
    )

    return SimulationResult(
        transcript=transcript,
        turns=turns,
        outcome=outcome,
        usage=usage,
        conversation_model=resolve(conversation_model, CONVERSATION),
        extraction_model=resolve(extraction_model, EXTRACTION),
        persona=persona.id,
        ended_because=ended_because,
        qualification=qualify_outcome(context, outcome) if context.scorecard else None,
    )


async def _persona_reply(
    client,
    system: str,
    transcript: list[Turn],
    usage: TokenUsage,
) -> str:
    """One turn from the simulated person.

    Roles are inverted relative to the agent's view: what the agent said is
    what this model *heard*, so it arrives as `user`.
    """
    messages = [
        {"role": "user" if t.role == "assistant" else "assistant", "content": t.text}
        for t in transcript
    ]
    if not messages or messages[0]["role"] != "user":
        # The API requires the first message to be from the user; a transcript
        # that somehow starts with the person can't be replayed as-is.
        messages.insert(0, {"role": "user", "content": "(the phone rings)"})

    model = persona_model()
    spec = active()

    if spec is None or spec.api == ANTHROPIC_API:
        response = await client.messages.create(
            model=model,
            max_tokens=PERSONA_MAX_TOKENS,
            system=system,
            messages=messages,
        )
        usage.add_response_usage(model, getattr(response, "usage", None))
        parts = [b.text for b in response.content if getattr(b, "type", "") == "text"]
        return " ".join(p.strip() for p in parts if p.strip()).strip()

    response = await client.chat.completions.create(
        model=model,
        max_tokens=PERSONA_MAX_TOKENS,
        messages=[{"role": "system", "content": system}, *messages],
    )
    usage.add_response_usage(model, getattr(response, "usage", None))
    return (response.choices[0].message.content or "").strip()


def _describe(contact: Contact) -> str:
    lines = [f"Your name is {contact.full_name}.", f"You are in the {contact.timezone} timezone."]
    # Sorted so a re-run with the same inputs produces the same prompt bytes.
    for key, value in sorted((contact.attributes or {}).items()):
        lines.append(f"{key.replace('_', ' ').capitalize()}: {value}")
    return "\n".join(lines)
