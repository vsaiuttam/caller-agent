/**
 * The campaign builder's working copy, and how it maps to and from the API.
 * One shape for new and edit, so the same steps serve both.
 */

import { DEFAULT_GREETING, type Campaign, type CampaignCreate, type CampaignTemplate, type NewContact } from "../../api";

export const STEPS = [
  { id: "basics", label: "Basics", short: "Basics" },
  { id: "agent", label: "Agent", short: "Agent" },
  { id: "tools", label: "Tools", short: "Tools" },
  { id: "contacts", label: "Contacts", short: "Contacts" },
  { id: "schedule", label: "Schedule & messages", short: "Schedule" },
  { id: "review", label: "Review & launch", short: "Review" },
] as const;

export type StepId = (typeof STEPS)[number]["id"];

export const isStep = (value: string | null): value is StepId => STEPS.some((s) => s.id === value);

export interface Draft {
  form: CampaignCreate;
  /** Textareas edited as text, split into lists on save. */
  fieldsText: string;
  constraintsText: string;
  /** New contacts to import on save (the saved ones stay on the server). */
  contacts: NewContact[];
  rejected: Array<{ line: number; reason: string }>;
  attributeColumns: string[];
  /** The template's greeting per language, when the campaign came from one. */
  templateGreetings: Record<string, string> | null;
}

export const DEFAULT_PRECALL =
  "Hi {name}, this is {agent} from {company}. We'll call you in about {minutes} minutes about your enquiry. Reply STOP to opt out.";

export const BLANK_FORM: CampaignCreate = {
  name: "",
  goal: "",
  greeting: DEFAULT_GREETING,
  scorecard: [],
  fields_to_collect: [],
  constraints: [],
  extra_instructions: "",
  language: "en",
  template_id: null,
  calling_hours_start: 9,
  calling_hours_end: 20,
  calling_days: [1, 2, 3, 4, 5],
  max_concurrent_calls: 10,
  max_attempts: 3,
  // Null means "inherit the workspace default"; a concrete value would pin
  // every new campaign to today's default.
  conversation_model: null,
  conversation_effort: null,
  extraction_model: null,
  extraction_effort: null,
  budget_usd: null,
  sms_followup: true,
  whatsapp_followup: true,
  webhook_url: null,
  mcp_tools: [],
  mcp_post_call_tools: [],
  mcp_post_call_instructions: "",
  conversation_provider_id: null,
  extraction_provider_id: null,
  voice: null,
  precall_enabled: false,
  precall_channel: "sms",
  precall_message: DEFAULT_PRECALL,
  precall_lead_minutes: 10,
};

export function blankDraft(): Draft {
  return {
    form: { ...BLANK_FORM },
    fieldsText: "",
    constraintsText: "",
    contacts: [],
    rejected: [],
    attributeColumns: [],
    templateGreetings: null,
  };
}

export function draftFromTemplate(template: CampaignTemplate, language: string): Draft {
  const draft = blankDraft();
  draft.form = {
    ...draft.form,
    name: template.name,
    goal: template.goal,
    greeting: template.greetings[language] ?? template.greetings.en ?? DEFAULT_GREETING,
    scorecard: template.scorecard ?? [],
    fields_to_collect: template.fields_to_collect,
    constraints: template.constraints,
    extra_instructions: template.extra_instructions,
    language,
    template_id: template.id,
  };
  draft.fieldsText = template.fields_to_collect.join("\n");
  draft.constraintsText = template.constraints.join("\n");
  draft.templateGreetings = template.greetings;
  return draft;
}

const KEYS = Object.keys(BLANK_FORM) as Array<keyof CampaignCreate>;

/** A saved campaign as a builder draft. Resolved model names stay null unless the campaign pinned them. */
export function draftFromCampaign(c: Campaign): Draft {
  const form = { ...BLANK_FORM } as Record<string, unknown>;
  for (const key of KEYS) {
    const value = (c as unknown as Record<string, unknown>)[key];
    if (value !== undefined) form[key] = value;
  }
  const f = form as unknown as CampaignCreate;
  f.precall_message = f.precall_message || DEFAULT_PRECALL;
  f.precall_channel = f.precall_channel || "sms";
  f.precall_lead_minutes = f.precall_lead_minutes ?? 10;
  f.mcp_tools = f.mcp_tools ?? [];
  f.mcp_post_call_tools = f.mcp_post_call_tools ?? [];
  f.mcp_post_call_instructions = f.mcp_post_call_instructions ?? "";
  return {
    form: f,
    fieldsText: c.fields_to_collect.join("\n"),
    constraintsText: c.constraints.join("\n"),
    contacts: [],
    rejected: [],
    attributeColumns: [],
    templateGreetings: null,
  };
}

const toLines = (text: string) =>
  text
    .split("\n")
    .map((l) => l.trim())
    .filter(Boolean);

export function payloadOf(draft: Draft): CampaignCreate {
  return {
    ...draft.form,
    name: draft.form.name.trim(),
    goal: draft.form.goal.trim(),
    fields_to_collect: toLines(draft.fieldsText),
    constraints: toLines(draft.constraintsText),
  };
}

/** Equal for autosave purposes: what would be sent, plus the pending contacts. */
export function sameDraft(a: Draft, b: Draft): boolean {
  return JSON.stringify([payloadOf(a), a.contacts.length]) === JSON.stringify([payloadOf(b), b.contacts.length]);
}

export const KNOWN_PLACEHOLDERS = ["first_name", "full_name", "campaign_name"];

export function unknownPlaceholders(greeting: string): string[] {
  return [...greeting.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).filter((name) => !KNOWN_PLACEHOLDERS.includes(name));
}

export function greetingPreview(greeting: string, name: string, sample = "Ananya Rao"): string {
  return greeting
    .replaceAll("{first_name}", sample.split(" ")[0])
    .replaceAll("{full_name}", sample)
    .replaceAll("{campaign_name}", name || "your campaign");
}

export const hour = (h: number) => `${String(h % 24).padStart(2, "0")}:00`;

export const DAY_NAMES = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export function daysLabel(days: number[]): string {
  const sorted = [...days].sort();
  if (sorted.length === 7) return "Every day";
  if (sorted.join() === "1,2,3,4,5") return "Weekdays";
  if (sorted.join() === "6,7") return "Weekends";
  return sorted.map((d) => DAY_NAMES[d]).join(", ") || "No days";
}
