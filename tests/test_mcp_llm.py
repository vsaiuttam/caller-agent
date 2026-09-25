"""Tools in the conversation: the model's tool loop on both provider shapes.

When a campaign allows tools and the provider supports them, the in-call
model may stop to use one. The caller must hear "let me check" before the
tool runs, never dead air; the tool's answer goes back to the model in the
provider's own format; the model then carries on speaking in the same turn.
A model that keeps asking for tools is cut off after `MAX_TOOL_ROUNDS`, and
a provider without tool support runs the call exactly as before
(docs/mcp-spec.md §1.3).

The model clients are fakes shaped the way the spec says each provider is
consumed:
- Anthropic: `client.messages.stream(**kwargs)` as an async context manager,
  `stream.text_stream`, then `await stream.get_final_message()` (with
  `.stop_reason`, `.content` blocks and `.usage`);
- chat/completions: `await client.chat.completions.create(stream=True, ...)`
  yielding `choices[0].delta.content` / `.tool_calls` fragments,
  `choices[0].finish_reason`, and a final usage event.
Each fake records the kwargs of every request, so the history shape can be
checked.

Runs standalone (`python tests/test_mcp_llm.py`) or under pytest. No API key,
no network. Names that don't exist yet are imported inside the tests.
"""

from __future__ import annotations

import asyncio
import dataclasses
import json
import logging
import os
import sys
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.voiceagent.models import CallContext, Contact, Turn  # noqa: E402

logging.basicConfig(level=logging.WARNING)
logging.getLogger().setLevel(logging.WARNING)

ANTHROPIC_ENV = dict(MODEL_PROVIDER="anthropic", ANTHROPIC_API_KEY="sk-ant-test-key")
OPENAI_SHAPE_ENV = dict(MODEL_PROVIDER="gemini", GEMINI_API_KEY="test-gemini-key")
NO_TOOLS_ENV = dict(MODEL_PROVIDER="sarvam", SARVAM_API_KEY="test-sarvam-key")

AVAILABILITY = "demo_crm__check_availability"
LOOKUP = "demo_crm__lookup_customer"
TICKET = "demo_crm__create_ticket"

TOOLS = {
    AVAILABILITY: (
        "Free appointment slots on a date (YYYY-MM-DD).",
        {"type": "object", "properties": {"date": {"type": "string"}}, "required": ["date"]},
    ),
    LOOKUP: (
        "Look up a customer by phone number.",
        {"type": "object", "properties": {"phone": {"type": "string"}}, "required": ["phone"]},
    ),
    TICKET: (
        "Open a support ticket.",
        {"type": "object", "properties": {"summary": {"type": "string"}}, "required": ["summary"]},
    ),
}
RESULTS = {
    AVAILABILITY: "Free slots on 2026-09-29: 10:00, 14:00, 15:30",
    LOOKUP: "Customer Asha Rao, account DEMO-0042, plan Gold.",
    TICKET: "Ticket T-00017 opened.",
}


# ---------------------------------------------------------------------------
# Harness
# ---------------------------------------------------------------------------


@contextmanager
def _env(**values: str | None):
    """Set (or, with None, unset) environment variables for the block."""
    saved = {key: os.environ.get(key) for key in values}
    try:
        for key, value in values.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value
        yield
    finally:
        for key, value in saved.items():
            if value is None:
                os.environ.pop(key, None)
            else:
                os.environ[key] = value


class _Obj(SimpleNamespace):
    """An SDK response object: attribute access, plus pydantic's `model_dump()`."""

    def model_dump(self, **_):
        return {k: _dump(v) for k, v in vars(self).items()}


def _dump(value):
    if isinstance(value, _Obj):
        return value.model_dump()
    if isinstance(value, list):
        return [_dump(v) for v in value]
    if isinstance(value, dict):
        return {k: _dump(v) for k, v in value.items()}
    return value


def _get(obj, key, default=None):
    """Read a field from a dict or an object alike."""
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def _text_of(content) -> str:
    """The text in a message or tool-result `content`, whatever its shape."""
    if content is None:
        return ""
    if isinstance(content, str):
        return content
    if isinstance(content, (list, tuple)):
        return " ".join(_text_of(_get(part, "text", "") if not isinstance(part, str) else part) for part in content)
    return str(content)


class FakeToolbox:
    """The Toolbox protocol: `specs()`, and an async `call()` that never raises.

    `log` records when each tool ran, so a test can tell whether the model
    wrapper handed over its pause before running anything.
    """

    def __init__(self, tool_ids=(AVAILABILITY, LOOKUP), *, results=None, log=None) -> None:
        from src.voiceagent.mcp.toolbox import ToolSpec

        self._specs = [
            ToolSpec(id=tool_id, description=TOOLS[tool_id][0], input_schema=TOOLS[tool_id][1])
            for tool_id in tool_ids
        ]
        self.results = dict(results or {})
        self.calls: list[tuple[str, dict]] = []
        self.log = log if log is not None else []

    def specs(self):
        return list(self._specs)

    async def call(self, tool_id: str, arguments: dict):
        from src.voiceagent.mcp.toolbox import ToolResult

        self.log.append(("tool ran", tool_id))
        self.calls.append((tool_id, arguments))
        await asyncio.sleep(0)
        ok, text = self.results.get(tool_id, (True, RESULTS.get(tool_id, "done")))
        return ToolResult(ok=ok, text=text)


# -- Anthropic-shaped client ----------------------------------------------------


class Say:
    """One scripted Anthropic response: streamed text, then optional tool calls.

    `tools` is a list of (tool_use_id, tool_name, input). With `thinking`, the
    final content starts with a signed thinking block, as it does with
    adaptive thinking on.
    """

    def __init__(self, *deltas: str, tools=(), thinking: str | None = None) -> None:
        self.deltas = list(deltas)
        content = []
        if thinking is not None:
            content.append(_Obj(type="thinking", thinking=thinking, signature=f"sig-{abs(hash(thinking))}"))
        text = "".join(deltas)
        if text:
            content.append(_Obj(type="text", text=text, citations=None))
        for tool_use_id, name, arguments in tools:
            content.append(_Obj(type="tool_use", id=tool_use_id, name=name, input=arguments))
        self.final = _Obj(
            id="msg_test",
            type="message",
            role="assistant",
            content=content,
            stop_reason="tool_use" if tools else "end_turn",
            stop_sequence=None,
            usage=_Obj(input_tokens=120, output_tokens=30, cache_read_input_tokens=0, cache_creation_input_tokens=0),
        )


class _AnthropicStream:
    def __init__(self, reply: Say) -> None:
        self._reply = reply

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc) -> bool:
        return False

    @property
    def text_stream(self):
        async def deltas():
            for delta in self._reply.deltas:
                await asyncio.sleep(0)
                yield delta

        return deltas()

    async def get_final_message(self):
        return self._reply.final


class FakeAnthropic:
    """`script` is a list of replies, or a function (request, number) -> reply."""

    def __init__(self, script) -> None:
        self._script = script
        self.requests: list[dict] = []
        self.messages = _Obj(stream=self._stream, create=self._create)

    def _reply(self, kwargs: dict) -> Say:
        snapshot = dict(kwargs)
        snapshot["messages"] = list(kwargs.get("messages") or [])
        self.requests.append(snapshot)
        if callable(self._script):
            return self._script(snapshot, len(self.requests))
        return self._script.pop(0) if self._script else Say("Okay.")

    def _stream(self, **kwargs):
        return _AnthropicStream(self._reply(kwargs))

    async def _create(self, **kwargs):
        return self._reply(kwargs).final

    async def close(self) -> None:
        pass


# -- chat/completions-shaped client -----------------------------------------------


def _chunk(content=None, tool_calls=None, finish_reason=None):
    return _Obj(
        id="chunk",
        choices=[
            _Obj(
                index=0,
                delta=_Obj(role=None, content=content, tool_calls=tool_calls),
                finish_reason=finish_reason,
            )
        ],
        usage=None,
    )


def _fragment(index: int, *, call_id=None, name=None, arguments=None):
    return _Obj(
        index=index,
        id=call_id,
        type="function" if call_id else None,
        function=_Obj(name=name, arguments=arguments),
    )


class Reply:
    """One scripted chat/completions response.

    `tool_calls` is a list of (call_id, tool_name, arguments_json). They are
    streamed the way providers do: the first fragment of each call carries its
    id, name and half the arguments; the rest of every call's arguments
    follow afterwards, interleaved by index.
    """

    def __init__(self, *deltas: str, tool_calls=()) -> None:
        self.deltas = list(deltas)
        self.tool_calls = list(tool_calls)

    def events(self):
        for delta in self.deltas:
            yield _chunk(content=delta)
        halves = [(args[: len(args) // 2], args[len(args) // 2:]) for _, _, args in self.tool_calls]
        for index, ((call_id, name, _), (head, _tail)) in enumerate(zip(self.tool_calls, halves)):
            yield _chunk(tool_calls=[_fragment(index, call_id=call_id, name=name, arguments=head)])
        for index, (_head, tail) in enumerate(halves):
            yield _chunk(tool_calls=[_fragment(index, arguments=tail)])
        yield _chunk(finish_reason="tool_calls" if self.tool_calls else "stop")
        yield _Obj(id="chunk", choices=[], usage=_Obj(prompt_tokens=120, completion_tokens=30, total_tokens=150))

    def completion(self):
        calls = [
            _Obj(id=call_id, type="function", function=_Obj(name=name, arguments=args))
            for call_id, name, args in self.tool_calls
        ]
        message = _Obj(role="assistant", content="".join(self.deltas) or None, tool_calls=calls or None, refusal=None)
        return _Obj(
            id="completion",
            choices=[_Obj(index=0, message=message, finish_reason="tool_calls" if calls else "stop")],
            usage=_Obj(prompt_tokens=120, completion_tokens=30, total_tokens=150),
        )


class FakeChat:
    """`script` is a list of replies, or a function (request, number) -> reply."""

    def __init__(self, script) -> None:
        self._script = script
        self.requests: list[dict] = []
        self.chat = _Obj(completions=_Obj(create=self._create))

    async def _create(self, **kwargs):
        snapshot = dict(kwargs)
        snapshot["messages"] = list(kwargs.get("messages") or [])
        self.requests.append(snapshot)
        if callable(self._script):
            reply = self._script(snapshot, len(self.requests))
        else:
            reply = self._script.pop(0) if self._script else Reply("Okay.")
        if not kwargs.get("stream"):
            return reply.completion()

        async def events():
            for event in reply.events():
                await asyncio.sleep(0)
                yield event

        return events()

    async def close(self) -> None:
        pass


# -- driving the model wrapper ------------------------------------------------------


def _llm(client, toolbox=None):
    from src.voiceagent.llm import ConversationLLM

    kwargs = {} if toolbox is None else {"toolbox": toolbox}
    return ConversationLLM(
        client,
        contact=Contact(
            contact_id="c1", full_name="Asha Rao", phone_e164="+15555550123", timezone="Asia/Kolkata"
        ),
        context=CallContext(campaign_id="camp-1", goal="Book Asha's next cleaning appointment."),
        **kwargs,
    )


def _said(role: str, text: str) -> Turn:
    return Turn(role=role, text=text, started_at=datetime.now(timezone.utc))


async def _turn(llm, log: list | None = None, timeout: float = 3.0) -> list:
    """Everything one `generate()` yields, in order."""

    async def drain():
        items = []
        async for item in llm.generate():
            items.append(item)
            if log is not None:
                log.append(("got", item))
        return items

    try:
        return await asyncio.wait_for(drain(), timeout)
    except asyncio.TimeoutError:
        raise AssertionError(f"generate() did not finish within {timeout}s") from None


def _split(items: list):
    """(text before the first pause, the pauses, text after it)."""
    from src.voiceagent.llm import ToolPause

    pauses = [i for i in items if isinstance(i, ToolPause)]
    at = items.index(pauses[0]) if pauses else len(items)
    before = " ".join(i.strip() for i in items[:at] if isinstance(i, str) and i.strip())
    after = " ".join(i.strip() for i in items[at:] if isinstance(i, str) and i.strip())
    return before, pauses, after


def _withheld(request: dict) -> bool:
    """Whether a request stops the model from calling tools."""
    choice = request.get("tool_choice")
    if not request.get("tools"):
        return True
    return choice == "none" or (isinstance(choice, dict) and choice.get("type") == "none")


def _anthropic_tool_turn() -> tuple[FakeAnthropic, Say]:
    first = Say(
        "One moment,",
        " let me check.",
        thinking="They asked about Tuesday. Check the calendar before answering.",
        tools=[("toolu_1", AVAILABILITY, {"date": "2026-09-29"})],
    )
    return FakeAnthropic([first, Say("Tuesday at ten ", "is free. Shall I book it?")]), first


def _chat_tool_turn() -> FakeChat:
    return FakeChat(
        [
            Reply(
                "Let me check ",
                "both of those.",
                tool_calls=[
                    ("call_a", AVAILABILITY, '{"date": "2026-09-29"}'),
                    ("call_b", LOOKUP, '{"phone": "+15555550123"}'),
                ],
            ),
            Reply("Tuesday at ten is free, ", "and I found your account."),
        ]
    )


async def _run_tool_turn(client, box, question: str = "Is Tuesday free?"):
    log = box.log
    llm = _llm(client, box)
    llm.record(_said("user", question))
    items = await _turn(llm, log)
    return llm, items, log


# ---------------------------------------------------------------------------
# The contract
# ---------------------------------------------------------------------------


def test_tool_pause_is_a_frozen_list_of_the_tools_about_to_run() -> None:
    """The session is told which tools are about to run, so the console can show them."""
    from src.voiceagent.llm import MAX_TOOL_ROUNDS, ToolPause

    pause = ToolPause(tools=(AVAILABILITY, LOOKUP))
    assert pause.tools == (AVAILABILITY, LOOKUP), pause
    assert pause == ToolPause(tools=(AVAILABILITY, LOOKUP))
    try:
        pause.tools = ()  # type: ignore[misc]
    except dataclasses.FrozenInstanceError:
        pass
    else:
        raise AssertionError("ToolPause must be a frozen dataclass")
    assert MAX_TOOL_ROUNDS == 3, MAX_TOOL_ROUNDS


def test_only_providers_that_support_tools_say_so() -> None:
    """Sarvam and NVIDIA calls never get tools they can't use."""
    from src.voiceagent.providers import PROVIDERS_BY_ID

    got = {pid: getattr(PROVIDERS_BY_ID[pid], "supports_tools", None) for pid in PROVIDERS_BY_ID}
    assert got == {"anthropic": True, "openai": True, "gemini": True, "sarvam": False, "nvidia": False}, got


# ---------------------------------------------------------------------------
# Tools offered
# ---------------------------------------------------------------------------


def test_tools_are_offered_to_anthropic_in_its_own_shape() -> None:
    """The model sees each allowed tool with its name, description and input schema."""

    async def scenario():
        client = FakeAnthropic([Say("Sure, what day suits you?")])
        llm = _llm(client, FakeToolbox())
        llm.record(_said("user", "I'd like to book a cleaning."))
        await _turn(llm)
        return client.requests

    with _env(**ANTHROPIC_ENV):
        requests = asyncio.run(scenario())
    tools = requests[0].get("tools")
    assert isinstance(tools, list) and len(tools) == 2, requests[0].get("tools")
    by_name = {t["name"]: t for t in tools}
    assert set(by_name) == {AVAILABILITY, LOOKUP}, by_name
    for tool_id in (AVAILABILITY, LOOKUP):
        assert by_name[tool_id]["description"] == TOOLS[tool_id][0], by_name[tool_id]
        assert by_name[tool_id]["input_schema"] == TOOLS[tool_id][1], by_name[tool_id]


def test_tools_are_offered_on_chat_completions_as_functions() -> None:
    """Gemini and OpenAI get the same tools in the function-calling shape."""

    async def scenario():
        client = FakeChat([Reply("Sure, what day suits you?")])
        llm = _llm(client, FakeToolbox())
        llm.record(_said("user", "I'd like to book a cleaning."))
        await _turn(llm)
        return client.requests

    with _env(**OPENAI_SHAPE_ENV):
        requests = asyncio.run(scenario())
    tools = requests[0].get("tools")
    assert isinstance(tools, list) and len(tools) == 2, tools
    assert all(t.get("type") == "function" for t in tools), tools
    by_name = {t["function"]["name"]: t["function"] for t in tools}
    assert set(by_name) == {AVAILABILITY, LOOKUP}, by_name
    for tool_id in (AVAILABILITY, LOOKUP):
        assert by_name[tool_id]["description"] == TOOLS[tool_id][0], by_name[tool_id]
        assert by_name[tool_id]["parameters"] == TOOLS[tool_id][1], by_name[tool_id]


def test_a_provider_without_tool_support_runs_the_call_as_before() -> None:
    """On Sarvam the call works exactly as it did before tools existed."""

    async def scenario():
        client = FakeChat([Reply("Sure, ", "Tuesday works.")])
        box = FakeToolbox()
        llm = _llm(client, box)
        llm.record(_said("user", "Is Tuesday free?"))
        items = await _turn(llm)
        return client.requests, items, box

    with _env(**NO_TOOLS_ENV):
        requests, items, box = asyncio.run(scenario())
    assert "tools" not in requests[0], requests[0].get("tools")
    assert all(isinstance(i, str) for i in items), items
    assert " ".join(items) == "Sure, Tuesday works.", items
    assert box.calls == [], box.calls
    system = next(m for m in requests[0]["messages"] if m["role"] == "system")
    assert "Tools" not in system["content"], "the prompt describes tools the model can't use"


def test_an_empty_toolbox_offers_no_tools() -> None:
    """A campaign with no tools chosen sends no (empty) tool list — the APIs reject one."""

    async def scenario(client):
        llm = _llm(client, FakeToolbox(tool_ids=()))
        llm.record(_said("user", "Is Tuesday free?"))
        items = await _turn(llm)
        return client.requests[0], items

    with _env(**ANTHROPIC_ENV):
        anthropic, a_items = asyncio.run(scenario(FakeAnthropic([Say("Yes, it is.")])))
    with _env(**OPENAI_SHAPE_ENV):
        chat, c_items = asyncio.run(scenario(FakeChat([Reply("Yes, it is.")])))
    assert "tools" not in anthropic, anthropic.get("tools")
    assert "tools" not in chat, chat.get("tools")
    assert a_items == ["Yes, it is."] and c_items == ["Yes, it is."], (a_items, c_items)


def test_without_a_toolbox_nothing_changes() -> None:
    """Calls on campaigns without tools stream text only, with no tools in the request."""

    async def scenario():
        client = FakeAnthropic([Say("Yes, ", "Tuesday is free.")])
        llm = _llm(client)
        llm.record(_said("user", "Is Tuesday free?"))
        return await _turn(llm), client.requests[0]

    with _env(**ANTHROPIC_ENV):
        items, request = asyncio.run(scenario())
    assert items == ["Yes, Tuesday is free."], items
    assert "tools" not in request, request.get("tools")


def test_the_prompt_gains_a_tools_section_only_when_tools_are_offered() -> None:
    """The model is told how to use tools on a call, without touching the cached persona."""
    from src.voiceagent.prompts import VOICE_PERSONA

    async def anthropic(box):
        client = FakeAnthropic([Say("Okay.")])
        llm = _llm(client, box)
        llm.record(_said("user", "Hello?"))
        await _turn(llm)
        return client.requests[0]["system"]

    async def chat(box):
        client = FakeChat([Reply("Okay.")])
        llm = _llm(client, box)
        llm.record(_said("user", "Hello?"))
        await _turn(llm)
        return next(m for m in client.requests[0]["messages"] if m["role"] == "system")["content"]

    with _env(**ANTHROPIC_ENV):
        with_tools = asyncio.run(anthropic(FakeToolbox()))
        without = asyncio.run(anthropic(None))
    with _env(**OPENAI_SHAPE_ENV):
        chat_with = asyncio.run(chat(FakeToolbox()))
        chat_without = asyncio.run(chat(None))

    assert with_tools[0]["text"] == VOICE_PERSONA, "the cached persona block changed"
    assert with_tools[0] == without[0], "the persona block differs with tools on, so the cache would miss"
    assert "Tools" in " ".join(block["text"] for block in with_tools[1:]), with_tools[1:]
    assert "Tools" not in " ".join(block["text"] for block in without), "a Tools section with no tools"
    assert "Tools" in chat_with and "Tools" not in chat_without


# ---------------------------------------------------------------------------
# A tool turn
# ---------------------------------------------------------------------------


def test_anthropic_says_let_me_check_then_pauses_before_the_tool_runs() -> None:
    """The caller hears "one moment, let me check" before the tool runs, then the answer, in one turn."""

    async def scenario():
        client, _ = _anthropic_tool_turn()
        box = FakeToolbox(log=[])
        _llm_, items, log = await _run_tool_turn(client, box)
        return client, box, items, log

    with _env(**ANTHROPIC_ENV):
        client, box, items, log = asyncio.run(scenario())

    before, pauses, after = _split(items)
    assert len(pauses) == 1, items
    assert tuple(pauses[0].tools) == (AVAILABILITY,), pauses[0]
    assert all(isinstance(i, str) for i in items if i is not pauses[0]), items
    assert before == "One moment, let me check.", f"not all the text before the tool was handed over first: {items}"
    assert after == "Tuesday at ten is free. Shall I book it?", items
    assert box.calls == [(AVAILABILITY, {"date": "2026-09-29"})], box.calls
    assert log.index(("got", pauses[0])) < log.index(("tool ran", AVAILABILITY)), log
    assert len(client.requests) == 2, len(client.requests)


def test_anthropic_gets_its_own_content_back_unchanged_with_the_tool_results() -> None:
    """Thinking blocks go back untouched — with thinking on, the API rejects a tool turn without them."""

    async def scenario():
        client, first = _anthropic_tool_turn()
        await _run_tool_turn(client, FakeToolbox(log=[]))
        return client.requests, first

    with _env(**ANTHROPIC_ENV):
        requests, first = asyncio.run(scenario())

    messages = requests[1]["messages"]
    assistant, results = messages[-2], messages[-1]
    assert assistant["role"] == "assistant", assistant
    assert list(assistant["content"]) == list(first.final.content), assistant["content"]
    assert _get(assistant["content"][0], "type") == "thinking", assistant["content"]

    assert results["role"] == "user", results
    blocks = results["content"]
    assert isinstance(blocks, list) and len(blocks) == 1, blocks
    block = blocks[0]
    assert _get(block, "type") == "tool_result", block
    assert _get(block, "tool_use_id") == "toolu_1", block
    assert _get(block, "is_error") is False, block
    assert RESULTS[AVAILABILITY] in _text_of(_get(block, "content")), block
    assert requests[1].get("tools"), "tools were withdrawn after a single round"


def test_chat_completions_assembles_streamed_tool_calls_then_pauses_before_running_them() -> None:
    """Gemini/OpenAI tool calls arrive in fragments; both run, after the caller heard "let me check"."""

    async def scenario():
        client = _chat_tool_turn()
        box = FakeToolbox(log=[])
        _llm_, items, log = await _run_tool_turn(client, box)
        return client, box, items, log

    with _env(**OPENAI_SHAPE_ENV):
        client, box, items, log = asyncio.run(scenario())

    before, pauses, after = _split(items)
    assert len(pauses) == 1, items
    assert tuple(pauses[0].tools) == (AVAILABILITY, LOOKUP), pauses[0]
    assert before == "Let me check both of those.", items
    assert after == "Tuesday at ten is free, and I found your account.", items
    assert box.calls == [
        (AVAILABILITY, {"date": "2026-09-29"}),
        (LOOKUP, {"phone": "+15555550123"}),
    ], box.calls
    assert log.index(("got", pauses[0])) < log.index(("tool ran", AVAILABILITY)), log
    assert len(client.requests) == 2, len(client.requests)


def test_chat_completions_gets_the_tool_calls_and_tool_messages_back() -> None:
    """The model's tool calls and one `role: tool` message per call go back in its history."""

    async def scenario():
        client = _chat_tool_turn()
        await _run_tool_turn(client, FakeToolbox(log=[]))
        return client.requests

    with _env(**OPENAI_SHAPE_ENV):
        requests = asyncio.run(scenario())

    messages = requests[1]["messages"]
    at = next(
        (i for i, m in enumerate(messages) if _get(m, "role") == "assistant" and _get(m, "tool_calls")), None
    )
    assert at is not None, f"no assistant message with tool_calls in {messages}"
    calls = _get(messages[at], "tool_calls")
    assert [_get(c, "id") for c in calls] == ["call_a", "call_b"], calls
    assert [_get(_get(c, "function"), "name") for c in calls] == [AVAILABILITY, LOOKUP], calls
    assert [json.loads(_get(_get(c, "function"), "arguments")) for c in calls] == [
        {"date": "2026-09-29"},
        {"phone": "+15555550123"},
    ], calls

    tool_messages = messages[at + 1:]
    assert [_get(m, "role") for m in tool_messages] == ["tool", "tool"], tool_messages
    assert [_get(m, "tool_call_id") for m in tool_messages] == ["call_a", "call_b"], tool_messages
    assert RESULTS[AVAILABILITY] in _text_of(_get(tool_messages[0], "content")), tool_messages[0]
    assert RESULTS[LOOKUP] in _text_of(_get(tool_messages[1], "content")), tool_messages[1]


def test_a_tool_call_with_unparseable_arguments_is_skipped_and_reported_back() -> None:
    """Garbled arguments never reach a tool; the model is told, and the call carries on."""

    async def scenario():
        client = FakeChat(
            [
                Reply(
                    "Let me look.",
                    tool_calls=[
                        ("call_a", AVAILABILITY, '{"date": "2026-09-29"}'),
                        ("call_b", LOOKUP, '{"phone": "+1555'),
                    ],
                ),
                Reply("Tuesday at ten is free."),
            ]
        )
        box = FakeToolbox(log=[])
        _llm_, items, _log = await _run_tool_turn(client, box)
        return client.requests, box, items

    with _env(**OPENAI_SHAPE_ENV):
        requests, box, items = asyncio.run(scenario())

    assert box.calls == [(AVAILABILITY, {"date": "2026-09-29"})], box.calls
    tool_messages = [m for m in requests[1]["messages"] if _get(m, "role") == "tool"]
    by_id = {_get(m, "tool_call_id"): _text_of(_get(m, "content")) for m in tool_messages}
    assert set(by_id) == {"call_a", "call_b"}, tool_messages
    assert by_id["call_b"].strip(), "the model was not told why its call was skipped"
    assert _split(items)[2] == "Tuesday at ten is free.", items


def test_a_failed_tool_is_reported_to_the_model_as_an_error() -> None:
    """The model learns the tool failed, so it can apologise instead of inventing an answer."""
    failure = {AVAILABILITY: (False, "The calendar did not answer in time.")}

    async def anthropic():
        client, _ = _anthropic_tool_turn()
        await _run_tool_turn(client, FakeToolbox(results=failure, log=[]))
        return client.requests[1]["messages"][-1]["content"][0]

    async def chat():
        client = _chat_tool_turn()
        await _run_tool_turn(client, FakeToolbox(results=failure, log=[]))
        return next(
            m for m in client.requests[1]["messages"]
            if _get(m, "role") == "tool" and _get(m, "tool_call_id") == "call_a"
        )

    with _env(**ANTHROPIC_ENV):
        block = asyncio.run(anthropic())
    with _env(**OPENAI_SHAPE_ENV):
        message = asyncio.run(chat())
    assert _get(block, "is_error") is True, block
    assert "did not answer in time" in _text_of(_get(block, "content")), block
    assert "did not answer in time" in _text_of(_get(message, "content")), message


def test_the_end_call_marker_still_ends_the_call_after_a_tool() -> None:
    """"You're booked, goodbye" after a booking tool still hangs up, and the marker is never spoken."""

    async def scenario():
        client = FakeAnthropic(
            [
                Say("Let me book that.", tools=[("toolu_1", AVAILABILITY, {"date": "2026-09-29"})]),
                Say("You're booked for Tuesday at ten. ", "Goodbye! [END", "_CALL]"),
            ]
        )
        llm, items, _log = await _run_tool_turn(client, FakeToolbox(log=[]), "Book Tuesday at ten.")
        return llm, items

    with _env(**ANTHROPIC_ENV):
        llm, items = asyncio.run(scenario())
    texts = [i for i in items if isinstance(i, str)]
    assert not any("[" in t or "END_CALL" in t for t in texts), texts
    assert _split(items)[2] == "You're booked for Tuesday at ten. Goodbye!", items
    assert llm.end_requested is True


# ---------------------------------------------------------------------------
# Rounds
# ---------------------------------------------------------------------------


def _anthropic_that_always_wants_tools(tool_turns: int):
    def script(request: dict, number: int) -> Say:
        if not _withheld(request) and number <= tool_turns:
            lead = ("Let me check.",) if number == 1 else ()
            return Say(*lead, tools=[(f"toolu_{number}", AVAILABILITY, {"date": "2026-09-29"})])
        return Say("Sorry, I can't check that right now.")

    return script


def _chat_that_always_wants_tools(tool_turns: int):
    def script(request: dict, number: int) -> Reply:
        if not _withheld(request) and number <= tool_turns:
            lead = ("Let me check.",) if number == 1 else ()
            return Reply(*lead, tool_calls=[(f"call_{number}", AVAILABILITY, '{"date": "2026-09-29"}')])
        return Reply("Sorry, I can't check that right now.")

    return script


def _capped_rounds(client):
    async def scenario():
        box = FakeToolbox(log=[])
        llm, items, _log = await _run_tool_turn(client, box)
        first_turn = len(client.requests)
        llm.record(_said("assistant", " ".join(i for i in items if isinstance(i, str))))
        llm.record(_said("user", "Okay, try again then."))
        await _turn(llm)
        return items, box, first_turn

    return scenario


def test_anthropic_tool_rounds_are_capped_and_the_model_must_answer() -> None:
    """A model stuck calling tools is stopped after three rounds and has to say something."""
    client = FakeAnthropic(_anthropic_that_always_wants_tools(tool_turns=4))
    with _env(**ANTHROPIC_ENV):
        items, box, first_turn = asyncio.run(_capped_rounds(client)())

    _before, pauses, after = _split(items)
    assert len(pauses) == 3, f"{len(pauses)} tool rounds in one turn"
    assert len(box.calls) == 3, box.calls
    assert first_turn == 4, f"{first_turn} model requests for one turn; expected 3 tool rounds + 1 answer"
    assert _withheld(client.requests[3]), "tools were still offered after MAX_TOOL_ROUNDS"
    assert "Sorry, I can't check that right now." in after, items
    assert not _withheld(client.requests[4]), "the next turn did not get its tools back"


def test_chat_completions_tool_rounds_are_capped_and_the_model_must_answer() -> None:
    client = FakeChat(_chat_that_always_wants_tools(tool_turns=4))
    with _env(**OPENAI_SHAPE_ENV):
        items, box, first_turn = asyncio.run(_capped_rounds(client)())

    _before, pauses, after = _split(items)
    assert len(pauses) == 3, f"{len(pauses)} tool rounds in one turn"
    assert len(box.calls) == 3, box.calls
    assert first_turn == 4, f"{first_turn} model requests for one turn; expected 3 tool rounds + 1 answer"
    assert _withheld(client.requests[3]), "tools were still offered after MAX_TOOL_ROUNDS"
    assert "Sorry, I can't check that right now." in after, items
    assert not _withheld(client.requests[4]), "the next turn did not get its tools back"


# ---------------------------------------------------------------------------
# Later turns remember what tools returned
# ---------------------------------------------------------------------------


def _blocks(message) -> list:
    content = _get(message, "content")
    return list(content) if isinstance(content, (list, tuple)) else []


def test_later_anthropic_turns_still_see_what_the_tool_returned() -> None:
    """Asked "book it" a turn later, the model still knows which slots were free."""

    async def scenario():
        client, _ = _anthropic_tool_turn()
        client._script.append(Say("Done, you're booked."))
        llm, items, _log = await _run_tool_turn(client, FakeToolbox(log=[]))
        llm.record(_said("assistant", " ".join(i for i in items if isinstance(i, str))))
        llm.record(_said("user", "Great, book ten o'clock."))
        later = await _turn(llm)
        return client.requests, later

    with _env(**ANTHROPIC_ENV):
        requests, later = asyncio.run(scenario())

    assert later == ["Done, you're booked."], later
    messages = requests[2]["messages"]
    uses = [
        i for i, m in enumerate(messages)
        if m["role"] == "assistant" and any(_get(b, "type") == "tool_use" and _get(b, "id") == "toolu_1" for b in _blocks(m))
    ]
    results = [
        i for i, m in enumerate(messages)
        if m["role"] == "user" and any(
            _get(b, "type") == "tool_result" and _get(b, "tool_use_id") == "toolu_1" for b in _blocks(m)
        )
    ]
    assert uses and results and uses[0] < results[0] < len(messages) - 1, messages
    assert messages[-1]["role"] == "user", messages[-1]
    assert "Great, book ten o'clock." in _text_of(messages[-1]["content"]), messages[-1]
    assert messages[0]["role"] == "user" and "Is Tuesday free?" in _text_of(messages[0]["content"]), messages[0]


def test_later_chat_completions_turns_still_see_what_the_tool_returned() -> None:
    async def scenario():
        client = _chat_tool_turn()
        client._script.append(Reply("Done, you're booked."))
        llm, items, _log = await _run_tool_turn(client, FakeToolbox(log=[]))
        llm.record(_said("assistant", " ".join(i for i in items if isinstance(i, str))))
        llm.record(_said("user", "Great, book ten o'clock."))
        later = await _turn(llm)
        return client.requests, later

    with _env(**OPENAI_SHAPE_ENV):
        requests, later = asyncio.run(scenario())

    assert later == ["Done, you're booked."], later
    messages = requests[2]["messages"]
    calls = [i for i, m in enumerate(messages) if _get(m, "role") == "assistant" and _get(m, "tool_calls")]
    tools = [i for i, m in enumerate(messages) if _get(m, "role") == "tool" and _get(m, "tool_call_id") == "call_a"]
    assert calls and tools and calls[0] < tools[0] < len(messages) - 1, messages
    assert RESULTS[AVAILABILITY] in _text_of(_get(messages[tools[0]], "content")), messages[tools[0]]
    assert messages[-1]["role"] == "user", messages[-1]
    assert "Great, book ten o'clock." in _text_of(messages[-1]["content"]), messages[-1]


# ---------------------------------------------------------------------------


def _run_all() -> int:
    # Failure messages can hold Devanagari; a cp1252 console must not crash the run.
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
