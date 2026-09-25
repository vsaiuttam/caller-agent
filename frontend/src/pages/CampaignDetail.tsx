import { useEffect, useState, type DragEvent } from "react";
import { useParams } from "react-router-dom";
import { api, type BulkResult, type Campaign, type Contact } from "../api";
import { parseContactsCsv } from "../csv";
import { IconCampaign, IconFlask, IconPause, IconPlay, IconUpload } from "../components/icons";
import { useCrumb } from "../components/shell/AppShell";
import {
  Button,
  ButtonLink,
  Callout,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Field,
  Page,
  PageHeader,
  Skeleton,
  Stat,
  StatusBadge,
  Switch,
  Textarea,
  cx,
  toast,
} from "../components/ui";
import { formatDateTime, formatUsd } from "../format";
import { useAsync, useDocumentTitle } from "../hooks";

const DAY_NAMES = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function CampaignDetail() {
  const { id = "" } = useParams();
  const campaign = useAsync(() => api.campaign(id), [id]);
  const contacts = useAsync(() => api.contacts(id, { limit: 500 }), [id]);
  const [busy, setBusy] = useState(false);
  const c = campaign.data;
  useCrumb(c?.name);
  useDocumentTitle(c?.name ?? "Campaign");

  const changeStatus = async (action: "start" | "pause") => {
    setBusy(true);
    try {
      const updated = await api.setCampaignStatus(id, action);
      campaign.setData(updated);
      toast.success(
        action === "start" ? "Campaign started" : "Campaign paused",
        action === "start"
          ? "Calls go out within each contact's calling window."
          : "No new calls will be placed. Calls already on the line finish.",
      );
    } catch (err) {
      toast.error(action === "start" ? "Couldn't start the campaign" : "Couldn't pause the campaign", (err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  if (campaign.loading) {
    return (
      <Page width="wide">
        <Skeleton className="h-4 w-24" />
        <Skeleton className="mt-4 h-8 w-72 max-w-full" />
        <Skeleton className="mt-2 h-4 w-96 max-w-full" />
        <div className="mt-8 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
        <Skeleton className="mt-3 h-96 rounded-xl" />
      </Page>
    );
  }
  if (campaign.error || !c) {
    return (
      <Page>
        <ErrorNote title="Couldn't open this campaign" message={campaign.error ?? "Campaign not found"} onRetry={campaign.reload} />
      </Page>
    );
  }

  const canStart = c.status !== "running" && c.total_contacts > 0;

  return (
    <Page width="wide">
      <PageHeader
        back={{ to: "/campaigns", label: "Campaigns" }}
        icon={<IconCampaign size={18} />}
        title={c.name}
        meta={<StatusBadge status={c.status} />}
        description={c.goal}
        actions={
          <>
            <ButtonLink to={`/test-lab?campaign=${c.id}`} variant="secondary" icon={<IconFlask size={14} />}>
              Test it
            </ButtonLink>
            {c.status === "running" ? (
              <Button variant="secondary" onClick={() => changeStatus("pause")} loading={busy} icon={<IconPause size={13} />}>
                Pause
              </Button>
            ) : (
              <Button onClick={() => changeStatus("start")} loading={busy} disabled={!canStart} icon={<IconPlay size={13} />}>
                Start calling
              </Button>
            )}
          </>
        }
      />

      <div className="mb-4 grid grid-cols-2 gap-3 lg:grid-cols-4">
        <Stat label="Contacts" value={c.total_contacts.toLocaleString()} hint={`${c.pending} still to call`} />
        <Stat label="Completed" value={c.completed.toLocaleString()} hint={c.total_contacts ? `${Math.round((c.completed / c.total_contacts) * 100)}% of the list` : "—"} />
        <Stat label="To review" value={c.needs_review} hint="Outcomes held for a human" accent={c.needs_review > 0} />
        <Stat
          label="Model spend"
          value={formatUsd(c.spend_usd)}
          hint={c.budget_usd != null ? `Pauses itself at ${formatUsd(c.budget_usd, 0)}` : "No spend cap"}
        />
      </div>

      {c.total_contacts === 0 && (
        <Callout tone="warning" title="Add contacts before starting" className="mb-4">
          Import a CSV on the right. Numbers already on the do-not-call list are dropped automatically.
        </Callout>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5 lg:items-start">
        <div className="min-w-0 space-y-4 lg:col-span-3">
          <ConversationEditor campaign={c} onSaved={campaign.setData} />
          <ContactsTable contacts={contacts.data} loading={contacts.loading} error={contacts.error} onRetry={contacts.reload} total={c.total_contacts} />
        </div>

        <div className="min-w-0 space-y-4 lg:col-span-2">
          <ImportPanel
            campaignId={id}
            onImported={() => {
              contacts.reload();
              campaign.reload();
            }}
          />

          <Card>
            <CardHeader title="Calling rules" subtitle="Evaluated in each contact's own timezone." />
            <dl className="divide-y divide-line text-sm">
              <Row label="Window" value={`${String(c.calling_hours_start).padStart(2, "0")}:00 – ${String(c.calling_hours_end).padStart(2, "0")}:00`} />
              <Row label="Days" value={c.calling_days.length === 7 ? "Every day" : c.calling_days.map((d) => DAY_NAMES[d]).join(", ")} />
              <Row label="Concurrency" value={`${c.max_concurrent_calls} lines`} />
              <Row label="Max attempts" value={String(c.max_attempts)} />
              <Row label="Language" value={c.language.toUpperCase()} />
            </dl>
          </Card>

          <FollowupSettings campaign={c} onSaved={campaign.setData} />

          <Card>
            <CardHeader title="Models" subtitle="Change workspace defaults on the Models page." />
            <dl className="divide-y divide-line text-sm">
              <Row label="On the call" value={`${c.conversation_model} · ${c.conversation_effort}`} />
              <Row label="After the call" value={`${c.extraction_model} · ${c.extraction_effort}`} />
            </dl>
          </Card>
        </div>
      </div>
    </Page>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4 px-5 py-2.5">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="min-w-0 truncate text-right font-medium text-ink">{value}</dd>
    </div>
  );
}

function FollowupSettings({ campaign, onSaved }: { campaign: Campaign; onSaved: (c: Campaign) => void }) {
  const [saving, setSaving] = useState<"sms_followup" | "whatsapp_followup" | null>(null);

  const toggle = async (field: "sms_followup" | "whatsapp_followup", label: string, value: boolean) => {
    setSaving(field);
    try {
      onSaved(await api.updateCampaign(campaign.id, { [field]: value }));
      toast.success(`${label} follow-ups ${value ? "on" : "off"}`);
    } catch (err) {
      toast.error(`Couldn't change ${label} follow-ups`, (err as Error).message);
    } finally {
      setSaving(null);
    }
  };

  return (
    <Card>
      <CardHeader title="Follow-up messages" subtitle="Sent after each call. Never after an opt-out." />
      <div className="space-y-4 px-5 py-4">
        <Switch
          checked={campaign.sms_followup}
          disabled={saving !== null}
          onChange={(v) => toggle("sms_followup", "SMS", v)}
          label="SMS"
          description="A thank-you with any booked appointment, or a missed-call note."
        />
        <Switch
          checked={campaign.whatsapp_followup}
          disabled={saving !== null}
          onChange={(v) => toggle("whatsapp_followup", "WhatsApp", v)}
          label="WhatsApp"
          description="Needs TWILIO_WHATSAPP_FROM on the server."
        />
      </div>
    </Card>
  );
}

function ContactsTable({
  contacts,
  loading,
  error,
  onRetry,
  total,
}: {
  contacts: Contact[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
  total: number;
}) {
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Contacts" subtitle={`${total.toLocaleString()} on the list${total > 500 ? " · showing the first 500" : ""}`} />
      <div className="max-h-[28rem] overflow-auto">
        {loading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2].map((i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : error ? (
          <div className="p-4">
            <ErrorNote message={error} onRetry={onRetry} />
          </div>
        ) : !contacts?.length ? (
          <EmptyState compact title="No contacts yet" hint="Import a CSV with name and phone columns — the panel on the right." />
        ) : (
          <table className="data-table">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Status</th>
                <th className="text-right">Next try</th>
              </tr>
            </thead>
            <tbody>
              {contacts.map((contact) => (
                <tr key={contact.id}>
                  <td className="font-medium text-ink">{contact.full_name}</td>
                  <td className="tnum text-ink-muted">{contact.phone_masked}</td>
                  <td className="text-xs capitalize text-ink-secondary">
                    {contact.status.replace(/_/g, " ")}
                    {contact.attempts > 0 && <span className="tnum text-ink-muted"> · {contact.attempts}×</span>}
                  </td>
                  <td className="whitespace-nowrap text-right text-xs text-ink-muted">
                    {contact.next_attempt_at ? formatDateTime(contact.next_attempt_at) : "—"}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function ConversationEditor({ campaign, onSaved }: { campaign: Campaign; onSaved: (c: Campaign) => void }) {
  const [goal, setGoal] = useState(campaign.goal);
  const [greeting, setGreeting] = useState(campaign.greeting);
  const [fieldsText, setFieldsText] = useState(campaign.fields_to_collect.join("\n"));
  const [constraintsText, setConstraintsText] = useState(campaign.constraints.join("\n"));
  const [extra, setExtra] = useState(campaign.extra_instructions);
  const [saving, setSaving] = useState(false);

  const reset = () => {
    setGoal(campaign.goal);
    setGreeting(campaign.greeting);
    setFieldsText(campaign.fields_to_collect.join("\n"));
    setConstraintsText(campaign.constraints.join("\n"));
    setExtra(campaign.extra_instructions);
  };
  // eslint-disable-next-line react-hooks/exhaustive-deps
  useEffect(reset, [campaign]);

  const toLines = (t: string) => t.split("\n").map((l) => l.trim()).filter(Boolean);

  const dirty =
    goal !== campaign.goal ||
    greeting !== campaign.greeting ||
    extra !== campaign.extra_instructions ||
    fieldsText !== campaign.fields_to_collect.join("\n") ||
    constraintsText !== campaign.constraints.join("\n");

  const save = async () => {
    setSaving(true);
    try {
      onSaved(
        await api.updateCampaign(campaign.id, {
          goal,
          greeting,
          extra_instructions: extra,
          fields_to_collect: toLines(fieldsText),
          constraints: toLines(constraintsText),
        }),
      );
      toast.success("Brief saved", "Calls placed from now on use the new version.");
    } catch (err) {
      toast.error("Couldn't save the brief", (err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const preview = greeting
    .replaceAll("{first_name}", "Dana")
    .replaceAll("{full_name}", "Dana Whitfield")
    .replaceAll("{campaign_name}", campaign.name);

  return (
    <Card>
      <CardHeader
        title="The brief"
        subtitle="What the agent is told to do. Changes apply to calls placed after saving."
        action={
          dirty && (
            <>
              <Button size="sm" variant="ghost" onClick={reset} disabled={saving}>
                Discard
              </Button>
              <Button size="sm" onClick={save} loading={saving}>
                Save changes
              </Button>
            </>
          )
        }
      />
      <div className="space-y-4 px-5 py-4">
        <Field label="Goal">
          <Textarea value={goal} onChange={(e) => setGoal(e.target.value)} />
        </Field>

        <Field label="Opening line" hint="Placeholders: {first_name}, {full_name}, {campaign_name}">
          <Textarea className="font-mono min-h-16 text-xs" value={greeting} onChange={(e) => setGreeting(e.target.value)} />
        </Field>

        <div className="rounded-lg border border-line bg-subtle/50 px-4 py-3">
          <p className="text-2xs font-medium uppercase tracking-wider text-ink-muted">Agent will say</p>
          <p className="mt-1.5 text-sm italic leading-relaxed text-ink-secondary">“{preview}”</p>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Information to collect" hint="One per line.">
            <Textarea className="font-mono min-h-24 text-xs" value={fieldsText} onChange={(e) => setFieldsText(e.target.value)} />
          </Field>
          <Field label="Guardrails" hint="Things the agent must never do. One per line.">
            <Textarea className="font-mono min-h-24 text-xs" value={constraintsText} onChange={(e) => setConstraintsText(e.target.value)} />
          </Field>
        </div>

        <Field label="Additional guidance" hint="Tone, vocabulary, objection handling." optional>
          <Textarea value={extra} onChange={(e) => setExtra(e.target.value)} />
        </Field>
      </div>
    </Card>
  );
}

function ImportPanel({ campaignId, onImported }: { campaignId: string; onImported: () => void }) {
  const [result, setResult] = useState<BulkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);

  const handleFile = async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const { contacts, rejected } = parseContactsCsv(await file.text());
      if (!contacts.length) {
        throw new Error(rejected[0]?.reason ?? "No usable rows. The file needs 'name' and 'phone' columns.");
      }
      const imported = await api.addContacts(campaignId, contacts);
      setResult(imported);
      toast.success(`${imported.created} contacts added`, file.name);
      onImported();
    } catch (err) {
      const message = (err as Error).message;
      setError(message);
      toast.error("Import failed", message);
    } finally {
      setBusy(false);
    }
  };

  const onDrop = (event: DragEvent<HTMLLabelElement>) => {
    event.preventDefault();
    setDragging(false);
    const file = event.dataTransfer.files?.[0];
    if (file) void handleFile(file);
  };

  return (
    <Card>
      <CardHeader title="Import contacts" subtitle="CSV with name and phone. Extra columns become context the agent can use." />
      <div className="space-y-3 px-5 py-4">
        <label
          onDragOver={(e) => {
            e.preventDefault();
            setDragging(true);
          }}
          onDragLeave={() => setDragging(false)}
          onDrop={onDrop}
          className={cx(
            "flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed px-4 py-7 text-center transition-colors",
            dragging ? "border-brand bg-brand/6" : "border-line-strong hover:border-brand/60 hover:bg-subtle/60",
            busy && "pointer-events-none opacity-60",
          )}
        >
          <input
            type="file"
            accept=".csv,text/csv"
            className="sr-only"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
              e.target.value = "";
            }}
          />
          <span className="flex h-10 w-10 items-center justify-center rounded-full bg-subtle text-ink-secondary">
            <IconUpload size={18} />
          </span>
          <span className="text-sm font-medium text-ink">{busy ? "Importing…" : "Drop a CSV here, or choose a file"}</span>
          <span className="text-2xs text-ink-muted">name, phone, timezone, and any extra columns</span>
        </label>

        {error && <Callout tone="critical">{error}</Callout>}

        {result && (
          <Callout tone="good" title={`${result.created} contacts added`}>
            {result.skipped_suppressed > 0 && <span className="block">{result.skipped_suppressed} skipped — on the do-not-call list</span>}
            {result.skipped_duplicate > 0 && <span className="block">{result.skipped_duplicate} skipped — already in this campaign</span>}
          </Callout>
        )}
      </div>
    </Card>
  );
}
