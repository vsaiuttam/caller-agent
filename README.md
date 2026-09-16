# Voice Agent Platform

Outbound calling with a conversational AI agent: place calls from a contact
list, hold a natural conversation against a per-campaign goal, extract what was
agreed, and write it to your calendar and records — with a human review gate on
anything the model wasn't sure about.

## Architecture

The system splits along a latency boundary, which is the single decision that
shapes everything else:

```
IN-CALL  (must be <800ms round trip)      POST-CALL  (latency-tolerant)
┌──────────────────────────────┐          ┌─────────────────────────────┐
│ STT ─▶ Claude Sonnet 5 ─▶ TTS│  ──────▶ │ transcript ─▶ Opus 5 extract│
│ streaming, effort=low         │          │  ─▶ deterministic dispatch │
│ prompt-cached system blocks   │          │  ─▶ calendar / records     │
└──────────────────────────────┘          └─────────────────────────────┘
```

Putting a CRM write on the in-call path is what makes voice agents sound
broken — the caller hears dead air while an API call resolves. Extraction after
the fact is also *more accurate*: the model sees corrections and reversals
("actually, make it Thursday") in full context instead of committing to
whatever it heard first.

### Processes

| Process | Command | Scales |
|---|---|---|
| API + UI | `uvicorn src.voiceagent.api.app:app` | 1–2 |
| Call worker | `python -m src.voiceagent.worker` | horizontally |

They share only the database. Workers claim contacts with a conditional
`UPDATE`, so several can run against one campaign without coordination.

## Running it

### 1. Backend

```bash
python -m venv .venv && .venv\Scripts\activate     # Windows
pip install -r requirements.txt
copy .env.example .env                              # then add one provider key
```

### 1a. Pick a model provider

One key is all it takes. Set any of these in `.env` and the app uses it:

| Key | Provider | Why you'd pick it |
|---|---|---|
| `ANTHROPIC_API_KEY` | Claude | Prompt caching with explicit breakpoints |
| `GEMINI_API_KEY` | Google Gemini | 97 languages incl. Hindi and Urdu; cheapest |
| `OPENAI_API_KEY` | OpenAI | Realtime speech-to-speech and SIP from one key |
| `SARVAM_API_KEY` | Sarvam AI | Indic-first; best on code-mixed Hinglish |
| `NVIDIA_API_KEY` | NVIDIA NIM | Free evaluation credits; 40 req/min |

Set several and `MODEL_PROVIDER` chooses between them. Switching providers
needs no migration: campaigns holding another vendor's model id resolve onto
the active provider's default rather than failing at dial time.

### 2. Frontend

```bash
cd frontend
npm install
npm run dev
```

### 3. Start everything

Three terminals:

```bash
uvicorn src.voiceagent.api.app:app --reload --port 8000   # API
python -m src.voiceagent.worker                            # calls
cd frontend && npm run dev                                 # UI on :5173
```

### 4. See it work without a phone line

```bash
python seed_demo.py
```

With `TELEPHONY=mock` (the default) the worker dials a scripted caller instead
of the PSTN. That exercises the full loop — turn-taking, barge-in, extraction,
dispatch, the live UI feed — using only your Anthropic key. It's also the right
way to iterate on prompts, since a scripted counterpart is reproducible in a
way a real call never is.

Set `MOCK_INTERRUPT=true` to make the scripted caller talk over the agent and
exercise the barge-in path.

### 5. Rehearse a campaign before dialling anyone

Open **Test calls** in the UI, or `POST /api/simulate`. Claude plays the person
answering, the real conversation model plays the agent, and the real extractor
reads the transcript afterwards — only the phone line is fake. You get the
transcript, per-turn time-to-first-audio, what was extracted, and what it cost.

Six personas ship with it: cooperative, busy, skeptical, confused, opts out,
wrong number. Running a script past the hostile ones is worth more than a
hundred live dials, and nobody gets called to find out.

Simulations write to the same `calls` table with `is_simulation` set, and every
aggregate filters them out — a morning of prompt-tuning must not read as a good
day of calling.

### 6. Take the call yourself

Open **Live mic**, pick a campaign, press *Call me*, and talk. Your voice goes
through the browser's speech recognition, the real conversation model answers,
the browser speaks its reply, and the real extractor reads the transcript when
you hang up. Only the phone line is fake.

This is the one thing a simulated persona cannot tell you: what the call is
like to sit through. Speech recognition mishears words a model never would,
you trail off and start again, and the pause before the reply is only
uncomfortable when it is your pause.

Two microphone modes, because a laptop's own speakers defeat barge-in — the
recogniser hears the agent's voice through them and cuts it off on its own:

| Mode | Behaviour | Use |
|---|---|---|
| Take turns (default) | Mic closes while the agent speaks | Laptop speakers |
| Talk over it | Mic stays open; interrupting works | Headphones |

Chrome and Edge have speech recognition; Firefox and Safari do not. The page
says so and gives you a text box instead — the rest of the call is unchanged.

Needs only `ANTHROPIC_API_KEY`. No Deepgram or Cartesia key, no phone number,
and nothing is dispatched. Like a simulation, a saved mic call is written with
`is_simulation` set and excluded from every aggregate.

### 7. Going live

Set `TELEPHONY=livekit` and fill in the LiveKit, Deepgram, and Cartesia keys.
Before the first real call, read the VERIFY notes in
`src/voiceagent/voice/livekit_adapter.py` — that file is the only one coupled
to LiveKit's plugin API, which has moved between releases.

## Layout

```
src/voiceagent/
  models.py            Data models; CallOutcome doubles as the extraction schema
  providers.py         Which vendor serves this deployment; one row per provider
  prompts.py           System prompt in two cached blocks
  llm.py               In-call streaming, flushes at clause boundaries
  catalog.py           Model registry, pricing, token ledger, cost estimator
  simulate.py          Dry-run a call against a simulated person
  live.py              Dry-run a call against yourself, over a microphone
  templates.py         Prebuilt campaigns, multilingual greetings
  webhooks.py          Signed per-call POST — the non-MCP integration escape hatch
  storage.py           SQLAlchemy schema
  worker.py            Call worker entrypoint
  orchestrator/
    scheduler.py       Calling hours, timezone, DNC, retry backoff (pure)
    runner.py          Concurrency-capped dispatch loop
    events.py          In-process pub/sub for the live feed
  voice/
    session.py         Turn-taking and barge-in (transport-agnostic)
    pipeline.py        One call, end to end
    livekit_adapter.py LiveKit/Deepgram/Cartesia  ⚠ version-sensitive
  postcall/
    extract.py         Transcript → CallOutcome
    actions.py         Deterministic dispatch with a review gate
  integrations/
    clients.py         Google Calendar, records API, DB suppression
    mocks.py           Scripted caller + logging stubs
  api/
    app.py             REST + WebSocket
frontend/              React + Vite + TypeScript + Tailwind
```

## Design notes worth knowing

**Prompt caching uses two breakpoints.** The persona block is byte-identical
across every call in a campaign, so it's written once and read by all of them;
the per-call context block is written on turn one and read by every turn after.
At volume this is most of your input tokens at ~0.1× cost. It's also why
`prompts.py` sorts attribute dicts — one unsorted dict makes the prefix differ
per process and nothing ever caches.

**One adapter, five providers.** There are two API shapes in the world here,
not five: Anthropic's Messages API, and the OpenAI `chat/completions` shape
that Gemini, OpenAI, Sarvam and NVIDIA all speak. `providers.py` is the table;
`llm.py` and `extract.py` each branch once. That is what makes "which model is
best for Hindi?" a question you answer by running the same campaign past the
same difficult persona on two providers and listening, rather than by reading
a benchmark page.

Two consequences worth knowing. Gemini reports thinking tokens only in
`total_tokens`, so the ledger derives output from the total — measured at 233
reported completion tokens against a 936-token total on a real extraction, and
billing the reported figure would have understated that turn by 70%. And the
OpenAI-shaped path collapses the two cached system blocks into one message:
those providers cache automatically on a matching prefix, so the layout in
`prompts.py` still pays, but the breakpoints can't be placed by hand.

**Different models on each path, and you choose them.** Sonnet 5 at
`effort: "low"` in-call for latency; Opus 5 at `effort: "high"` for extraction,
because that output writes an appointment into a real calendar and a wrong
booking costs more than the few tenths of a cent between them. Both are
per-campaign settings on the **Models** page, with a workspace default new
campaigns inherit.

The catalog enforces which models are offered for which role — Haiku is not
offered for extraction and Fable is not offered for the in-call path, and the
API rejects those pairings rather than trusting the picker. `resolve()` falls
back rather than raising, so a campaign pointing at a retired model keeps
dialling instead of failing at connect time.

**Cost is measured, not guessed.** Every call records the token counts the API
actually reported, per model, and the dollar figure that follows from them. The
estimator on the Models page projects a campaign before you spend it; the
dashboard shows what it really cost. A campaign can carry a hard spend cap and
pauses itself when it's reached — calls already in flight always finish, since
hanging up on someone mid-sentence to save four cents is not a behaviour worth
having. Interrupted turns are undercounted, so the recorded figure is a floor.

**Thinking stays on.** Disabling it is the tempting latency lever and it
misfires: on Sonnet 5 it makes the model noticeably less willing to call tools,
and on Opus 5 it can emit a tool call as plain text — the turn succeeds, the
call never runs, no error is raised. `effort: "low"` gets most of the latency
win without either failure mode.

**Barge-in records what was heard, not what was generated.** When someone
interrupts, the model has usually generated further than the speaker has
played. Recording the generated text leaves the model believing it delivered
information the caller never heard. `Speaker.stop()` returns the actual played
prefix, and the estimate deliberately errs low.

The mic path holds the same rule across a network hop: the browser reports
what its speaker actually played, and an agent turn it never confirms is
dropped rather than recorded optimistically. An agent repeating itself is a
recoverable annoyance; an agent certain it already said something is not.

**Suppression is not gated behind review.** Every other write is held when the
extractor flags low confidence. An opt-out is honoured unconditionally, keyed
on phone number rather than contact id so it stops every campaign at once, and
re-importing the number later won't undo it.

**Demo mode announces itself.** `GET /api/health` reports which integrations
hold credentials and which are running on mocks, and the sidebar says so on
every screen. A platform that looks fully operational while running on stubs is
how a demo becomes a production incident. The check is presence, not validity —
a placeholder key reads as configured and fails on first use.

**Schema changes apply themselves, additively.** `create_all` creates missing
tables and silently ignores missing *columns*, so pulling a schema change onto
a seeded database fails later with "no such column". `_add_missing_columns`
closes that for the only shape safe to run unattended: additive, defaulted,
never a drop or a type change. Renames and backfills still need Alembic and a
human.

## Before dialling real numbers

Automated outbound calling is regulated. Depending on jurisdiction you'll need
consent records, DNC list scrubbing beyond the internal list here, calling-hour
compliance (the scheduler enforces a window per contact timezone — set it to
what your rules actually require), and in a growing number of places explicit
disclosure that the caller is an AI. The persona prompt discloses this on
request and honours opt-outs immediately; the rest is your policy to set.
