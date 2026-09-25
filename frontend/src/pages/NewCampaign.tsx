import { useMemo, useState, type DragEvent } from "react";
import { useLocation, useNavigate } from "react-router-dom";
import {
  DEFAULT_GREETING,
  api,
  campaignTools,
  type CampaignCreate,
  type CampaignTemplate,
  type NewContact,
} from "../api";
import { IconCampaign, IconUpload } from "../components/icons";
import { CampaignToolsCard } from "../components/mcp/CampaignTools";
import { ScorecardEditor } from "../components/Scorecard";
import {
  Button,
  Callout,
  Card,
  CardHeader,
  Field,
  Input,
  Page,
  PageHeader,
  Select,
  Skeleton,
  Switch,
  Textarea,
  cx,
  toast,
} from "../components/ui";
import { useAsync, useDocumentTitle } from "../hooks";

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
  mcp_tools: [],
  mcp_post_call_tools: [],
  mcp_post_call_instructions: "",
};

/** Seed the builder from a template handed over by the Templates page. */
function fromTemplate(template: CampaignTemplate, language: string): CampaignCreate {
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

const chip = (active: boolean) =>
  cx(
    "h-8 rounded-md px-3 text-xs font-medium transition-colors duration-150",
    active ? "bg-brand text-on-brand" : "border border-line-strong bg-surface text-ink-secondary hover:bg-subtle hover:text-ink",
  );

export default function NewCampaign() {
  useDocumentTitle("New campaign");
  const navigate = useNavigate();
  const location = useLocation();
  const handoff = location.state as { template?: CampaignTemplate; language?: string } | null;

  const seed = handoff?.template ? fromTemplate(handoff.template, handoff.language ?? "en") : BLANK;

  const languages = useAsync(() => api.languages());
  const catalog = useAsync(() => api.models());
  const modelName = (id: string) => catalog.data?.models.find((m) => m.id === id)?.name ?? id;

  const [form, setForm] = useState<CampaignCreate>(seed);
  const [fieldsText, setFieldsText] = useState(seed.fields_to_collect.join("\n"));
  const [constraintsText, setConstraintsText] = useState(seed.constraints.join("\n"));
  const [contacts, setContacts] = useState<NewContact[]>([]);
  const [rejected, setRejected] = useState<Array<{ line: number; reason: string }>>([]);
  const [attributeColumns, setAttributeColumns] = useState<string[]>([]);
  const [pasted, setPasted] = useState("");
  const [error, setError] = useState<string | null>(null);
  const [saving, setSaving] = useState(false);
  const [parsing, setParsing] = useState(false);
  const [parseError, setParseError] = useState<string | null>(null);
  const [dragging, setDragging] = useState(false);

  const set = <K extends keyof CampaignCreate>(key: K, value: CampaignCreate[K]) =>
    setForm((f) => ({ ...f, [key]: value }));

  const toLines = (text: string) => text.split("\n").map((l) => l.trim()).filter(Boolean);

  const ingestFile = async (file: File) => {
    setParsing(true);
    setParseError(null);
    try {
      const result = await api.parseContactsFile(file, form.language);
      setContacts(result.contacts);
      setRejected(result.rejected);
      setAttributeColumns(result.attribute_columns);
      if (result.contacts.length) toast.success(`${result.contacts.length} contacts ready`, "They're imported when you create the campaign.");
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
    return form.greeting
      .replaceAll("{first_name}", sample.split(" ")[0])
      .replaceAll("{full_name}", sample)
      .replaceAll("{campaign_name}", form.name || "your campaign");
  }, [form.greeting, form.name, contacts]);

  const unknownPlaceholders = useMemo(() => {
    const known = new Set(["first_name", "full_name", "campaign_name"]);
    return [...form.greeting.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).filter((name) => !known.has(name));
  }, [form.greeting]);

  const missing = [!form.name.trim() && "a name", !form.goal.trim() && "a goal"].filter(Boolean) as string[];
  const canSubmit = missing.length === 0 && !saving;

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
        const imported = await api.addContacts(campaign.id, contacts);
        toast.success(`“${campaign.name}” created`, `${imported.created} contacts imported. Nothing dials until you press start.`);
      } else {
        toast.success(`“${campaign.name}” created`, "Add contacts, then press start.");
      }
      navigate(`/campaigns/${campaign.id}`);
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      toast.error("Couldn't create the campaign", message);
    } finally {
      setSaving(false);
    }
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void ingestFile(file);
  };

  return (
    <Page width="wide">
      <PageHeader
        back={{ to: "/campaigns", label: "Campaigns" }}
        icon={<IconCampaign size={18} />}
        title="New campaign"
        description={
          handoff?.template
            ? `Starting from the “${handoff.template.name}” template — edit anything. Nothing dials until you press start.`
            : "Brief the agent, then load the people to call. Nothing dials until you press start."
        }
      />

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5 lg:items-start">
        {/* Brief */}
        <div className="min-w-0 space-y-4 lg:col-span-3">
          <Card>
            <CardHeader title="The brief" subtitle="Given to the agent as instructions — write it the way you'd brief a new hire." />
            <div className="space-y-5 px-5 py-5">
              <Field label="Campaign name">
                <Input value={form.name} onChange={(e) => set("name", e.target.value)} placeholder="Q3 appointment confirmations" />
              </Field>

              <Field label="Language" group hint="The agent speaks this language, and switches if the person replies in another.">
                {languages.loading ? (
                  <Skeleton className="h-8 w-64" />
                ) : (
                  <div className="flex flex-wrap gap-1.5">
                    {(languages.data ?? []).map((lang) => (
                      <button
                        key={lang.code}
                        type="button"
                        aria-pressed={form.language === lang.code}
                        onClick={() => {
                          set("language", lang.code);
                          // Swap in the template's greeting for the new
                          // language if this campaign came from one.
                          if (handoff?.template?.greetings[lang.code]) set("greeting", handoff.template.greetings[lang.code]);
                        }}
                        className={chip(form.language === lang.code)}
                      >
                        {lang.native_name}
                      </button>
                    ))}
                  </div>
                )}
              </Field>

              <Field label="Goal" hint="What this call needs to accomplish, in one or two sentences.">
                <Textarea
                  value={form.goal}
                  onChange={(e) => set("goal", e.target.value)}
                  placeholder="Confirm the customer still wants their upcoming service appointment. If the time no longer works, agree a new one."
                />
              </Field>

              <Field label="Opening line" hint="Placeholders: {first_name}, {full_name}, {campaign_name}">
                <Textarea className="font-mono min-h-16 text-xs" value={form.greeting} onChange={(e) => set("greeting", e.target.value)} />
              </Field>

              <div className="rounded-lg border border-line bg-subtle/50 px-4 py-3">
                <p className="text-2xs font-medium uppercase tracking-wider text-ink-muted">Agent will say</p>
                <p className="mt-1.5 text-sm italic leading-relaxed text-ink">“{greetingPreview}”</p>
                {unknownPlaceholders.length > 0 && (
                  <p className="mt-2 text-xs text-critical">
                    Unknown placeholder{unknownPlaceholders.length > 1 ? "s" : ""}: {unknownPlaceholders.map((p) => `{${p}}`).join(", ")} —
                    these will be read aloud literally.
                  </p>
                )}
              </div>

              <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
                <Field label="Information to collect" hint="One per line.">
                  <Textarea
                    className="font-mono min-h-28 text-xs"
                    value={fieldsText}
                    onChange={(e) => setFieldsText(e.target.value)}
                    placeholder={"Whether the appointment still works\nPreferred day and time if rescheduling\nBest contact email"}
                  />
                </Field>
                <Field label="Guardrails" hint="Things the agent must never do. One per line.">
                  <Textarea
                    className="font-mono min-h-28 text-xs"
                    value={constraintsText}
                    onChange={(e) => setConstraintsText(e.target.value)}
                    placeholder={"Never quote a price\nDo not offer refunds or credits\nDo not discuss other customers"}
                  />
                </Field>
              </div>

              <Field label="Scorecard" group hint="What each call is judged on. Turns results into a ranked list instead of a call log.">
                <ScorecardEditor value={form.scorecard} onChange={(next) => set("scorecard", next)} />
              </Field>

              <Field label="Additional guidance" optional hint="Tone, vocabulary, how to handle common objections.">
                <Textarea
                  value={form.extra_instructions}
                  onChange={(e) => set("extra_instructions", e.target.value)}
                  placeholder="Customers often ask whether a technician will call ahead — they will, about 30 minutes before arrival. Keep it warm but brief."
                />
              </Field>
            </div>
          </Card>

          <CampaignToolsCard value={campaignTools(form)} onChange={(next) => setForm((f) => ({ ...f, ...next }))} />
        </div>

        {/* Contacts, rules, models */}
        <div className="min-w-0 space-y-4 lg:col-span-2">
          <Card>
            <CardHeader title="Who to call" subtitle="Excel or CSV with name and phone columns. Extra columns become context for the agent." />
            <div className="space-y-3 px-5 py-4">
              <label
                onDragOver={(e) => {
                  e.preventDefault();
                  setDragging(true);
                }}
                onDragLeave={() => setDragging(false)}
                onDrop={onDrop}
                className={cx(
                  "flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-6 text-center transition-colors",
                  dragging ? "border-brand bg-brand/6" : "border-line-strong hover:border-brand/60 hover:bg-subtle/60",
                  parsing && "pointer-events-none opacity-60",
                )}
              >
                <input
                  type="file"
                  accept=".csv,.xlsx,.xls,.xlsm,text/csv"
                  className="sr-only"
                  disabled={parsing}
                  onChange={(e) => {
                    const file = e.target.files?.[0];
                    if (file) void ingestFile(file);
                    e.target.value = "";
                  }}
                />
                <span className="flex h-10 w-10 items-center justify-center rounded-full bg-subtle text-ink-secondary">
                  <IconUpload size={18} />
                </span>
                <span className="text-sm font-medium text-ink">{parsing ? "Reading…" : "Drop a file here, or choose one"}</span>
                <span className="text-2xs text-ink-muted">.xlsx · .xls · .csv</span>
              </label>

              <details className="group">
                <summary className="cursor-pointer rounded text-xs font-medium text-ink-muted transition-colors hover:text-ink">
                  …or paste rows
                </summary>
                <Textarea
                  className="font-mono mt-2 min-h-24 text-xs"
                  value={pasted}
                  onChange={(e) => setPasted(e.target.value)}
                  onBlur={() => void ingestPasted(pasted)}
                  placeholder={"name,phone,timezone\nDana Whitfield,+14155550142,America/Los_Angeles"}
                  aria-label="Paste contact rows"
                />
              </details>

              {parseError && <Callout tone="critical">{parseError}</Callout>}

              {contacts.length > 0 && (
                <div className="overflow-hidden rounded-lg border border-line">
                  <div className="flex items-center justify-between border-b border-line bg-subtle/50 px-3 py-2">
                    <span className="text-xs font-medium text-ink">
                      {contacts.length} contact{contacts.length === 1 ? "" : "s"} ready
                    </span>
                    <button
                      type="button"
                      onClick={() => {
                        setContacts([]);
                        setRejected([]);
                        setAttributeColumns([]);
                        setPasted("");
                      }}
                      className="text-xs font-medium text-ink-muted transition-colors hover:text-critical"
                    >
                      Clear
                    </button>
                  </div>
                  <ul className="max-h-44 divide-y divide-line overflow-y-auto">
                    {contacts.slice(0, 50).map((c, i) => (
                      <li key={`${c.phone_e164}-${i}`} className="flex items-center justify-between gap-3 px-3 py-1.5 text-xs">
                        <span className="truncate text-ink">{c.full_name}</span>
                        <span className="tnum shrink-0 text-ink-muted">{c.phone_e164}</span>
                      </li>
                    ))}
                  </ul>
                  {contacts.length > 50 && (
                    <p className="border-t border-line px-3 py-1.5 text-xs text-ink-muted">…and {contacts.length - 50} more</p>
                  )}
                  {attributeColumns.length > 0 && (
                    <p className="border-t border-line px-3 py-2 text-xs text-ink-muted">
                      Extra context per contact: <span className="text-ink-secondary">{attributeColumns.join(", ")}</span>
                    </p>
                  )}
                </div>
              )}

              {rejected.length > 0 && (
                <Callout tone="warning" title={`${rejected.length} row${rejected.length === 1 ? "" : "s"} skipped`}>
                  {rejected.slice(0, 5).map((r) => (
                    <span key={r.line} className="block">
                      Line {r.line}: {r.reason}
                    </span>
                  ))}
                </Callout>
              )}
            </div>
          </Card>

          <Card>
            <CardHeader title="When to call" subtitle="Evaluated in each contact's own timezone." />
            <div className="space-y-4 px-5 py-4">
              <div className="grid grid-cols-2 gap-3">
                <Field label="From (hour)">
                  <Input type="number" min={0} max={23} value={form.calling_hours_start} onChange={(e) => set("calling_hours_start", Number(e.target.value))} />
                </Field>
                <Field label="Until (hour)">
                  <Input type="number" min={1} max={24} value={form.calling_hours_end} onChange={(e) => set("calling_hours_end", Number(e.target.value))} />
                </Field>
              </div>

              <Field label="Days" group>
                <div className="flex flex-wrap gap-1.5">
                  {WEEKDAYS.map((day) => {
                    const on = form.calling_days.includes(day.value);
                    return (
                      <button
                        key={day.value}
                        type="button"
                        aria-pressed={on}
                        onClick={() =>
                          set(
                            "calling_days",
                            on ? form.calling_days.filter((d) => d !== day.value) : [...form.calling_days, day.value].sort(),
                          )
                        }
                        className={chip(on)}
                      >
                        {day.label}
                      </button>
                    );
                  })}
                </div>
              </Field>

              <div className="grid grid-cols-2 gap-3">
                <Field label="Concurrent lines">
                  <Input type="number" min={1} value={form.max_concurrent_calls} onChange={(e) => set("max_concurrent_calls", Number(e.target.value))} />
                </Field>
                <Field label="Max attempts">
                  <Input type="number" min={1} max={10} value={form.max_attempts} onChange={(e) => set("max_attempts", Number(e.target.value))} />
                </Field>
              </div>
            </div>
          </Card>

          <Card>
            <CardHeader title="Models, spend & follow-ups" subtitle="Blank model fields inherit the workspace defaults." />
            <div className="space-y-4 px-5 py-4">
              {catalog.loading ? (
                <Skeleton className="h-20 w-full" />
              ) : (
                catalog.data && (
                  <>
                    <Field label="On the call" hint="Latency is what the person on the line feels.">
                      <Select value={form.conversation_model ?? ""} onChange={(e) => set("conversation_model", e.target.value || null)}>
                        <option value="">Default ({modelName(catalog.data.defaults.conversation_model)})</option>
                        {catalog.data.models
                          .filter((m) => m.roles.includes("conversation"))
                          .map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                            </option>
                          ))}
                      </Select>
                    </Field>
                    <Field label="After the call" hint="Reads the transcript and writes the record.">
                      <Select value={form.extraction_model ?? ""} onChange={(e) => set("extraction_model", e.target.value || null)}>
                        <option value="">Default ({modelName(catalog.data.defaults.extraction_model)})</option>
                        {catalog.data.models
                          .filter((m) => m.roles.includes("extraction"))
                          .map((m) => (
                            <option key={m.id} value={m.id}>
                              {m.name}
                            </option>
                          ))}
                      </Select>
                    </Field>
                  </>
                )
              )}

              <Field label="Spend cap (USD)" optional hint="The campaign pauses itself when model spend reaches this. Calls in flight always finish.">
                <Input
                  type="number"
                  min={0}
                  step="1"
                  placeholder="No cap"
                  className="tnum"
                  value={form.budget_usd ?? ""}
                  onChange={(e) => set("budget_usd", e.target.value === "" ? null : Number(e.target.value))}
                />
              </Field>

              <div className="space-y-3 rounded-lg border border-line p-3.5">
                <p className="text-xs font-medium text-ink-secondary">Follow-up messages after each call</p>
                <Switch checked={form.sms_followup} onChange={(v) => set("sms_followup", v)} label="SMS" />
                <Switch
                  checked={form.whatsapp_followup}
                  onChange={(v) => set("whatsapp_followup", v)}
                  label="WhatsApp"
                  description="A thank-you with any booked appointment, or a missed-call note. Never after an opt-out."
                />
              </div>

              <Field label="Webhook URL" optional hint="POSTed once per completed call, signed with WEBHOOK_SIGNING_SECRET when it's set.">
                <Input type="url" placeholder="https://…" value={form.webhook_url ?? ""} onChange={(e) => set("webhook_url", e.target.value || null)} />
              </Field>
            </div>
          </Card>

          {error && <Callout tone="critical" title="The campaign wasn't created">{error}</Callout>}

          <div className="sticky bottom-4 z-10 flex items-center justify-between gap-3 rounded-xl border border-line bg-raised/95 px-4 py-3 elev-2 backdrop-blur">
            <p className="text-xs text-ink-muted">
              {missing.length
                ? `Add ${missing.join(" and ")} to continue.`
                : contacts.length
                  ? `Creates the campaign and imports ${contacts.length} contact${contacts.length === 1 ? "" : "s"}.`
                  : "You can add contacts after creating."}
            </p>
            <Button onClick={submit} disabled={!canSubmit} loading={saving}>
              {saving ? "Creating…" : "Create campaign"}
            </Button>
          </div>
        </div>
      </div>
    </Page>
  );
}
