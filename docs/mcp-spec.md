# Samvaad — MCP Integrations (round 2 spec)

Owner: lead (main session). The contract DEV-AGENT, TEST-AGENT and
UI-UX-AGENT build against in parallel. Names in `code` are exact — TEST-AGENT
writes tests against them before the implementation exists. If something here
is wrong or impossible, stop and report it under NEEDS; don't improvise a
different contract. Base commit: `993a3d8` (Samvaad v2, see docs/v2-spec.md).

## 0. What we're building

Samvaad becomes an **MCP client**. The user connects their own applications
(CRM, calendar, helpdesk, database, Zapier, Composio…) by adding their **MCP
servers** under Integrations. Per campaign they choose which tools the agent
may use:
- **in the call** — look things up and take actions while talking ("let me
  check tomorrow's slots…"), and
- **after the call** — write the outcome back into their systems, guided by
  a plain-language instruction.

Principles: a tool must never cost the caller dead air (say "let me check"
first, warm connections before the call connects); a broken tool must never
break a call; every tool call is visible live and saved on the call record;
secrets (server URLs and headers) never leave the server after they're
entered; nothing reaches private network addresses unless explicitly allowed.

MCP SDK: `mcp>=2.2,<2.3` (v2 API — high-level `from mcp import Client`;
`Client(server_or_transport)` is an async context manager with
`list_tools()` → `.tools[i].name/.description/.input_schema` and
`call_tool(name, args)` → `CallToolResult(.is_error, .content[i].text)`;
servers via `from mcp.server.mcpserver import MCPServer` and `@server.tool()`;
remote transports via `mcp.client.streamable_http.streamable_http_client(url,
http_client=create_mcp_http_client(headers=...))` and
`mcp.client.sse.sse_client(url, headers=...)`). Field names are snake_case.

## 1. Backend — DEV-AGENT (scope: `src/voiceagent/**`)

### 1.1 Data model (`storage.py`, additive only; Postgres-safe defaults)
- New table `mcp_servers` (ORM `McpServer`): `id` String(36) PK, `name`
  String(100), `slug` String(32) unique (lowercase `[a-z0-9_]`, derived from
  name, de-duplicated with a numeric suffix), `transport` String(24)
  (`"streamable_http" | "sse" | "builtin"`), `host` String(255) (display
  only), `secrets` Text (the URL and headers, sealed — §1.4), `enabled`
  Boolean default TRUE, `status` String(16) (`"ok" | "error" | "unchecked"`),
  `last_error` Text nullable, `tools` JSON (discovered: list of `{name,
  description, input_schema}`), `checked_at` DateTime nullable, `created_at`.
- `Campaign`: `mcp_tools` JSON (list of tool ids allowed in the call),
  `mcp_post_call_tools` JSON (tool ids allowed after the call),
  `mcp_post_call_instructions` Text default `""`. Readers treat null as `[]`.
- `Call`: `tool_calls` JSON nullable — the log, list of
  `{at, phase: "in_call"|"post_call", server, tool, arguments, ok,
  duration_ms, excerpt, error}` (`excerpt` = first 300 chars of the result).

**Tool id** = `f"{server.slug}__{tool.name}"`, truncated/sanitised to match
`^[a-zA-Z0-9_-]{1,64}$` (both Anthropic and OpenAI require this).

### 1.2 MCP layer — new package `src/voiceagent/mcp/`
- `mcp/guard.py`: `check_url(url: str) -> None` raises `UnsafeUrl(ValueError)`
  unless: scheme is `https` (or `http` when private hosts are allowed); host
  resolves only to public addresses (reject loopback, private, link-local,
  multicast, reserved, unspecified — IPv4 and IPv6 — via `ipaddress`).
  `MCP_ALLOW_PRIVATE_HOSTS=true` (read at call time) lifts both rules for
  local development. `builtin://…` URLs are always allowed.
- `mcp/secrets.py`: `seal(data: dict) -> str`, `unseal(text: str) -> dict`,
  `sealing_enabled() -> bool`. Fernet (`cryptography`) with a key derived by
  SHA-256 from `SECRETS_KEY`, else `AUTH_SECRET`; if neither is set, store as
  `"plain:" + base64(json)` and `sealing_enabled()` is False. `unseal` of a
  token it can't decrypt raises `SecretsUnavailable` (surfaced as server
  status `error`, "Re-enter this server's URL and credentials").
- `mcp/demo_server.py`: `demo_server() -> MCPServer` — a built-in "Demo CRM"
  (`builtin://demo`, in-process, no network) with deterministic fake data:
  `lookup_customer(phone: str)`, `check_availability(date: str)` (YYYY-MM-DD →
  free slots), `book_appointment(name: str, date: str, time: str)`,
  `create_ticket(summary: str, priority: str = "normal")`. Lets anyone try
  tools end to end with no external account.
- `mcp/client.py`:
  - `async def discover(server: McpServer) -> list[dict]` — connect, list
    tools, return `[{name, description, input_schema}]`; raises
    `McpUnavailable` with a readable message on failure (auth rejected,
    unreachable, timeout, not an MCP endpoint). Connect timeout
    `MCP_CONNECT_TIMEOUT_SECONDS` (default 10).
  - Transport `"auto"` on create: try streamable HTTP, fall back to SSE; store
    the one that worked.
- `mcp/toolbox.py`:
  ```python
  @dataclass(frozen=True)
  class ToolSpec:  id: str; description: str; input_schema: dict
  @dataclass(frozen=True)
  class ToolResult: ok: bool; text: str

  class Toolbox(Protocol):
      def specs(self) -> list[ToolSpec]: ...
      async def call(self, tool_id: str, arguments: dict) -> ToolResult: ...

  class CallToolbox:            # implements Toolbox for one call
      @classmethod
      async def for_tool_ids(cls, session_factory, tool_ids: list[str],
                             *, phase: str, on_event=None) -> "CallToolbox"
      async def warm(self) -> None      # connect to every needed server now
      def specs(self) -> list[ToolSpec]
      async def call(self, tool_id, arguments) -> ToolResult
      async def aclose(self) -> None
  ```
  - Only enabled servers with status ok; unknown/removed tool ids are skipped.
  - One MCP session per server per call, opened lazily (or by `warm()`),
    reused for the whole call, closed by `aclose()`.
  - `call()` never raises: timeout (`MCP_TOOL_TIMEOUT_SECONDS`, default 8),
    MCP errors, `is_error` results and exceptions all become
    `ToolResult(ok=False, text=<short reason>)`. Result text is the joined
    text content, truncated to 4000 chars.
  - `on_event(dict)` (async, optional) is awaited with
    `{"phase", "server", "tool", "status": "started"|"ok"|"error",
    "arguments", "duration_ms", "excerpt", "error"}` — exceptions from it are
    swallowed.

### 1.3 Tools in the conversation (`llm.py`, `voice/session.py`, Twilio)
- `ConversationLLM(..., toolbox: Toolbox | None = None)`. With a toolbox
  whose `specs()` is non-empty **and** a provider that supports tools
  (`ProviderSpec.supports_tools`; True for anthropic, openai, gemini; False for
  sarvam, nvidia), tools are offered to the model; otherwise the call runs
  exactly as today.
- `@dataclass(frozen=True) class ToolPause: tools: tuple[str, ...]` in
  `llm.py`. `generate()` now yields `str | ToolPause`: text chunks as before;
  when the model stops to call tools, it yields one `ToolPause` (ids about to
  run) **before** executing them, then runs them via the toolbox, feeds the
  results back, and continues streaming the model's continuation — up to
  `MAX_TOOL_ROUNDS = 3` rounds per turn (after that, tools are withheld and
  the model must answer). `END_CALL_MARKER` handling is unchanged.
- History: tool exchanges stay in the model's history in the provider's
  native shape so later turns see what tools returned. The transcript
  (`Turn`s) holds speech only; barge-in truncation still applies to the
  spoken text.
  - Anthropic: consume `client.messages.stream(**kwargs)` as an async context
    manager; iterate `stream.text_stream`; then `final = await
    stream.get_final_message()`; if `final.stop_reason == "tool_use"`, the
    assistant message is `final.content` passed back **unchanged** (including
    `thinking` / `redacted_thinking` blocks — required with thinking on),
    followed by a user message of `tool_result` blocks (`tool_use_id`,
    `content`, `is_error`). Tool definitions: `{"name", "description",
    "input_schema"}`.
  - chat/completions: `tools=[{"type": "function", "function": {"name",
    "description", "parameters"}}]`; accumulate streamed
    `choices[0].delta.tool_calls` fragments by `index` (`id`,
    `function.name`, `function.arguments` concatenated); on
    `finish_reason == "tool_calls"` append the assistant message with
    `tool_calls` and one `{"role": "tool", "tool_call_id", "content"}` per
    call. Unparseable arguments → call skipped, error result fed back.
- Prompt: when tools are offered, the per-call context block (not the cached
  persona) gains a short "Tools" section: say a brief natural line ("let me
  check that") before using one; summarise results in plain speech, never
  read IDs or raw data aloud; if a tool fails, apologise briefly and offer a
  follow-up; never invent a result.
- `CallPhrases.checking` (new field): en "One moment, let me check that.", hi
  "एक सेकंड, ज़रा देख लेते हैं।", ur "एक लम्हा, ज़रा देख लेते हैं।", hi-en
  "Ek second, check kar lete hain."
- `CallSession` on a `ToolPause`: emits `on_event("state", {"state":
  "working", "tools": [...]})`; if the speaker has `flush_interim()`, awaits
  it; streaming speakers need nothing. Text spoken before and after the pause
  is recorded as one agent turn. `latency_ms` is measured to the first audio,
  which may now be the interim.
- `TwilioSpeaker.flush_interim()`: queues the buffered segments — or
  `phrases.checking` if nothing was said yet this turn — as a `_Reply` with
  `interim=True`, rendered as the audio followed by `<Redirect>` to
  `/twilio/wait/{room}` (no `<Gather>`); the final reply arrives on that
  wait. Uses the call's phrases (from `prepare_call`'s language).
- Pipeline, async test call and simulations (`simulate.py`) build a
  `CallToolbox` from the campaign's `mcp_tools` (phase `"in_call"`), call
  `warm()` before/while dialling, pass it to `ConversationLLM`, and
  `aclose()` it when the call ends. Its `on_event` feeds the call's live feed:
  append to `Call.tool_calls` (saved with the transcript) and publish
  `call.tool` events (payload = the event dict + `call_id`). Add constant
  `CALL_TOOL = "call.tool"` to `orchestrator/events.py`.

### 1.4 After the call — `postcall/mcp_actions.py`
`async def run_post_call_actions(client, *, model, effort, campaign, contact,
outcome, toolbox, usage) -> list[dict]` — only when the campaign has
`mcp_post_call_tools`, the outcome does **not** need human review, and the
disposition is not `no_answer`, `voicemail`, `wrong_number` or `failed`.
Runs a non-streaming tool loop on the extraction model (max 5 tool calls,
same provider shapes as §1.3) with the outcome JSON, the contact and the
campaign's `mcp_post_call_instructions`, under a system prompt that says:
record the outcome using only clearly warranted tools, never invent data, and
call nothing if nothing applies. Returns the phase `"post_call"` log entries,
which are appended to `Call.tool_calls` and summarised in
`dispatch_result["mcp_actions"]`. Held for review → skipped, with
`dispatch_result["mcp_actions_skipped"] = "held for review"`. Never raises.

### 1.5 API (`api/app.py`, `api/schemas.py`)
- `GET /api/mcp/servers` → list of `McpServerOut {id, name, slug, transport,
  host, header_names: [str], enabled, status, last_error, checked_at,
  tools: [{id, name, description, input_schema}]}`. The URL and header values
  are never returned.
- `POST /api/mcp/servers` `{name, url, transport: "auto"|"streamable_http"|
  "sse" = "auto", headers: {str: str} = {}}` → `check_url` (400 on unsafe),
  seal, save, run discovery immediately; 201 with the server (status `ok`, or
  `error` + `last_error` — still saved so the user can fix it). `url =
  "builtin://demo"` adds the Demo CRM.
- `PATCH /api/mcp/servers/{id}` `{name?, url?, headers?, enabled?}` — `headers`
  replaces all headers when present; omitted keeps them. Re-discovers when the
  URL or headers change.
- `DELETE /api/mcp/servers/{id}` → 204; also removes its tool ids from every
  campaign's `mcp_tools` / `mcp_post_call_tools`.
- `POST /api/mcp/servers/{id}/refresh` → re-discover; returns the server.
- `POST /api/mcp/servers/{id}/tools/{name}/test` `{arguments: {}}` → `{ok,
  text, duration_ms}` (runs the tool once; for the "Try it" panel).
- `GET /api/mcp/tools` → every tool of enabled, healthy servers: `[{id,
  server_id, server_name, name, description, input_schema}]`.
- Campaign create/update/out: `mcp_tools`, `mcp_post_call_tools`,
  `mcp_post_call_instructions`. Unknown tool ids → 400.
- `CallDetail.tool_calls: list[dict]` (empty list when none).
- `/api/health` adds `mcp_servers` (count enabled), `provider_supports_tools`
  (bool) and `secrets_sealed` (bool = `sealing_enabled()`).
- All behind the existing opt-in auth like every `/api/*` route.

### 1.6 Done criteria (DEV)
All existing 145 tests + TEST-AGENT's new tests pass; `python -m compileall -q
src` clean; nothing outside `src/voiceagent/**` touched. New env vars listed
in the final report (lead documents them). `mcp` and `cryptography` are
already installed locally (lead adds them to requirements.txt).

## 2. Tests — TEST-AGENT (scope: `tests/**`)

Write the tests for §1 **first** (Red). New files only: `tests/test_mcp_core.py`
(guard, secrets, demo server, discovery, toolbox), `tests/test_mcp_llm.py`
(tool loop on both provider shapes with fake streaming clients, `ToolPause`,
history shape incl. thinking blocks passed back unchanged, max rounds,
provider without tool support), `tests/test_mcp_call.py` (session + Twilio
interim reply, tool log + `call.tool` events, post-call actions), and
`tests/test_mcp_api.py` (endpoints, secrets never returned, SSRF 400,
campaign tool ids, delete cleanup, health flags). Same conventions as
round 1 (standalone `_run_all()` with `sys.stdout.reconfigure(errors=
"backslashreplace")`, pytest-compatible, no network, no real keys, temp SQLite
via `dependency_overrides[get_session]` + monkeypatched
`storage.SessionLocal`, pin `twilio_adapter.VOICE_PROVIDER`, env set/restored
inside tests). Use the real in-process `demo_server()` through `builtin://demo`
for MCP round trips — no network. For `check_url`, monkeypatch DNS resolution
(`socket.getaddrinfo`) rather than resolving real hosts.
Report the Red results and the seams the implementation must provide.

## 3. Frontend — UI-UX-AGENT (scope: `frontend/**`)

Build on the round-1 design system (components in `components/ui.tsx`,
`overlay.tsx`, `toast.tsx`; `AgentAvatar`; pages under `src/pages`). Verify
with `npx tsc --noEmit -p tsconfig.json` and `npx vite build --outDir <temp
dir outside the repo>` (run `npm ci` in `frontend/` first; never `tsc -b`).

1. **Integrations → "Connected apps (MCP)"** — the headline of this round:
   - Server cards: name, host, status (ok / error with the message / checking),
     tool count, last checked, enable toggle, Refresh, Edit, Remove (confirm).
   - "Connect an app" dialog: a preset grid (**Demo CRM — built in, one
     click**; Zapier MCP; Composio; "Any MCP server") with a line on where to
     find each URL, then name, URL (password-style input with reveal), transport
     (Auto / Streamable HTTP / SSE, under "Advanced"), header rows (key +
     masked value; e.g. `Authorization: Bearer …`), and "Connect & discover"
     showing progress, the discovered tools on success, or the error with a
     hint (401 → check the key; unreachable → check the URL; unsafe URL → why).
   - Tools list per server with descriptions; a **"Try it"** drawer that builds
     a form from `input_schema` (string / number / integer / boolean / enum
     fields; raw JSON fallback for anything else), runs
     `POST …/tools/{name}/test`, shows the result and time.
   - Banners: provider without tool support (`provider_supports_tools` false);
     secrets stored unsealed (`secrets_sealed` false → "set SECRETS_KEY").
2. **Campaign → "Tools" card** (campaign detail + new-campaign form): tools
   grouped by server with descriptions; two sections — "During the call" and
   "After the call" (+ instructions textarea with an example); a one-line
   explanation of each; empty state linking to Integrations; save via PATCH.
3. **Live console:** `call.tool` events render inline in the transcript as
   compact activity rows ("Checking availability… → ✓ 1.2 s" / "✕ failed:
   reason"), the avatar shows `thinking` while `state === "working"`, and the
   stepper/labels say "Using a tool".
4. **Call detail (Calls page):** a "Tools used" section from `tool_calls` —
   in-call and after-call, tool, server, arguments (collapsible JSON), result
   excerpt, duration, ok/error.
5. **Overview onboarding:** add "Connect an app (MCP)" to the checklist.
6. Types in `api.ts` for everything in §1.5; keep all existing behaviour.

## 4. Not in this round
OAuth-based MCP servers (hosted servers that need an OAuth login rather than a
key/header) · stdio (local-process) servers · re-running post-call actions
when a reviewer approves a held call · per-tool argument policies/approvals ·
MCP resources and prompts.
