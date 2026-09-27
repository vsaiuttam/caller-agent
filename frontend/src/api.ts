/**
 * Typed API client. Mirrors src/voiceagent/api/schemas.py, the v2 contract in
 * docs/v2-spec.md §1 and the MCP contract in docs/mcp-spec.md §1.5 — when a
 * schema changes there, change it here too; there's no codegen step wired up yet.
 */

import { authHeaders, notifyUnauthorized, withToken } from "./authStore";

export type CampaignStatus = "draft" | "running" | "paused" | "completed";

export type Disposition =
  | "completed"
  | "partial"
  | "callback_requested"
  | "declined"
  | "do_not_call"
  | "voicemail"
  | "no_answer"
  | "wrong_number"
  | "failed";

export type Sentiment = "positive" | "neutral" | "negative";

export const DEFAULT_GREETING =
  "Hi {first_name}, this is an AI assistant calling on behalf of {campaign_name}. Do you have a moment?";

/** One row of a campaign's scorecard. */
export interface ScoreCriterion {
  name: string;
  description: string;
  /** 1–5. Only the ratio between criteria matters. */
  weight: number;
  /** Failing this disqualifies the call regardless of everything else. */
  knockout: boolean;
}

export type QualificationBand =
  | "strong"
  | "possible"
  | "weak"
  | "disqualified"
  | "not_assessed";

export interface CriterionScore {
  name: string;
  /** 0 not addressed · 1 falls short · 2 partial · 3 meets · 4 exceeds. */
  rating: number;
  met: boolean;
  evidence: string;
}

export interface Qualification {
  score: number;
  band: QualificationBand;
  reasons: string;
  disqualified_by: string;
}

export interface CampaignCreate {
  name: string;
  goal: string;
  /** Empty for informational campaigns, which score nothing. */
  scorecard: ScoreCriterion[];
  greeting: string;
  fields_to_collect: string[];
  constraints: string[];
  extra_instructions: string;
  /** Language code: en, hi, ur, hi-en. */
  language: string;
  /** Template this was created from, if any. */
  template_id: string | null;
  calling_hours_start: number;
  calling_hours_end: number;
  calling_days: number[];
  max_concurrent_calls: number;
  max_attempts: number;
  /** Null means "inherit the workspace default", resolved server-side. */
  conversation_model: string | null;
  conversation_effort: string | null;
  extraction_model: string | null;
  extraction_effort: string | null;
  /** Hard spend cap in USD. The campaign pauses itself when it's reached. */
  budget_usd: number | null;
  /** Text the person after each call. Requires Twilio. */
  sms_followup: boolean;
  /** WhatsApp the person after each call. Requires TWILIO_WHATSAPP_FROM. */
  whatsapp_followup: boolean;
  webhook_url: string | null;
  /**
   * MCP tool ids (`{server_slug}__{tool_name}`) the agent may use during the
   * call. Optional so older backends, which don't send it, still type-check;
   * read it through `campaignTools()`.
   */
  mcp_tools?: string[];
  /** Tool ids the agent may use after the call to record the outcome. */
  mcp_post_call_tools?: string[];
  /** Plain-language guidance for the after-call tools. */
  mcp_post_call_instructions?: string;

  // --- v3 (docs/v3-spec.md). Optional so older backends still type-check. ---
  /** Provider row id (`env:<preset>` for env rows). Null means the workspace default. */
  conversation_provider_id?: string | null;
  extraction_provider_id?: string | null;
  /** Sarvam speaker id. Null means the default speaker. */
  voice?: string | null;
  /** Pre-call heads-up message (§6). */
  precall_enabled?: boolean;
  precall_channel?: PrecallChannel | null;
  precall_message?: string | null;
  /** 2–240. */
  precall_lead_minutes?: number | null;
}

export type PrecallChannel = "sms" | "whatsapp";

export type CampaignUpdate = Partial<CampaignCreate>;

/** A campaign's tool choices, with the "null/absent means none" rule applied. */
export function campaignTools(c: CampaignCreate): Required<
  Pick<CampaignCreate, "mcp_tools" | "mcp_post_call_tools" | "mcp_post_call_instructions">
> {
  return {
    mcp_tools: c.mcp_tools ?? [],
    mcp_post_call_tools: c.mcp_post_call_tools ?? [],
    mcp_post_call_instructions: c.mcp_post_call_instructions ?? "",
  };
}

export interface Campaign extends CampaignCreate {
  id: string;
  status: CampaignStatus;
  created_at: string;
  total_contacts: number;
  pending: number;
  completed: number;
  needs_review: number;
  spend_usd: number;
  // Always resolved on the way out.
  conversation_model: string;
  conversation_effort: string;
  extraction_model: string;
  extraction_effort: string;
  /** Present when the list endpoint embeds the dialler state; otherwise fetched per campaign. */
  dialer?: DialerStatus;
  updated_at?: string;
}

// --- Models -----------------------------------------------------------------

export type ModelRole = "conversation" | "extraction";

export interface ModelSpec {
  id: string;
  name: string;
  family: string;
  provider: string;
  context_tokens: number;
  input_per_mtok: number;
  output_per_mtok: number;
  cache_read_per_mtok: number;
  cache_write_per_mtok: number;
  speed: "fastest" | "fast" | "balanced" | "deliberate";
  roles: ModelRole[];
  tagline: string;
  strengths: string[];
  watch_out: string;
  note: string;
  recommended_for: string[];
}

export interface EffortOption {
  value: string;
  label: string;
  output_multiplier: number;
  description: string;
}

export interface ModelDefaults {
  conversation_model: string;
  conversation_effort: string;
  extraction_model: string;
  extraction_effort: string;
}

export interface ModelCatalog {
  models: ModelSpec[];
  efforts: EffortOption[];
  defaults: ModelDefaults;
  pricing_as_of: string;
  roles: ModelRole[];
  /** Only the active provider's models are listed in `models`. */
  provider: string;
  provider_label: string;
}

export interface CostEstimate {
  conversation_model: string;
  extraction_model: string;
  exchanges: number;
  conversation_cost_usd: number;
  extraction_cost_usd: number;
  cost_per_call_usd: number;
  input_tokens: number;
  output_tokens: number;
  assumes_cache_hit: boolean;
  contacts: number;
  connect_rate: number;
  connected_calls: number;
  total_cost_usd: number;
}

// --- v3: model providers (§1.4) -----------------------------------------------

export type ApiShape = "anthropic" | "openai";
export type ProviderStatus = "ok" | "untested" | "error";

export interface Provider {
  /** A uuid, or `env:<preset>` for a provider configured by environment variable. */
  id: string;
  kind: string;
  label: string;
  base_url: string | null;
  source: "db" | "env";
  enabled: boolean;
  supports_tools: boolean;
  api_shape: ApiShape;
  /** Last four characters of the key; the key itself is never returned. */
  key_hint: string | null;
  status: ProviderStatus;
  last_error: string | null;
  models_count: number;
}

export interface ProviderPreset {
  kind: string;
  label: string;
  default_base_url: string | null;
  needs_base_url: boolean;
  key_url: string | null;
  supports_tools: boolean;
  api_shape: ApiShape;
  popular_models: Array<string | { id: string; name?: string }>;
}

export interface CustomModel {
  id: string;
  name: string;
  input_per_mtok: number | null;
  output_per_mtok: number | null;
}

export interface ProviderCreate {
  kind: string;
  label?: string;
  base_url?: string;
  api_key: string;
  custom_models?: CustomModel[];
}

export interface ProviderUpdate {
  label?: string;
  base_url?: string | null;
  api_key?: string;
  enabled?: boolean;
  custom_models?: CustomModel[];
}

export interface ProviderTestResult {
  ok: boolean;
  latency_ms: number | null;
  model: string | null;
  error?: string | null;
}

export type SpeedTier = "fastest" | "fast" | "balanced" | "deliberate";

export interface ProviderModel {
  id: string;
  name: string;
  input_per_mtok: number | null;
  output_per_mtok: number | null;
  speed?: SpeedTier | string | null;
  roles: ModelRole[];
  supports_tools: boolean;
  source: "catalog" | "custom" | "discovered";
}

export interface ModelChoice {
  provider_id: string | null;
  model: string | null;
}

export interface WorkspaceModelDefaults {
  conversation: ModelChoice;
  extraction: ModelChoice;
}

export type EstimateComponent = "llm" | "extraction" | "stt" | "tts" | "telephony";

export interface EstimateRequest {
  provider_id?: string | null;
  conversation_model?: string | null;
  extraction_model?: string | null;
  language?: string;
  minutes_per_call?: number;
  calls?: number;
  telephony_region?: "IN" | "US";
  include_voice?: boolean;
}

export interface Estimate {
  per_call: Record<EstimateComponent, number | null> & { total: number | null };
  per_minute_total: number | null;
  for_calls: { calls: number; total: number | null };
  assumptions: string[];
  pricing_as_of: string;
  /** Components whose price isn't known. They're never counted as $0. */
  unknown: string[];
}

// --- v3: dialler status (§2.3) ------------------------------------------------

export type DialerState = "dialing" | "waiting_window" | "paused" | "draft" | "completed" | "blocked" | "asleep_risk";

export interface DialerStatus {
  state: DialerState;
  reason: string;
  next_window_start: string | null;
  pending: number;
  in_progress: number;
  done: number;
  failed: number;
  blockers: string[];
}

// --- v3: voices (§4) ------------------------------------------------------------

export interface Voice {
  id: string;
  name: string;
  gender: string;
  languages: string[];
  provider: string;
  sample_text: string;
}

// --- v3: assistant (§7) ---------------------------------------------------------

export interface AssistantMessage {
  role: "user" | "assistant";
  content: string;
}

export interface AssistantLink {
  label: string;
  to: string;
}

// --- Simulation -------------------------------------------------------------

export interface Persona {
  id: string;
  name: string;
  description: string;
}

/** Shared by both rehearsal modes: a scripted persona, and your own voice. */
export interface CallSetupRequest {
  campaign_id?: string | null;
  goal?: string;
  greeting?: string;
  fields_to_collect?: string[];
  constraints?: string[];
  extra_instructions?: string;
  language?: string;
  contact_name?: string;
  contact_timezone?: string;
  contact_attributes?: Record<string, string>;
  conversation_model?: string;
  conversation_effort?: string;
  extraction_model?: string;
  extraction_effort?: string;
  save?: boolean;
}

export interface SimulationRequest extends CallSetupRequest {
  persona: string;
  max_exchanges?: number;
}

export interface SimulatedTurn {
  role: "user" | "assistant";
  text: string;
  first_chunk_ms: number | null;
  total_ms: number | null;
}

export interface UsageReport {
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  cache_hit_rate: number;
  cost_usd: number;
  by_model: Record<string, Record<string, number>>;
}

export interface SimulationResult {
  persona?: string;
  conversation_model: string;
  extraction_model: string;
  ended_because: string;
  greeting: string;
  turns: SimulatedTurn[];
  outcome: Outcome;
  /** Null when the campaign scores nothing. */
  qualification: Qualification | null;
  usage: UsageReport;
  median_first_chunk_ms: number | null;
  call_id?: string;
  /** Real test calls only: what happened to the follow-up messages. */
  followups?: Partial<Record<FollowupChannel, FollowupResult>>;
}

/** What `call.extracted.payload.result` carries for a real test call. */
export interface TestCallResult extends SimulationResult {
  call_id: string;
  recording_url?: string | null;
  phone_number?: string;
}

export type FollowupChannel = "sms" | "whatsapp";

export interface FollowupResult {
  channel: FollowupChannel;
  /** A Twilio status ("queued", "sent", "delivered", "read"…) or "failed". */
  status: string;
  sid: string | null;
  error: string | null;
}

export interface TestCallRequest extends CallSetupRequest {
  phone_number: string;
  /** Null/omitted means "do what the campaign does". */
  send_sms?: boolean;
  send_whatsapp?: boolean;
}

/** `POST /api/test-call` answers 202 before dialling; the call streams over /api/events. */
export interface TestCallAccepted {
  call_id: string;
  status: "dialing";
}

// --- Live microphone call ---------------------------------------------------
//
// Mirrors the protocol documented at the top of src/voiceagent/live.py. The
// browser owns the audio and is the authority on what was actually heard;
// the server owns the model and the transcript.

export type LiveServerMessage =
  | {
      type: "ready";
      greeting: string;
      conversation_model: string;
      language: string;
    }
  /** A chunk to say now. Chunks arrive at clause boundaries, not turn ends. */
  | { type: "speak"; turn: number; text: string }
  | {
      type: "turn_end";
      turn: number;
      first_chunk_ms: number | null;
      total_ms: number | null;
      interrupted: boolean;
    }
  /** The utterance the server accepted and recorded. */
  | { type: "heard"; text: string }
  /** The agent said goodbye. Stop listening once playback finishes. */
  | { type: "closing" }
  | { type: "extracting" }
  | { type: "outcome"; result: SimulationResult }
  | { type: "error"; message: string; fatal?: boolean };

export type LiveClientMessage =
  | { type: "utterance"; text: string }
  | { type: "interrupt" }
  /** What the speaker actually played — truncated when barged in on. */
  | { type: "spoken"; text: string }
  | { type: "end"; reason: string };

// --- Health & auth ------------------------------------------------------------

export interface Health {
  ok: boolean;
  checks: Record<string, boolean>;
  live: string[];
  mocked: string[];
  can_place_calls: boolean;
  can_run_simulations: boolean;
  /** Which model provider is serving this deployment; "" when none is usable. */
  provider: string;
  provider_label: string;
  providers_configured: string[];
  /** "mock" | "livekit" | "twilio" | "telnyx" */
  telephony_mode: string;
  note: string;
  /** v2: true when ADMIN_PASSWORD is set. Absent on older backends. */
  auth_enabled?: boolean;
  /** MCP round: enabled connected apps. Absent on backends without MCP. */
  mcp_servers?: number;
  /** False when the active model provider can't call tools (Sarvam, NVIDIA). */
  provider_supports_tools?: boolean;
  /** False when server URLs and headers are stored unencrypted (no SECRETS_KEY / AUTH_SECRET). */
  secrets_sealed?: boolean;
  /** Accounts round. Absent on older backends. */
  accounts?: { users: number; registration_mode: string };
}

/** Accounts round: who is signed in. Legacy admin-password sessions report
 *  `{id: "admin", email: "", name: "Admin", role: "owner"}`. */
export type UserRole = "owner" | "admin" | "member";

export interface AuthUser {
  id: string;
  email: string;
  name: string;
  role: UserRole;
}

/**
 * How new people get in. "owner" while no account exists yet (the first
 * registration becomes the owner); then the server's REGISTRATION_MODE.
 */
export type RegistrationMode = "owner" | "invite" | "open" | "closed";

export interface RegistrationInfo {
  mode: RegistrationMode;
  /** The owner bootstrap must present ADMIN_PASSWORD as `setup_code`. */
  setup_code_required: boolean;
}

export interface AuthStatus {
  auth_enabled: boolean;
  authenticated: boolean;
  /** Absent on backends from before accounts. */
  user?: AuthUser | null;
  registration?: RegistrationInfo;
}

export interface LoginResult {
  token: string;
  expires_at: string;
  user?: AuthUser;
}

/** `{email, password}` for an account, or `{password}` for the legacy admin password. */
export type Credentials = { email: string; password: string } | { password: string };

export interface RegisterRequest {
  name: string;
  email: string;
  password: string;
  invite_code?: string;
  setup_code?: string;
}

export interface TeamUser {
  id: string;
  email: string;
  name: string;
  role: UserRole;
  disabled: boolean;
  created_at: string;
  last_login_at: string | null;
}

export type InviteStatus = "pending" | "used" | "expired" | "revoked";

export interface TeamInvite {
  id: string;
  email: string | null;
  role: "member" | "admin";
  created_at: string;
  expires_at: string;
  used_at: string | null;
  revoked: boolean;
  status: InviteStatus;
}

/** Returned once, at creation: the only time the code is ever shown. */
export interface CreatedInvite {
  id: string;
  code: string;
  email: string | null;
  role: "member" | "admin";
  expires_at: string;
}

export interface CampaignTemplate {
  id: string;
  name: string;
  category: string;
  description: string;
  goal: string;
  greetings: Record<string, string>;
  scorecard: ScoreCriterion[];
  fields_to_collect: string[];
  constraints: string[];
  extra_instructions: string;
  typical_duration: string;
  languages: string[];
}

export interface TemplateCatalog {
  categories: string[];
  templates: CampaignTemplate[];
}

export interface LanguageOption {
  code: string;
  name: string;
  native_name: string;
}

export interface NewContact {
  full_name: string;
  phone_e164: string;
  timezone: string;
  attributes?: Record<string, string>;
}

export interface Contact {
  id: string;
  full_name: string;
  phone_masked: string;
  timezone: string;
  status: string;
  attempts: number;
  next_attempt_at: string | null;
}

export interface CallSummary {
  id: string;
  campaign_id: string;
  contact_id: string;
  contact_name: string;
  phone_masked: string;
  /** "dialing" | "connected" | "completed" | "failed" */
  status: string;
  disposition: Disposition | null;
  summary: string | null;
  needs_human_review: boolean;
  review_reason: string | null;
  started_at: string;
  ended_at: string | null;
  duration_seconds: number | null;
  cost_usd: number;
  is_simulation: boolean;
  /** Null when the campaign has no scorecard. */
  score: number | null;
  qualification_band: QualificationBand | null;
  /** v2. Null until extraction has run (and on older backends). */
  sentiment?: Sentiment | null;
}

export interface TranscriptTurn {
  role: "user" | "assistant";
  text: string;
  started_at: string;
  /** Agent turns on live calls: ms from the person finishing to the reply being ready. */
  latency_ms?: number | null;
}

export interface CollectedField {
  name: string;
  value: string;
  verbatim: boolean;
}

export interface Appointment {
  starts_at_local: string;
  timezone: string;
  duration_minutes: number;
  subject: string;
  notes: string;
}

export interface Outcome {
  disposition: Disposition;
  summary: string;
  collected: CollectedField[];
  scores: CriterionScore[];
  appointment: Appointment | null;
  needs_human_review: boolean;
  review_reason: string;
  sentiment?: Sentiment;
  sentiment_reason?: string;
}

export interface DispatchResult {
  suppressed: boolean;
  calendar_event_id: string | null;
  fields_written: number;
  queued_for_review: boolean;
  errors: string[];
  /** Set (to "held for review") when after-call tools were skipped. */
  mcp_actions_skipped?: string;
}

export interface CallDetail extends CallSummary {
  transcript: TranscriptTurn[];
  outcome: Outcome | null;
  /** Per-criterion ratings from the model, and the verdict we derived. */
  scores: CriterionScore[];
  qualification: Qualification | null;
  dispatch_result: DispatchResult | null;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_write_tokens: number;
  conversation_model: string | null;
  extraction_model: string | null;
  /** Twilio recording URL for playback. */
  recording_url: string | null;
  recording_sid: string | null;
  recording_duration: number | null;
  /** Answering Machine Detection result. */
  amd_result: string | null;
  /** Follow-up messages and their delivery status. */
  sms_sid: string | null;
  sms_status: string | null;
  whatsapp_sid: string | null;
  whatsapp_status: string | null;
  followup_errors: Partial<Record<FollowupChannel, string>> | null;
  /** Every MCP tool the agent ran, during and after the call. Absent on older backends. */
  tool_calls?: ToolCallLog[];
}

// --- MCP: connected apps ------------------------------------------------------
//
// Mirrors docs/mcp-spec.md §1.5. A server's URL and header values are write-
// only: the API never returns them, so nothing here can show them again.

export type JsonValue = string | number | boolean | null | JsonValue[] | { [key: string]: JsonValue };

/** The subset of JSON Schema that tool inputs use in practice. */
export interface JsonSchema {
  type?: string | string[];
  title?: string;
  description?: string;
  properties?: Record<string, JsonSchema>;
  required?: string[];
  additionalProperties?: boolean | JsonSchema;
  items?: JsonSchema;
  enum?: JsonValue[];
  const?: JsonValue;
  default?: JsonValue;
  examples?: JsonValue[];
  format?: string;
  minimum?: number;
  maximum?: number;
  maxLength?: number;
  anyOf?: JsonSchema[];
  oneOf?: JsonSchema[];
  allOf?: JsonSchema[];
  $ref?: string;
}

export type McpTransport = "streamable_http" | "sse" | "builtin";
/** What to try when connecting. "auto" tries Streamable HTTP, then SSE. */
export type McpTransportChoice = "auto" | "streamable_http" | "sse";
export type McpServerStatus = "ok" | "error" | "unchecked";

export interface McpTool {
  /** `{server_slug}__{name}` — what campaigns store. */
  id: string;
  name: string;
  description: string;
  input_schema: JsonSchema;
}

export interface McpServer {
  id: string;
  name: string;
  slug: string;
  transport: McpTransport;
  /** Display only — the full URL is never returned. */
  host: string;
  /** Header names only; values are never returned. */
  header_names: string[];
  enabled: boolean;
  status: McpServerStatus;
  last_error: string | null;
  checked_at: string | null;
  tools: McpTool[];
}

export interface McpServerCreate {
  name: string;
  /** `builtin://demo` adds the built-in Demo CRM. */
  url: string;
  transport?: McpTransportChoice;
  headers?: Record<string, string>;
}

/** `headers`, when present, replaces every saved header. Omit it to keep them. */
export interface McpServerUpdate {
  name?: string;
  url?: string;
  headers?: Record<string, string>;
  enabled?: boolean;
}

export interface McpToolTestResult {
  ok: boolean;
  text: string;
  duration_ms: number;
}

/** `GET /api/mcp/tools` row: a tool of an enabled, healthy server. */
export interface McpToolOption {
  id: string;
  server_id: string;
  server_name: string;
  name: string;
  description: string;
  input_schema: JsonSchema;
}

export type ToolPhase = "in_call" | "post_call";

/** One entry of `CallDetail.tool_calls`. */
export interface ToolCallLog {
  at: string;
  phase: ToolPhase;
  /** The server's display name. */
  server: string;
  /** The bare MCP tool name. */
  tool: string;
  /** Unique within the call; the same on a tool's "started" event and its result. */
  invocation_id?: string;
  /** Namespaced `{server_slug}__{name}`. */
  tool_id?: string;
  arguments: JsonValue;
  ok: boolean;
  duration_ms: number | null;
  /** First 300 characters of the result. */
  excerpt: string | null;
  error: string | null;
}

/** `call.tool` payload: the toolbox event plus the call it belongs to. */
export interface CallToolEvent {
  call_id: string;
  phase: ToolPhase;
  /** The server's display name. */
  server: string;
  /** The bare MCP tool name. */
  tool: string;
  /** Unique within the call; the same on "started" and its "ok"/"error". */
  invocation_id?: string;
  /** Namespaced `{server_slug}__{name}`. */
  tool_id?: string;
  status: "started" | "ok" | "error";
  arguments: JsonValue;
  duration_ms: number | null;
  excerpt: string | null;
  error: string | null;
}

export interface HourBucket {
  hour: string;
  label: string;
  total: number;
  connected: number;
}

/** How far back the Overview looks; volume is hourly for 24h, daily beyond. */
export type StatsPeriod = "24h" | "7d" | "30d";

/** Shared by every page that lists or counts calls, so the choice carries over. */
export const INCLUDE_TESTS_KEY = "samvaad.includeTestCalls";

export interface DashboardStats {
  campaigns_running: number;
  calls_today: number;
  calls_in_progress: number;
  connect_rate: number;
  completion_rate: number;
  avg_duration_seconds: number;
  pending_review: number;
  suppressed_total: number;
  disposition_breakdown: Record<string, number>;
  /** Fractional change vs the preceding 24h. Null when there's no baseline. */
  calls_delta: number | null;
  connect_rate_delta: number | null;
  avg_duration_delta: number | null;
  spend_usd: number;
  spend_delta: number | null;
  cost_per_connected_call_usd: number;
  cache_hit_rate: number;
  volume_by_hour: HourBucket[];
  /** v2, real calls only. Absent on older backends. */
  sentiment_breakdown?: Partial<Record<Sentiment, number>>;
}

export interface Suppression {
  phone_masked: string;
  reason: string;
  created_at: string;
}

export interface BulkResult {
  created: number;
  skipped_suppressed: number;
  skipped_duplicate: number;
}

// --- Live calls & the event stream -----------------------------------------------

/**
 * What the session reports while a call is up (§1.1 `on_event("state")`).
 * "working" (MCP round): the agent paused its reply to run tools.
 */
export type CallStateName = "speaking" | "listening" | "thinking" | "working" | "ended";

/** One turn as the live registry / call.turn event carries it. */
export interface LiveTurn {
  role: "user" | "assistant";
  text: string;
  latency_ms?: number | null;
  at?: string;
  started_at?: string;
}

/** `GET /api/calls/live` row. `turns` is the transcript so far. */
export interface LiveCallInfo {
  call_id: string;
  room_name: string;
  campaign_id: string | null;
  contact_name: string;
  started_at: string;
  state: string;
  is_test: boolean;
  /** The contract leaves this loose: a list of turns, or a count on some builds. */
  turns: LiveTurn[] | number;
}

export interface CallExtractedPayload {
  call_id: string;
  disposition: Disposition;
  summary: string;
  needs_review: boolean;
  cost_usd: number;
  sentiment?: Sentiment | null;
  /** Test calls only: the full result object. */
  result?: TestCallResult;
}

/** Payload per event type, per §1.2. Every call event carries `call_id`. */
export interface EventPayloads {
  "call.started": {
    call_id: string;
    campaign_id: string | null;
    contact_name: string;
    phone: string;
    is_test?: boolean;
  };
  "call.connected": { call_id: string };
  /** `tools` (tool ids about to run) comes with state "working". */
  "call.state": { call_id: string; state: CallStateName; tools?: string[] };
  "call.tool": CallToolEvent;
  "call.turn": {
    call_id: string;
    role: "user" | "assistant";
    text: string;
    latency_ms: number | null;
    at: string;
  };
  "call.whisper": { call_id: string; text: string };
  /** Legacy; superseded by call.turn. */
  "call.transcript": { call_id: string };
  "call.ended": { call_id: string; turns: number; duration_seconds?: number | null };
  "call.extracted": CallExtractedPayload;
  "call.failed": { call_id: string; error: string };
  "campaign.updated": { campaign_id: string; dispatched?: number; paused_reason?: string };
}

export type LiveEventType = keyof EventPayloads;

export type LiveEvent = {
  [K in LiveEventType]: { type: K; payload: EventPayloads[K]; at: string };
}[LiveEventType];

// ---------------------------------------------------------------------------

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
  ) {
    super(message);
  }
}

/** Turn a failed response into a readable ApiError (and report 401s). */
async function toError(res: Response, reportUnauthorized = true): Promise<ApiError> {
  if (res.status === 401 && reportUnauthorized) notifyUnauthorized();
  // FastAPI puts validation failures under `detail`, which may be a string
  // or an array of per-field errors. Surface something readable either way.
  let message = res.statusText || `Request failed (${res.status})`;
  try {
    const body = await res.json();
    message = Array.isArray(body.detail)
      ? body.detail.map((d: { msg: string }) => d.msg).join("; ")
      : (body.detail ?? message);
  } catch {
    /* non-JSON error body; keep statusText */
  }
  return new ApiError(message, res.status);
}

async function request<T>(
  path: string,
  init?: RequestInit,
  options: { reportUnauthorized?: boolean } = {},
): Promise<T> {
  let res: Response;
  try {
    res = await fetch(path, {
      ...init,
      headers: { "Content-Type": "application/json", ...authHeaders(), ...init?.headers },
    });
  } catch {
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }

  if (!res.ok) throw await toError(res, options.reportUnauthorized ?? true);
  return res.status === 204 ? (undefined as T) : res.json();
}

const post = (body?: unknown): RequestInit => ({
  method: "POST",
  body: body === undefined ? undefined : JSON.stringify(body),
});

const qs = (params: Record<string, unknown>) => {
  const search = new URLSearchParams();
  for (const [k, v] of Object.entries(params)) {
    if (v !== undefined && v !== null && v !== "") search.set(k, String(v));
  }
  const s = search.toString();
  return s ? `?${s}` : "";
};

export interface CallFilters {
  campaign_id?: string;
  disposition?: string;
  needs_review?: boolean;
  include_simulations?: boolean;
  band?: QualificationBand;
  min_score?: number;
  /** "score" gives the ranked queue; "recent" the call log. */
  sort?: "recent" | "score";
}

/**
 * Fill in anything missing from a health payload. The pill and the
 * onboarding checklist read it on every screen, so a proxy pointed at the
 * wrong server (or an older backend) must degrade to "not configured"
 * rather than take the shell down.
 */
function normaliseHealth(raw: Partial<Health>): Health {
  return {
    ok: raw.ok ?? false,
    checks: raw.checks ?? {},
    live: raw.live ?? [],
    mocked: raw.mocked ?? [],
    can_place_calls: raw.can_place_calls ?? false,
    can_run_simulations: raw.can_run_simulations ?? false,
    provider: raw.provider ?? "",
    provider_label: raw.provider_label ?? "",
    providers_configured: raw.providers_configured ?? [],
    telephony_mode: raw.telephony_mode ?? "unknown",
    note: raw.note ?? "",
    auth_enabled: raw.auth_enabled,
    mcp_servers: raw.mcp_servers,
    provider_supports_tools: raw.provider_supports_tools,
    secrets_sealed: raw.secrets_sealed,
    accounts: raw.accounts,
  };
}

export const api = {
  stats: (opts: { include_simulations?: boolean; period?: StatsPeriod } = {}) =>
    request<DashboardStats>(
      `/api/stats?${new URLSearchParams({
        include_simulations: String(!!opts.include_simulations),
        period: opts.period ?? "24h",
      })}`,
    ),
  health: async () => normaliseHealth(await request<Partial<Health>>("/api/health")),

  authStatus: () => request<AuthStatus>("/api/auth/status", undefined, { reportUnauthorized: false }),
  /** 401 here means wrong credentials, not an expired session. */
  login: (credentials: Credentials) =>
    request<LoginResult>("/api/auth/login", post(credentials), { reportUnauthorized: false }),
  /** 201 with a session; 400 bad input, 403 closed / bad code, 409 email taken, 429 throttled. */
  register: (body: RegisterRequest) =>
    request<LoginResult & { user: AuthUser }>("/api/auth/register", post(body), { reportUnauthorized: false }),

  // Team (owner and admin only). 404 on backends from before accounts.
  teamUsers: () => request<TeamUser[]>("/api/team/users"),
  updateTeamUser: (id: string, body: { role?: "admin" | "member"; disabled?: boolean }) =>
    request<TeamUser>(`/api/team/users/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  removeTeamUser: (id: string) => request<void>(`/api/team/users/${encodeURIComponent(id)}`, { method: "DELETE" }),
  teamInvites: () => request<TeamInvite[]>("/api/team/invites"),
  createInvite: (body: { email?: string; role: "member" | "admin"; expires_in_days: number }) =>
    request<CreatedInvite>("/api/team/invites", post(body)),
  revokeInvite: (id: string) => request<void>(`/api/team/invites/${encodeURIComponent(id)}`, { method: "DELETE" }),

  templates: () => request<TemplateCatalog>("/api/templates"),
  languages: () => request<LanguageOption[]>("/api/languages"),

  models: () => request<ModelCatalog>("/api/models"),
  modelDefaults: () => request<ModelDefaults>("/api/settings/models"),
  saveModelDefaults: (body: ModelDefaults) =>
    request<ModelDefaults>("/api/settings/models", {
      method: "PUT",
      body: JSON.stringify(body),
    }),
  estimate: (body: {
    conversation_model: string;
    conversation_effort: string;
    extraction_model: string;
    extraction_effort: string;
    contacts: number;
    exchanges: number;
    connect_rate: number;
  }) => request<CostEstimate>("/api/estimate", post(body)),

  personas: () => request<Persona[]>("/api/personas"),
  simulate: (body: SimulationRequest) => request<SimulationResult>("/api/simulate", post(body)),
  /** Place a real phone call. Returns at once; the call streams over /api/events. */
  startTestCall: (body: TestCallRequest) =>
    request<TestCallAccepted>("/api/test-call", post(body)),
  /** Send (or re-send) a finished call's SMS / WhatsApp follow-up. */
  resendFollowup: (callId: string, body: { sms: boolean; whatsapp: boolean }) =>
    request<Partial<Record<FollowupChannel, FollowupResult>>>(
      `/api/calls/${callId}/followup`,
      post(body),
    ),

  /**
   * Parse a contact file without saving it. Excel goes to the server because
   * xlsx needs a real parser; CSV rides the same path so there's one code
   * route and one set of edge cases to reason about.
   */
  parseContactsFile: async (file: File, language = "en") => {
    const form = new FormData();
    form.append("file", file);
    // Language picks the default dial code for bare local numbers — a
    // 10-digit Indian number must not be prefixed +1.
    const res = await fetch(`/api/parse-contacts?language=${language}`, {
      method: "POST",
      body: form,
      headers: authHeaders(),
    });
    if (!res.ok) throw await toError(res);
    return (await res.json()) as {
      contacts: NewContact[];
      rejected: Array<{ line: number; reason: string }>;
      attribute_columns: string[];
    };
  },

  campaigns: () => request<Campaign[]>("/api/campaigns"),
  campaign: (id: string) => request<Campaign>(`/api/campaigns/${id}`),
  createCampaign: (body: CampaignCreate) => request<Campaign>("/api/campaigns", post(body)),
  updateCampaign: (id: string, body: CampaignUpdate) =>
    request<Campaign>(`/api/campaigns/${id}`, {
      method: "PATCH",
      body: JSON.stringify(body),
    }),
  setCampaignStatus: (id: string, action: "start" | "pause" | "complete") =>
    request<Campaign>(`/api/campaigns/${id}/status?action=${action}`, post()),

  contacts: (campaignId: string, params: { status?: string; limit?: number } = {}) =>
    request<Contact[]>(`/api/campaigns/${campaignId}/contacts${qs(params)}`),
  addContacts: (campaignId: string, contacts: NewContact[]) =>
    request<BulkResult>(`/api/campaigns/${campaignId}/contacts`, post({ contacts })),

  calls: (params: CallFilters & { limit?: number } = {}) =>
    request<CallSummary[]>(`/api/calls${qs({ ...params })}`),
  /** Browser-navigated so the download streams with the server's Content-Disposition. */
  callsExportUrl: (params: CallFilters = {}) => withToken(`/api/calls/export.csv${qs({ ...params })}`),
  call: (id: string) => request<CallDetail>(`/api/calls/${id}`),
  reviewCall: (id: string, approve: boolean, note = "") =>
    request<CallSummary>(`/api/calls/${id}/review`, post({ approve, note })),
  /** For <audio src>, which can't send headers. */
  recordingUrl: (id: string) => withToken(`/api/calls/${id}/recording`),

  // --- v2: live calls -------------------------------------------------------
  liveCalls: () => request<LiveCallInfo[]>("/api/calls/live"),
  hangup: (id: string) => request<unknown>(`/api/calls/${id}/hangup`, post()),
  whisper: (id: string, text: string) => request<unknown>(`/api/calls/${id}/whisper`, post({ text })),
  /**
   * Download a transcript as a file. Fetched (rather than navigated) so a
   * missing call surfaces as an error message instead of a JSON page.
   */
  downloadTranscript: async (id: string, format: "txt" | "json") => {
    const res = await fetch(`/api/calls/${id}/transcript?format=${format}`, {
      headers: authHeaders(),
    });
    if (!res.ok) throw await toError(res);
    const disposition = res.headers.get("Content-Disposition") ?? "";
    const name = /filename="?([^";]+)"?/.exec(disposition)?.[1] ?? `transcript-${id}.${format}`;
    saveBlob(await res.blob(), name);
  },

  suppressions: () => request<Suppression[]>("/api/suppressions"),
  addSuppression: (phone_e164: string, reason: string) =>
    request<Suppression>("/api/suppressions", post({ phone_e164, reason })),

  // --- MCP: connected apps ----------------------------------------------------
  mcpServers: () => request<McpServer[]>("/api/mcp/servers"),
  /** Saves and discovers at once. A server that fails discovery is still saved, with status "error". */
  createMcpServer: (body: McpServerCreate) => request<McpServer>("/api/mcp/servers", post(body)),
  /** Re-discovers when `url` or `headers` are present. */
  updateMcpServer: (id: string, body: McpServerUpdate) =>
    request<McpServer>(`/api/mcp/servers/${id}`, { method: "PATCH", body: JSON.stringify(body) }),
  /** Also removes its tools from every campaign. */
  deleteMcpServer: (id: string) => request<void>(`/api/mcp/servers/${id}`, { method: "DELETE" }),
  refreshMcpServer: (id: string) => request<McpServer>(`/api/mcp/servers/${id}/refresh`, post()),
  /** Runs the tool once, for real. */
  testMcpTool: (id: string, toolName: string, args: Record<string, JsonValue>) =>
    request<McpToolTestResult>(
      `/api/mcp/servers/${id}/tools/${encodeURIComponent(toolName)}/test`,
      post({ arguments: args }),
    ),
  /** Tools of enabled, healthy servers — what a campaign can choose from. */
  mcpTools: () => request<McpToolOption[]>("/api/mcp/tools"),

  // --- v3 (docs/v3-spec.md). Wrap reads in `unlessMissing` so a backend that
  // predates them renders "not available yet" instead of an error. ----------
  providers: () => request<Provider[]>("/api/providers"),
  providerPresets: () => request<ProviderPreset[]>("/api/providers/presets"),
  createProvider: (body: ProviderCreate) => request<Provider>("/api/providers", post(body)),
  updateProvider: (id: string, body: ProviderUpdate) =>
    request<Provider>(`/api/providers/${encodeURIComponent(id)}`, { method: "PATCH", body: JSON.stringify(body) }),
  /** 409 when it's a workspace default. */
  deleteProvider: (id: string) => request<void>(`/api/providers/${encodeURIComponent(id)}`, { method: "DELETE" }),
  testProvider: (id: string) => request<ProviderTestResult>(`/api/providers/${encodeURIComponent(id)}/test`, post()),
  providerModels: (id: string) => request<ProviderModel[]>(`/api/providers/${encodeURIComponent(id)}/models`),
  workspaceModelDefaults: () => request<WorkspaceModelDefaults>("/api/model-defaults"),
  saveWorkspaceModelDefaults: (body: WorkspaceModelDefaults) =>
    request<WorkspaceModelDefaults>("/api/model-defaults", { method: "PUT", body: JSON.stringify(body) }),
  estimateCost: (body: EstimateRequest) => request<Estimate>("/api/estimate", post(body)),

  dialer: (campaignId: string) => request<DialerStatus>(`/api/campaigns/${encodeURIComponent(campaignId)}/dialer`),

  voices: (language?: string) => request<Voice[]>(`/api/voices${qs({ language })}`),
  /** A short WAV of `voice` speaking. 409 (with a message) when the deployment has no Sarvam key. */
  voicePreview: async (body: { voice: string; language: string; text?: string }): Promise<Blob> => {
    let res: Response;
    try {
      res = await fetch("/api/voices/preview", {
        method: "POST",
        body: JSON.stringify(body),
        headers: { "Content-Type": "application/json", Accept: "audio/wav", ...authHeaders() },
      });
    } catch {
      throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
    }
    if (!res.ok) throw await toError(res);
    return res.blob();
  },

  /** Uses the workspace default model. The result is a suggestion the user edits. */
  translate: async (text: string, to: string): Promise<string> => {
    const body = await request<{ text?: string; translation?: string; translated?: string } | string>(
      "/api/translate",
      post({ text, to }),
    );
    if (typeof body === "string") return body;
    return body.text ?? body.translation ?? body.translated ?? "";
  },

  /** Re-runs extraction on the saved transcript (owner/admin). */
  reextractCall: (id: string) => request<CallDetail>(`/api/calls/${encodeURIComponent(id)}/reextract`, post()),
};

/** Resolve to null when the endpoint doesn't exist on this backend (404/405). */
export async function unlessMissing<T>(promise: Promise<T>): Promise<T | null> {
  try {
    return await promise;
  } catch (err) {
    if (isMissing(err)) return null;
    throw err;
  }
}

export const isMissing = (err: unknown) => err instanceof ApiError && (err.status === 404 || err.status === 405);

/**
 * Ask Samvaad (§7): POST /api/assistant/chat answers with text/event-stream.
 * Each event's data is a token, either raw text or JSON (`{token}`, `{delta}`,
 * `{text}` or `{content}`); the last one is `{done: true, links: [...]}`.
 * Resolves with the links once the stream ends.
 */
export async function streamAssistant(
  body: { messages: AssistantMessage[]; page?: string },
  onToken: (text: string) => void,
  signal?: AbortSignal,
): Promise<AssistantLink[]> {
  let res: Response;
  try {
    res = await fetch("/api/assistant/chat", {
      method: "POST",
      body: JSON.stringify(body),
      signal,
      headers: { "Content-Type": "application/json", Accept: "text/event-stream", ...authHeaders() },
    });
  } catch (err) {
    if ((err as Error).name === "AbortError") throw err;
    throw new ApiError("Can't reach the server. Check your connection and try again.", 0);
  }
  if (!res.ok) throw await toError(res);

  // A server that answered with plain JSON instead of a stream.
  const type = res.headers.get("Content-Type") ?? "";
  if (type.includes("application/json")) {
    const json = (await res.json()) as { content?: string; text?: string; links?: AssistantLink[] };
    onToken(json.content ?? json.text ?? "");
    return json.links ?? [];
  }
  if (!res.body) throw new ApiError("The assistant sent an empty reply.", 0);

  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let links: AssistantLink[] = [];

  const handle = (raw: string) => {
    let parsed: unknown;
    try {
      parsed = JSON.parse(raw);
    } catch {
      onToken(raw);
      return;
    }
    if (typeof parsed === "string") {
      onToken(parsed);
      return;
    }
    const data = parsed as {
      done?: boolean;
      links?: AssistantLink[];
      token?: string;
      delta?: string;
      text?: string;
      content?: string;
      error?: string;
    };
    if (data.error) throw new ApiError(data.error, 500);
    const text = data.token ?? data.delta ?? data.text ?? data.content;
    if (text) onToken(text);
    if (data.done) links = data.links ?? [];
  };

  for (;;) {
    const { value, done } = await reader.read();
    if (value) buffer += decoder.decode(value, { stream: true });
    // Events are separated by a blank line; each may carry several data lines.
    let cut: number;
    while ((cut = buffer.search(/\r?\n\r?\n/)) >= 0) {
      const event = buffer.slice(0, cut);
      buffer = buffer.slice(cut).replace(/^\r?\n\r?\n/, "");
      const data = event
        .split(/\r?\n/)
        .filter((line) => line.startsWith("data:"))
        .map((line) => line.slice(5).replace(/^ /, ""))
        .join("\n");
      if (data && data !== "[DONE]") handle(data);
    }
    if (done) break;
  }
  if (buffer.trim().startsWith("data:")) handle(buffer.trim().slice(5).trim());
  return links;
}

function saveBlob(blob: Blob, filename: string) {
  const url = URL.createObjectURL(blob);
  const link = document.createElement("a");
  link.href = url;
  link.download = filename;
  document.body.appendChild(link);
  link.click();
  link.remove();
  window.setTimeout(() => URL.revokeObjectURL(url), 1000);
}

/**
 * The backend origin for WebSocket connections.
 *
 * In development Vite proxies everything, so same-origin works. In production
 * the frontend is on Vercel and the backend on Render — Vercel cannot proxy
 * WebSockets, so we connect directly to the backend origin.
 *
 * Set VITE_API_ORIGIN in the Vercel environment to your Render service URL
 * (e.g. "https://voiceagent-api.onrender.com"). When unset, same-origin is used.
 */
const API_ORIGIN: string =
  import.meta.env.VITE_API_ORIGIN ||
  (import.meta.env.DEV ? "" : "https://voiceagent-api-vzpp.onrender.com");

/** WebSocket URL for the live event feed. Carries the token when auth is on. */
export function liveFeedUrl(): string {
  return withToken(wsUrl("/api/events"));
}

/** WebSocket URL for one microphone call. */
export function liveCallUrl(): string {
  return withToken(wsUrl("/api/live"));
}

function wsUrl(path: string): string {
  if (API_ORIGIN) {
    const proto = API_ORIGIN.startsWith("https") ? "wss:" : "ws:";
    const host = API_ORIGIN.replace(/^https?:\/\//, "");
    return `${proto}//${host}${path}`;
  }
  const proto = location.protocol === "https:" ? "wss:" : "ws:";
  return `${proto}//${location.host}${path}`;
}
