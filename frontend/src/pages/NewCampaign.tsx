import { useMemo, useState } from "react";
import { Link, useLocation, useNavigate } from "react-router-dom";
import {
  DEFAULT_GREETING,
  api,
  type CampaignCreate,
  type CampaignTemplate,
  type NewContact,
} from "../api";
import { IconArrowLeft, IconUpload } from "../components/icons";
import { ScorecardEditor } from "../components/Scorecard";
import {
  Button,
  Card,
  CardHeader,
  ErrorNote,
  Field,
  PageWrapper,
  inputClass,
} from "../components/ui";
import { useAsync } from "../hooks";

const WEEKDAYS = [
  { value: 1, label: "Mon" },
  { value: 2, label: "Tue" },
  { value: 3, label: "Wed" },
  { value: 4, label: "Thu" },
  { value: 5, label: "Fri" },
  { value: 6, label: "Sat" },
  { value: 7, label: "Sun" },
];

const BLANK: CampaignCreate = {
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
  // Null means "inherit whatever is set on the Models page". Sending a
  // concrete value here would silently pin every new campaign to the code
  // default and make that page do nothing.
  conversation_model: null,
  conversation_effort: null,
  extraction_model: null,
  extraction_effort: null,
  budget_usd: null,
  sms_followup: true,
  whatsapp_followup: true,
  webhook_url: null,
};

/** Seed the builder from a template handed over by the Templates page. */
function fromTemplate(
  template: CampaignTemplate,
  language: string,
): CampaignCreate {
  return {
    ...BLANK,
    name: template.name,
    goal: template.goal,
    greeting: template.greetings[language] ?? template.greetings.en,
    scorecard: template.scorecard ?? [],
    fields_to_collect: template.fields_to_collect,
    constraints: template.constraints,
    extra_instructions: template.extra_instructions,
    language,
    template_id: template.id,
  };
}

export default function NewCampaign() {
  const navigate = useNavigate();
  const location = useLocation();
  const handoff = location.state as
    | { template?: CampaignTemplate; language?: string }
    | null;

  const seed = handoff?.template
    ? fromTemplate(handoff.template, handoff.language ?? "en")
    : BLANK;

  const languages = useAsync(() => api.languages());
  const catalog = useAsync(() => api.models());
  const modelName = (id: string) =>
    catalog.data?.models.find((m) => m.id === id)?.name ?? id;

  const [form, setForm] = useState<CampaignCreate>(seed);
  const [fieldsText, setFieldsText] = useState(seed.fields_to_collect.join("\n"));
  const [constraintsText, setConstraintsText] = useState(
    seed.constraints.join("\n"),
  );
  const [contacts, setContacts] = useState<NewContact[]>([]);
  const [rejected, setRejected] = useState<Array<{ line: number; reason: string }>>([]);
  const [attributeColumns, setAttributeColumns] = useState<string[]>([]);
  const [pasted, setPasted] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);

  const set = <K extends keyof CampaignCreate>(key: K, value: CampaignCreate[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const toLines = (text: string) =>
    text.split("\n").map((l) => l.trim()).filter(Boolean);

  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);

  const ingestFile = async (file: File) => {
    setParsing(true);
    setParseError(null);
    try {
      const result = await api.parseContactsFile(file, form.language);
      setContacts(result.contacts);
      setRejected(result.rejected);
      setAttributeColumns(result.attribute_columns);
    } catch (err) {
      setParseError((err as Error).message);
      setContacts([]);
    } finally {
      setParsing(false);
    }
  };

  const ingestPasted = async (text: string) => {
    if (!text.trim()) return;
    // Route pasted rows through the same server parser as uploads, so the
    // accepted formats and the rejection reasons stay identical.
    await ingestFile(new File([text], "pasted.csv", { type: "text/csv" }));
  };

  // Preview the opening line with a real-looking name, so a broken
  // placeholder is obvious here rather than on the first live call.
  const greetingPreview = useMemo(() => {
    const sample = contacts[0]?.full_name ?? "Dana Whitfield";
    try {
      return form.greeting
        .replaceAll("{first_name}", sample.split(" ")[0])
        .replaceAll("{full_name}", sample)
        .replaceAll("{campaign_name}", form.name || "your campaign");
    } catch {
      return form.greeting;
    }
  }, [form.greeting, form.name, contacts]);

  const unknownPlaceholders = useMemo(() => {
    const known = new Set(["first_name", "full_name", "campaign_name"]);
    return [...form.greeting.matchAll(/\{(\w+)\}/g)]
      .map((m) => m[1])
      .filter((name) => !known.has(name));
  }, [form.greeting]);

  const canSubmit = form.name.trim() && form.goal.trim() && !saving;

  const submit = async () => {
    setSaving(true);
    setError(null);
    try {
      const campaign = await api.createCampaign({
        ...form,
        fields_to_collect: toLines(fieldsText),
        constraints: toLines(constraintsText),
      });
      if (contacts.length) {
        await api.addContacts(campaign.id, contacts);
      }
      navigate(`/campaigns/${campaign.id}`);
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  return (
    <PageWrapper className="mx-auto max-w-6xl px-3 py-4 sm:px-8 sm:py-7">
      <Link
        to="/campaigns"
        className="inline-flex items-center gap-1.5 text-xs text-ink-muted transition hover:text-brand-bright"
      >
        <IconArrowLeft /> Campaigns
      </Link>

      <header className="mt-4 mb-6">
        <h1 className="text-2xl font-bold tracking-tight">New campaign</h1>
        <p className="mt-1 text-sm text-ink-muted">
          Define what the agent should accomplish, then load the people to call.
          Nothing dials until you press start.
        </p>
      </header>

      <div className="grid grid-cols-1 gap-3 lg:grid-cols-5">
        {/* ---------------------------------------------------------- */}
        {/* Conversation                                                */}
        {/* ---------------------------------------------------------- */}
        <div className="space-y-3 lg:col-span-3">
          <Card>
            <CardHeader
              title="Conversation"
              subtitle="This text is given to the agent as instructions — write it the way you'd brief a new hire."
            />
            <div className="space-y-4 px-5 py-4">
              <Field label="Campaign name">
                <input
                  className={inputClass}
                  value={form.name}
                  onChange={(e) => set("name", e.target.value)}
                  placeholder="Q3 appointment confirmations"
                />
              </Field>

              <Field
                label="Language"
                hint="The agent is instructed to speak this language and to switch if the person replies in another."
              >
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {(languages.data ?? []).map((lang) => (
                    <button
                      key={lang.code}
                      type="button"
                      onClick={() => {
                        set("language", lang.code);
                        // Swap in the template's greeting for the new language
                        // if this campaign came from one.
                        if (handoff?.template?.greetings[lang.code]) {
                          set("greeting", handoff.template.greetings[lang.code]);
                        }
                      }}
                      className={`rounded-lg px-3 py-1.5 text-xs font-medium transition ${
                        form.language === lang.code
                          ? "bg-brand text-[#1a1730]"
                          : "border border-white/10 text-ink-secondary hover:bg-white/5"
                      }`}
                    >
                      {lang.native_name}
                    </button>
                  ))}
                </div>
              </Field>

              <Field
                label="Goal"
                hint="What this call needs to accomplish, in one or two sentences."
              >
                <textarea
                  className={`${inputClass} min-h-20 resize-y`}
                  value={form.goal}
                  onChange={(e) => set("goal", e.target.value)}
                  placeholder="Confirm the customer still wants their upcoming service appointment. If the existing time no longer works, agree a new one."
                />
              </Field>

              <Field
                label="Opening line"
                hint="Placeholders: {first_name}, {full_name}, {campaign_name}"
              >
                <textarea
                  className={`${inputClass} min-h-16 resize-y font-mono text-xs`}
                  value={form.greeting}
                  onChange={(e) => set("greeting", e.target.value)}
                />
              </Field>

              <div className="rounded-lg border border-white/10 bg-white/3 px-3.5 py-3">
                <p className="text-xs font-medium uppercase tracking-wide text-ink-muted">
                  Agent will say
                </p>
                <p className="mt-1.5 text-sm leading-relaxed">“{greetingPreview}”</p>
                {unknownPlaceholders.length > 0 && (
                  <p className="mt-2 text-xs text-critical">
                    Unknown placeholder{unknownPlaceholders.length > 1 ? "s" : ""}:{" "}
                    {unknownPlaceholders.map((p) => `{${p}}`).join(", ")} — these will be
                    read aloud literally.
                  </p>
                )}
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Information to collect" hint="One per line.">
                  <textarea
                    className={`${inputClass} min-h-28 resize-y font-mono text-xs`}
                    value={fieldsText}
                    onChange={(e) => setFieldsText(e.target.value)}
                    placeholder={
                      "Whether the existing appointment still works\nPreferred day and time if rescheduling\nBest contact email"
                    }
                  />
                </Field>
                <Field
                  label="Boundaries"
                  hint="Things the agent must never do. One per line."
                >
                  <textarea
                    className={`${inputClass} min-h-28 resize-y font-mono text-xs`}
                    value={constraintsText}
                    onChange={(e) => setConstraintsText(e.target.value)}
                    placeholder={
                      "Never quote a price\nDo not offer refunds or credits\nDo not discuss other customers"
                    }
                  />
                </Field>
              </div>

              <Field
                label="Scorecard"
                hint="What each call is judged on. Turns results into a ranked list instead of a call log."
              >
                <div className="mt-1.5">
                  <ScorecardEditor
                    value={form.scorecard}
                    onChange={(next) => set("scorecard", next)}
                  />
                </div>
              </Field>

              <Field
                label="Additional guidance"
                hint="Tone, vocabulary, how to handle common objections. Optional."
              >
                <textarea
                  className={`${inputClass} min-h-20 resize-y`}
                  value={form.extra_instructions}
                  onChange={(e) => set("extra_instructions", e.target.value)}
                  placeholder="Customers often ask whether a technician will call ahead — they will, about 30 minutes before arrival. Keep the tone warm but brief; most of these people are at work."
                />
              </Field>
            </div>
          </Card>
        </div>

        {/* ---------------------------------------------------------- */}
        {/* Contacts + rules                                            */}
        {/* ---------------------------------------------------------- */}
        <div className="space-y-3 lg:col-span-2">
          <Card>
            <CardHeader
              title="Who to call"
              subtitle="CSV with name and phone columns. Any extra columns become context the agent can reference on the call."
            />
            <div className="space-y-3 px-5 py-4">
              <label className="flex cursor-pointer flex-col items-center gap-2 rounded-lg border border-dashed border-white/10 px-4 py-6 text-center transition hover:border-brand hover:bg-brand/6">
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls,.xlsm,text/csv"
                  className="hidden"
                  disabled={parsing}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void ingestFile(file);
                    e.target.value = "";
                  }}
                />
                <span className="text-ink-muted">
                  <IconUpload />
                </span>
                <span className="text-xs text-ink-secondary">
                  {parsing ? "Reading…" : "Choose an Excel or CSV file"}
                </span>
                <span className="text-[10px] text-ink-muted">
                  .xlsx · .xls · .csv
                </span>
              </label>

              <details className="group">
                <summary className="cursor-pointer text-xs text-ink-muted transition hover:text-ink">
                  or paste rows
                </summary>
                <textarea
                  className={`${inputClass} min-h-24 resize-y font-mono text-xs`}
                  value={pasted}
                  onChange={(e) => setPasted(e.target.value)}
                  onBlur={() => void ingestPasted(pasted)}
                  placeholder={"name,phone,timezone\nDana Whitfield,+14155550142,America/Los_Angeles"}
                />
              </details>

              {parseError && <ErrorNote message={parseError} />}

              {contacts.length > 0 && (
                <div className="rounded-lg border border-white/10">
                  <div className="flex items-center justify-between border-b border-white/10 px-3 py-2">
                    <span className="text-xs font-medium">
                      {contacts.length} contact{contacts.length === 1 ? "" : "s"} ready
                    </span>
                    <button
                      onClick={() => {
                        setContacts([]);
                        setRejected([]);
                        setAttributeColumns([]);
                        setPasted("");
                      }}
                      className="text-xs text-ink-muted transition hover:text-critical"
                    >
                      Clear
                    </button>
                  </div>
                  <ul className="max-h-40 divide-y divide-line overflow-y-auto">
                    {contacts.slice(0, 50).map((c, i) => (
                      <li
                        key={`${c.phone_e164}-${i}`}
                        className="flex items-center justify-between px-3 py-1.5 text-xs"
                      >
                        <span className="truncate">{c.full_name}</span>
                        <span className="tnum shrink-0 text-ink-muted">
                          {c.phone_e164}
                        </span>
                      </li>
                    ))}
                  </ul>
                  {contacts.length > 50 && (
                    <p className="border-t border-white/10 px-3 py-1.5 text-xs text-ink-muted">
                      …and {contacts.length - 50} more
                    </p>
                  )}
                  {attributeColumns.length > 0 && (
                    <p className="border-t border-white/10 px-3 py-2 text-xs text-ink-muted">
                      Extra context per contact:{" "}
                      <span className="text-ink-secondary">
                        {attributeColumns.join(", ")}
                      </span>
                    </p>
                  )}
                </div>
              )}

              {rejected.length > 0 && (
                <div className="rounded-lg border border-warning/40 bg-warning/8 px-3 py-2">
                  <p className="text-xs font-medium text-warning">
                    {rejected.length} row{rejected.length === 1 ? "" : "s"} skipped
                  </p>
                  <ul className="mt-1 space-y-0.5">
                    {rejected.slice(0, 5).map((r) => (
                      <li key={r.line} className="text-xs text-ink-secondary">
                        Line {r.line}: {r.reason}
                      </li>
                    ))}
                  </ul>
                </div>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader
              title="When to call"
              subtitle="Evaluated in each contact's own timezone."
            />
            <div className="space-y-4 px-5 py-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label="From">
                  <input
                    type="number"
                    min={0}
                    max={23}
                    className={inputClass}
                    value={form.calling_hours_start}
                    onChange={(e) =>
                      set("calling_hours_start", Number(e.target.value))
                    }
                  />
                </Field>
                <Field label="Until">
                  <input
                    type="number"
                    min={1}
                    max={24}
                    className={inputClass}
                    value={form.calling_hours_end}
                    onChange={(e) => set("calling_hours_end", Number(e.target.value))}
                  />
                </Field>
              </div>

              <Field label="Days">
                <div className="mt-1.5 flex flex-wrap gap-1.5">
                  {WEEKDAYS.map((day) => {
                    const on = form.calling_days.includes(day.value);
                    return (
                      <button
                        key={day.value}
                        type="button"
                        onClick={() =>
                          set(
                            "calling_days",
                            on
                              ? form.calling_days.filter((d) => d !== day.value)
                              : [...form.calling_days, day.value].sort(),
                          )
                        }
                        className={`rounded-lg px-2.5 py-1.5 text-xs font-medium transition ${
                          on
                            ? "bg-brand text-white"
                            : "border border-white/10 text-ink-muted hover:bg-white/3"
                        }`}
                      >
                        {day.label}
                      </button>
                    );
                  })}
                </div>
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Concurrent lines">
                  <input
                    type="number"
                    min={1}
                    className={inputClass}
                    value={form.max_concurrent_calls}
                    onChange={(e) =>
                      set("max_concurrent_calls", Number(e.target.value))
                    }
                  />
                </Field>
                <Field label="Max attempts">
                  <input
                    type="number"
                    min={1}
                    max={10}
                    className={inputClass}
                    value={form.max_attempts}
                    onChange={(e) => set("max_attempts", Number(e.target.value))}
                  />
                </Field>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader
              title="Models &amp; spend"
              subtitle="Leave blank to inherit the workspace defaults."
            />
            <div className="space-y-3 px-5 py-4">
              {catalog.data && (
                <>
                  <Field
                    label="On the call"
                    hint="Latency is what the person on the line feels."
                  >
                    <select
                      className={inputClass}
                      value={form.conversation_model ?? ""}
                      onChange={(e) =>
                        set("conversation_model", e.target.value || null)
                      }
                    >
                      <option value="">
                        Default ({modelName(catalog.data.defaults.conversation_model)})
                      </option>
                      {catalog.data.models
                        .filter((m) => m.roles.includes("conversation"))
                        .map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                    </select>
                  </Field>

                  <Field
                    label="After the call"
                    hint="Reads the transcript and writes the record."
                  >
                    <select
                      className={inputClass}
                      value={form.extraction_model ?? ""}
                      onChange={(e) =>
                        set("extraction_model", e.target.value || null)
                      }
                    >
                      <option value="">
                        Default ({modelName(catalog.data.defaults.extraction_model)})
                      </option>
                      {catalog.data.models
                        .filter((m) => m.roles.includes("extraction"))
                        .map((m) => (
                          <option key={m.id} value={m.id}>
                            {m.name}
                          </option>
                        ))}
                    </select>
                  </Field>
                </>
              )}

              <Field
                label="Spend cap (USD)"
                hint="The campaign pauses itself when model spend reaches this. Calls already in flight always finish."
              >
                <input
                  type="number"
                  min={0}
                  step="1"
                  placeholder="No cap"
                  className={`${inputClass} tnum`}
                  value={form.budget_usd ?? ""}
                  onChange={(e) =>
                    set(
                      "budget_usd",
                      e.target.value === "" ? null : Number(e.target.value),
                    )
                  }
                />
              </Field>

              <Field
                label="Follow-up messages"
                hint="After each call: a thank-you with any booked appointment, or a missed-call note if nobody answered. Nothing is sent after an opt-out."
              >
                <div className="flex flex-wrap gap-x-5 gap-y-2">
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.sms_followup}
                      onChange={(e) => set("sms_followup", e.target.checked)}
                      className="accent-[var(--color-brand)]"
                    />
                    <span className="text-sm">SMS</span>
                  </label>
                  <label className="flex cursor-pointer items-center gap-2">
                    <input
                      type="checkbox"
                      checked={form.whatsapp_followup}
                      onChange={(e) => set("whatsapp_followup", e.target.checked)}
                      className="accent-[var(--color-brand)]"
                    />
                    <span className="text-sm">WhatsApp</span>
                  </label>
                </div>
              </Field>

              <Field
                label="Webhook URL"
                hint="POSTed once per completed call, signed with WEBHOOK_SIGNING_SECRET when it's set."
              >
                <input
                  type="url"
                  placeholder="https://…"
                  className={inputClass}
                  value={form.webhook_url ?? ""}
                  onChange={(e) => set("webhook_url", e.target.value || null)}
                />
              </Field>
            </div>
          </Card>

          {error && <ErrorNote message={error} />}

          <div className="flex items-center justify-between gap-3 rounded-xl border border-white/10 bg-surface px-4 py-3">
            <p className="text-xs text-ink-muted">
              {contacts.length
                ? `Creates the campaign and imports ${contacts.length} contact${contacts.length === 1 ? "" : "s"}.`
                : "You can add contacts after creating."}
            </p>
            <Button onClick={submit} disabled={!canSubmit}>
              {saving ? "Creating…" : "Create campaign"}
            </Button>
          </div>
        </div>
      </div>
    </PageWrapper>
  );
}
