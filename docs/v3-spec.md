# Samvaad v3: from a calling tool to a voice-agent product

Status: approved for build (lead decision; the owner delegated product calls).
Owner asks this release answers, in their words:

- "add any LLM API, not fixed to Gemini"; "API and model selection in the
  campaign itself"; "show me how much a model costs if I use it"
- "the Models page is not relevant, revamp it"
- "Calls and Review queue are duplicates"
- "no campaign I created is calling" (fixed in 511e13f; this release shows
  *why* a campaign isn't dialling right now)
- "selecting an MCP tool in a campaign sends me to Settings, and coming back
  the campaign isn't saved"
- "a chatbot where users can ask questions about this"
- "more languages like Telugu"; "only one Sarvam voice, I need voice selection"
- "message the person before the campaign calls them"
- "human handoff: later, keep it on the TODO list"
- "it feels bland; industry standard; streamlined UX"

Team roles and file scopes are as in v2: DEV `src/voiceagent/**`, TEST
`tests/**`, UI `frontend/**`. The contracts below are the interface between
them. Where this spec is silent, follow the existing code's conventions.

---

## 1. Model providers: bring any LLM (DEV + UI)

Today there is one provider per deployment, chosen by env var, and campaigns
pick a model name but not a provider. v3 makes providers a workspace resource
managed in the app.

### 1.1 Data

New table `llm_providers`:

| column | type | notes |
|---|---|---|
| id | str(36) pk | uuid |
| kind | str(32) | a preset id (below) or `openai_compatible` |
| label | str(80) | display name, defaults to the preset label |
| base_url | str(500) null | required for `openai_compatible`, `azure_openai`; optional override for others |
| secret | text | `mcp.secrets.seal({"api_key": ...})`; never returned by the API |
| enabled | bool default TRUE | |
| created_at, updated_at | datetime tz | |

Presets (`kind`): `openai`, `anthropic`, `gemini`, `sarvam`, `groq`,
`openrouter`, `deepseek`, `mistral`, `together`, `fireworks`, `xai`,
`nvidia`, `azure_openai`, `openai_compatible` (Ollama, vLLM, LM Studio, any
other OpenAI-shaped endpoint). Each preset has a label, default base_url, key
hint URL, `supports_tools`, and an API shape: `anthropic` or `openai`. Only
those two shapes exist, the same as `providers.py` today. Extend that module
rather than replacing it.

Environment keys keep working. A provider configured by env var appears in
the list as a read-only row with `source: "env"` and id `env:<preset>`. A
database row of the same kind takes precedence. Nothing existing breaks when
no rows exist.

Workspace defaults live in the `settings` table under key
`model_defaults`: `{"conversation": {"provider_id", "model"}, "extraction":
{"provider_id", "model"}}`. When unset they fall back to today's behaviour:
the active env provider and its catalog defaults.

Campaign gets two nullable columns: `conversation_provider_id` and
`extraction_provider_id`, each str(64). Null means the workspace default. The
existing `conversation_model` and `extraction_model` stay. Additive migration
only.

### 1.2 Models and prices

`catalog.py` keeps the priced model list and gains entries for the new
presets' popular models. Use the prices and dates the researcher records in
`docs/research.md` §6, and keep `PRICING_AS_OF`. For models that aren't in
the catalog (custom ids, Ollama, OpenRouter's long tail), a provider row may
carry `custom_models: [{id, name, input_per_mtok, output_per_mtok}]`, stored
in the row as JSON and entered by the user. Unknown prices are allowed; they
show as "price not set" and cost reads as unknown, never $0.

### 1.3 Runtime

The pipeline gets a model client per campaign, not one global client.
`providers.client_for(provider_id | None)` returns a cached client, cached by
provider id and invalidated when the row changes. `resolve()` validates a
model against the chosen provider. A campaign whose provider was deleted or
disabled falls back to the workspace default and logs a warning; the call
doesn't fail.

### 1.4 API

```
GET    /api/providers            -> [{id, kind, label, base_url, source: "db"|"env",
                                      enabled, supports_tools, api_shape, key_hint (last 4),
                                      status: "ok"|"untested"|"error", last_error, models_count}]
GET    /api/providers/presets    -> [{kind, label, default_base_url, needs_base_url,
                                      key_url, supports_tools, api_shape, popular_models: [...]}]
POST   /api/providers            {kind, label?, base_url?, api_key, custom_models?} -> provider
PATCH  /api/providers/{id}       {label?, base_url?, api_key?, enabled?, custom_models?}
DELETE /api/providers/{id}       -> 204  (409 if it's a workspace default; campaigns fall back)
POST   /api/providers/{id}/test  -> {ok, latency_ms, model, error?}   (one tiny completion)
GET    /api/providers/{id}/models -> [{id, name, input_per_mtok|null, output_per_mtok|null,
                                       speed?, roles, supports_tools, source: "catalog"|"custom"|"discovered"}]
                                   (openai-shaped providers may also list GET {base_url}/models)
GET    /api/model-defaults       -> {conversation: {provider_id, model}, extraction: {...}}
PUT    /api/model-defaults       same shape (owner/admin only)
POST   /api/estimate             {provider_id?, conversation_model?, extraction_model?,
                                  language?, minutes_per_call? (default 3), calls? (default 1000),
                                  telephony_region?: "IN"|"US" (default "IN"),
                                  include_voice?: bool (default true)}
                               -> {per_call: {llm, extraction, stt, tts, telephony, total},
                                   per_minute_total, for_calls: {calls, total},
                                   assumptions: [str], pricing_as_of, unknown: [component]}
```

Only owners and admins may create, update or delete providers or defaults;
members may list them. SSRF: an `openai_compatible` base_url goes through the
same guard as MCP URLs, with the same `MCP_ALLOW_PRIVATE_HOSTS` escape hatch
for local Ollama. Keys are never logged or returned.

`GET /api/models` (the current catalog) stays for compatibility.

### 1.5 UI: the "AI models" page replaces "Models"

The nav item stays under Configure and is renamed "AI models".
- **Providers:** cards for connected providers with status dot, key hint,
  tools support and model count, plus Test / Edit / Disable. "Add provider"
  opens a drawer: preset grid with logos drawn as letter marks, not brand
  assets; key field; base URL when needed; custom models editor; and Test
  before Save.
- **Defaults:** conversation and extraction provider plus model.
- **Model browser:** table of every model across connected providers, with
  price in/out per 1M, speed tier, tools support and a "best for" tag.
  Filterable.
- **Cost calculator:** pick provider, model, language, minutes per call,
  number of calls and region. Shows a stacked breakdown (LLM, extraction,
  STT, TTS, telephony) per call, per minute, and for N calls, with the
  assumptions listed. Data from `POST /api/estimate`.

---

## 2. Campaign builder: one flow that never loses work (UI + DEV)

### 2.1 Structure

New and edit use the same builder, a stepper with a sticky summary rail:

1. **Basics:** name, goal, template.
2. **Agent:** language, voice (§4), greeting, instructions, provider and
   model with a live cost chip (§1.4 estimate).
3. **Tools:** MCP tools during and after the call.
4. **Contacts:** upload or paste, with preview.
5. **Schedule & messages:** calling window, days, attempts, concurrency,
   pre-call heads-up (§5), follow-ups, webhook.
6. **Review & launch:** checklist of blockers (no telephony, no provider, no
   contacts, outside window), then Save draft or Launch.

The summary rail shows name, language, voice, model, estimated cost per call
and for the list, and contact count.

### 2.2 Never lose work

- The builder autosaves the in-progress form to localStorage (key per
  campaign id or `new`) on every change, debounced. Returning restores it,
  with a "Restored your unsaved changes" toast and a Discard option.
- **MCP: connect without leaving.** "Connect an app" opens the existing
  connect flow in a drawer or modal over the builder. On success the new
  server's tools appear in the picker immediately. No navigation to
  Settings. The same for "Add provider" in step 2.
- "Save draft" is available on every step and creates the campaign as DRAFT
  server-side.

### 2.3 Campaign detail

Tabs: **Overview** (dialler status, progress, KPIs), **Calls** (this
campaign's calls), **Contacts**, **Settings** (opens the builder at a step).

Dialler status comes from `GET /api/campaigns/{id}/dialer`:

```
{state: "dialing"|"waiting_window"|"paused"|"draft"|"completed"|"blocked"|"asleep_risk",
 reason: str,                     // human sentence: "Outside calling hours — next window Mon 09:00 (Asia/Kolkata)"
 next_window_start: iso|null,
 pending: int, in_progress: int, done: int, failed: int,
 blockers: [str]}                 // e.g. "No telephony configured", "No model provider"
```

The campaign list shows the same state as a pill. This is the answer to
"why isn't it calling".

### 2.4 Dialler robustness (DEV)

On startup, contacts stuck `IN_PROGRESS` with no live call for more than 10
minutes go back to `PENDING`. This happens when a redeploy interrupts a call.
Log how many.

---

## 3. Calls and Review: one place (UI)

- Remove "Review queue" from the nav. Calls gets a view switch: **All** |
  **Needs review (n)** | **Live now (n)**, with a count badge on the nav item
  when reviews are pending.
- `/app/review` redirects to `/app/calls?view=review` and keeps working.
- Live stays its own page (the wallboard) but is linked from the Calls view
  switch.

---

## 4. Voices (DEV + UI)

- Campaign column `voice` str(40), nullable = the default speaker.
- `GET /api/voices?language=te` returns
  `[{id, name, gender, languages: [codes], provider: "sarvam", sample_text}]`,
  every bulbul:v3 speaker the Sarvam API supports. Check current names
  against Sarvam's docs; don't guess.
- `POST /api/voices/preview {voice, language, text?}` returns `audio/wav`
  (cached by voice, language and text; rate-limited per user). It uses the
  deployment's Sarvam key and returns 409 with a message when there's none.
- The TTS path uses `campaign.voice` for the call. Test calls and simulations
  honour it too.
- UI: a voice picker grid with name, gender and a ▶ preview button, filtered
  by the campaign's language.

## 5. Languages (DEV + UI)

Add every language Sarvam STT/TTS supports that we don't have: Telugu `te`,
Tamil `ta`, Kannada `kn`, Malayalam `ml`, Marathi `mr`, Bengali `bn`,
Gujarati `gu`, Punjabi `pa`, Odia `od`, plus English (India) behaviour for
`en`.
- `templates.LANGUAGES`: name, native name, and a spoken-register
  instruction like Hindi's (everyday register, English loanwords kept,
  switch if the person switches).
- `voice/phrases.py`: CallPhrases for each language: fillers, "are you still
  there", goodbye, voicemail line. Native-quality short phrases. Never
  machine-translate at runtime.
- Language code maps to Sarvam `xx-IN` codes for STT and TTS.
- A template greeting missing for a language: the builder offers
  "Translate greeting" through `POST /api/translate {text, to}`, using the
  workspace default model. The result is editable. At call time the greeting
  is never translated; the saved greeting is spoken.

## 6. Pre-call heads-up message (DEV + UI)

Campaign columns: `precall_enabled` bool FALSE, `precall_channel` str(16)
("sms" | "whatsapp"), `precall_message` text, `precall_lead_minutes` int
default 10 (range 2–240).
- When a contact becomes due, the runner sends the heads-up first, records
  `contacts.precall_sent_at` and `precall_status`, and sets
  `next_attempt_at = now + lead`. The call is placed on a later tick. Retries
  don't send another heads-up within 12 hours.
- The template supports `{name}`, `{company}` (campaign name if unset),
  `{minutes}` and `{agent}`. The default wording is short and says who is
  calling and why, with an opt-out line ("Reply STOP to opt out").
- A STOP reply is out of scope. The builder notes Indian DLT template
  registration for SMS and approved templates for WhatsApp.
- Uses the existing `followup` senders. With the channel unconfigured, the
  builder blocks enabling it with a clear reason.

## 7. "Ask Samvaad": in-app help assistant (DEV + UI)

- `POST /api/assistant/chat {messages: [{role, content}], page?: str}`
  streams text/event-stream tokens and ends with
  `{done: true, links: [{label, to}]}`.
- The system prompt is grounded in a product guide the DEV agent writes at
  `src/voiceagent/assistant/guide.md`: what each page does, how to connect
  providers, telephony, MCP, languages, voices, pre-call, costs, and common
  errors. Add a compact read-only workspace snapshot: counts, which services
  are configured, and running campaigns with their dialler states. No
  secrets, no contact PII.
- It answers questions only; it takes no actions. It suggests deep links
  from a fixed allow-list of console routes. It uses the workspace default
  conversation model, capped at 600 output tokens and rate-limited per user.
- UI: a launcher button bottom-right on console pages opens a side panel
  chat with suggested questions for the current page, streaming replies,
  clickable links, copy, and clear. Hidden on the landing and auth pages.

## 8. Post-call extraction reliability (DEV)

Ten of 12 recent calls ended "Extraction call failed" after provider
overload. Now:
- Retry extraction with backoff: 3 attempts over about 20 s on
  overload/rate-limit errors. Then try the workspace extraction default if
  it's a different provider. Only then mark for review.
- `POST /api/calls/{id}/reextract` (owner/admin) re-runs extraction on the
  saved transcript and returns the updated call. The UI shows "Re-run
  extraction" on calls whose extraction failed.

## 9. UX baseline (UI)

The UI agent uses the project design skills (`.claude/skills/`) and
`frontend/DESIGN.md`.
- One page header pattern, one empty-state pattern, one table pattern,
  skeletons everywhere data loads.
- Navigation: Overview · Campaigns · Calls · Live · Test lab · Templates ·
  AI models · Integrations (MCP, telephony, messaging, webhooks, moved out of
  Settings) · Settings (workspace, team, security) · Do not call. Keep old
  URLs working with redirects.
- Every blocking state names the fix and links to it (for example "No
  telephony, Set up Twilio"). Every destructive action confirms.
- It must still feel like our product: keep the colour system and the
  AgentAvatar character, and add restrained motion to state changes.

## 10. TODO: not in this release

- **Warm transfer to a human** when the caller asks ("I need a human"):
  detect intent, say a handoff line, `<Dial>` the campaign's
  `handoff_number` over Twilio, and post a summary to the human's screen.
  Needs a handoff number per campaign and after-hours behaviour.
- Research-driven items from `docs/research.md` §5, planned into v4.

---

## Test plan (TEST writes these first; they fail until DEV lands)

- `tests/test_providers_api.py`:
  - CRUD, including env rows being read-only and keys never echoed (the
    response never contains the key, only the last 4 characters).
  - Owner/admin-only writes; members get 403.
  - The SSRF guard rejects a private base_url unless allowed.
  - `/test` returns ok against a stubbed client and the error message
    against a stubbed failure.
  - Model defaults round-trip.
  - Deleting a default returns 409.
  - A campaign with a disabled provider falls back to the default.
- `tests/test_estimate.py`: component sums, unknown price shows up in
  `unknown` and never as 0, region changes telephony, `calls` scales linearly.
- `tests/test_campaign_v3.py`:
  - New columns round-trip through create, get and patch (provider ids,
    voice, precall_*).
  - `/dialer` states: draft, waiting_window with next_window_start, dialing,
    and blocked with reasons.
- `tests/test_precall.py`:
  - A due contact gets a heads-up and its call is deferred by the lead time.
  - The call is placed on a later tick.
  - A retry within 12 h doesn't send a second heads-up.
  - Suppressed numbers get nothing.
- `tests/test_voices_languages.py`:
  - `/api/voices` filters by language.
  - Every language in `LANGUAGES` has CallPhrases and a Sarvam code.
  - Preview returns 409 without a Sarvam key.
- `tests/test_assistant.py`:
  - Streams from a stubbed model.
  - The snapshot has no secrets or phone numbers.
  - Links come only from the allow-list.
  - Rate limit.
- `tests/test_reextract.py`:
  - Overload then success within the retries.
  - Fallback to the default provider.
  - The re-extract endpoint updates the call.
- `tests/test_dialer.py` (exists): add stale IN_PROGRESS recovery.

Existing suites must stay green. UI: `tsc -b` and `vite build` clean.
