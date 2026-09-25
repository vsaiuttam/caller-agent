"""After the call: writing the outcome back into the user's own apps.

`actions.dispatch` is deliberately a dispatch table, because it knows its
targets. This cannot be: what "record the outcome" means depends on which
apps the user connected and on an instruction they wrote in plain words —
"open a ticket for every complaint", "add a note to the deal". So a model
decides, on the extraction model and under tight rules: only the campaign's
after-call tools, only what the outcome clearly warrants, nothing invented,
at most MAX_TOOL_CALLS calls.

And never on a call a human still has to check — the same gate dispatch
applies to calendar and record writes — or on one that reached nobody.
Nothing here raises: a failure after the call must never lose the call.
"""

from __future__ import annotations

import logging
import time
from typing import Any

from ..catalog import EXTRACTION, TokenUsage, resolve, resolve_effort
from ..llm import (
    ToolCall,
    anthropic_tool_call,
    anthropic_tool_results,
    anthropic_tools,
    chat_assistant_message,
    chat_call,
    chat_tool_results,
    chat_tools,
    parse_chat_call,
)
from ..mcp.ids import SEPARATOR
from ..mcp.toolbox import EXCERPT_CHARS, CallToolbox, Toolbox, ToolLog, ToolResult
from ..models import CallOutcome, Contact, Disposition
from ..providers import ANTHROPIC_API, active

logger = logging.getLogger(__name__)

# Writes into someone's CRM, per call. A model still calling tools after five
# is looping, and every extra call is another record somebody has to delete.
MAX_TOOL_CALLS = 5
MAX_TOKENS = 4096

HELD_FOR_REVIEW = "held for review"

# Calls where nobody was reached, or the call itself broke: there is nothing
# true to write back. A "no thanks" is different — that is an outcome.
_NOTHING_TO_RECORD = frozenset(
    {Disposition.NO_ANSWER, Disposition.VOICEMAIL, Disposition.WRONG_NUMBER, Disposition.FAILED}
)

SYSTEM = """\
You record the result of a phone call in the business's own systems, using \
the tools you are given. The call is over; nobody is waiting on you.

Rules:
- Follow the campaign owner's instructions.
- Use a tool only when the call's outcome clearly calls for it. If nothing \
applies, call no tools at all.
- Never invent data. Use only what is in the outcome and the contact details \
below; if a tool needs something they don't say, skip that action.
- Do each action once. Do not retry an action that succeeded.
- When you are done, reply with one short sentence saying what you recorded.\
"""


def _wants_actions(campaign, outcome: CallOutcome) -> bool:
    return (
        bool(getattr(campaign, "mcp_post_call_tools", None))
        and not outcome.needs_human_review
        and outcome.disposition not in _NOTHING_TO_RECORD
    )


async def run_post_call_actions(
    client,
    *,
    model: str | None,
    effort: str | None,
    campaign,
    contact: Contact,
    outcome: CallOutcome,
    toolbox: Toolbox,
    usage: TokenUsage,
) -> list[dict[str, Any]]:
    """Record `outcome` with the campaign's after-call tools. Returns the tool log.

    Entries have phase "post_call", in `Call.tool_calls`' shape. Empty when
    the call does not qualify or nothing applied. Never raises.
    """
    if not _wants_actions(campaign, outcome) or not toolbox.specs():
        return []
    spec = active()
    if spec is not None and not spec.supports_tools:
        logger.info("Post-call actions skipped: %s cannot call tools", spec.label)
        return []

    actions = _Actions(toolbox)
    run = _anthropic_loop if spec is None or spec.api == ANTHROPIC_API else _chat_loop
    try:
        await run(
            client,
            resolve(model, EXTRACTION),
            resolve_effort(effort, EXTRACTION),
            _brief(campaign, contact, outcome),
            actions,
            usage,
        )
    except Exception:  # noqa: BLE001 - the call's outcome is already saved; keep it that way
        logger.exception("Post-call actions failed for contact %s", contact.contact_id)
    return actions.log.entries


async def run_for_call(
    client,
    session_factory,
    *,
    model: str | None,
    effort: str | None,
    campaign,
    contact: Contact,
    outcome: CallOutcome,
    usage: TokenUsage,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    """Post-call actions for a finished call, with their own toolbox.

    Returns (tool log entries, keys to add to the call's `dispatch_result`):
    a summary under `mcp_actions` when they ran, or `mcp_actions_skipped`
    when the call was held for review — so a reviewer can see that nothing
    was written back, and why.
    """
    if not getattr(campaign, "mcp_post_call_tools", None):
        return [], {}
    if outcome.needs_human_review:
        return [], {"mcp_actions_skipped": HELD_FOR_REVIEW}
    if outcome.disposition in _NOTHING_TO_RECORD:
        return [], {}

    toolbox = await CallToolbox.for_tool_ids(
        session_factory, campaign.mcp_post_call_tools, phase="post_call"
    )
    try:
        entries = await run_post_call_actions(
            client,
            model=model,
            effort=effort,
            campaign=campaign,
            contact=contact,
            outcome=outcome,
            toolbox=toolbox,
            usage=usage,
        )
    finally:
        await toolbox.aclose()
    summary = [
        {"server": e["server"], "tool": e["tool"], "ok": e["ok"], "error": e["error"]} for e in entries
    ]
    return entries, {"mcp_actions": summary}


class _Actions:
    """Runs the model's tool calls within the budget, and logs each one."""

    def __init__(self, toolbox: Toolbox) -> None:
        self._toolbox = toolbox
        self.left = MAX_TOOL_CALLS
        self.log = ToolLog()

    def specs(self):
        return self._toolbox.specs()

    async def run(self, call: ToolCall) -> ToolResult:
        if call.problem is not None:
            return ToolResult(ok=False, text=call.problem)
        if self.left <= 0:
            return ToolResult(ok=False, text=f"Not run: the limit of {MAX_TOOL_CALLS} actions was reached.")
        self.left -= 1

        started = time.perf_counter()
        try:
            result = await self._toolbox.call(call.tool, call.arguments)
        except Exception:  # noqa: BLE001 - Toolbox promises not to raise; hold it to that
            logger.exception("Post-call tool %s raised", call.tool)
            result = ToolResult(ok=False, text="The tool failed unexpectedly.")

        server, tool = self._names(call.tool)
        self.log.add(
            {
                "phase": "post_call",
                "server": server,
                "tool": tool,
                "status": "ok" if result.ok else "error",
                "arguments": call.arguments,
                "duration_ms": int((time.perf_counter() - started) * 1000),
                "excerpt": result.text[:EXCERPT_CHARS],
                "error": None if result.ok else result.text[:EXCERPT_CHARS],
            }
        )
        return result

    def _names(self, tool_id: str) -> tuple[str, str]:
        """(server, tool) for the log: the toolbox's names, else read off the id."""
        label = getattr(self._toolbox, "label", None)
        names = label(tool_id) if label else None
        if names:
            return names
        server, _, tool = tool_id.partition(SEPARATOR)
        return (server, tool) if tool else ("", tool_id)


async def _anthropic_loop(client, model, effort, brief, actions: _Actions, usage) -> None:
    tools = anthropic_tools(actions.specs())
    messages: list[dict[str, Any]] = [{"role": "user", "content": brief}]
    # Bounded by requests as well as calls: a model sending arguments that
    # never parse uses no budget, and would otherwise go round forever.
    for request_number in range(MAX_TOOL_CALLS + 1):
        allowed = actions.left > 0 and request_number < MAX_TOOL_CALLS
        kwargs: dict[str, Any] = dict(
            model=model,
            max_tokens=MAX_TOKENS,
            thinking={"type": "adaptive"},
            output_config={"effort": effort},
            system=SYSTEM,
            messages=messages,
            tools=tools,
        )
        if not allowed:
            kwargs["tool_choice"] = {"type": "none"}
        response = await client.messages.create(**kwargs)
        usage.add_response_usage(model, getattr(response, "usage", None))

        if not allowed or getattr(response, "stop_reason", None) != "tool_use":
            return
        calls = [anthropic_tool_call(b) for b in response.content if getattr(b, "type", None) == "tool_use"]
        results = [await actions.run(call) for call in calls]
        # The model's content goes back unchanged, thinking blocks included.
        messages += [
            {"role": "assistant", "content": response.content},
            anthropic_tool_results(calls, results),
        ]


async def _chat_loop(client, model, effort, brief, actions: _Actions, usage) -> None:
    tools = chat_tools(actions.specs())
    messages: list[dict[str, Any]] = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": brief},
    ]
    # Bounded by requests as well as calls: a model sending arguments that
    # never parse uses no budget, and would otherwise go round forever.
    for request_number in range(MAX_TOOL_CALLS + 1):
        allowed = actions.left > 0 and request_number < MAX_TOOL_CALLS
        kwargs: dict[str, Any] = dict(
            model=model, max_tokens=MAX_TOKENS, reasoning_effort=effort, messages=messages, tools=tools
        )
        if not allowed:
            kwargs["tool_choice"] = "none"
        response = await client.chat.completions.create(**kwargs)
        usage.add_response_usage(model, getattr(response, "usage", None))

        message = response.choices[0].message
        raw = [chat_call(tool_call) for tool_call in getattr(message, "tool_calls", None) or []]
        if not allowed or not raw:
            return
        calls = [parse_chat_call(call) for call in raw]
        results = [await actions.run(call) for call in calls]
        messages += [
            chat_assistant_message(getattr(message, "content", None) or "", raw),
            *chat_tool_results(calls, results),
        ]


def _brief(campaign, contact: Contact, outcome: CallOutcome) -> str:
    instructions = (getattr(campaign, "mcp_post_call_instructions", "") or "").strip()
    attributes = "\n".join(f"  {k}: {v}" for k, v in sorted((contact.attributes or {}).items()))
    return f"""\
Campaign: {campaign.name}
What the call was for: {campaign.goal}

The campaign owner's instructions for after the call:
{instructions or "None given. Record the outcome where it clearly belongs, or do nothing."}

Who was called:
  Name: {contact.full_name}
  Phone: {contact.phone_e164}
  Timezone: {contact.timezone}
{attributes or "  (nothing else on file)"}

What happened on the call, as extracted from the transcript:
{outcome.model_dump_json(indent=2)}\
"""
