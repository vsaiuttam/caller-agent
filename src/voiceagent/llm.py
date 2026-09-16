"""Model streaming for the in-call path.

Two things matter here and nothing else does: time-to-first-audio, and being
interruptible.

Time-to-first-audio: we don't wait for the full response. We emit at clause
boundaries so TTS starts speaking while the model is still generating. On a
two-sentence reply that's the difference between ~200ms and ~900ms before the
person hears anything.

Interruptible: `generate()` is a plain async generator, so the caller cancels
it by breaking out or cancelling the task when barge-in is detected. The HTTP
stream is closed by the context manager on the way out.

Provider-independent: the clause-flushing above is the part worth keeping,
and it is identical whichever model produces the tokens. Only the request
differs, so only the request is branched — see `_stream_anthropic` and
`_stream_openai` at the bottom of this file.
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator

from .catalog import (
    CONVERSATION,
    DEFAULT_CONVERSATION_EFFORT,
    DEFAULT_CONVERSATION_MODEL,
    TokenUsage,
    resolve,
    resolve_effort,
)
from .models import CallContext, Contact, Turn
from .prompts import build_system_blocks, build_system_text
from .providers import ANTHROPIC_API, active

# Sonnet 5 at low effort: near-Opus conversational quality, and the effort
# lever is what buys us the latency. Note we keep adaptive thinking ON —
# disabling it makes the model measurably less willing to call tools, which
# in a voice agent shows up as "let me check that for you" followed by
# nothing actually being checked.
#
# Both are now per-campaign settings; these remain the fallback when a
# campaign has no explicit choice.
MODEL = DEFAULT_CONVERSATION_MODEL
EFFORT = DEFAULT_CONVERSATION_EFFORT

# Short cap. Turns are one or two sentences by prompt; this is a backstop
# against a runaway monologue tying up the line, not a target.
MAX_TOKENS = 150

# Flush a chunk to TTS at a sentence end, or at a clause break once we have
# enough words to sound natural rather than clipped. Lower threshold = faster
# first audio — the person hears something sooner.
_SENTENCE_END = re.compile(r"[.!?]['\")\]]*\s")
_CLAUSE_BREAK = re.compile(r"[,;:]\s")
_MIN_CLAUSE_CHARS = 30


class ConversationLLM:
    """One instance per live call."""

    def __init__(
        self,
        client,
        contact: Contact,
        context: CallContext,
        tools: list[dict] | None = None,
        *,
        model: str | None = None,
        effort: str | None = None,
        usage: TokenUsage | None = None,
    ) -> None:
        self._client = client
        self._system = build_system_blocks(contact, context)
        self._system_text = build_system_text(contact, context)
        self._tools = tools or []
        self._turns: list[Turn] = []
        self._model = resolve(model, CONVERSATION)
        self._effort = resolve_effort(effort, CONVERSATION)
        spec = active()
        self._api = spec.api if spec else ANTHROPIC_API
        # Shared with the pipeline so the call's ledger accumulates across
        # both the conversation and the extraction that follows it.
        self.usage = usage if usage is not None else TokenUsage()

    @property
    def model(self) -> str:
        return self._model

    # -- history -----------------------------------------------------------

    def record(self, turn: Turn) -> None:
        """Append a completed turn. Call this for both sides.

        On barge-in, record what the agent *actually said* before it was cut
        off, not what it had generated. Otherwise the model believes it
        delivered information the person never heard, and won't repeat it.
        """
        self._turns.append(turn)

    def _messages(self) -> list[dict]:
        return [{"role": t.role, "content": t.text} for t in self._turns]

    # -- generation --------------------------------------------------------

    async def generate(self) -> AsyncIterator[str]:
        """Stream the next agent turn as speakable chunks."""
        buffer = ""

        deltas = (
            self._stream_anthropic()
            if self._api == ANTHROPIC_API
            else self._stream_openai()
        )

        async for delta in deltas:
            buffer += delta

            while True:
                split_at = _find_flush_point(buffer)
                if split_at is None:
                    break
                chunk, buffer = buffer[:split_at], buffer[split_at:]
                chunk = chunk.strip()
                if chunk:
                    yield chunk

        tail = buffer.strip()
        if tail:
            yield tail

    # -- provider paths ----------------------------------------------------
    #
    # Both yield raw text deltas and fold usage into the ledger on completion.
    # Neither is reached on an interrupted turn — barge-in cancels the
    # generator mid-iteration — so interrupted turns are undercounted. The
    # bill is a floor, not an exact figure, and that is the right way round:
    # better to understate our own estimate than overstate it.

    async def _stream_anthropic(self) -> AsyncIterator[str]:
        async with self._client.messages.stream(
            model=self._model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": self._effort},
            system=self._system,
            tools=self._tools,
            messages=self._messages(),
        ) as stream:
            async for delta in stream.text_stream:
                yield delta

            try:
                final = await stream.get_final_message()
                self.usage.add_response_usage(self._model, final.usage)
            except Exception:  # noqa: BLE001 - accounting must never break a call
                pass

    async def _stream_openai(self) -> AsyncIterator[str]:
        """The `chat/completions` shape: Gemini, OpenAI, Sarvam, NVIDIA.

        The two cached system blocks collapse into one system message. That
        loses Anthropic's explicit breakpoints, but these providers cache
        automatically on a matching prefix, and the prompt is laid out
        prefix-stable anyway — the persona still leads, the volatile
        conversation still trails.
        """
        stream = await self._client.chat.completions.create(
            model=self._model,
            max_tokens=MAX_TOKENS,
            reasoning_effort=self._effort,
            messages=[
                {"role": "system", "content": self._system_text},
                *self._messages(),
            ],
            stream=True,
            # Usage arrives in a final chunk only if asked for, and without it
            # every call on this path would silently record as free.
            stream_options={"include_usage": True},
        )

        async for event in stream:
            if event.choices and event.choices[0].delta.content:
                yield event.choices[0].delta.content
            if getattr(event, "usage", None):
                self.usage.add_response_usage(self._model, event.usage)


def _find_flush_point(buffer: str) -> int | None:
    """Index to split at, or None if we should keep buffering."""
    match = _SENTENCE_END.search(buffer)
    if match:
        return match.end()

    if len(buffer) >= _MIN_CLAUSE_CHARS:
        match = _CLAUSE_BREAK.search(buffer, _MIN_CLAUSE_CHARS)
        if match:
            return match.end()

    return None
