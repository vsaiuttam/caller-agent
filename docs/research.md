# Samvaad — market research and product ideas

Researched 27 Sep 2026. Prices are list prices from vendor pages where one could be fetched, and from
third-party teardowns where not; the source for each number is linked. FX used: **₹96 = $1**
(USD/INR was 95.9–96.1 in the week of 21–26 Sep 2026, [Trading Economics](https://tradingeconomics.com/india/currency)).
Treat every price as something to check again before launch. They move every quarter.

---

## 1. Executive summary

- **Where Samvaad stands.** The outbound core is solid: campaigns, rehearsal on mock telephony, a
  live call view with whisper, post-call extraction, a human review queue, MCP tools during and after
  calls, and SMS/WhatsApp follow-ups. The MCP tools during calls plus the review gate are rarer than
  they look. Most Indian startups (Bolna, Ringg) and several global ones don't offer both. Samvaad is
  well behind the global leaders on **inbound calls, knowledge base, test/eval suites, a public API,
  and billing**, and behind Indian incumbents on **Indian telephony and TRAI compliance tooling**.
- **Naming risk (act now).** Sarvam AI's own voice-agent platform is called **"Sarvam Samvaad"**.
  It brings in about 80% of Sarvam's ~$12M run rate and is opening to self-serve users
  ([Inc42](https://inc42.com/buzz/exclusive-sarvam-ai-to-open-voice-ai-agents-platform-for-public-use/)).
  Samvaad also buys STT/TTS from Sarvam. Expect search collisions and possible trademark friction.
  Get a trademark opinion before spending on the brand.
- **Gap 1: Indian telephony.** Twilio charges **$0.0496/min (≈₹4.76)** to Indian mobiles
  ([Twilio IN](https://www.twilio.com/en-us/voice/pricing/in)). Plivo's domestic rate is **₹0.38/min**
  ([Plivo IN](https://www.plivo.com/voice/pricing/in/)), which is 12× cheaper, and Indian mobile-series
  caller IDs get far better pickup than 080/079 landline-style numbers
  ([Vomyra](https://vomyra.com/)).
- **Gap 2: no inbound / receptionist.** Every serious competitor runs inbound and outbound on the same
  agent. Inbound is also the easier sale in India, because TRAI's rules on commercial calls don't apply to it.
- **Gap 3: no knowledge base (RAG).** This is table stakes at Retell, ElevenLabs, Synthflow and Bland
  (Bland caps knowledge bases per plan). Samvaad agents can only know what's in the prompt or an MCP tool.
- **Gap 4: compliance scaffolding.** TRAI's TCCCPR amendments (Feb 2025, **third amendment 18 Sep 2026**)
  now require declaring automated/AI calls and their caller IDs (CLIs) to the telecom operator in advance,
  notifying recipients that a call is automated, and using 140-series (promotional) or 1600-series (BFSI/govt
  service) numbers. Undeclared application-to-person (A2P) calls count as spam
  ([ETV Bharat](https://www.etvbharat.com/en/business/trai-tightens-regulations-on-spam-callers-to-leverage-ai-tools-to-detect-unsolicited-calls-enn26091805208),
  [MediaNama](https://www.medianama.com/2026/07/223-trai-releases-clarification-designated-promotional-transactional-number-series/)).
  DPDP's consent-manager phase starts **13 Nov 2026**
  ([PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2190014&reg=3&lang=2)).
- **Gap 5: no metering, billing or public API.** You can't sell per-minute plans, let agencies resell,
  or trigger a call from a website form (speed-to-lead) without these.
- **Opportunity 1: compliance by default as the India moat.** Global platforms ship "none
  India-specific" ([Caller Digital](https://caller.digital/blog/top-10-voice-ai-agents-india-2026)).
  A built-in consent ledger, DND scrub, AI disclosure, CLI declaration register and spam-reputation
  guard is a real differentiator. The Air AI case shows what overclaiming costs: an FTC ban and an $18M
  judgment in Mar 2026 ([FTC](https://www.ftc.gov/news-events/news/press-releases/2026/03/air-ai-its-owners-will-be-banned-marketing-business-opportunities-settle-ftc-charges-company-misled)).
- **Opportunity 2: WhatsApp as the second voice channel.** The WhatsApp Business Calling API is
  generally available. Calls from customers to the business are **free**, and the business can call
  customers who have given call permission ([Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing)).
  Samvaad already sends WhatsApp follow-ups, so this extends existing work.
- **Opportunity 3: Indic breadth with auto-detect and code-mixing.** Samvaad ships English, Hindi,
  Urdu and Hinglish today. Sarvam Saaras v3 does streaming STT in all 22 scheduled languages with
  language detection ([Republic](https://www.republicworld.com/tech/sarvam-launches-saaras-v3-strengthens-lead-in-22-indian-language-speech-recognition)),
  and Bulbul v3 covers 11 languages ([Sarvam](https://www.sarvam.ai/blogs/bulbul-v3)). Most of the
  models are already there; Samvaad needs the product layer on top.
- **Opportunity 4 and 5: a transparent all-in price, and QA as a product.** The default India stack
  costs about **₹2.9/min** (§6), while Indian buyers pay **₹6–25/min effective**
  ([Caller Digital](https://caller.digital/blog/voice-ai-vendor-pricing-teardown-india-2026)). That leaves
  room for a flat ₹5–6/min all-in price with healthy margin. Separately, the Test lab can grow into
  regression suites and auto-QA, and then into QA for human agents' calls: an adjacent product that
  sells to every Indian contact centre scoring only ~2% of calls today
  ([Mihup](https://mihup.ai/blog/automated-agent-scoring-ai-contact-center)).

---

## 2. Competitor matrix

"All-in" means platform + STT + LLM + TTS + telephony, as typically reported.

| Vendor | Segment | Pricing model | Headline → typical all-in | Indic support | Standout features | Threat to Samvaad |
|---|---|---|---|---|---|---|
| **Vapi** | Global, developer-first orchestration | $0.05/min platform + pass-through; 10 concurrent lines included, $10/line; HIPAA $2k/mo | $0.05 → **$0.13–0.33/min** | Through pluggable STT/TTS; nothing native | Squads (multi-agent handoff), Simulations/test suites, LLM-graded scorecards, A/B experiments, Composer (natural-language builder), web/iOS SDKs; Workflows retired 18 Aug 2026 | High for developers |
| **Retell AI** | Global, developer + ops | $0.07/min voice engine + LLM + telephony; 20 concurrent free, $8/slot | $0.07 → **$0.13–0.31/min** | 80+ languages via providers | Simulation testing, AI QA add-on ($0.10/min), warm transfer with briefing, auto-syncing KB, batch calls, branded caller ID, SOC 2 Type II/HIPAA, PII redaction, ~600 ms | High |
| **Bland AI** | Global, enterprise-leaning | Bundled: $0.14 (free plan, 100 calls/day), $0.12 + $299/mo, $0.11 + $499/mo | **$0.11–0.14/min** all-in | Limited | Pathways (graph builder), self-hosted models, VPC/on-prem, transfer billed $0.03–0.05/min | Medium |
| **Synthflow** | Global SMB/agency, no-code | Pay-as-you-go since Dec 2025 (voice engine ~$0.09/min + LLM); enterprise from $30k/yr | **$0.15–0.24/min** effective | Via ElevenLabs voices | Best **agency white-label** (sub-accounts, custom domain, Stripe rebilling, GoHighLevel), Flow Designer, KB recall claimed 75%→96% | Medium (agency segment) |
| **ElevenLabs Agents** | Global, voice-quality leader | $0.08/min (burst $0.16) + LLM + telephony; plans with included minutes and concurrency | ~$0.10–0.20/min | 31 languages, 12 Indian voices; not India-compliance aware | Workflow builder, KB/RAG, A/B tests on live traffic, automated agent tests, batch calling, widget/SDKs, CLI, hosted MCP | High on quality |
| **PolyAI** | Enterprise inbound CX | ~$150k/yr+ plus usage; self-serve Agent Studio free for 2 months since May 2026 | Custom | 45 languages | Draft/sandbox/live environments, own ASR, voice + chat + SMS on one agent | Low (different buyer) |
| **Sierra** | Enterprise CX | Outcome-based, ~$1.50/resolution; $150k+/yr | Custom | Limited | Outcome pricing, agent SDK | Low |
| **Decagon** | Enterprise CX | ~$50k/yr platform + per conversation | Custom | Limited | AOPs, Duet (auto-drafts procedures and tests), outbound voice since spring 2026 | Low |
| **Cognigy (NICE)** | Enterprise CCaaS | Enterprise licence | Custom | Broad | Bought by NICE for ~$955M (closed Sep 2025); generates and tests agents from engagement data | Low |
| **Air.ai** | Defunct in practice | $25–100k upfront licences | n/a | n/a | FTC case; banned Mar 2026 | None, but a cautionary tale |
| **Yellow.ai** | Indian enterprise omnichannel | Enterprise | Custom | Nexus Vox (May 2026): 20+ Indian languages, voice cloning, <400 ms claimed | Medium in enterprise |
| **Haptik (Jio)** | Indian enterprise | Enterprise | Custom | Published WER for 8 Indian languages | Medium in enterprise |
| **Gnani.ai (Inya)** | Indian BFSI enterprise | Custom INR; 6–9 month sales cycles | Custom | 12+ Indic, voice biometrics, 30M+ conversations/day | Medium (BFSI) |
| **Sarvam Samvaad** | Indian full-stack sovereign | Enterprise; self-serve coming | Custom | Best-in-class Indic models (11 TTS, 22 STT languages) | 2M+ voice conversations/day; Mahindra Finance 10M+ calls in 12 languages | **High, and the same name** |
| **Smallest.ai (Atoms)** | India/US, developer | From $0.05/min by model; $10 credit | ~$0.05–0.10/min | Lightning TTS strong in Hindi/Tamil | Own STT (Pulse), TTS (Lightning), speech-to-speech (Hydra) | Medium |
| **Bolna** | Indian developer platform | ~6¢/min standard; pilot 4.2¢/min; telephony extra | ~₹5.5/min | Sarvam-powered | Open-source roots, developer API | **High (same buyer)** |
| **Exotel / Ozonetel** | Indian CPaaS/CCaaS incumbents | Seats + minutes | ₹0.6–1.5/min telephony | Hindi/English production-grade | Exotel: GenAI voicebot, AgentStream bidirectional streaming, bought the Dubverse team (Apr 2026). Ozonetel: dialer + QM | Medium; also **potential telephony partners** |
| **Twilio (ConversationRelay)** | Global CPaaS | $0.07/min + voice minutes | ~$0.09–0.15/min before LLM | Via providers | 491 ms p50 benchmark, Conversational Intelligence | Low (infrastructure) |
| **Plivo AI Agents** | Global/India CPaaS | Voice ₹0.38/min in India + AI | Low | Via Deepgram/ElevenLabs | "Vibe Agent" natural-language builder; one agent with shared memory across voice/SMS/WhatsApp/chat | Medium; **telephony partner** |
| **Telnyx Voice AI** | Global CPaaS | $0.05/min incl. STT/TTS; LLM extra | ~$0.07/min | Limited | Owns its carrier network | Low; already integrated |
| **Caller Digital / Ringg / SquadStack** | Indian vertical players | INR per outcome (₹8–25) or per minute | — | 14 Indian languages (Caller Digital) | Pre-built agents for COD checks, EMI reminders and NPS; TRAI DLT, DPDP, RBI and IRDAI built in | **High for SMB verticals** |

### Notes per competitor

- **Vapi.** The developer default. Its weak point is cost stacking: platform, then STT/LLM/TTS, then
  concurrency lines, then HIPAA $2k/mo and zero data retention $1k/mo
  ([Zeeg](https://zeeg.me/en/blog/post/vapi-ai-pricing), [Cekura](https://www.cekura.ai/blogs/vapi-ai-pricing)).
  It dropped visual Workflows in favour of Assistants + Squads ([Vapi docs](https://docs.vapi.ai/workflows/legacy-migration)),
  a sign that prompt + tools + handoff beats big flow graphs. Samvaad's campaign/template model fits that direction.
- **Retell.** The most complete feature list: simulations, QA add-on, warm transfer, KB auto-sync,
  branded caller ID and SOC 2/HIPAA ([Cekura feature list](https://www.cekura.ai/blogs/retell-ai-voice-automation-features)).
  Use it as the checklist to benchmark against.
- **Bland.** Moved from $0.09 flat to plan tiers in Dec 2025 ([getmacha](https://www.getmacha.com/blog/bland-ai-pricing-explained),
  [Bland pricing](https://www.bland.ai/pricing)). Bundled all-in pricing is simple and sells well to
  non-technical buyers. Samvaad should offer the same simplicity in INR.
- **Synthflow.** Won the agencies with white-label and rebilling
  ([Synthflow docs](https://docs.synthflow.ai/about-agency-whitelabel)). Agencies are the fastest
  distribution channel for SMB voice AI in India too (lead-gen and real-estate agencies).
- **ElevenLabs.** Best voices, plus A/B tests on live traffic, automated tests and a hosted MCP
  server for building agents ([docs](https://elevenlabs.io/docs/agents-platform/overview),
  [pricing](https://elevenlabs.io/pricing/agents)). It is weak in India on latency and USD/FX billing
  ([Caller Digital](https://caller.digital/blog/voice-ai-vendor-pricing-teardown-india-2026)).
- **PolyAI / Sierra / Decagon / Cognigy.** Enterprise inbound CX, sold on six-figure contracts and
  outcomes ([Synthflow on PolyAI](https://synthflow.ai/blog/polyai-review),
  [Retell on Sierra vs Decagon](https://www.retellai.com/blog/sierra-vs-decagon),
  [NICE](https://www.nice.com/press-releases/nice-closes-acquisition-of-cognigy-transforming-customer-experience-with-best-in-class-data-driven-cx-ai-platform)).
  Two ideas are worth borrowing: **draft/sandbox/live versioning** (PolyAI) and **auto-generated
  tests from real transcripts** (Decagon Duet).
- **Air.ai.** The FTC sued in Aug 2025 over "AI washing" and refund claims, and a ban followed in Mar 2026
  ([FTC](https://www.ftc.gov/news-events/news/press-releases/2025/08/ftc-sues-stop-air-ai-using-deceptive-claims-about-business-growth-earnings-potential-refund)).
  Lesson: publish real metrics and honest limits, and keep refunds simple.
- **Yellow.ai / Haptik / Gnani.** Indian enterprise vendors with omnichannel reach and Indic
  benchmarks ([The Wire on Nexus Vox](https://m.thewire.in/article/ptiprnews/built-in-bharat-yellow-ai-launches-nexus-vox-the-first-enterprise-voice-ai-that-can-clone-any-voice-and-deploy-it-across-500-languages-in-under-a-second),
  [Haptik](https://www.haptik.ai/blog/voice-ai-agents-for-indian-languages), [Gnani](https://www.gnani.ai/inya-workforce-automate365-ai)).
  Their long sales cycles leave the self-serve mid-market open.
- **Sarvam.** Both supplier and competitor. Its models are the best Indic building blocks
  ([API pricing](https://www.sarvam.ai/api-pricing)). Samvaad can differentiate on multi-provider
  choice, campaign operations, MCP tools and compliance, not on model quality.
- **Bolna / Smallest / Caller Digital / Ringg.** The direct India mid-market fight: INR pricing,
  Sarvam-based stacks, vertical templates ([Bolna pricing](https://www.bolna.ai/pricing),
  [Smallest pricing](https://smallest.ai/pricing/agents)). Caller Digital's pitch is compliance built
  in plus per-outcome pricing, which is the direction Samvaad should take, but self-serve.
- **Exotel / Plivo / Ozonetel.** Partner with them before competing. Samvaad needs an Indian
  carrier with bidirectional media streaming. Plivo has the best developer experience and price
  (₹0.38/min, number ₹200/mo, DIDs in 24–48 h). Exotel is stronger on DLT/compliance, at 10–25% more
  per minute ([Caller Digital telephony comparison](https://caller.digital/blog/telephony-partner-voice-ai-india-plivo-exotel-ozonetel-knowlarity-twilio-2026)).

---

## 3. Table-stakes checklist

Status is based on the current repo: `src/voiceagent/**`, the `/api/*` routes, `templates.LANGUAGES`
(en, hi, ur, hi-en), and AMD handling in `voice/pipeline.py`.

| Capability buyers expect | Samvaad | Notes |
|---|---|---|
| Outbound campaigns, retries, calling windows, concurrency cap | **Have** | `max_concurrent_calls`, per-timezone windows |
| Batch upload + per-contact variables | **Have** | CSV parse, dedupe, suppression on import |
| Live monitoring, whisper, hang up | **Have** | Ahead of most Indian players |
| Transcripts, recordings, post-call extraction, sentiment, score | **Have** | |
| Human review queue | **Have** | Differentiator |
| Follow-up SMS/WhatsApp, webhooks (HMAC), calendar | **Have** | |
| Tool calling during calls | **Have** (MCP) | Differentiator; add a native HTTP tool for non-MCP APIs |
| Multi-provider LLM | **Partial** | One active provider via env vars; bring-your-own keys and per-campaign model are planned |
| Voice choice per campaign | **Partial** | Planned |
| Voicemail detection + drop | **Partial** | Twilio/Telnyx AMD, then a spoken message. No pre-recorded drop, no beep-wait tuning, no LiveKit AMD |
| Inbound calls / receptionist | **Missing** | |
| Knowledge base / RAG | **Missing** | |
| Warm / cold transfer to a human | **Missing** | Planned "later"; move it up |
| Simulation tests / regression suites | **Partial** | Test lab runs single simulated calls; no suites, rubric scoring or diffs between versions |
| A/B testing of prompts, voices, openers | **Missing** | |
| Agent versioning, draft → live, rollback | **Missing** | |
| Analytics dashboards | **Partial** | Overview 7/30 days; no funnel, cost per outcome or latency percentiles |
| Latency telemetry (p50/p95 per turn) | **Missing** | Industry target: p50 < 700 ms, p95 < 1.2 s ([DestiLabs](https://www.destilabs.com/blog/ai-voice-agent-benchmark-2026)) |
| Indic languages ≥ 10 + auto-detect | **Partial** | 4 today (en, hi, ur, Hinglish); more planned |
| Indian telephony (Indian caller ID, INR per-minute) | **Missing** | Twilio/Telnyx/LiveKit only |
| DND / do-not-call | **Partial** | Internal list only; no NCPR/DND registry scrub |
| TRAI 140/1600 + A2P declaration register | **Missing** | |
| Consent capture with proof (TCPA / DPDP) | **Missing** | |
| AI + recording disclosure enforced | **Missing** | Nothing forces an opening disclosure |
| PII redaction, retention policies | **Missing** | MCP redaction covers secrets only |
| Accounts, roles, invites | **Have** | |
| SSO, audit log, SOC 2 posture | **Missing** | |
| Public REST API + API keys + SDKs | **Missing** | The API is console-only (session auth) |
| Embeddable web voice widget | **Missing** | |
| Phone number provisioning in-app | **Missing** | |
| Usage metering, credits, invoices (INR/USD) | **Missing** | `/api/estimate` covers LLM only |
| Multi-tenant / agency / white-label | **Missing** | Single workspace |

---

## 4. Idea backlog (40 ideas)

Format: **Name** — user value · *for* · Effort (S ≤ 1 week, M 2–4 weeks, L > 1 month) · Impact (1–5) ·
evidence.

### A. Core calling quality

1. **Indian carrier adapter (Plivo first, Exotel second)** — Indian mobile caller IDs, 12× cheaper
   minutes and better pickup · *all India customers* · M · **5** ·
   ₹0.38/min vs Twilio $0.0496/min to Indian mobiles ([Plivo](https://www.plivo.com/voice/pricing/in/),
   [Twilio](https://www.twilio.com/en-us/voice/pricing/in)); mobile-series caller IDs reach >80% pickup vs
   25–30% for 080/079 numbers ([Vomyra](https://vomyra.com/)).
2. **Latency meter** — log per-turn STT-final → first-audio time; show p50/p95 on each call and
   campaign; alert when p95 goes above 1.2 s · *ops, and Samvaad itself* · S · **4** ·
   production fleets run at 680 ms p50 / 1,180 ms p95 ([DestiLabs](https://www.destilabs.com/blog/ai-voice-agent-benchmark-2026));
   Twilio publishes 491 ms p50 ([same source](https://www.destilabs.com/blog/ai-voice-agent-benchmark-2026)).
3. **Indic turn-taking pack** — tuned endpointing, barge-in and backchannels ("haan ji", "achha")
   so the agent neither talks over callers nor leaves dead air · *India campaigns* · M · **4** ·
   conversational STT with turn detection (Deepgram Flux, $0.0065/min) is now standard
   ([Deepgram pricing](https://deepgram.com/pricing)).
4. **Language auto-detect and mid-call switching across 10+ Indic languages** — a caller can
   answer in Telugu and the agent follows · *India* · M · **5** · Saaras v3 streams 22 languages with
   detection ([Republic](https://www.republicworld.com/tech/sarvam-launches-saaras-v3-strengthens-lead-in-22-indian-language-speech-recognition));
   MyOperator sells mid-call switching ([Caller Digital](https://caller.digital/blog/top-10-voice-ai-agents-india-2026)).
5. **Pronunciation and normalisation dictionary** — ₹ amounts, dates, EMI numbers, PIN codes,
   brand and person names read correctly in each language · *all* · S · **4** · the most common
   complaint about Indic TTS; Bulbul v3 added LLM prosody for this reason
   ([Sarvam](https://www.sarvam.ai/blogs/bulbul-v3)).
6. **Better voicemail handling** — wait for the beep, drop pre-recorded audio (cheaper, no TTS),
   AMD for LiveKit, and IVR/DTMF navigation for B2B calls · *US, B2B* · S–M · **3** · Twilio AMD
   $0.0075/call ([Twilio US](https://www.twilio.com/en-us/voice/pricing/us)); Retell sells IVR navigation.
7. **Warm transfer with a whisper summary** (planned, pull forward) — hand the live caller to a human
   who hears a 10-second brief first · *sales, support, collections* · M · **5** · table stakes at
   Retell, Bland and Vapi; Bland bills transfer time at $0.03–0.05/min ([Bland](https://www.bland.ai/pricing)).
8. **Per-campaign choice of speech-to-speech or cascaded pipeline** — show the cost and latency
   trade-off in the UI · *cost-sensitive buyers* · M · **3** · Gemini 3.8 Live audio is
   $0.005/min in and $0.018/min out ([Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing)).

### B. Build and configure (studio)

9. **Knowledge base** — upload PDF/DOCX, add URLs with auto re-sync, retrieve during the call,
   show which chunk was used in the transcript · *all* · M · **5** · table stakes (Retell KB
   auto-sync, ElevenLabs RAG, Synthflow recall 96%) ([Cekura](https://www.cekura.ai/blogs/retell-ai-voice-automation-features),
   [Synthflow changelog](https://feedback.synthflow.ai/changelog)).
10. **Bring-your-own keys through one OpenAI-compatible adapter** (planned, extend) — one adapter
    with `base_url` covers OpenRouter, Groq, Together, Fireworks, DeepSeek, Mistral, Azure OpenAI v1,
    Sarvam, NVIDIA, Ollama and vLLM; keep native Anthropic and Gemini adapters for prompt caching and
    Live audio · *developers, cost-sensitive buyers* · M · **5** · see §6.4.
11. **Scenario suites and regression runs** — turn the Test lab into saved suites of simulated
    callers (angry, busy, wrong person, code-mixing, "call me later"), each scored against a rubric,
    re-run on every prompt change with a pass/fail diff · *everyone shipping prompts* · M · **5** · Vapi
    Simulations, Retell simulation testing, a whole category of tools (Coval, Hamming, Cekura)
    ([Speechmatics roundup](https://www.speechmatics.com/company/articles-and-news/de-risk-your-voice-agent-11-best-voice-agent-testing-platforms)).
12. **Generate tests from real calls** — one click turns a failed or flagged call from the review
    queue into a regression scenario · *ops* · S · **4** · Decagon Duet does this
    ([Drag](https://www.dragapp.com/blog/decagon-vs-sierra/)); Samvaad's review queue already holds the input.
13. **Agent versioning: draft → test → live, with rollback** · *teams* · M · **4** · PolyAI Agent
    Studio has draft/sandbox/live ([Synthflow on PolyAI](https://synthflow.ai/blog/polyai-review)).
14. **A/B experiments** — split live traffic between prompts, openers or voices; pick the winner on
    the extracted outcome rate with a significance check · *sales, collections* · M · **4** ·
    ElevenLabs and Vapi both ship this ([ElevenLabs docs](https://elevenlabs.io/docs/agents-platform/overview)).
15. **"Describe it" builder** — plain-language brief → persona, goal, extraction schema, follow-up
    template and a test suite, in any supported language · *SMB, non-technical* · S–M · **4** · Plivo
    "Vibe Agent", Vapi Composer ([Plivo](https://www.plivo.com/blog/end-to-end-guide-to-plivo-ai-agents-platform/)).
16. **Voice lab** (with the planned per-campaign voice) — preview voices per language, set speed and
    pitch, save a brand voice; voice cloning only with a recorded consent statement · *brands* · M ·
    **3** · Yellow.ai Nexus Vox leads on cloning ([The Wire](https://m.thewire.in/article/ptiprnews/built-in-bharat-yellow-ai-launches-nexus-vox-the-first-enterprise-voice-ai-that-can-clone-any-voice-and-deploy-it-across-500-languages-in-under-a-second)).
17. **Native HTTP tool** — call any REST endpoint mid-call without writing an MCP server · *SMB,
    developers* · S · **3** · every competitor offers custom functions; MCP is powerful but has a
    higher barrier.

### C. Channels beyond outbound calls (separate functionalities)

18. **Inbound AI receptionist / IVR replacement** — answer a number 24×7, answer FAQs from the KB,
    book, route, transfer, take messages · *clinics, real estate, D2C, SMB* · L · **5** · the largest
    SMB use case globally; inbound avoids TRAI's rules on outgoing commercial calls; users can reuse
    campaign agents.
19. **WhatsApp Business Calling agent** — the same agent answers WhatsApp voice calls (free when the
    customer calls) and places calls with permission · *India* · M–L · **5** · GA with 6-second-pulse
    per-minute billing ([Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing),
    [respond.io](https://respond.io/whatsapp-business-calling-api)).
20. **WhatsApp voice-note and chat agent** — the agent replies to voice notes and texts with the same
    persona, tools and memory as the calls · *India* · M · **4** · Plivo sells shared memory across
    channels ([Plivo](https://www.plivo.com/blog/end-to-end-guide-to-plivo-ai-agents-platform/)); utility
    messages cost ₹0.115 ([whautomate](https://whautomate.com/whatsapp-business-api-pricing-india)).
21. **Missed-call → AI callback** — give out a missed-call number; Samvaad calls back within 60
    seconds in the caller's language · *India lead generation, D2C* · S (after #1) · **4** · an
    India-native pattern; an inbound callback isn't cold calling
    ([CallMissed](https://www.callmissed.com/blog/whatsapp-ai-voice-agent-india-callmissed-production)).
22. **Embeddable web voice widget** — `<script>` snippet with a "Talk to us" button over WebRTC,
    using the same agent · *SaaS, D2C sites* · M · **4** · ElevenLabs, Vapi and Retell all ship one;
    Plivo WebRTC is ₹0.25/min ([Plivo IN](https://www.plivo.com/voice/pricing/in/)).
23. **Collections and reminders pack** — EMI/COD/renewal reminders with a UPI payment link sent by
    SMS/WhatsApp during the call, promise-to-pay captured, schedule by due date · *NBFCs, MFIs,
    D2C COD* · M · **5** · Mahindra Finance ran 10M+ calls with Sarvam; an MFI reports 79% pickup
    ([Vomyra](https://vomyra.com/)); Caller Digital sells EMI/COD agents.
24. **Voice surveys / NPS** — short structured surveys with scores extracted into a dashboard ·
    *D2C, healthcare, education* · S · **3** · a templates-only extension.
25. **Call QA for human agents (separate SKU)** — upload or connect human call recordings, get
    diarised Indic transcripts, rubric scores, compliance flags and coaching notes · *contact centres,
    inside-sales teams* · M · **4** · AI QA replaces 2% manual sampling
    ([Mihup](https://mihup.ai/blog/automated-agent-scoring-ai-contact-center),
    [AmplifAI](https://www.amplifai.com/blog/call-center-quality-assurance-software)); Saaras v3 has
    diarisation at ₹30/hr ([Sarvam](https://www.sarvam.ai/api-pricing)). It reuses extraction and scoring.
26. **Real-time agent assist** (later) — live transcript plus next-best-answer for human callers ·
    *contact centres* · L · **3** · crowded (Cresta, Mihup); only after #25.

### D. Analytics and QA

27. **Outcome funnel** — dialled → connected → conversation → qualified → booked, sliced by campaign,
    language, hour, caller ID and version; plus **best time to call**, where the scheduler learns
    answer rates by hour and weekday and adapts within the allowed windows · *managers* · S–M · **4**.
28. **Auto-QA scorecard on every AI call** — rubric score, policy/hallucination flags, "moments",
    full-text search across transcripts · *ops* · M · **4** · Retell charges $0.10/min for AI QA
    ([Cekura](https://www.cekura.ai/blogs/retell-ai-voice-automation-features)); Vapi scorecards.
29. **Cost per outcome** — ₹ per connected call, per qualified lead, per booking, from metered usage ·
    *buyers justifying spend* · S (after #37) · **4** · Indian buyers compare against a ₹8–25 per-outcome
    market ([Caller Digital](https://caller.digital/blog/top-10-voice-ai-agents-india-2026)).
### E. Integrations

30. **Public API + API keys + webhooks-in** — create contacts and trigger a call from any form
    (speed-to-lead in under 60 s), Python/JS SDK, OpenAPI docs · *developers, agencies* · M · **5** ·
    table stakes at every global competitor.
31. **India-first CRM connectors** — Zoho CRM, LeadSquared, Freshsales, HubSpot, Salesforce, Google
    Sheets, plus Zapier/Make/n8n apps; and more calendars (Cal.com, Calendly, Outlook) · *SMB, mid-market* · M (each S) · **5** · buyers expect results in
    the CRM; MCP covers power users, native connectors cover everyone else.
32. **Samvaad as an MCP server** — let Claude, ChatGPT or any agent create campaigns, place a test
    call and read outcomes · *AI-native teams* · S–M · **3** · ElevenLabs hosts an MCP server for
    agent building ([docs](https://elevenlabs.io/docs/agents-platform/overview)); Samvaad already has
    the MCP expertise.

### F. Compliance and trust

33. **India compliance pack** — (a) consent ledger: source, timestamp, purpose, proof, the DPDP
    notice shown, per contact; (b) DND/NCPR scrub hook through the carrier or DLT platform; (c) a
    register of declared A2P caller IDs, with 140-series (promotional) and 1600-series (BFSI/govt
    service) tagging per campaign; (d) a mandatory "this is an automated call from ___" opening,
    enforced; (e) promotional calling hours guard · *every India customer* · M · **5** ·
    TCCCPR Feb 2025 + third amendment 18 Sep 2026
    ([ETV Bharat](https://www.etvbharat.com/en/business/trai-tightens-regulations-on-spam-callers-to-leverage-ai-tools-to-detect-unsolicited-calls-enn26091805208),
    [Frejun](https://frejun.com/auto-dialer-robocall-140-series-trai-rules-india/)); fines up to ₹10 lakh per
    violation; DPDP consent managers from 13 Nov 2026, full duties by 13 May 2027
    ([PIB](https://www.pib.gov.in/PressReleasePage.aspx?PRID=2190014&reg=3&lang=2)).
34. **US / TCPA mode** — AI-voice disclosure, prior-express-consent checkbox with proof, state
    quiet hours, federal DNC scrub integration · *US customers* · S–M · **4** · the FCC ruled AI voices
    are "artificial" under the TCPA (Feb 2024) and proposed AI-specific consent and disclosure
    ([FCC](https://www.fcc.gov/document/fcc-makes-ai-generated-voices-robocalls-illegal),
    [Wiley](https://www.wiley.law/alert-FCC-Extends-Regulatory-Reach-Over-AI-Announces-TCPA-Restrictions-Cover-AI-Generated-Voices-in-Outbound-Calls)).
35. **Caller-ID reputation guard** — per-number daily caps, answer-rate drop alerts, cool-down and
    rotation *within declared numbers only* · *high-volume outbound* · S–M · **4** · TRAI can act when
    5+ caller lines from one sender are flagged in 10 days; operators now use AI spam detection and
    caller-ID apps must share spam reports
    ([Business Standard](https://www.business-standard.com/technology/tech-news/ai-calls-how-to-identify-legitimate-calls-spam-scams-126091500686_1.html));
    CNAP shows KYC-verified caller names ([Mondaq](https://www.mondaq.com/india/telecoms-mobile-cable-communications/1715710/india-rolls-out-cnap-in-2026-official-caller-name-display-to-fight-spam-powered-by-kyc-databases-and-privacy-opt-out)),
    so register the business name on the CLI.
36. **PII redaction + retention + data-subject requests** — mask Aadhaar, PAN, card numbers and
    OTPs in transcripts and recordings; retention per workspace; export and delete per contact;
    audit log; India data residency option; SSO later · *BFSI, healthcare, enterprise* · M · **4** ·
    Retell ships PII redaction and SOC 2 ([Cekura](https://www.cekura.ai/blogs/retell-ai-voice-automation-features));
    DPDP duties apply from May 2027.

### G. Monetisation and platform

37. **Usage metering + prepaid wallet billing** — per-second metering of telephony, STT, LLM and TTS;
    wallet in INR (Razorpay, GST invoice) and USD (Stripe); low-balance auto-pause of campaigns ·
    *all paying customers* · M · **5** · prerequisite for #29, #39 and #40; Bolna uses a wallet with
    carry-over ([Bolna](https://www.bolna.ai/pricing)).
38. **Full-stack cost calculator** — extend `/api/estimate` (LLM-only today) to telephony by country,
    STT, TTS, WhatsApp and extraction, fed by the §6 tables · *buyers, sales* · S · **4** ·
    hidden costs are the top complaint about Vapi/Retell
    ([CloudTalk](https://www.cloudtalk.io/blog/vapi-ai-pricing/)).
39. **Agency / white-label mode** — sub-accounts, custom domain and logo, feature toggles,
    rebilling with markup · *agencies and resellers* · L · **4** · Synthflow's main differentiator
    ([Synthflow docs](https://docs.synthflow.ai/about-agency-whitelabel)).
40. **Outcome-based plan** — ₹ per qualified lead or confirmed booking for proven templates ·
    *SMBs who distrust per-minute* · S (after #37) · **3** · Caller Digital ₹8–25/outcome; Sierra
    ~$1.50/resolution ([Retell](https://www.retellai.com/blog/sierra-vs-decagon)).

---

## 5. Recommended roadmap

### Next release: "Ready for India" (6–8 weeks)

| # | Item | Why now |
|---|---|---|
| 1 | **Plivo carrier adapter** (#1), Indian caller IDs, INR rates | Unit economics fall 12× and pickup improves. Nothing else matters for India until this lands. |
| 2 | **India compliance pack v1** (#33 a, c, d; #35 caps and alerts) | The 18 Sep 2026 TRAI amendment makes undeclared automated calls spam, and AI disclosure is now expected. Shipping this is also the sales pitch. |
| 3 | **Knowledge base** (#9) | The most-asked-for table-stakes gap; unlocks inbound later. |
| 4 | **Bring-your-own keys through the OpenAI-compatible adapter + full-stack cost calculator** (#10, #38) | Already planned; one adapter covers ~12 providers, and the calculator makes the "transparent price" claim concrete. |
| 5 | **Indic expansion: Telugu, Tamil, Kannada, Marathi, Bengali, Gujarati + auto-detect + pronunciation dictionary** (#4, #5) | Already planned (Telugu). The Saaras v3 / Bulbul v3 coverage is available now. |
| 6 | **Warm transfer** (#7) | Move it from "later": without a human fallback, buyers won't point real customers at the agent. |
| 7 | **Scenario suites + tests from flagged calls** (#11, #12) | Cheap to build on the Test lab and review queue, and it protects every later prompt change. |
| 8 | **Latency meter** (#2) | Needed to verify #1 and #5 don't regress the ~800 ms budget in the README. |

The planned pre-call SMS/WhatsApp heads-up belongs in this release too. It's S effort, and TRAI
now tightens how long a business may contact someone after an inquiry (7 days, with proof),
so the heads-up should also record consent.

### Following release: "One agent, every channel" (next 2–3 months)

- **Inbound receptionist** (#18) and **missed-call callback** (#21).
- **WhatsApp calling + voice notes** (#19, #20).
- **Public API + keys + SDK** (#30) and the first **CRM connectors**: Zoho, LeadSquared, HubSpot,
  Sheets, n8n/Zapier (#31).
- **Usage metering + wallet billing** (#37), then **cost per outcome** (#29) and the **funnel** (#27).
- **Versioning + A/B experiments** (#13, #14) and **auto-QA scorecards** (#28).
- **PII redaction + retention + DPDP export/delete** (#36), before the May 2027 DPDP deadline.
- **Web widget** (#22) and the **"describe it" builder** (#15).

Rationale: after the India basics, reusing the same agent across inbound, WhatsApp and the web is
the cheapest way to become one-stop. API and billing turn the product into a platform.

### Later (quarter 2+)

- **Call QA for human agents** as a separate SKU (#25), then **real-time agent assist** (#26).
- **Agency / white-label** (#39) and **outcome-based pricing** (#40).
- **Collections pack with UPI links** (#23) as the first vertical bundle, then surveys/NPS (#24).
- **Voice lab + consented brand voices** (#16), **speech-to-speech option** (#8).
- **Samvaad MCP server** (#32), native HTTP tool (#17).
- **Enterprise:** SSO, audit log export, SOC 2 Type II / ISO 27001, India data-residency option,
  US TCPA mode (#34) when the first US customer signs.

**Deliberately not recommended:** one-way voice broadcast/robocalls (the TRAI crackdown targets
exactly this; low differentiation), visual flow-graph builders (Vapi retired theirs), and a
proprietary Indic model (Sarvam, AI4Bharat and Smallest already compete there).

---

## 6. Cost-calculator reference data

### 6.1 Per-minute conversation assumptions

| Quantity | Value used | Reasoning |
|---|---|---|
| Agent turns per minute | 4 | Typical phone cadence |
| LLM input tokens per minute | **12,000** uncached | ~2k system/persona + growing history, re-sent every turn (≈2.9k × 4). With prompt caching, 70–90% of this is billed at the cached rate |
| LLM output tokens per minute | **200** | ~40–50 tokens per spoken turn |
| TTS characters per minute | **500** | Agent speaks ~half the time at ~150 wpm (English); similar in Devanagari |
| STT minutes per minute | 1.0 | Caller channel streamed for the whole call |
| Post-call extraction | 4k in / 400 out per call | One structured extraction on a mid-tier model |
| Average connected call | 3 min | Spreads per-call costs (extraction, AMD, WhatsApp) over the minutes |

### 6.2 LLM list prices (USD per 1M tokens, standard tier) and cost per conversation minute

Cost per minute = 12k × input + 200 × output, uncached. Prices are as of 25–27 Sep 2026.

| Model | Provider | Input | Output | $/conv-min | OpenAI-compatible? | Source |
|---|---|---|---|---|---|---|
| GPT-5 nano | OpenAI | 0.05 | 0.40 | 0.0007 | native | [OpenAI](https://developers.openai.com/api/docs/pricing) |
| GPT-6 Luna | OpenAI | 0.10 | 0.50 | 0.0013 | native | same |
| GPT-4o mini | OpenAI | 0.15 | 0.60 | 0.0019 | native | same |
| GPT-5.6 Luna | OpenAI | 0.20 | 1.20 | 0.0026 | native | same |
| GPT-5 mini | OpenAI | 0.25 | 2.00 | 0.0034 | native | same |
| GPT-4.1 mini | OpenAI | 0.40 | 1.60 | 0.0051 | native | same |
| GPT-5.4 mini | OpenAI | 0.75 | 4.50 | 0.0099 | native | same |
| GPT-4.1 | OpenAI | 2.00 | 8.00 | 0.0256 | native | same |
| GPT-6 Sol | OpenAI | 2.00 | 10.00 | 0.0260 | native | same |
| GPT-4o | OpenAI | 2.50 | 10.00 | 0.0320 | native | same |
| Claude Haiku 4.5 | Anthropic | 1.00 | 5.00 | 0.0130 | test-only compat layer; use native | [Claude pricing](https://claude.com/pricing) |
| Claude Sonnet 5 | Anthropic | 2.00 | 10.00 | 0.0260 | native adapter | same |
| Claude Opus 5.5 | Anthropic | 4.00 | 20.00 | 0.0520 | native adapter | same |
| Gemini 2.5 Flash-Lite | Google | 0.10 | 0.40 | 0.0013 | yes (`/v1beta/openai/`) | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| Gemini 3.1 Flash-Lite | Google | 0.25 | 1.50 | 0.0033 | yes | same |
| Gemini 2.5 Flash | Google | 0.30 | 2.50 | 0.0041 | yes | same |
| Gemini 3.8 Flash | Google | 0.75* | 3.75* | 0.0098 | yes | same |
| Gemini 3.1 Pro (preview) | Google | 2.00 | 12.00 | 0.0264 | yes | same |
| Llama 3.1 8B Instant | Groq | 0.05 | 0.08 | 0.0006 | yes | [CloudZero on Groq](https://www.cloudzero.com/blog/groq-pricing/) |
| Llama 3.3 70B Versatile | Groq | 0.59 | 0.79 | 0.0072 | yes | same |
| DeepSeek V4.1 Flash (peak / off-peak) | DeepSeek | 0.30 / 0.15 | 1.20 / 0.60 | 0.0038 / 0.0019 | yes | [DeepSeek](https://api-docs.deepseek.com/quick_start/pricing) |
| DeepSeek V4 Pro (peak) | DeepSeek | 1.32 | 3.96 | 0.0166 | yes | same |
| Mistral Small 4 | Mistral | 0.15 | 0.60 | 0.0019 | mostly | [BenchLM](https://benchlm.ai/llm-pricing) |
| Mistral Large 3 | Mistral | 0.50 | 1.50 | 0.0063 | mostly | same |
| Qwen3.5 Flash | Alibaba | 0.10 | 0.40 | 0.0013 | yes (via OpenRouter/Together) | same |
| **Sarvam 105B** | Sarvam | ₹29.28 (≈0.305) | ₹73.20 (≈0.763) | **0.0038 (₹0.37)** | yes (`api.sarvam.ai/v1`) | [Sarvam](https://www.sarvam.ai/api-pricing) |

\* Gemini 3.7/3.8 Flash prices double on 1 Jan 2027 ($1.50/$7.50). **Sarvam-M** (24B, open weights)
is no longer on Sarvam's price list; self-host it with vLLM or reach it through NVIDIA NIM
([NVIDIA](https://docs.api.nvidia.com/nim/reference/sarvamai-sarvam-m)).
Takeaway: for a mini/flash-class model, **the LLM is under ₹1 per minute**. TTS and telephony
dominate the bill, so the calculator must model those accurately.

Speech-to-speech models (priced per minute of audio; they also re-bill the accumulated context each
turn, so meter real usage):

| Model | Audio in | Audio out | Source |
|---|---|---|---|
| Gemini 3.8 Live | $0.005/min ($3/1M tok) | $0.018/min ($12/1M tok) | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| OpenAI gpt-realtime-2.1 | $32/1M tok (≈$0.02/min) | $64/1M tok (≈$0.08/min) | [OpenAI](https://developers.openai.com/api/docs/pricing) |

### 6.3 STT, TTS, telephony and messaging

| Component | Price | Per conversation minute | Source |
|---|---|---|---|
| **STT** Sarvam Saaras (streaming, 22 langs) | ₹30/hour | ₹0.50 ($0.0052) | [Sarvam](https://www.sarvam.ai/api-pricing) |
| STT Deepgram Nova-3 streaming | $0.0077/min (promo $0.0048) | $0.0077 | [Deepgram](https://deepgram.com/pricing), [ConvertAudioToText](https://convertaudiototext.com/blog/deepgram-nova-3-explained) |
| STT Deepgram Flux (turn-aware) | $0.0065 EN / $0.0078 multi | $0.0065–0.0078 | [DIYAI](https://diyai.io/ai-tools/speech-to-text/deepgram-pricing-2026/) |
| STT OpenAI gpt-4o-transcribe / mini | $0.006 / $0.003 per min | $0.003–0.006 | [OpenAI](https://developers.openai.com/api/docs/pricing) |
| **TTS** Sarvam Bulbul v3 | ₹30 per 10k chars | ₹1.50 ($0.0156) | [Sarvam](https://www.sarvam.ai/api-pricing), [InVideo](https://invideo.io/blog/sarvam-bulbul-indian-tts/) |
| TTS ElevenLabs Flash v2.5 | $0.05 per 1k chars | $0.025 | [Apiframe](https://apiframe.ai/guides/elevenlabs-api-guide) |
| TTS OpenAI gpt-4o-mini-tts | $12 per 1M chars | $0.006 | [OpenAI](https://developers.openai.com/api/docs/pricing) |
| TTS Cartesia Sonic | ~$0.03 per 900 chars | ~$0.017 | [Cartesia](https://www.cartesia.ai/pricing) |
| TTS Smallest Lightning | from $0.175 per 10k chars | ~$0.009 | [Smallest](https://smallest.ai/pricing/models) |
| TTS Gemini 3.8 Flash TTS | $0.50 in / $9 out per 1M tok | ~$0.01 (≈32 audio tok/s; verify) | [Gemini pricing](https://ai.google.dev/gemini-api/docs/pricing) |
| **Telephony India** Plivo domestic | ₹0.38/min in and out; DID ₹200/mo; 30-s pulse; AMD free | ₹0.38 | [Plivo IN](https://www.plivo.com/voice/pricing/in/) |
| Telephony India Exotel | ~₹0.80–1.15/min outbound (historical list) | ~₹1.0 | [CloudTalk on Exotel](https://www.cloudtalk.io/blog/exotel-pricing/), [dialnexa](https://dialnexa.com/blogs/exotel-pricing/) |
| Telephony India direct Airtel/Jio/Tata SIP | ₹0.60–1.20 out / ₹0.30–0.70 in | ~₹0.9 | [Caller Digital](https://caller.digital/blog/telephony-partner-voice-ai-india-plivo-exotel-ozonetel-knowlarity-twilio-2026) |
| Telephony India via Twilio | $0.0496/min mobile, $0.0699 landline | ₹4.76 | [Twilio IN](https://www.twilio.com/en-us/voice/pricing/in) |
| **Telephony US** Twilio | out $0.014/min; in $0.0085; number $1.15/mo; AMD $0.0075/call; recording $0.0025/min | $0.014 | [Twilio US](https://www.twilio.com/en-us/voice/pricing/us) |
| WhatsApp India (Meta, per message, + 18% GST) | marketing ₹0.8631; utility / auth ₹0.1150; service messages chargeable from 1 Oct 2026 (1,000 free/number/month) | per call | [whautomate](https://whautomate.com/whatsapp-business-api-pricing-india), [ChatMaxima](https://chatmaxima.com/whatsapp-api-pricing/india/) |
| WhatsApp Business calls | Customer calls free; business calls per minute in 6-s pulses, per country rate card | — | [Meta](https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing) |

### 6.4 One adapter for OpenAI-compatible providers

| Provider | `base_url` | Caveats |
|---|---|---|
| OpenAI | `https://api.openai.com/v1` | reference implementation |
| Azure OpenAI (v1 GA) | `https://<resource>.openai.azure.com/openai/v1/` | no `api-version` needed; deployment name as the model ([Microsoft](https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle)) |
| Google Gemini | `https://generativelanguage.googleapis.com/v1beta/openai/` | keep the native adapter for the Live API and caching ([Google](https://ai.google.dev/gemini-api/docs/openai)) |
| Anthropic | `https://api.anthropic.com/v1/` | Anthropic calls this layer testing-only: `strict` and `response_format` are ignored and system messages are hoisted, so keep the native adapter ([Anthropic](https://docs.anthropic.com/en/api/openai-sdk)) |
| OpenRouter | `https://openrouter.ai/api/v1` | 300+ models behind one key; good default for bring-your-own keys ([docs](https://openrouter.ai/docs/quickstart)) |
| Groq | `https://api.groq.com/openai/v1` | lowest latency for Llama/Qwen ([docs](https://console.groq.com/docs/openai)) |
| Together | `https://api.together.xyz/v1` | ([docs](https://docs.together.ai/docs/openai-api-compatibility)) |
| Fireworks | `https://api.fireworks.ai/inference/v1` | ([docs](https://docs.fireworks.ai/tools-sdks/openai-compatibility)) |
| DeepSeek | `https://api.deepseek.com` | also has an Anthropic-format endpoint; peak/off-peak pricing ([docs](https://api-docs.deepseek.com/quick_start/pricing)) |
| Mistral | `https://api.mistral.ai/v1` | mostly compatible; test tool calling ([docs](https://docs.mistral.ai/api/)) |
| Sarvam | `https://api.sarvam.ai/v1` | Bearer auth; streaming and function calling ([docs](https://docs.sarvam.ai/api-reference-docs/api-guides-tutorials/chat-completion/overview)) |
| NVIDIA NIM | `https://integrate.api.nvidia.com/v1` | already a Samvaad provider |
| Ollama / vLLM | `http://localhost:11434/v1` / `http://<host>:8000/v1` | self-hosted, on-prem deals ([Ollama](https://ollama.com/blog/openai-compatibility), [vLLM](https://docs.vllm.ai/en/latest/serving/openai_compatible_server.html)) |

The adapter must normalise: `max_tokens` vs `max_completion_tokens`; tool-call streaming deltas;
missing `parallel_tool_calls`; reasoning/thinking fields; `usage` on the final stream chunk (needed for
metering); and 429/5xx retry semantics. Store a per-provider price table so the estimator and
metering (#37, #38) share one source.

### 6.5 Worked example: India (Hindi outbound, Plivo, Sarvam STT/TTS, Gemini 3.1 Flash-Lite)

| Line | Calculation | ₹ per conv-min |
|---|---|---|
| Telephony (Plivo domestic) | ₹0.38 | 0.38 |
| STT (Saaras) | ₹30/60 | 0.50 |
| LLM (Gemini 3.1 Flash-Lite) | $0.0033 × 96 | 0.32 |
| TTS (Bulbul v3) | 500 chars × ₹0.003 | 1.50 |
| Post-call extraction (Gemini 3.8 Flash) | $0.0045/call ÷ 3 min × 96 | 0.14 |
| WhatsApp utility follow-up | ₹0.1150 × 1.18 ÷ 3 min | 0.05 |
| Recording storage | free 90 days on Plivo | 0.00 |
| **Total** | | **≈ ₹2.9/min ($0.030)** |

Variants: Sarvam 105B instead of Flash-Lite ≈ ₹2.9 (about the same). Claude Sonnet 5 as the
conversation model: +₹2.2 → **≈ ₹5.1**. Twilio instead of Plivo: +₹4.4 → **≈ ₹7.3**. Exotel instead
of Plivo: +₹0.6 → ≈ ₹3.5. TTS is the largest line, so caching repeated phrases (greetings,
disclosures, voicemail) as pre-rendered audio saves 10–20%. Market reference: ₹4–10/min mid-market,
₹6–25 effective ([Bolti](https://bolti.co.in/blog/voice-ai-platform-pricing-india-comparison),
[Caller Digital](https://caller.digital/blog/voice-ai-vendor-pricing-teardown-india-2026)).
**Suggested list price: ₹6/min all-in** (≈50% gross margin on the default stack) plus ₹200–300 per
number per month. Charge per connected minute, and don't bill ring time or unanswered calls.

### 6.6 Worked example: US (English outbound, Twilio, Deepgram, GPT-5 mini, ElevenLabs Flash)

| Line | Calculation | $ per conv-min |
|---|---|---|
| Telephony (Twilio outbound) | | 0.0140 |
| STT (Deepgram Nova-3 streaming) | | 0.0077 |
| LLM (GPT-5 mini) | 12k × 0.25 + 200 × 2.00 per 1M | 0.0034 |
| TTS (ElevenLabs Flash) | 0.5k chars × $0.05 | 0.0250 |
| Recording | | 0.0025 |
| AMD | $0.0075/call ÷ 3 | 0.0025 |
| Post-call extraction | $0.0045 ÷ 3 | 0.0015 |
| **Total** | | **≈ $0.057/min** |

Variants: Claude Haiku 4.5 → ≈ $0.067. Cartesia instead of ElevenLabs → ≈ $0.049. Gemini 3.8 Live
speech-to-speech (replaces STT+LLM+TTS) → roughly $0.014 + context re-billing + telephony, so
≈ $0.035–0.05; measure it before you promise it. Market reference: Vapi $0.13–0.33, Retell
$0.13–0.31, Bland $0.11–0.14, Synthflow $0.15–0.24 all-in (§2). **Suggested list price:
$0.10–0.12/min all-in**, undercutting Bland at about 45% margin, with bring-your-own keys at a
platform-only $0.04/min.

---

## 7. Sources

Competitors and pricing
- Vapi: https://www.cekura.ai/blogs/vapi-ai-pricing · https://zeeg.me/en/blog/post/vapi-ai-pricing · https://www.cloudtalk.io/blog/vapi-ai-pricing/ · https://docs.vapi.ai/workflows/legacy-migration · https://docs.vapi.ai/calls/voicemail-detection · https://www.coval.ai/blog/vapi-review-2026-is-this-voice-ai-platform-right-for-your-project/
- Retell: https://www.cekura.ai/blogs/retell-ai-pricing-per-minute · https://www.cekura.ai/blogs/retell-ai-voice-automation-features · https://www.retellai.com/features/call-transfer
- Bland: https://www.bland.ai/pricing · https://www.getmacha.com/blog/bland-ai-pricing-explained
- Synthflow: https://zeeg.me/en/blog/post/synthflow-ai-pricing · https://docs.synthflow.ai/about-agency-whitelabel · https://feedback.synthflow.ai/changelog
- ElevenLabs: https://elevenlabs.io/pricing/agents · https://elevenlabs.io/docs/agents-platform/overview · https://apiframe.ai/guides/elevenlabs-api-guide
- PolyAI: https://synthflow.ai/blog/polyai-review · https://www.cekura.ai/blogs/polyai-pricing
- Sierra / Decagon: https://www.retellai.com/blog/sierra-vs-decagon · https://www.dragapp.com/blog/decagon-vs-sierra/
- Cognigy / NICE: https://www.nice.com/press-releases/nice-closes-acquisition-of-cognigy-transforming-customer-experience-with-best-in-class-data-driven-cx-ai-platform · https://www.nice.com/press-releases/nice-cognigy-unveils-breakthrough-agentic-ai-innovations-at-nexus-2026
- Air AI / FTC: https://www.ftc.gov/news-events/news/press-releases/2025/08/ftc-sues-stop-air-ai-using-deceptive-claims-about-business-growth-earnings-potential-refund · https://www.ftc.gov/news-events/news/press-releases/2026/03/air-ai-its-owners-will-be-banned-marketing-business-opportunities-settle-ftc-charges-company-misled
- Yellow.ai / Haptik / Gnani: https://m.thewire.in/article/ptiprnews/built-in-bharat-yellow-ai-launches-nexus-vox-the-first-enterprise-voice-ai-that-can-clone-any-voice-and-deploy-it-across-500-languages-in-under-a-second · https://www.haptik.ai/blog/voice-ai-agents-for-indian-languages · https://www.gnani.ai/inya-workforce-automate365-ai · https://caller.digital/blog/gnani-ai-alternatives-india-2026
- Sarvam: https://www.sarvam.ai/api-pricing · https://www.sarvam.ai/blogs/bulbul-v3 · https://inc42.com/buzz/exclusive-sarvam-ai-to-open-voice-ai-agents-platform-for-public-use/ · https://www.republicworld.com/tech/sarvam-launches-saaras-v3-strengthens-lead-in-22-indian-language-speech-recognition · https://invideo.io/blog/sarvam-bulbul-indian-tts/ · https://docs.sarvam.ai/api-reference-docs/api-guides-tutorials/chat-completion/overview
- Smallest.ai: https://smallest.ai/pricing/agents · https://smallest.ai/pricing/models
- Bolna: https://www.bolna.ai/pricing · https://bolti.co.in/blog/voice-ai-platform-pricing-india-comparison
- India market: https://caller.digital/blog/top-10-voice-ai-agents-india-2026 · https://caller.digital/blog/voice-ai-vendor-pricing-teardown-india-2026 · https://caller.digital/blog/telephony-partner-voice-ai-india-plivo-exotel-ozonetel-knowlarity-twilio-2026 · https://vomyra.com/ · https://www.callmissed.com/blog/whatsapp-ai-voice-agent-india-callmissed-production
- Exotel / Ozonetel: https://exotel.com/products/gen-ai-powered-voicebot/ · https://exotel.com/blog/achieve-low-latency-voice-ai-exotel/ · https://www.cloudtalk.io/blog/exotel-pricing/ · https://dialnexa.com/blogs/exotel-pricing/
- Twilio: https://www.twilio.com/en-us/voice/pricing/us · https://www.twilio.com/en-us/voice/pricing/in · https://www.twilio.com/en-us/products/conversational-ai/pricing
- Plivo: https://www.plivo.com/voice/pricing/in/ · https://www.plivo.com/blog/end-to-end-guide-to-plivo-ai-agents-platform/
- Telnyx: https://telnyx.com/pricing/voice-ai-agents

Regulation and compliance
- TRAI TCCCPR amendment (Feb 2025): https://trai.gov.in/sites/default/files/2025-02/Regulation_12022025.pdf · https://frejun.com/auto-dialer-robocall-140-series-trai-rules-india/
- TRAI third amendment (18 Sep 2026): https://www.etvbharat.com/en/business/trai-tightens-regulations-on-spam-callers-to-leverage-ai-tools-to-detect-unsolicited-calls-enn26091805208 · https://www.business-standard.com/technology/tech-news/ai-calls-how-to-identify-legitimate-calls-spam-scams-126091500686_1.html · https://chambers.com/articles/trai-s-crackdown-on-spam-calls-and-ai-driven-telemarketing
- 140 / 1600 series clarification (Jul 2026): https://www.medianama.com/2026/07/223-trai-releases-clarification-designated-promotional-transactional-number-series/ · https://www.scconline.com/blog/post/2026/07/18/trai-clarifies-1600-and-140-series-number-framework/
- CNAP: https://www.mondaq.com/india/telecoms-mobile-cable-communications/1715710/india-rolls-out-cnap-in-2026-official-caller-name-display-to-fight-spam-powered-by-kyc-databases-and-privacy-opt-out
- DPDP Rules 2025: https://www.pib.gov.in/PressReleasePage.aspx?PRID=2190014&reg=3&lang=2 · https://www.consently.in/blog/dpdp-rules-2025-implementation-timeline-india
- FCC / TCPA on AI voices: https://www.fcc.gov/document/fcc-makes-ai-generated-voices-robocalls-illegal · https://www.wiley.law/alert-FCC-Extends-Regulatory-Reach-Over-AI-Announces-TCPA-Restrictions-Cover-AI-Generated-Voices-in-Outbound-Calls · https://library.nclc.org/article/top-six-tcparobocall-developments-20242025
- WhatsApp: https://developers.facebook.com/documentation/business-messaging/whatsapp/calling/pricing · https://respond.io/whatsapp-business-calling-api · https://whautomate.com/whatsapp-business-api-pricing-india · https://chatmaxima.com/whatsapp-api-pricing/india/

Models, speech and cost
- OpenAI: https://developers.openai.com/api/docs/pricing
- Anthropic: https://claude.com/pricing · https://docs.anthropic.com/en/api/openai-sdk
- Google Gemini: https://ai.google.dev/gemini-api/docs/pricing · https://ai.google.dev/gemini-api/docs/openai
- DeepSeek: https://api-docs.deepseek.com/quick_start/pricing
- Groq: https://www.cloudzero.com/blog/groq-pricing/ · https://console.groq.com/docs/openai
- Cross-provider table: https://benchlm.ai/llm-pricing
- Azure OpenAI v1: https://learn.microsoft.com/en-us/azure/foundry/openai/api-version-lifecycle
- Deepgram: https://deepgram.com/pricing · https://diyai.io/ai-tools/speech-to-text/deepgram-pricing-2026/ · https://convertaudiototext.com/blog/deepgram-nova-3-explained
- Cartesia: https://www.cartesia.ai/pricing
- AI4Bharat (open Indic ASR/TTS): https://github.com/AI4Bharat/IndicConformerASR · https://huggingface.co/ai4bharat/indic-conformer-600m-multilingual · https://ai4bharat.iitm.ac.in/areas/tts/
- Latency: https://www.destilabs.com/blog/ai-voice-agent-benchmark-2026 · https://telnyx.com/resources/voice-ai-agents-compared-latency
- Testing/QA category: https://www.speechmatics.com/company/articles-and-news/de-risk-your-voice-agent-11-best-voice-agent-testing-platforms · https://mihup.ai/blog/automated-agent-scoring-ai-contact-center · https://www.amplifai.com/blog/call-center-quality-assurance-software
- FX: https://tradingeconomics.com/india/currency
