# Samvaad product guide

Samvaad places outbound phone calls with an AI voice agent. A campaign holds
who to call, what the call is for, how the agent speaks, and when it may
call. After each call Samvaad saves the transcript, extracts a structured
outcome (disposition, summary, appointment, sentiment, scores), and can send
a follow-up message, fire a webhook, or write back into connected apps.

## Pages

- **Overview** (`/app/dashboard`): calls, connect rate, sentiment and spend
  for the last 7 or 30 days. Test calls are included unless hidden.
- **Campaigns** (`/app/campaigns`): every campaign with its dialler state
  pill. "New campaign" (`/app/campaigns/new`) opens the builder.
- **Campaign detail**: Overview (dialler status, progress, KPIs), Calls,
  Contacts, and Settings, which reopens the builder at a step.
- **Calls** (`/app/calls`): every call. The view switch has All, **Needs
  review** (`/app/calls?view=review`) and Live now. The old Review queue
  page now lives here.
- **Live** (`/app/live`): the wallboard of calls in progress. You can listen
  to the transcript as it happens, whisper guidance to the agent, or hang up.
- **Test lab** (`/app/test-lab`): rehearse a campaign against a simulated
  person, talk to the agent yourself through the microphone, or place a real
  test call to your own phone.
- **Templates** (`/app/templates`): ready-made campaigns (appointment
  confirmation, lead qualification, payment reminders and more) to start
  from.
- **AI models** (`/app/models`): model providers, workspace defaults, the
  model browser with prices, and the cost calculator.
- **Integrations** (`/app/integrations`): connected apps (MCP), telephony,
  messaging (SMS and WhatsApp) and webhooks.
- **Settings** (`/app/settings`): workspace, team members and roles, and
  security.
- **Do not call** (`/app/suppressions`): numbers that are never dialled, in
  any campaign.

## The campaign builder

One stepper for new and existing campaigns, with a summary rail showing the
name, language, voice, model and estimated cost:

1. **Basics**: name, goal, template.
2. **Agent**: language, voice, greeting, extra instructions, and the model
   provider and model for the conversation, with a live cost chip.
3. **Tools**: connected-app (MCP) tools the agent may use during the call,
   and after it to record the outcome.
4. **Contacts**: upload a CSV or Excel file, or paste numbers. Numbers are
   normalised to E.164 (+91...).
5. **Schedule & messages**: calling hours and days (in each contact's own
   timezone), attempts, concurrency, the pre-call heads-up, follow-ups, and
   a webhook.
6. **Review & launch**: a checklist of blockers, then Save draft or Launch.

The builder autosaves in your browser, so leaving the page (for example to
connect an app) never loses work. "Save draft" works on every step.

## Model providers

Samvaad works with any LLM provider. Add one on the AI models page: pick a
preset (OpenAI, Anthropic, Google Gemini, Sarvam, Groq, OpenRouter,
DeepSeek, Mistral, Together, Fireworks, xAI, NVIDIA, Azure OpenAI) or
"OpenAI-compatible" for Ollama, vLLM, LM Studio or any server that speaks
`chat/completions`. Paste the API key, add a base URL where needed, and
press Test. Keys are encrypted at rest and never shown again; only the last
four characters appear.

- A provider configured by an environment variable (for example
  `GEMINI_API_KEY`) is listed as read-only.
- Only owners and admins can add, change or remove providers and defaults.
- **Defaults**: the workspace picks a provider and model for conversation
  and one for extraction. A campaign can override either. If a campaign's
  provider is deleted or disabled, it falls back to the default.
- Custom models: for a model the catalog doesn't list, add it to the
  provider with its price. Without a price, costs show as unknown.
- Local servers (Ollama on localhost) need `MCP_ALLOW_PRIVATE_HOSTS=true` on
  the server, since private addresses are refused by default.
- Tools during calls need a provider that supports tool calling; Sarvam,
  NVIDIA and generic OpenAI-compatible servers run without tools.

Choosing a model: a fast, cheap model on the live call (Gemini Flash Lite,
GPT-4.1 mini, Claude Haiku, Llama on Groq) and a more careful one for
extraction (Gemini Flash, GPT-5 mini, Claude Opus). Low effort in-call keeps
replies quick.

## Costs

The cost calculator and the builder's cost chip estimate a call from its
parts: the conversation model, the extraction, speech-to-text, text-to-speech
and telephony. Assumptions: about 12,000 input and 200 output tokens per
minute of conversation, 500 spoken characters per minute, one extraction per
call, 3 minutes per call by default. Telephony is priced for India or the US.
Speech and the phone line usually cost more than the model. A model without a
known price makes the total show as unknown rather than $0. Each call's
actual token cost is recorded on the call, and a campaign can have a spend
cap (budget) that pauses it automatically.

## Telephony

Real calls need a phone line. Samvaad supports Twilio (recommended),
Telnyx, and LiveKit SIP. For Twilio set `TELEPHONY=twilio`,
`TWILIO_ACCOUNT_SID`, `TWILIO_AUTH_TOKEN`, `TWILIO_PHONE_NUMBER` and a
public `TWILIO_WEBHOOK_URL`. With `TELEPHONY=mock` nothing real is dialled.
Twilio trial accounts can only call verified numbers.

## Why a campaign isn't calling

The dialler status on each campaign says why:

- **Draft**: not launched yet. Press Launch.
- **Blocked**: something is missing. "No telephony configured" means the
  Twilio settings are absent; "No model provider" means add a provider on
  AI models; "No contacts" means upload some.
- **Waiting for the window**: every contact is outside its calling hours or
  days; the status shows when the next window opens and in which timezone.
  Contacts are called in their own timezone.
- **Paused**: paused by hand, or it reached its spend cap.
- **Completed**: everyone has been called.

Contacts marked Do not call are skipped everywhere. Retries wait longer
after each unanswered attempt (hours, then days), up to the campaign's
maximum attempts. If the server restarts mid-call, those contacts are put
back in the queue automatically.

## Languages

Calls can be in English, Hindi, Urdu, Hinglish, Telugu, Tamil, Kannada,
Malayalam, Marathi, Bengali, Gujarati, Punjabi and Odia. The agent speaks the
everyday spoken register, keeps common English words, and switches if the
person switches. Pick the language in the Agent step. If a template has no
greeting in that language, use "Translate greeting" and edit the result; the
saved greeting is spoken as written, never translated during a call.

Telugu and the other Indian languages use Sarvam voices. Speech recognition
on Twilio covers all of them except Odia, which is heard as Indian English.

## Voices

Voices are Sarvam Bulbul v3 speakers (for example Shubh, Ritu, Priya,
Kavya, Aditya, Rahul), male and female, each able to speak every supported
language. Choose one in the Agent step and press play to hear a preview in
the campaign's language. Previews need `SARVAM_API_KEY` on the server. Test
calls use the campaign's voice too.

## Pre-call heads-up

A campaign can text each person a few minutes before calling them
("Hi Asha, our assistant from Smile Dental will call you in about 10
minutes. Reply STOP to opt out."). Turn it on in Schedule & messages, pick
SMS or WhatsApp, and set the lead time (2 to 240 minutes). The message can
use {name}, {company}, {minutes} and {agent}. It is sent at most once every
12 hours per person, never outside calling hours, and never to Do not call
numbers. In India SMS templates must be registered on DLT, and WhatsApp needs
an approved template; the channel must be configured in Integrations first.

## Connected apps (MCP)

Connect your own apps (a CRM, a calendar, a ticketing tool) as MCP servers
under Integrations. Their tools can be used by the agent during a call (for
example to check availability and book a slot) and after the call to record
the outcome. Pick the tools per campaign in the Tools step; "Connect an app"
opens the connect flow without leaving the builder. Server URLs and headers
are encrypted and never shown again. Every tool call is logged on the call.

## Follow-ups and webhooks

After a call Samvaad can send a thank-you or missed-call note by SMS or
WhatsApp, with any appointment that was booked. A webhook URL receives each
completed call's outcome as JSON, signed when `WEBHOOK_SIGNING_SECRET` is set.

## Review and quality

Calls that need a human look land in **Needs review** on the Calls page:
extraction failures, disputed or unclear outcomes, and anything the
extractor was unsure of. Open the call to read the transcript, play the
recording, and mark it reviewed. If extraction failed because the provider
was busy, use **Re-run extraction** on the call. Extraction already retries
three times over about 20 seconds and then tries the workspace default
extraction provider before a call is marked for review.

Scorecards: a campaign can define criteria (with weights and knockouts). Each
call is rated against them and gets a score and a band, so the best leads
sort to the top.

## Common errors

- "The key was rejected": the API key is wrong or expired. Edit the provider
  and paste a new key, then Test.
- "Rate limited" or "no quota": free tiers often allow only some models.
  Choose another model or enable billing.
- "Overloaded": the provider is busy. Samvaad retries; try again in a minute.
- "Trial accounts can only call verified numbers": verify the number in
  Twilio or upgrade.
- "Outside calling hours": the campaign is waiting for the window; widen the
  hours or days if that's wrong.
- A test call fails at once: check `TELEPHONY` and the Twilio settings.

## Team and access

The first person to register is the owner. Owners and admins manage the
team, providers, defaults and integrations; members can run and view
campaigns. Invites are single-use codes.
