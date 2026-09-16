import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, type BulkResult, type Campaign } from "../api";
import { parseContactsCsv } from "../csv";
import {
  IconArrowLeft,
  IconPause,
  IconPlay,
  IconUpload,
} from "../components/icons";
import {
  Button,
  Card,
  CardHeader,
  EmptyState,
  ErrorNote,
  Field,
  PageWrapper,
  Skeleton,
  StatusBadge,
  formatDateTime,
  inputClass,
} from "../components/ui";
import { useAsync } from "../hooks";

const DAY_NAMES = ["", "Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"];

export default function CampaignDetail() {
  const { id = "" } = useParams();
  const campaign = useAsync(() => api.campaign(id), [id]);
  const contacts = useAsync(() => api.contacts(id, { limit: 500 }), [id]);
  const [busy, setBusy] = useState(false);

  const c = campaign.data;

  const changeStatus = async (action: "start" | "pause") => {
    setBusy(true);
    try {
      await api.setCampaignStatus(id, action);
      campaign.reload();
    } finally {
      setBusy(false);
    }
  };

  if (campaign.loading) {
    return (
      <div className="mx-auto max-w-6xl space-y-3 px-8 py-7">
        <Skeleton className="h-16 rounded-2xl" />
        <Skeleton className="h-64 rounded-2xl" />
      </div>
    );
  }
  if (campaign.error || !c) {
    return (
      <div className="px-8 py-7">
        <ErrorNote message={campaign.error ?? "Campaign not found"} />
      </div>
    );
  }

  const canStart = c.status !== "running" && c.total_contacts > 0;

  return (
    <PageWrapper className="mx-auto max-w-6xl px-8 py-7">
      <Link
        to="/campaigns"
        className="inline-flex items-center gap-1.5 text-xs text-ink-muted transition hover:text-brand-bright"
      >
        <IconArrowLeft /> Campaigns
      </Link>

      <header className="mt-4 mb-6 flex items-start justify-between gap-6">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-3">
            <h1 className="text-xl font-bold tracking-tight">
              {c.name}
            </h1>
            <StatusBadge status={c.status} />
          </div>
          <p className="mt-1.5 max-w-2xl text-sm text-ink-secondary">{c.goal}</p>
        </div>
        <div className="shrink-0">
          {c.status === "running" ? (
            <Button variant="secondary" onClick={() => changeStatus("pause")} disabled={busy}>
              <IconPause /> Pause
            </Button>
          ) : (
            <Button onClick={() => changeStatus("start")} disabled={busy || !canStart}>
              <IconPlay /> Start calling
            </Button>
          )}
        </div>
      </header>

      {c.total_contacts === 0 && (
        <div className="mb-3 rounded-lg border border-warning/20 bg-warning/5 px-4 py-3 text-xs text-warning">
          Add contacts before starting. Numbers already on the do-not-call list are
          dropped automatically at import.
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <div className="space-y-4 lg:col-span-3">
          <ConversationEditor campaign={c} onSaved={campaign.reload} />

          <Card hover={false}>
            <CardHeader
              title="Contacts"
              subtitle={`${c.total_contacts} total · ${c.pending} pending · ${c.completed} completed`}
            />
            <div className="max-h-96 overflow-y-auto">
              {contacts.loading ? (
                <div className="space-y-2 p-4">
                  {[0, 1, 2].map((i) => (
                    <Skeleton key={i} className="h-8" />
                  ))}
                </div>
              ) : !contacts.data?.length ? (
                <EmptyState title="No contacts yet" hint="Import a CSV to get started." />
              ) : (
                <table className="w-full text-sm">
                  <thead className="sticky top-0 bg-surface/90 text-xs text-ink-muted backdrop-blur-sm">
                    <tr className="border-b border-white/5">
                      <th className="px-5 py-2.5 text-left font-medium">Name</th>
                      <th className="px-3 py-2.5 text-left font-medium">Phone</th>
                      <th className="px-3 py-2.5 text-left font-medium">Status</th>
                      <th className="px-5 py-2.5 text-right font-medium">Next try</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {contacts.data.map((contact) => (
                      <tr key={contact.id} className="transition-colors hover:bg-white/3">
                        <td className="px-5 py-2.5 font-medium">{contact.full_name}</td>
                        <td className="tnum px-3 py-2.5 text-ink-muted">
                          {contact.phone_masked}
                        </td>
                        <td className="px-3 py-2.5 text-xs capitalize text-ink-secondary">
                          {contact.status.replace(/_/g, " ")}
                          {contact.attempts > 0 && (
                            <span className="tnum text-ink-muted"> · {contact.attempts}×</span>
                          )}
                        </td>
                        <td className="px-5 py-2.5 text-right text-xs text-ink-muted">
                          {contact.next_attempt_at
                            ? formatDateTime(contact.next_attempt_at)
                            : "—"}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              )}
            </div>
          </Card>
        </div>

        <div className="space-y-4 lg:col-span-2">
          <ImportPanel
            campaignId={id}
            onImported={() => {
              contacts.reload();
              campaign.reload();
            }}
          />

          <Card>
            <CardHeader title="Calling rules" />
            <dl className="space-y-3 px-5 py-4 text-sm">
              <Row
                label="Window"
                value={`${c.calling_hours_start}:00 – ${c.calling_hours_end}:00 local`}
              />
              <Row
                label="Days"
                value={
                  c.calling_days.length === 7
                    ? "Every day"
                    : c.calling_days.map((d) => DAY_NAMES[d]).join(", ")
                }
              />
              <Row label="Concurrency" value={`${c.max_concurrent_calls} lines`} />
              <Row label="Max attempts" value={String(c.max_attempts)} />
            </dl>
          </Card>
        </div>
      </div>
    </PageWrapper>
  );
}

function Row({ label, value }: { label: string; value: string }) {
  return (
    <div className="flex justify-between gap-4">
      <dt className="text-ink-muted">{label}</dt>
      <dd className="text-right font-medium">{value}</dd>
    </div>
  );
}

function ConversationEditor({
  campaign,
  onSaved,
}: {
  campaign: Campaign;
  onSaved: () => void;
}) {
  const [goal, setGoal] = useState(campaign.goal);
  const [greeting, setGreeting] = useState(campaign.greeting);
  const [fieldsText, setFieldsText] = useState(campaign.fields_to_collect.join("\n"));
  const [constraintsText, setConstraintsText] = useState(
    campaign.constraints.join("\n"),
  );
  const [extra, setExtra] = useState(campaign.extra_instructions);
  const [saving, setSaving] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const [saved, setSaved] = useState(false);

  useEffect(() => {
    setGoal(campaign.goal);
    setGreeting(campaign.greeting);
    setFieldsText(campaign.fields_to_collect.join("\n"));
    setConstraintsText(campaign.constraints.join("\n"));
    setExtra(campaign.extra_instructions);
  }, [campaign]);

  const toLines = (t: string) => t.split("\n").map((l) => l.trim()).filter(Boolean);

  const dirty =
    goal !== campaign.goal ||
    greeting !== campaign.greeting ||
    extra !== campaign.extra_instructions ||
    fieldsText !== campaign.fields_to_collect.join("\n") ||
    constraintsText !== campaign.constraints.join("\n");

  const save = async () => {
    setSaving(true);
    setError(null);
    try {
      await api.updateCampaign(campaign.id, {
        goal,
        greeting,
        extra_instructions: extra,
        fields_to_collect: toLines(fieldsText),
        constraints: toLines(constraintsText),
      });
      setSaved(true);
      setTimeout(() => setSaved(false), 2500);
      onSaved();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setSaving(false);
    }
  };

  const preview = greeting
    .replaceAll("{first_name}", "Dana")
    .replaceAll("{full_name}", "Dana Whitfield")
    .replaceAll("{campaign_name}", campaign.name);

  return (
    <Card hover={false}>
      <CardHeader
        title="Conversation"
        subtitle="What the agent is briefed to do. Changes apply to calls placed after saving."
        action={
          saved ? (
            <span className="text-xs font-semibold text-good">Saved</span>
          ) : dirty ? (
            <Button size="sm" onClick={save} disabled={saving}>
              {saving ? "Saving…" : "Save changes"}
            </Button>
          ) : null
        }
      />
      <div className="space-y-4 px-5 py-4">
        <Field label="Goal">
          <textarea
            className={`${inputClass} min-h-20 resize-y`}
            value={goal}
            onChange={(e) => setGoal(e.target.value)}
          />
        </Field>

        <Field
          label="Opening line"
          hint="Placeholders: {first_name}, {full_name}, {campaign_name}"
        >
          <textarea
            className={`${inputClass} min-h-16 resize-y font-mono text-xs`}
            value={greeting}
            onChange={(e) => setGreeting(e.target.value)}
          />
        </Field>

        <div className="rounded-lg border border-white/5 bg-elevated/50 px-4 py-3">
          <p className="text-[11px] font-medium text-ink-muted">
            Agent will say
          </p>
          <p className="mt-1.5 text-sm leading-relaxed italic text-ink-secondary">"{preview}"</p>
        </div>

        <div className="grid grid-cols-1 gap-4 sm:grid-cols-2">
          <Field label="Information to collect" hint="One per line.">
            <textarea
              className={`${inputClass} min-h-24 resize-y font-mono text-xs`}
              value={fieldsText}
              onChange={(e) => setFieldsText(e.target.value)}
            />
          </Field>
          <Field label="Boundaries" hint="One per line.">
            <textarea
              className={`${inputClass} min-h-24 resize-y font-mono text-xs`}
              value={constraintsText}
              onChange={(e) => setConstraintsText(e.target.value)}
            />
          </Field>
        </div>

        <Field label="Additional guidance" hint="Tone, vocabulary, objection handling.">
          <textarea
            className={`${inputClass} min-h-20 resize-y`}
            value={extra}
            onChange={(e) => setExtra(e.target.value)}
            placeholder="Optional."
          />
        </Field>

        {error && <ErrorNote message={error} />}
      </div>
    </Card>
  );
}

function ImportPanel({
  campaignId,
  onImported,
}: {
  campaignId: string;
  onImported: () => void;
}) {
  const [result, setResult] = useState<BulkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);

  const handleFile = async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const { contacts, rejected } = parseContactsCsv(await file.text());
      if (!contacts.length) {
        throw new Error(
          rejected[0]?.reason ?? "No usable rows. Needs 'name' and 'phone' columns.",
        );
      }
      setResult(await api.addContacts(campaignId, contacts));
      onImported();
    } catch (err) {
      setError((err as Error).message);
    } finally {
      setBusy(false);
    }
  };

  return (
    <Card>
      <CardHeader
        title="Import contacts"
        subtitle="CSV with name and phone. Extra columns become context the agent can reference."
      />
      <div className="space-y-3 px-5 py-4">
        <label className="flex cursor-pointer flex-col items-center gap-2 rounded-xl border border-dashed border-white/10 px-4 py-7 text-center transition-all hover:border-brand/40 hover:bg-brand/5">
          <input
            type="file"
            accept=".csv,text/csv"
            className="hidden"
            disabled={busy}
            onChange={(e) => {
              const file = e.target.files?.[0];
              if (file) void handleFile(file);
              e.target.value = "";
            }}
          />
          <span className="text-ink-muted">
            <IconUpload />
          </span>
          <span className="text-xs text-ink-secondary">
            {busy ? "Importing…" : "Choose a CSV file"}
          </span>
        </label>

        {error && <ErrorNote message={error} />}

        {result && (
          <div className="rounded-lg border border-good/20 bg-good/5 px-3 py-2.5 text-xs">
            <p className="font-semibold text-good">{result.created} contacts added</p>
            {result.skipped_suppressed > 0 && (
              <p className="mt-0.5 text-ink-secondary">
                {result.skipped_suppressed} skipped — on the do-not-call list
              </p>
            )}
            {result.skipped_duplicate > 0 && (
              <p className="mt-0.5 text-ink-secondary">
                {result.skipped_duplicate} skipped — already in this campaign
              </p>
            )}
          </div>
        )}
      </div>
    </Card>
  );
}
