/**
 * One campaign, in four tabs (?tab=):
 *
 *   overview   dialler status (why it is or isn't calling), progress, KPIs
 *   calls      this campaign's calls
 *   contacts   the list, and importing more
 *   settings   what it's set to, each part opening the builder at its step
 */

import { useState, type DragEvent, type ReactNode } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { INCLUDE_TESTS_KEY, api, type BulkResult, type Campaign, type Contact } from "../api";
import { DialerCard, DialerPill, useDialer } from "../components/campaign/Dialer";
import { daysLabel, hour, type StepId } from "../components/builder/draft";
import { voiceLabel } from "../components/builder/SummaryRail";
import { IconCampaign, IconFlask, IconPause, IconPencil, IconPlay, IconUpload } from "../components/icons";
import { useCrumb } from "../components/shell/AppShell";
import {
  Button,
  ButtonLink,
  Callout,
  Card,
  CardHeader,
  ConfirmDialog,
  DispositionBadge,
  EmptyState,
  ErrorNote,
  Page,
  PageHeader,
  ScoreBadge,
  Skeleton,
  Stat,
  Switch,
  Tabs,
  TestBadge,
  cx,
  toast,
} from "../components/ui";
import { formatDateTime, formatDuration, formatUsd } from "../format";
import { useAsync, useDocumentTitle, useLocalStorage } from "../hooks";

type Tab = "overview" | "calls" | "contacts" | "settings";
const TABS: Tab[] = ["overview", "calls", "contacts", "settings"];

export default function CampaignDetail() {
  const { id = "" } = useParams();
  const [params, setParams] = useSearchParams();
  const tab: Tab = TABS.includes(params.get("tab") as Tab) ? (params.get("tab") as Tab) : "overview";
  const campaign = useAsync(() => api.campaign(id), [id]);
  const c = campaign.data;
  const dialer = useDialer(c, true);
  const [busy, setBusy] = useState(false);
  useCrumb(c?.name);
  useDocumentTitle(c?.name ?? "Campaign");

  const setTab = (value: Tab) => {
    const next = new URLSearchParams(params);
    if (value === "overview") next.delete("tab");
    else next.set("tab", value);
    setParams(next, { replace: true });
  };

  const changeStatus = async (action: "start" | "pause" | "complete") => {
    setBusy(true);
    try {
      const updated = await api.setCampaignStatus(id, action);
      campaign.setData(updated);
      dialer.reload();
      toast.success(
        action === "start" ? "Campaign started" : action === "pause" ? "Campaign paused" : "Campaign completed",
        action === "start"
          ? "Calls go out within each contact's calling window."
          : action === "pause"
            ? "No new calls will be placed. Calls already on the line finish."
            : "It won't dial again. Its calls and results stay.",
      );
    } catch (err) {
      toast.error(`Couldn't ${action === "complete" ? "complete" : action} the campaign`, (err as Error).message);
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
        <Skeleton className="mt-6 h-10 w-80 max-w-full" />
        <Skeleton className="mt-4 h-28 rounded-xl" />
        <div className="mt-3 grid gap-3 sm:grid-cols-2 lg:grid-cols-4">
          {[0, 1, 2, 3].map((i) => (
            <Skeleton key={i} className="h-24 rounded-xl" />
          ))}
        </div>
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

  const noContacts = c.total_contacts === 0;

  return (
    <Page width="wide">
      <PageHeader
        back={{ to: "/app/campaigns", label: "Campaigns" }}
        icon={<IconCampaign size={18} />}
        title={c.name}
        meta={<DialerPill campaign={c} status={dialer.status} />}
        description={c.goal}
        actions={
          <>
            <ButtonLink to={`/app/test-lab?campaign=${c.id}`} variant="secondary" icon={<IconFlask size={14} />}>
              Test it
            </ButtonLink>
            <ButtonLink to={`/app/campaigns/${c.id}/edit`} variant="secondary" icon={<IconPencil size={14} />}>
              Edit
            </ButtonLink>
            {c.status === "running" ? (
              <Button variant="secondary" onClick={() => changeStatus("pause")} loading={busy} icon={<IconPause size={13} />}>
                Pause
              </Button>
            ) : c.status === "draft" ? (
              <ButtonLink to={`/app/campaigns/${c.id}/edit?step=review`} icon={<IconPlay size={13} />}>
                Review and launch
              </ButtonLink>
            ) : c.status === "paused" ? (
              <Button onClick={() => changeStatus("start")} loading={busy} disabled={noContacts} icon={<IconPlay size={13} />}>
                Resume
              </Button>
            ) : null}
          </>
        }
      />

      <Tabs
        label="Campaign"
        value={tab}
        onChange={setTab}
        className="mb-5"
        tabs={[
          { value: "overview", label: "Overview" },
          { value: "calls", label: "Calls" },
          { value: "contacts", label: "Contacts", count: c.total_contacts },
          { value: "settings", label: "Settings" },
        ]}
      />

      <div role="tabpanel" aria-label={tab}>
        {tab === "overview" && (
          <div className="space-y-4">
            <DialerCard campaign={c} dialer={dialer} />
            {noContacts && (
              <Callout
                tone="warning"
                title="No contacts yet"
                action={
                  <Button size="sm" variant="secondary" onClick={() => setTab("contacts")}>
                    Add contacts
                  </Button>
                }
              >
                Import a spreadsheet of people to call. Numbers on the do-not-call list are dropped automatically.
              </Callout>
            )}
            <div className="grid grid-cols-2 gap-3 lg:grid-cols-4">
              <Stat label="Contacts" value={c.total_contacts.toLocaleString()} hint={`${c.pending.toLocaleString()} still to call`} />
              <Stat
                label="Completed"
                value={c.completed.toLocaleString()}
                hint={c.total_contacts ? `${Math.round((c.completed / c.total_contacts) * 100)}% of the list` : "Nothing yet"}
              />
              <Stat label="To review" value={c.needs_review} hint={c.needs_review ? <Link to={`/app/calls?view=review`} className="text-brand hover:underline">Open the queue</Link> : "Nothing held"} accent={c.needs_review > 0} />
              <Stat label="Model spend" value={formatUsd(c.spend_usd)} hint={c.budget_usd != null ? `Pauses itself at ${formatUsd(c.budget_usd, 0)}` : "No spend cap"} />
            </div>
            <RecentCalls campaignId={c.id} limit={5} onAll={() => setTab("calls")} />
          </div>
        )}
        {tab === "calls" && <RecentCalls campaignId={c.id} limit={200} />}
        {tab === "contacts" && (
          <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,1fr)_340px] lg:items-start">
            <ContactsTable campaignId={c.id} total={c.total_contacts} />
            <ImportPanel campaignId={c.id} language={c.language} onImported={campaign.reload} />
          </div>
        )}
        {tab === "settings" && <SettingsTab campaign={c} busy={busy} onComplete={() => changeStatus("complete")} />}
      </div>
    </Page>
  );
}

// ---------------------------------------------------------------------------

function RecentCalls({ campaignId, limit, onAll }: { campaignId: string; limit: number; onAll?: () => void }) {
  const [includeTests, setIncludeTests] = useLocalStorage(INCLUDE_TESTS_KEY, true);
  const calls = useAsync(() => api.calls({ campaign_id: campaignId, include_simulations: includeTests, limit }), [campaignId, includeTests, limit]);
  const compact = !!onAll;

  return (
    <Card className="overflow-hidden">
      <CardHeader
        title={compact ? "Latest calls" : "Calls"}
        subtitle={compact ? undefined : "Open any call for its transcript, recording and outcome."}
        action={
          compact ? (
            <Button size="sm" variant="ghost" onClick={onAll}>
              See all
            </Button>
          ) : (
            <Switch checked={includeTests} onChange={setIncludeTests} label="Include test calls" className="items-center gap-2" />
          )
        }
      />
      {calls.loading ? (
        <div className="space-y-2 p-4">
          {Array.from({ length: compact ? 3 : 6 }, (_, i) => (
            <Skeleton key={i} className="h-10" />
          ))}
        </div>
      ) : calls.error ? (
        <div className="p-4">
          <ErrorNote message={calls.error} onRetry={calls.reload} />
        </div>
      ) : !calls.data?.length ? (
        <EmptyState compact title="No calls yet" hint="Calls appear here as soon as the dialler places them. Rehearse in the test lab meanwhile." />
      ) : (
        <div className="overflow-x-auto">
          <table className="data-table min-w-[560px]">
            <thead>
              <tr>
                <th>Contact</th>
                <th>Outcome</th>
                <th className="text-right">Talk time</th>
                <th className="text-right">When</th>
              </tr>
            </thead>
            <tbody>
              {calls.data.map((call) => (
                <tr key={call.id}>
                  <td>
                    <Link to={`/app/calls?call=${call.id}`} className="flex items-center gap-1.5 font-medium text-ink hover:text-brand">
                      <span className="truncate">{call.contact_name}</span>
                      {call.is_simulation && <TestBadge />}
                    </Link>
                    {call.summary && <p className="mt-0.5 line-clamp-1 max-w-md text-xs text-ink-muted">{call.summary}</p>}
                  </td>
                  <td className="whitespace-nowrap">
                    {call.qualification_band && call.qualification_band !== "not_assessed" ? (
                      <ScoreBadge score={call.score} band={call.qualification_band} />
                    ) : (
                      <DispositionBadge value={call.disposition} />
                    )}
                  </td>
                  <td className="tnum whitespace-nowrap text-right text-ink-secondary">{formatDuration(call.duration_seconds)}</td>
                  <td className="tnum whitespace-nowrap text-right text-xs text-ink-muted">{formatDateTime(call.started_at)}</td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </Card>
  );
}

function ContactsTable({ campaignId, total }: { campaignId: string; total: number }) {
  const contacts = useAsync<Contact[]>(() => api.contacts(campaignId, { limit: 500 }), [campaignId, total]);
  return (
    <Card className="overflow-hidden">
      <CardHeader title="Contacts" subtitle={`${total.toLocaleString()} on the list${total > 500 ? ", showing the first 500" : ""}`} />
      <div className="max-h-[32rem] overflow-auto">
        {contacts.loading ? (
          <div className="space-y-2 p-4">
            {[0, 1, 2, 3].map((i) => (
              <Skeleton key={i} className="h-8" />
            ))}
          </div>
        ) : contacts.error ? (
          <div className="p-4">
            <ErrorNote message={contacts.error} onRetry={contacts.reload} />
          </div>
        ) : !contacts.data?.length ? (
          <EmptyState compact title="No contacts yet" hint="Import a spreadsheet with name and phone columns." />
        ) : (
          <table className="data-table min-w-[520px]">
            <thead className="sticky top-0 z-10 bg-surface">
              <tr>
                <th>Name</th>
                <th>Phone</th>
                <th>Status</th>
                <th className="text-right">Next try</th>
              </tr>
            </thead>
            <tbody>
              {contacts.data.map((contact) => (
                <tr key={contact.id}>
                  <td className="font-medium text-ink">{contact.full_name}</td>
                  <td className="tnum text-ink-muted">{contact.phone_masked}</td>
                  <td className="text-xs capitalize text-ink-secondary">
                    {contact.status.replace(/_/g, " ").toLowerCase()}
                    {contact.attempts > 0 && <span className="tnum text-ink-muted"> · {contact.attempts}×</span>}
                  </td>
                  <td className="whitespace-nowrap text-right text-xs text-ink-muted">{contact.next_attempt_at ? formatDateTime(contact.next_attempt_at) : "—"}</td>
                </tr>
              ))}
            </tbody>
          </table>
        )}
      </div>
    </Card>
  );
}

function ImportPanel({ campaignId, language, onImported }: { campaignId: string; language: string; onImported: () => void }) {
  const [result, setResult] = useState<BulkResult | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [busy, setBusy] = useState(false);
  const [dragging, setDragging] = useState(false);

  const handleFile = async (file: File) => {
    setBusy(true);
    setError(null);
    setResult(null);
    try {
      const { contacts, rejected } = await api.parseContactsFile(file, language);
      if (!contacts.length) throw new Error(rejected[0]?.reason ?? "No usable rows. The file needs name and phone columns.");
      const imported = await api.addContacts(campaignId, contacts);
      setResult(imported);
      toast.success(`${imported.created} contacts added`, file.name);
      onImported();
    } catch (err) {
      setError((err as Error).message);
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
      <CardHeader title="Import contacts" subtitle="Excel or CSV with name and phone. Extra columns become context the agent can use." />
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
            accept=".csv,.xlsx,.xls,.xlsm,text/csv"
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
          <span className="text-sm font-medium text-ink">{busy ? "Importing…" : "Drop a file here, or choose one"}</span>
          <span className="text-2xs text-ink-muted">.xlsx · .xls · .csv</span>
        </label>
        {error && <Callout tone="critical">{error}</Callout>}
        {result && (
          <Callout tone="good" title={`${result.created} contacts added`}>
            {result.skipped_suppressed > 0 && <span className="block">{result.skipped_suppressed} skipped: on the do-not-call list</span>}
            {result.skipped_duplicate > 0 && <span className="block">{result.skipped_duplicate} skipped: already in this campaign</span>}
          </Callout>
        )}
      </div>
    </Card>
  );
}

// ---------------------------------------------------------------------------

function SettingsTab({ campaign: c, busy, onComplete }: { campaign: Campaign; busy: boolean; onComplete: () => void }) {
  const [confirm, setConfirm] = useState(false);
  const edit = (step: StepId) => `/app/campaigns/${c.id}/edit?step=${step}`;
  const tools = (c.mcp_tools?.length ?? 0) + (c.mcp_post_call_tools?.length ?? 0);

  return (
    <div className="space-y-4">
      <Card className="overflow-hidden">
        <CardHeader title="Configuration" subtitle="Each part opens the builder at its step. Changes apply to calls placed after saving." />
        <dl className="divide-y divide-line text-sm">
          <SettingRow label="Basics" to={edit("basics")}>
            <p className="font-medium text-ink">{c.name}</p>
            <p className="mt-0.5 line-clamp-2 text-xs text-ink-secondary">{c.goal}</p>
          </SettingRow>
          <SettingRow label="Agent" to={edit("agent")}>
            <p className="text-ink">
              {c.language.toUpperCase()} · {voiceLabel(c.voice)} · {c.conversation_model}
            </p>
            <p className="mt-0.5 line-clamp-2 text-xs italic text-ink-secondary">“{c.greeting}”</p>
          </SettingRow>
          <SettingRow label="Tools" to={edit("tools")}>
            <p className="text-ink">{tools ? `${c.mcp_tools?.length ?? 0} during the call, ${c.mcp_post_call_tools?.length ?? 0} after` : "No tools"}</p>
          </SettingRow>
          <SettingRow label="Schedule" to={edit("schedule")}>
            <p className="text-ink">
              {daysLabel(c.calling_days)}, {hour(c.calling_hours_start)} to {hour(c.calling_hours_end)} · {c.max_attempts} attempts · {c.max_concurrent_calls} lines
            </p>
          </SettingRow>
          <SettingRow label="Messages" to={edit("schedule")}>
            <p className="text-ink">
              {c.precall_enabled ? `Heads-up by ${c.precall_channel === "whatsapp" ? "WhatsApp" : "SMS"}, ${c.precall_lead_minutes ?? 10} min before` : "No heads-up"}
              {" · "}
              Follow-ups: {[c.sms_followup && "SMS", c.whatsapp_followup && "WhatsApp"].filter(Boolean).join(" and ") || "none"}
            </p>
            {c.webhook_url && <p className="mt-0.5 truncate font-mono text-2xs text-ink-muted">{c.webhook_url}</p>}
          </SettingRow>
          <SettingRow label="Models" to={edit("agent")}>
            <p className="text-ink">
              {c.conversation_model} on the call · {c.extraction_model} after
            </p>
          </SettingRow>
        </dl>
      </Card>

      {c.status !== "completed" && (
        <Card className="border-critical/30">
          <div className="flex flex-wrap items-center justify-between gap-3 px-5 py-4">
            <div className="min-w-0">
              <p className="text-sm font-semibold text-ink">Complete this campaign</p>
              <p className="mt-0.5 text-xs text-ink-muted">It stops dialling for good. Calls, results and contacts stay.</p>
            </div>
            <Button variant="danger" onClick={() => setConfirm(true)} disabled={busy}>
              Complete campaign
            </Button>
          </div>
        </Card>
      )}

      <ConfirmDialog
        open={confirm}
        onClose={() => setConfirm(false)}
        onConfirm={() => {
          setConfirm(false);
          onComplete();
        }}
        busy={busy}
        title={`Complete “${c.name}”?`}
        description={`${c.pending.toLocaleString()} contacts still waiting won't be called. This can't be undone.`}
        confirmLabel="Complete campaign"
      />
    </div>
  );
}

function SettingRow({ label, to, children }: { label: string; to: string; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[5.5rem_minmax(0,1fr)_auto] items-start gap-3 px-5 py-3.5 sm:grid-cols-[8rem_minmax(0,1fr)_auto]">
      <dt className="text-xs font-medium text-ink-muted">{label}</dt>
      <dd className="min-w-0">{children}</dd>
      <Link to={to} className="rounded text-xs font-medium text-brand hover:underline">
        Edit
      </Link>
    </div>
  );
}
