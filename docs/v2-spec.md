# Samvaad v2 — build spec

Owner: lead (main session). This is the contract DEV-AGENT, TEST-AGENT and
UI-UX-AGENT build against in parallel. Names in `code` are exact — tests are
written against them before the implementation exists. If something here is
wrong or impossible, stop and report it; do not improvise a different contract.

## 0. Product decisions

- **Brand:** the product is renamed **Samvaad** (संवाद, "conversation").
  Tagline: *"AI voice agents that sound human."* The brand name, tagline and
  logo live in one place on the frontend (`frontend/src/brand.ts` + `Logo`
  component) so a rename is a one-file change. Backend strings mentioning
  "Voice Agent Platform" (FastAPI title) change to "Samvaad API".
- **Feel:** a production console in the class of AWS / Azure / Vercel / Linear,
  but warmer: an animated agent character is the face of the product.
- **Principles:** real-time first (you watch a call happen), nothing
  lost (every conversation saved and exportable), honest state (health,
  mocks, failures said plainly), fast (no dead air, no spinners without
  skeletons), accessible (keyboard, contrast, reduced motion).

## 1. Backend — DEV-AGENT (scope: `src/voiceagent/**`)

### 1.1 Graceful call ending (user-reported bug)

Today: the person says "thank you"/"bye", the agent's reply isn't recognised
as a goodbye (esp. in Hindi), the line goes quiet, then the agent says an
English "Sorry — are you still there?" and hangs up. Fix it end to end:

**`src/voiceagent/llm.py`**
- `END_CALL_MARKER = "[END_CALL]"`.
- `class EndMarkerFilter`: streaming filter over model text.
  - `feed(text: str) -> str` — returns the text that is safe to emit now.
    Holds back any trailing text that could be the start of the marker
    (e.g. `"... bye! [EN"`) until it is resolved.
  - `flush() -> str` — end of stream: returns anything still held back that
    turned out not to be the marker.
  - `found: bool` — True once the full marker has been seen. Everything after
    the marker is dropped (never emitted).
- `ConversationLLM.generate()` runs model deltas through a fresh
  `EndMarkerFilter` each turn (before clause flushing), so the marker is never
  spoken, recorded, or sent to TTS. Exposes `end_requested: bool`, reset to
  False at the start of every `generate()` and set True when the marker was
  found.

**`src/voiceagent/prompts.py`** — replace the "Ending the call" section of
`VOICE_PERSONA` so the model: ends the call when the goal is done, when the
person signals they're finished ("thank you", "bye", "that's all",
"dhanyavaad", "bas", "shukriya", "alvida"…), asks to end or opt out, or it is
a wrong number; says ONE short warm farewell **in the call's language**; then
writes `[END_CALL]` as the very last thing. Never writes the marker otherwise;
never says it aloud; does not end just because the person said "thanks"
mid-conversation when something is still pending.

**`src/voiceagent/voice/phrases.py`** (new)
```python
@dataclass(frozen=True)
class CallPhrases:
    still_there: str        # first silence strike
    goodbye_silence: str    # second silence strike, then hang up
    goodbye_timeout: str    # max call duration reached
    goodbye_default: str    # model ended without a farewell, or operator hung up
    voicemail: str          # appended to the greeting on voicemail
    acknowledgements: tuple[str, ...]  # short fillers while a reply is prepared

def phrases_for(language: str | None) -> CallPhrases
```
Languages `en`, `hi`, `ur`, `hi-en`; case-insensitive; unknown/None → `en`.
Use these texts (Hindi/Urdu in Devanagari because the TTS voice reads
Devanagari; genderless phrasing because the voice gender varies):

| key | en | hi | ur | hi-en |
| --- | --- | --- | --- | --- |
| still_there | Sorry, are you still there? | माफ़ कीजिए, क्या आप अभी भी लाइन पर हैं? | माफ़ कीजिए, क्या आप अभी लाइन पर हैं? | Sorry, kya aap abhi line par hain? |
| goodbye_silence | I'll let you go for now. Thanks for your time — goodbye! | कोई बात नहीं, हम बाद में बात करेंगे। आपके समय के लिए धन्यवाद, नमस्ते! | कोई बात नहीं, हम बाद में बात करेंगे। आपके वक़्त का शुक्रिया, ख़ुदा हाफ़िज़! | Koi baat nahi, hum baad mein baat karenge. Thank you, bye! |
| goodbye_timeout | I've taken enough of your time. Thank you so much — goodbye! | आपका काफ़ी समय ले लिया। बहुत-बहुत धन्यवाद, नमस्ते! | आपका काफ़ी वक़्त ले लिया। बहुत-बहुत शुक्रिया, ख़ुदा हाफ़िज़! | Aapka kaafi time le liya. Thank you so much, bye! |
| goodbye_default | Thank you so much for your time. Have a great day — goodbye! | आपके समय के लिए बहुत-बहुत धन्यवाद। आपका दिन शुभ हो, नमस्ते! | आपके वक़्त का बहुत शुक्रिया। आपका दिन अच्छा गुज़रे, ख़ुदा हाफ़िज़! | Aapke time ke liye bahut shukriya. Aapka din achha ho, bye! |
| voicemail | Sorry we missed you. We'll try again later. Thank you! | माफ़ कीजिए, आपसे बात नहीं हो पाई। हम बाद में फिर कॉल करेंगे। धन्यवाद! | माफ़ कीजिए, आपसे बात नहीं हो सकी। हम बाद में फिर कॉल करेंगे। शुक्रिया! | Sorry, aapse baat nahi ho paayi. Hum baad mein phir call karenge. Thank you! |
| acknowledgements | "Okay.", "Mm-hmm.", "Got it.", "Right." | "जी।", "अच्छा।", "ठीक है।", "जी, एक सेकंड।" | "जी।", "अच्छा।", "ठीक है।" | "Haan ji.", "Achha.", "Theek hai.", "Okay." |

**`src/voiceagent/voice/session.py`**
- `CallSession(..., phrases: CallPhrases | None = None, on_event=None)`;
  `phrases` defaults to `phrases_for("en")`. All stock lines (silence,
  timeout) come from `phrases` — no hard-coded English left in the session.
- After an uninterrupted reply the call ends when
  `getattr(llm, "end_requested", False)` **or** `_is_closing(text)`.
  If the model requested the end but said nothing, speak
  `phrases.goodbye_default`, then end. An interrupted (barged-in) reply never
  ends the call.
- `_CLOSING_MARKERS` also covers farewells (not thank-yous) in the other
  languages: `alvida`, `अलविदा`, `khuda hafiz`, `ख़ुदा हाफ़िज़`, `خدا حافظ`,
  `phir milenge`, `फिर मिलेंगे`, `नमस्ते!`-style closings are handled by the
  marker, not the heuristic. A bare "dhanyavaad"/"धन्यवाद"/"shukriya"/"thank
  you" must NOT count as closing.
- `request_end()` — ask a running session to wrap up: if it is waiting for the
  person, it speaks `phrases.goodbye_default` and ends; if it is mid-reply, it
  ends right after that reply. Used by the operator "End call" button.
- `on_event: Callable[[str, dict], Awaitable[None]] | None` — called as:
  - `("turn", {"role", "text", "latency_ms", "at"})` after every recorded
    turn (`at` = ISO 8601 UTC),
  - `("state", {"state": s})` with `s` in `"speaking"` (agent turn handed to
    the speaker), `"listening"` (agent finished handing over / waiting for
    the person), `"thinking"` (person's utterance received), `"ended"` (last
    event, from `run()`).
  Exceptions raised by `on_event` are logged and swallowed — a broken
  observer must never break a call.

**Callers** (`voice/pipeline.py`, `api/app.py`) pass
`phrases=phrases_for(<campaign language>)`; the pipeline's voicemail message
uses `phrases.voicemail`.

### 1.2 Real-time call streaming + saved conversations

**Event bus** (`orchestrator/events.py`): add `CALL_TURN = "call.turn"`,
`CALL_STATE = "call.state"`, `CALL_FAILED = "call.failed"`,
`CALL_WHISPER = "call.whisper"`. Every call event payload includes `call_id`:

| type | payload (besides `call_id`) |
| --- | --- |
| call.started | campaign_id, contact_name, phone (masked), is_test |
| call.connected | — |
| call.state | state |
| call.turn | role, text, latency_ms, at |
| call.whisper | text |
| call.ended | turns, duration_seconds |
| call.extracted | disposition, summary, needs_review, cost_usd, sentiment; test calls also `result` (the full result object, §1.2 test call) |
| call.failed | error (human-readable) |

Campaign calls (pipeline) and test calls both publish these.

**Live registry** — `src/voiceagent/voice/live_registry.py` (new), in-process:
`register(call_id, *, session, room_name, campaign_id, contact_name, is_test)`,
`unregister(call_id)`, `get(call_id) -> LiveCall | None`,
`all() -> list[LiveCall]`, `set_state(call_id, state)`. `LiveCall` holds the
session plus `room_name, campaign_id, contact_name, started_at, state,
is_test, turns`.

**Async test call** — `POST /api/test-call` (same request body as today plus
`send_sms`/`send_whatsapp`) now returns **HTTP 202** immediately:
`{"call_id": "...", "status": "dialing"}`. It creates the `Call` row up front
(status `dialing`, `is_simulation=True`, the placeholder contact as today,
`room_name`), then runs the call in a background task (keep a strong
reference). Seams, exact names:
- `app._test_call_telephony()` — builds the telephony adapter (Twilio or
  Telnyx per `TELEPHONY`); tests monkeypatch it.
- `app._run_test_call(call_id, room_name, body, setup)` — the background
  coroutine.
The task: dial → `call.connected` → session with `on_event` publishing
`call.turn` / `call.state` and **saving the transcript to the row after every
turn** → extraction, scoring, follow-ups as today → row completed →
`call.ended` → `call.extracted` with `result` = the object the old endpoint
returned (plus `call_id`, `followups`, `median_first_chunk_ms`). Any failure
(dial refused, no answer, model error) → row status `failed` +
`call.failed` with a readable error. Validation errors (bad phone, no
provider, `TELEPHONY` not twilio/telnyx) still return 4xx synchronously.

**New endpoints**
- `GET /api/calls/live` → `[{call_id, room_name, campaign_id, contact_name,
  started_at, state, is_test, turns}]`.
- `GET /api/calls/{id}/transcript?format=txt|json` (default txt) → download
  (`Content-Disposition: attachment`). txt: a header (contact, campaign,
  started, disposition, summary) then one line per turn
  `[mm:ss] Agent|<contact name>: text`, offsets from the first turn. json:
  `{call_id, contact_name, campaign_id, started_at, disposition, summary,
  sentiment, turns: [...]}`. 404 if the call doesn't exist; 400 bad format.
- `POST /api/calls/{id}/hangup` → 202 and `session.request_end()`; 404 if the
  call is not live in this process.
- `POST /api/calls/{id}/whisper` `{"text": "..."}` (1–500 chars) → 202;
  404 if not live. Calls `ConversationLLM.add_guidance(text)`: guidance is
  added to the system prompt for all following turns as supervisor guidance
  the agent follows but never mentions (Anthropic: an extra system block
  *without* cache_control after the two cached blocks; chat/completions:
  appended to the system text). Publishes `call.whisper`.

### 1.3 Latency

- **Per-call language.** Optional telephony method
  `prepare_call(room_name: str, *, language: str, greeting: str) -> None`,
  called (via `hasattr`) before `dial` by the pipeline and the test call.
  Twilio implementation: remembers the language for that room, and when the
  voice is Sarvam pre-synthesizes the greeting and that language's
  acknowledgements. Gather STT language per call: the `SARVAM_STT_LANGUAGE`
  env var wins when set; otherwise `en`→`en-IN` (Sarvam voice) / `en-US`
  (other), `hi`→`hi-IN`, `hi-en`→`hi-IN`, `ur`→`ur-IN`. Sarvam TTS language
  per call: `SARVAM_TTS_LANGUAGE` wins when set; otherwise `en`→`en-IN`,
  `hi`/`hi-en`/`ur`→`hi-IN`. The audio cache key includes the TTS language.
- **Acknowledgement fillers.** `TWILIO_FILLER_AFTER_MS` (default `1200`,
  `0` disables). When the caller has just spoken and the reply is not ready
  within that time, the gather webhook answers with one acknowledgement from
  `phrases.acknowledgements` (rotating, never the same one twice in a row)
  followed by `<Redirect>` to `/twilio/wait/{room}`, which then returns the
  reply. With Sarvam, only use a filler whose audio is already cached (never
  synthesize on the hot path). Fillers are not recorded in the transcript.

### 1.4 Recordings actually saved

Twilio's recording callback arrives after hang-up, when the in-memory call
state is already gone, so recordings are never stored. The recording webhook
must persist `recording_url`, `recording_sid`, `recording_duration` to the
`Call` row whose `room_name` matches, whether or not the state still exists
(use `storage.SessionLocal` looked up at call time, so tests can swap it).

### 1.5 Sentiment

`models.Sentiment(str, Enum)`: `positive`, `neutral`, `negative`.
`CallOutcome.sentiment: Sentiment = Sentiment.NEUTRAL` and
`CallOutcome.sentiment_reason: str = ""` (defaults keep old stored outcomes
valid). Extraction fills them. `Call.sentiment` column (String(16),
nullable, indexed), written by pipeline, test calls and saved simulations.
`CallSummary.sentiment: str | None`. `DashboardStats.sentiment_breakdown:
dict[str, int]` (real calls only).

### 1.6 Access control (opt-in)

`src/voiceagent/api/auth.py`: `auth_enabled() -> bool` (True iff
`ADMIN_PASSWORD` is set and non-empty), `issue_token(now=None) -> tuple[str,
datetime]`, `verify_token(token: str, now=None) -> bool`. Token =
`base64url(json {"exp": unix_seconds}) + "." + base64url(HMAC-SHA256)`;
secret = `AUTH_SECRET`, else derived from `ADMIN_PASSWORD`; lifetime
`AUTH_TOKEN_TTL_HOURS` (default 12). Compare in constant time.
- `POST /api/auth/login {"password"}` → 200 `{token, expires_at}` / 401;
  more than 5 failures from one client in 5 minutes → 429.
- `GET /api/auth/status` → `{auth_enabled, authenticated}`.
- When enabled, every `/api/*` HTTP route except `/api/health`,
  `/api/auth/login`, `/api/auth/status` requires `Authorization: Bearer
  <token>` or `?token=<token>` (for `<audio>`/downloads) → else 401
  `{"detail": "Authentication required"}`. WebSockets `/api/events` and
  `/api/live` require `?token=` → else close with code 4401. `/twilio/*` is
  never behind auth.
- `/api/health` adds `auth_enabled`.
- When `ADMIN_PASSWORD` is unset everything stays open exactly as today.

### 1.7 Done criteria (DEV)
All existing tests + TEST-AGENT's new tests pass; `python -m compileall -q src`
clean; no file outside `src/voiceagent/**` touched.

## 2. Tests — TEST-AGENT (scope: `tests/**`)

Write the tests for §1 **first**, before the implementation exists (Red).
New files only (don't rewrite existing tests): `tests/test_call_ending.py`,
`tests/test_live_streaming.py`, `tests/test_latency_v2.py`,
`tests/test_api_v2.py`, `tests/test_auth.py`. Follow the repo convention:
each file runs standalone (`python tests/<file>.py`, `_run_all()` at the
bottom, `sys.path` insert) and under pytest. No network, no API keys, no real
Twilio.
- Pin `twilio_adapter.VOICE_PROVIDER` in tests (the package loads `.env`,
  which may say `sarvam`) — see the `_voice` helper in `tests/test_twilio.py`.
- API tests: build a throwaway SQLite engine; override
  `app.dependency_overrides[get_session]` and monkeypatch
  `storage.SessionLocal`; call `Base.metadata.create_all`. Don't rely on
  `DATABASE_URL` (other test modules may have imported storage first).
- Use fakes like `FakeLLM` in `tests/test_core.py` (give it `end_requested`)
  and `MockSpeaker`/`MockControl` from `integrations/mocks.py`.
Cover at least: every `EndMarkerFilter` case (marker at end, split across
feeds, mid-text drops the rest, absent, a lone `[` that isn't the marker);
`phrases_for` (all four + fallback + case); session ends on `end_requested`,
speaks `goodbye_default` when the model said nothing, uses localized silence
lines, never ends an interrupted reply, `request_end()` while waiting;
`on_event` order and swallowed exceptions; `_is_closing` on farewells vs bare
thank-yous; Twilio filler served when the reply is slow and not when fast,
per-call Gather language; recording webhook persists by `room_name` after the
state is gone; `/api/test-call` 202 + `dialing` row + `call.failed` on a
refused dial (monkeypatch `_test_call_telephony`); transcript export
txt/json/404/400; `/api/calls/live` empty; whisper/hangup 404 when not live;
auth off = open, auth on = 401 / login / bad password / bearer / query token /
expired token / health stays open; sentiment default and round-trip.
Report which tests fail on the current code (expected) and why.

## 3. Frontend — UI-UX-AGENT (scope: `frontend/**`)

Stack stays: React 19, Vite 6, Tailwind 4, TypeScript, framer-motion (already
a dependency). Avoid new dependencies unless clearly worth it. Verify with
`npx tsc --noEmit -p tsconfig.json` and
`npx vite build --outDir <a temp dir outside the repo>` (don't run `tsc -b` —
it rewrites the tracked `tsconfig.tsbuildinfo`). Run `npm ci` in `frontend/`
first (the worktree has no `node_modules`).

1. **Brand:** `brand.ts` (name "Samvaad", tagline, short description) and a
   new `Logo` / `LogoMark` SVG component — a speech bubble whose tail becomes
   a sound wave, crisp at 16px, works in light and dark. New SVG favicon,
   `<title>`, meta description, theme-color. Replace every "Voice Agent" /
   old logo usage.
2. **Design system:** consistent tokens (color, type scale, spacing, radius,
   elevation, motion durations) in `index.css`; light + dark themes (keep
   `theme.tsx`); one component vocabulary in `components/ui.tsx` (buttons,
   inputs, selects, toggles, tabs, badges, cards, tables, dialogs, drawers,
   toasts, tooltips, skeletons, empty states). Visible focus rings, WCAG AA
   contrast, `prefers-reduced-motion` respected everywhere.
3. **Console shell:** collapsible left nav grouped like a cloud console
   (Overview · Campaigns · Calls · Live · Test lab · Templates · Models ·
   Integrations/Settings), top bar with breadcrumbs, global search / command
   palette (⌘K / Ctrl+K — `CommandPalette.tsx` exists), system-health pill,
   theme toggle, and a user menu with Sign out when auth is enabled. Fully
   responsive (mobile drawer nav), no horizontal scroll.
4. **Animated agent character** — `AgentAvatar` (SVG + framer-motion), a
   friendly character with a headset. States: `idle` (breathes, blinks),
   `ringing`, `listening` (ear/pulse rings), `thinking` (eyes drift, dots),
   `speaking` (mouth + sound waves), `ended` (waves goodbye), `error`
   (concerned). Sizes sm/md/lg. Used in the live console, empty states,
   onboarding, login, and 404. Static pose under reduced motion.
5. **Live call console** (Test lab "Call a real phone" and the Live page): start
   a test call → `POST /api/test-call` returns `call_id` → subscribe to the
   `/api/events` WebSocket and filter by `call_id`. Show: avatar driven by
   `call.state`, call timer, status stepper (Dialing → Ringing → Connected →
   Wrapping up → Done), transcript streaming in as chat bubbles as
   `call.turn` events arrive (auto-scroll with "jump to latest", per-turn
   latency chips), a whisper box (`POST /api/calls/{id}/whisper`), End call
   (`POST /api/calls/{id}/hangup`), and when `call.extracted` arrives the
   outcome, scorecard, follow-up status. `call.failed` shows a clear error with
   the avatar's `error` state. Transcript actions: copy, download TXT/JSON
   (`GET /api/calls/{id}/transcript`). Reconnect the socket with backoff; if
   it drops mid-call, fall back to polling `GET /api/calls/{id}`.
6. **Live page:** `GET /api/calls/live` list (poll + events), click to open
   the console for any live call (watch-only for campaign calls, with whisper
   and end).
7. **Calls page:** sentiment badges and filter, transcript export buttons,
   recording player, per-turn latency chips and a small latency bar chart,
   follow-up status (keep the current resend), better filters/search, row
   density toggle.
8. **Overview (dashboard):** KPI cards with deltas, charts (existing
   `charts.tsx`), sentiment breakdown, live calls strip, and an onboarding
   checklist (model provider ✓, telephony ✓, first campaign, first test
   call, follow-ups, auth enabled) driven by `/api/health` + data.
9. **Auth UI:** when `/api/auth/status` says `auth_enabled` and not
   authenticated → a branded login page (avatar + password). Store the token
   (localStorage, try/catch), send `Authorization: Bearer`, append `?token=`
   to WebSocket URLs, `<audio>` src and download links; on 401 go to login.
   When auth is disabled show a dismissible banner: "Anyone with this link can
   place calls — set ADMIN_PASSWORD to lock it."
10. **Polish:** toasts for every mutation, skeletons instead of spinners,
    friendly empty states with the avatar, error boundary with retry,
    keyboard shortcuts help (`?`), 404 page, consistent page headers.

## 4. Not in this round (roadmap)

Twilio Media Streams + streaming STT/TTS for sub-second turns · warm transfer
to a human · inbound calls · knowledge base / RAG per campaign · A/B prompt
tests · teams, roles and per-user accounts · per-campaign voice picker with
preview · Urdu calls in Urdu script (the Sarvam voice needs Devanagari today).
