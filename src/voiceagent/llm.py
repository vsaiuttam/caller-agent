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

Ending the call: the model decides when a call is over and says so by writing
`END_CALL_MARKER` after its farewell. Guessing from the words alone misses
most goodbyes that aren't English, so the model's own signal is what ends the
call — and the marker is filtered out of the stream before anything is
spoken, recorded, or synthesized.

Tools: with a `Toolbox` (the campaign's MCP apps) and a provider that can
call tools, the model may stop mid-turn to use them. Everything it said
first is handed over, then a `ToolPause` — before any tool runs, so the
speaker can put "let me check" on the line while it does. The results go
back to the model in its provider's own shape and its answer streams on as
the rest of the same turn. Tool exchanges stay in the model's history, so a
later turn still knows what a tool returned; the transcript holds speech
only.
"""

from __future__ import annotations

import asyncio
import json
import logging
import re
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

from .catalog import (
    CONVERSATION,
    DEFAULT_CONVERSATION_EFFORT,
    DEFAULT_CONVERSATION_MODEL,
    TokenUsage,
    resolve,
    resolve_effort,
)
from .models import CallContext, Contact, Turn
from .prompts import build_guidance_block, build_system_blocks, build_system_text
from .providers import ANTHROPIC_API, active

if TYPE_CHECKING:
    from .mcp.toolbox import Toolbox, ToolResult, ToolSpec

logger = logging.getLogger(__name__)

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
MAX_TOKENS = 300

# Tool rounds the model may take in one turn before it has to answer. Each
# is a tool call plus another model request while the person waits; a model
# still reaching for tools after three is looping, not finding things out.
MAX_TOOL_ROUNDS = 3

# Flush a chunk to TTS at a sentence end, or at a clause break once we have
# enough words to sound natural rather than clipped.
_SENTENCE_END = re.compile(r"[.!?]['\")\]]*\s")
_CLAUSE_BREAK = re.compile(r"[,;:]\s")
_MIN_CLAUSE_CHARS = 45

# Written by the model after its farewell to end the call. VOICE_PERSONA in
# prompts.py spells the same string out literally; the two must match.
END_CALL_MARKER = "[END_CALL]"


@dataclass(frozen=True)
class ToolPause:
    """The model stopped to use tools. `tools` are the ids about to run.

    Yielded by `generate()` after every word the model wrote before reaching
    for them, and before any of them runs.
    """

    tools: tuple[str, ...]


class EndMarkerFilter:
    """Strips `END_CALL_MARKER` from a stream of model text.

    The marker can arrive split across deltas ("... bye! [EN", "D_CALL]"), so
    any trailing text that could still become the marker is held back until
    the next delta settles it. Everything after the marker is dropped: the
    model was told it is the last thing it writes, and anything it adds
    afterwards was never meant to be heard.
    """

    def __init__(self) -> None:
        self._held = ""
        self.found = False

    def feed(self, text: str) -> str:
        """Return the text that is safe to emit now."""
        if self.found:
            return ""

        text = self._held + text
        at = text.find(END_CALL_MARKER)
        if at >= 0:
            self.found = True
            self._held = ""
            return text[:at]

        keep = _partial_marker_length(text)
        self._held = text[len(text) - keep:] if keep else ""
        return text[: len(text) - keep]

    def flush(self) -> str:
        """End of stream: release held text that turned out not to be the marker."""
        held, self._held = self._held, ""
        return "" if self.found else held


def _partial_marker_length(text: str) -> int:
    """Length of the longest suffix of `text` that begins the marker."""
    for length in range(min(len(text), len(END_CALL_MARKER) - 1), 0, -1):
        if text.endswith(END_CALL_MARKER[:length]):
            return length
    return 0


@dataclass
class ToolCall:
    """One tool call the model asked for. `problem` means it will not run."""

    id: str
    tool: str
    arguments: dict[str, Any]
    problem: str | None = None


@dataclass
class _Request:
    """One model request within a turn, and the tool calls it ended with."""

    tools_allowed: bool
    # The model's own message asking for the calls, to go back in history.
    assistant: dict[str, Any] | None = None
    calls: list[ToolCall] = field(default_factory=list)


@dataclass
class _ToolExchange:
    """A tool round in the model's history, in its provider's native messages."""

    messages: list[dict[str, Any]]


class ConversationLLM:
    """One instance per live call."""

    def __init__(
        self,
        client,
        contact: Contact,
        context: CallContext,
        *,
        model: str | None = None,
        effort: str | None = None,
        usage: TokenUsage | None = None,
        toolbox: Toolbox | None = None,
    ) -> None:
        self._client = client
        self._model = resolve(model, CONVERSATION)
        self._effort = resolve_effort(effort, CONVERSATION)
        spec = active()
        self._api = spec.api if spec else ANTHROPIC_API
        # Tools are offered only where the provider can use them; otherwise
        # the call runs exactly as it would with no toolbox at all.
        supports_tools = spec.supports_tools if spec else True
        self._toolbox = toolbox if supports_tools else None
        self._specs: list[ToolSpec] = self._toolbox.specs() if self._toolbox else []
        tools = bool(self._specs)
        self._system = build_system_blocks(contact, context, tools=tools)
        self._system_text = build_system_text(contact, context, tools=tools)
        # Speech turns and tool exchanges, in the order they happened.
        self._history: list[Turn | _ToolExchange] = []
        # What this turn said before its last tool round. Those words are in
        # the tool exchange already, so they are left out of the turn's text
        # in history rather than said twice. See record().
        self._said_before_tools = ""
        # Shared with the pipeline so the call's ledger accumulates across
        # both the conversation and the extraction that follows it.
        self.usage = usage if usage is not None else TokenUsage()
        # Notes whispered by a supervisor during the call. See add_guidance().
        self._guidance: list[str] = []
        # Whether the last generated turn ended with END_CALL_MARKER.
        self.end_requested = False

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
        said_before, self._said_before_tools = self._said_before_tools, ""
        if turn.role == "assistant" and said_before:
            # Only the words after the tools; the ones before went back with
            # the tool call. Cut off before the tools, and nothing is left.
            rest = turn.text[len(said_before):] if turn.text.startswith(said_before) else ""
            turn = turn.model_copy(update={"text": rest.strip()})
        if turn.text:
            self._history.append(turn)

    def _messages(self) -> list[dict]:
        messages: list[dict] = []
        for entry in self._history:
            if isinstance(entry, _ToolExchange):
                messages.extend(entry.messages)
            else:
                messages.append({"role": entry.role, "content": entry.text})
        return messages

    def add_guidance(self, text: str) -> None:
        """Steer the rest of the call with a supervisor's note.

        Applies from the next turn on. The note goes into the system prompt
        after both cached blocks, so it costs neither cache — the persona and
        this call's context are still read from cache on every turn.
        """
        text = text.strip()
        if text:
            self._guidance.append(text)

    def _system_blocks(self) -> list[dict]:
        if not self._guidance:
            return self._system
        # No cache_control: guidance can change mid-call, and a breakpoint
        # here would write a new cache entry every time it did.
        return [*self._system, {"type": "text", "text": build_guidance_block(self._guidance)}]

    def _system_prompt_text(self) -> str:
        if not self._guidance:
            return self._system_text
        return f"{self._system_text}\n\n{build_guidance_block(self._guidance)}"

    # -- generation --------------------------------------------------------

    async def generate(self) -> AsyncIterator[str | ToolPause]:
        """Stream the next agent turn as speakable chunks, pausing for tools.

        Yields text chunks, and one `ToolPause` per tool round. Sets
        `end_requested` when the model ended the turn with the end-call
        marker; the marker itself is never yielded.
        """
        self.end_requested = False
        self._said_before_tools = ""
        marker = EndMarkerFilter()
        buffer = ""
        said: list[str] = []

        for round_number in range(MAX_TOOL_ROUNDS + 1):
            request = _Request(tools_allowed=bool(self._specs) and round_number < MAX_TOOL_ROUNDS)
            deltas = (
                self._stream_anthropic(request)
                if self._api == ANTHROPIC_API
                else self._stream_openai(request)
            )

            async for delta in deltas:
                buffer += marker.feed(delta)
                if marker.found:
                    self.end_requested = True

                while True:
                    split_at = _find_flush_point(buffer)
                    if split_at is None:
                        break
                    chunk, buffer = buffer[:split_at], buffer[split_at:]
                    chunk = chunk.strip()
                    if chunk:
                        said.append(chunk)
                        yield chunk

            if not request.calls:
                break

            # Everything said so far goes out before the tools run: "let me
            # check" is only worth saying while the checking happens.
            tail, buffer = (buffer + marker.flush()).strip(), ""
            if tail:
                said.append(tail)
                yield tail
            runnable = tuple(call.tool for call in request.calls if call.problem is None)
            if runnable:
                yield ToolPause(tools=runnable)

            results = await self._run_tools(request.calls)
            self._history.append(_ToolExchange(self._exchange_messages(request, results)))
            self._said_before_tools = " ".join(said)

        tail = (buffer + marker.flush()).strip()
        if tail:
            yield tail

    async def _run_tools(self, calls: list[ToolCall]) -> list[ToolResult]:
        """Run a round's calls together; each comes back as a result, never an exception."""
        from .mcp.toolbox import ToolResult

        async def run(call: ToolCall) -> ToolResult:
            if call.problem is not None:
                return ToolResult(ok=False, text=call.problem)
            try:
                return await self._toolbox.call(call.tool, call.arguments)
            except Exception:  # noqa: BLE001 - Toolbox promises not to raise; hold it to that
                logger.exception("Tool %s raised; the model is told it failed", call.tool)
                return ToolResult(ok=False, text="The tool failed unexpectedly.")

        return list(await asyncio.gather(*(run(call) for call in calls)))

    def _exchange_messages(self, request: _Request, results: list[ToolResult]) -> list[dict]:
        """The model's tool request and the results, as its provider expects them back."""
        if self._api == ANTHROPIC_API:
            return [request.assistant, anthropic_tool_results(request.calls, results)]
        return [request.assistant, *chat_tool_results(request.calls, results)]

    # -- provider paths ----------------------------------------------------
    #
    # Both yield raw text deltas and fold usage into the ledger on completion.
    # Neither is reached on an interrupted turn — barge-in cancels the
    # generator mid-iteration — so interrupted turns are undercounted. The
    # bill is a floor, not an exact figure, and that is the right way round:
    # better to understate our own estimate than overstate it.
    #
    # Once a turn has used its tool rounds the tools stay in the request but
    # the model may not call them: both APIs refuse a history holding tool
    # calls when the request defines no tools.

    async def _stream_anthropic(self, request: _Request) -> AsyncIterator[str]:
        kwargs: dict = dict(
            model=self._model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": self._effort},
            system=self._system_blocks(),
            messages=self._messages(),
        )
        # Only pass tools when non-empty — the API rejects an empty list.
        if self._specs:
            kwargs["tools"] = anthropic_tools(self._specs)
            if not request.tools_allowed:
                kwargs["tool_choice"] = {"type": "none"}

        final = None
        async with self._client.messages.stream(**kwargs) as stream:
            async for delta in stream.text_stream:
                yield delta

            try:
                final = await stream.get_final_message()
                self.usage.add_response_usage(self._model, final.usage)
            except Exception:  # noqa: BLE001 - accounting must never break a call
                pass

        if request.tools_allowed and getattr(final, "stop_reason", None) == "tool_use":
            # Passed back exactly as it came, thinking blocks and all: with
            # thinking on, the API rejects a tool result whose request lost them.
            request.assistant = {"role": "assistant", "content": final.content}
            request.calls = [
                anthropic_tool_call(block)
                for block in final.content
                if getattr(block, "type", None) == "tool_use"
            ]

    async def _stream_openai(self, request: _Request) -> AsyncIterator[str]:
        """The `chat/completions` shape: Gemini, OpenAI, Sarvam, NVIDIA.

        The two cached system blocks collapse into one system message. That
        loses Anthropic's explicit breakpoints, but these providers cache
        automatically on a matching prefix, and the prompt is laid out
        prefix-stable anyway — the persona still leads, the volatile
        conversation still trails. Supervisor guidance is appended last for
        the same reason.

        Tool calls stream in fragments keyed by index — the id and name
        first, the arguments in pieces after — and are put together here.
        """
        kwargs: dict = dict(
            model=self._model,
            max_tokens=MAX_TOKENS,
            reasoning_effort=self._effort,
            messages=[
                {"role": "system", "content": self._system_prompt_text()},
                *self._messages(),
            ],
            stream=True,
            # Usage arrives in a final chunk only if asked for, and without it
            # every call on this path would silently record as free.
            stream_options={"include_usage": True},
        )
        if self._specs:
            kwargs["tools"] = chat_tools(self._specs)
            if not request.tools_allowed:
                kwargs["tool_choice"] = "none"

        stream = await self._client.chat.completions.create(**kwargs)
        text: list[str] = []
        fragments: dict[int, dict[str, Any]] = {}
        async for event in stream:
            if event.choices:
                delta = event.choices[0].delta
                if delta.content:
                    text.append(delta.content)
                    yield delta.content
                for fragment in getattr(delta, "tool_calls", None) or []:
                    _gather_fragment(fragments, fragment)
            if getattr(event, "usage", None):
                self.usage.add_response_usage(self._model, event.usage)

        if request.tools_allowed and fragments:
            calls = [fragments[index] for index in sorted(fragments)]
            request.assistant = chat_assistant_message("".join(text), calls)
            request.calls = [parse_chat_call(call) for call in calls]


# --------------------------------------------------------------------------
# Tool calls in each provider's shape. Shared with the post-call actions
# (postcall/mcp_actions.py), which run the same loop without streaming.
# --------------------------------------------------------------------------


def anthropic_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {"name": s.id, "description": s.description, "input_schema": s.input_schema} for s in specs
    ]


def chat_tools(specs: list[ToolSpec]) -> list[dict[str, Any]]:
    return [
        {
            "type": "function",
            "function": {"name": s.id, "description": s.description, "parameters": s.input_schema},
        }
        for s in specs
    ]


def anthropic_tool_results(calls: list[ToolCall], results: list[ToolResult]) -> dict[str, Any]:
    """The user message answering an assistant message's tool_use blocks."""
    return {
        "role": "user",
        "content": [
            {
                "type": "tool_result",
                "tool_use_id": call.id,
                "content": result.text or "(no output)",
                "is_error": not result.ok,
            }
            for call, result in zip(calls, results)
        ],
    }


def chat_tool_results(calls: list[ToolCall], results: list[ToolResult]) -> list[dict[str, Any]]:
    """One `tool` message per call, answering an assistant message's tool_calls."""
    return [
        {
            "role": "tool",
            "tool_call_id": call.id,
            "content": result.text if result.ok else f"Error: {result.text}",
        }
        for call, result in zip(calls, results)
    ]


def anthropic_tool_call(block) -> ToolCall:
    arguments = getattr(block, "input", None)
    if isinstance(arguments, dict):
        return ToolCall(id=block.id, tool=block.name, arguments=arguments)
    return ToolCall(
        id=block.id, tool=block.name, arguments={}, problem="The arguments were not an object; not run."
    )


def _gather_fragment(fragments: dict[int, dict[str, Any]], fragment) -> None:
    call = fragments.setdefault(
        getattr(fragment, "index", None) or 0, {"id": "", "name": "", "arguments": "", "extra": None}
    )
    if getattr(fragment, "id", None):
        call["id"] = fragment.id
    function = getattr(fragment, "function", None)
    if function is not None:
        if getattr(function, "name", None):
            call["name"] = function.name
        if getattr(function, "arguments", None):
            call["arguments"] += function.arguments
    # Gemini signs its function calls ("thought signatures") and refuses the
    # next request if the signature does not come back with the call.
    extra = getattr(fragment, "extra_content", None)
    if extra:
        call["extra"] = extra


def chat_call(tool_call) -> dict[str, Any]:
    """A non-streamed `message.tool_calls` entry, as `_gather_fragment` assembles one."""
    function = getattr(tool_call, "function", None)
    return {
        "id": getattr(tool_call, "id", "") or "",
        "name": getattr(function, "name", "") or "",
        "arguments": getattr(function, "arguments", "") or "",
        "extra": getattr(tool_call, "extra_content", None),
    }


def chat_assistant_message(text: str, calls: list[dict[str, Any]]) -> dict[str, Any]:
    """The assistant message asking for `calls`, to go back into the history."""
    return {
        "role": "assistant",
        "content": text or None,
        "tool_calls": [_chat_tool_call(call) for call in calls],
    }


def _chat_tool_call(call: dict[str, Any]) -> dict[str, Any]:
    message = {
        "id": call["id"],
        "type": "function",
        "function": {"name": call["name"], "arguments": call["arguments"]},
    }
    if call["extra"]:
        message["extra_content"] = call["extra"]
    return message


def parse_chat_call(call: dict[str, Any]) -> ToolCall:
    try:
        arguments = json.loads(call["arguments"] or "{}")
    except ValueError:
        arguments = None
    if not isinstance(arguments, dict):
        return ToolCall(
            id=call["id"],
            tool=call["name"],
            arguments={},
            problem="The arguments for this call were not valid JSON, so it was not run.",
        )
    return ToolCall(id=call["id"], tool=call["name"], arguments=arguments)


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
