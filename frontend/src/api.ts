/**
 * Typed API client. Mirrors src/voiceagent/api/schemas.py and the v2 contract
 * in docs/v2-spec.md §1 — when a schema changes there, change it here too;
 * there's no codegen step wired up yet.
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
}

export type CampaignUpdate = Partial<CampaignCreate>;

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
}

export interface AuthStatus {
  auth_enabled: boolean;
  authenticated: boolean;
}

export interface LoginResult {
  token: string;
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
}

export interface HourBucket {
  hour: string;
  label: string;
  total: number;
  connected: number;
}

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

/** What the session reports while a call is up (§1.1 `on_event("state")`). */
export type CallStateName = "speaking" | "listening" | "thinking" | "ended";

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
  "call.state": { call_id: string; state: CallStateName };
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

export const api = {
  stats: () => request<DashboardStats>("/api/stats"),
  health: () => request<Health>("/api/health"),

  authStatus: () => request<AuthStatus>("/api/auth/status", undefined, { reportUnauthorized: false }),
  /** 401 here means a wrong password, not an expired session. */
  login: (password: string) =>
    request<LoginResult>("/api/auth/login", post({ password }), { reportUnauthorized: false }),

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
};

export function saveBlob(blob: Blob, filename: string) {
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
