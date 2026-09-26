/**
 * The call log (and, with `reviewOnly`, the review queue).
 *
 * List on the left, the selected call on the right (a drawer on phones).
 * Selection lives in ?call= so any call is linkable — the Overview, the
 * Live console and the command palette all deep-link here.
 */

import { useMemo, useState, type KeyboardEvent } from "react";
import { useSearchParams } from "react-router-dom";
import {
  api,
  type CallDetail,
  type CallFilters,
  type CallSummary,
  type FollowupChannel,
  type QualificationBand,
  type Sentiment,
} from "../api";
import { LatencyBars } from "../components/charts";
import {
  IconCalendar,
  IconCheck,
  IconDownload,
  IconFrown,
  IconMeh,
  IconPhone,
  IconReview,
  IconRows,
  IconRowsCompact,
  IconSearch,
  IconSmile,
} from "../components/icons";
import { ToolCallsCard } from "../components/mcp/ToolCallsCard";
import { ScorecardResult } from "../components/Scorecard";
import { TranscriptActions, TranscriptList, toolTurnFromLog, withTools, type DisplayTurn } from "../components/Transcript";
import {
  Badge,
  Button,
  ButtonLink,
  Card,
  CardHeader,
  DispositionBadge,
  Drawer,
  EmptyState,
  ErrorNote,
  Eyebrow,
  Figure,
  FollowupBadge,
  Input,
  Page,
  PageHeader,
  ScoreBadge,
  Segmented,
  Select,
  SentimentBadge,
  Skeleton,
  SkeletonText,
  Switch,
  TestBadge,
  Textarea,
  buttonClass,
  cx,
  toast,
} from "../components/ui";
import { formatDateTime, formatDuration, formatUsd } from "../format";
import { useAsync, useDocumentTitle, useLocalStorage, useMediaQuery } from "../hooks";

const DISPOSITIONS: Array<[string, string]> = [
  ["completed", "Completed"],
  ["partial", "Partial"],
  ["callback_requested", "Callback"],
  ["declined", "Declined"],
  ["do_not_call", "Do not call"],
  ["voicemail", "Voicemail"],
  ["no_answer", "No answer"],
  ["wrong_number", "Wrong number"],
  ["failed", "Failed"],
];

type Density = "comfortable" | "compact";

export default function Calls({ reviewOnly = false }: { reviewOnly?: boolean }) {
  useDocumentTitle(reviewOnly ? "Review queue" : "Calls");
  const [params, setParams] = useSearchParams();
  const selected = params.get("call");
  const wide = useMediaQuery("(min-width: 1024px)");

  const [includeTests, setIncludeTests] = useLocalStorage("samvaad.calls.tests", false);
  const [density, setDensity] = useLocalStorage<Density>("samvaad.calls.density", "comfortable");
  const [sort, setSort] = useState<"recent" | "score">("recent");
  const [band, setBand] = useState<QualificationBand | "">("");
  const [campaignId, setCampaignId] = useState("");
  const [disposition, setDisposition] = useState("");
  const [sentiment, setSentiment] = useState<Sentiment | "all">("all");
  const [query, setQuery] = useState("");

  const campaigns = useAsync(() => api.campaigns(), []);
  const filters: CallFilters = {
    include_simulations: includeTests,
    sort,
    ...(band ? { band } : {}),
    ...(campaignId ? { campaign_id: campaignId } : {}),
    ...(disposition ? { disposition } : {}),
    ...(reviewOnly ? { needs_review: true } : {}),
  };
  const calls = useAsync(
    () => api.calls({ ...filters, limit: reviewOnly ? 200 : 150 }),
    [reviewOnly, includeTests, sort, band, campaignId, disposition],
  );

  // Search and sentiment filter client-side: instant, and the API has no
  // parameter for either.
  const visible = useMemo(() => {
    const q = query.trim().toLowerCase();
    return (calls.data ?? []).filter(
      (c) =>
        (sentiment === "all" || c.sentiment === sentiment) &&
        (!q ||
          c.contact_name.toLowerCase().includes(q) ||
          c.phone_masked.includes(q) ||
          (c.summary ?? "").toLowerCase().includes(q)),
    );
  }, [calls.data, query, sentiment]);

  const filtered = !!(query || band || campaignId || disposition || sentiment !== "all");
  const clearFilters = () => {
    setQuery("");
    setBand("");
    setCampaignId("");
    setDisposition("");
    setSentiment("all");
  };

  const select = (id: string | null) => {
    const next = new URLSearchParams(params);
    if (id) next.set("call", id);
    else next.delete("call");
    setParams(next, { replace: true });
  };

  const campaignName = (id: string) => campaigns.data?.find((c) => c.id === id)?.name;

  const detail = selected ? (
    <CallDetailPanel
      key={selected}
      callId={selected}
      campaignName={campaignName}
      onChanged={() => {
        calls.reload();
        if (reviewOnly) select(null);
      }}
    />
  ) : null;

  return (
    <Page width="wide">
      <PageHeader
        icon={reviewOnly ? <IconReview size={18} /> : <IconPhone size={18} />}
        title={reviewOnly ? "Review queue" : "Calls"}
        description={
          reviewOnly
            ? "Calls the model wasn't confident enough to write automatically. Approve to write the outcome through, or dismiss."
            : "Every conversation, saved — transcript, recording, outcome and follow-ups."
        }
        actions={
          <a href={api.callsExportUrl(filters)} className={buttonClass("secondary")} download>
            <IconDownload size={15} /> Export CSV
          </a>
        }
      />

      {/* Filters */}
      <div className="mb-4 flex flex-col gap-3">
        <div className="flex flex-wrap items-center gap-2">
          <label className="relative min-w-0 flex-1 basis-60">
            <span className="sr-only">Search calls</span>
            <IconSearch size={15} className="pointer-events-none absolute left-3 top-1/2 -translate-y-1/2 text-ink-muted" />
            <Input value={query} onChange={(e) => setQuery(e.target.value)} placeholder="Search name, number or summary" className="pl-9" />
          </label>
          <Select value={campaignId} onChange={(e) => setCampaignId(e.target.value)} aria-label="Campaign" className="w-full sm:w-48">
            <option value="">All campaigns</option>
            {(campaigns.data ?? []).map((c) => (
              <option key={c.id} value={c.id}>
                {c.name}
              </option>
            ))}
          </Select>
          <Select value={disposition} onChange={(e) => setDisposition(e.target.value)} aria-label="Outcome" className="w-[calc(50%-4px)] sm:w-40">
            <option value="">All outcomes</option>
            {DISPOSITIONS.map(([value, label]) => (
              <option key={value} value={value}>
                {label}
              </option>
            ))}
          </Select>
          <Select
            value={band}
            onChange={(e) => setBand(e.target.value as QualificationBand | "")}
            aria-label="Score"
            className="w-[calc(50%-4px)] sm:w-40"
          >
            <option value="">All scores</option>
            <option value="strong">Strong</option>
            <option value="possible">Possible</option>
            <option value="weak">Weak</option>
            <option value="disqualified">Disqualified</option>
          </Select>
        </div>
        <div className="flex flex-wrap items-center gap-x-4 gap-y-2">
          <Segmented
            label="Sentiment"
            size="sm"
            value={sentiment}
            onChange={setSentiment}
            options={[
              { value: "all", label: "All" },
              { value: "positive", label: "Positive", icon: <IconSmile size={13} /> },
              { value: "neutral", label: "Neutral", icon: <IconMeh size={13} /> },
              { value: "negative", label: "Negative", icon: <IconFrown size={13} /> },
            ]}
          />
          <Segmented
            label="Sort"
            size="sm"
            value={sort}
            onChange={setSort}
            options={[
              { value: "recent", label: "Recent" },
              { value: "score", label: "Ranked", title: "Best-scoring first" },
            ]}
          />
          <Switch checked={includeTests} onChange={setIncludeTests} label="Include test calls" className="items-center gap-2" />
          <div className="ml-auto flex items-center gap-3">
            <span className="tnum text-xs text-ink-muted" aria-live="polite">
              {calls.loading ? "Loading…" : `${visible.length} ${visible.length === 1 ? "call" : "calls"}`}
            </span>
            {filtered && (
              <button type="button" onClick={clearFilters} className="text-xs font-medium text-brand hover:underline">
                Clear filters
              </button>
            )}
            <Segmented
              label="Row density"
              size="sm"
              value={density}
              onChange={setDensity}
              options={[
                { value: "comfortable", label: <span className="sr-only">Comfortable</span>, icon: <IconRows size={14} />, title: "Comfortable rows" },
                { value: "compact", label: <span className="sr-only">Compact</span>, icon: <IconRowsCompact size={14} />, title: "Compact rows" },
              ]}
            />
          </div>
        </div>
      </div>

      {calls.error && (
        <div className="mb-4">
          <ErrorNote message={calls.error} onRetry={calls.reload} />
        </div>
      )}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-[minmax(0,2fr)_minmax(0,3fr)] lg:items-start">
        <Card className="overflow-hidden lg:sticky lg:top-20">
          <div className="max-h-[calc(100dvh-16rem)] min-h-64 overflow-y-auto">
            {calls.loading ? (
              <div className="space-y-2 p-4">
                {[0, 1, 2, 3, 4].map((i) => (
                  <Skeleton key={i} className="h-16" />
                ))}
              </div>
            ) : visible.length === 0 ? (
              <EmptyState
                avatar={reviewOnly ? "ended" : "idle"}
                title={filtered ? "No calls match" : reviewOnly ? "Nothing to review" : "No calls yet"}
                hint={
                  filtered
                    ? "Try a broader search, or clear the filters."
                    : reviewOnly
                      ? "Outcomes the model was confident about are written automatically. You're all caught up."
                      : "Calls show up here as soon as a campaign starts dialling — or place a test call to see one now."
                }
                action={
                  filtered ? (
                    <Button variant="secondary" size="sm" onClick={clearFilters}>
                      Clear filters
                    </Button>
                  ) : !reviewOnly ? (
                    <ButtonLink to="/app/test-lab/phone" size="sm">
                      Place a test call
                    </ButtonLink>
                  ) : undefined
                }
              />
            ) : (
              <CallList calls={visible} selected={selected} density={density} onSelect={select} campaignName={campaignName} />
            )}
          </div>
        </Card>

        {wide ? (
          <div className="min-w-0">
            {detail ?? (
              <Card>
                <EmptyState
                  avatar="listening"
                  title="Select a call"
                  hint="You'll see the full transcript with reply times, the recording, what the agent extracted, and whether it was written to your systems."
                />
              </Card>
            )}
          </div>
        ) : (
          <Drawer open={!!selected} onClose={() => select(null)} title="Call" width="max-w-2xl">
            <div className="p-4">{detail}</div>
          </Drawer>
        )}
      </div>
    </Page>
  );
}

// ---------------------------------------------------------------------------

function CallList({
  calls,
  selected,
  density,
  onSelect,
  campaignName,
}: {
  calls: CallSummary[];
  selected: string | null;
  density: Density;
  onSelect: (id: string) => void;
  campaignName: (id: string) => string | undefined;
}) {
  // Arrow keys walk the list, like a mail client.
  const onKeyDown = (event: KeyboardEvent<HTMLUListElement>) => {
    if (event.key !== "ArrowDown" && event.key !== "ArrowUp") return;
    const buttons = [...event.currentTarget.querySelectorAll<HTMLButtonElement>("button[data-call]")];
    const index = buttons.indexOf(document.activeElement as HTMLButtonElement);
    const next = buttons[Math.max(0, Math.min(buttons.length - 1, index + (event.key === "ArrowDown" ? 1 : -1)))];
    if (next) {
      event.preventDefault();
      next.focus();
      onSelect(next.dataset.call!);
    }
  };

  const compact = density === "compact";
  return (
    <ul className="divide-y divide-line" onKeyDown={onKeyDown} aria-label="Calls">
      {calls.map((call) => {
        const active = call.id === selected;
        return (
          <li key={call.id}>
            <button
              type="button"
              data-call={call.id}
              aria-current={active ? "true" : undefined}
              onClick={() => onSelect(call.id)}
              className={cx(
                "relative w-full px-4 text-left transition-colors duration-150",
                compact ? "py-2" : "py-3.5",
                active ? "bg-brand/8" : "hover:bg-subtle/70",
              )}
            >
              {active && <span className="absolute inset-y-0 left-0 w-0.5 bg-brand" aria-hidden />}
              <div className="flex items-center justify-between gap-3">
                <span className="flex min-w-0 items-center gap-1.5">
                  <span className="truncate text-sm font-semibold text-ink">{call.contact_name}</span>
                  {call.is_simulation && <TestBadge />}
                </span>
                <span className="flex shrink-0 items-center gap-1.5">
                  {!compact && <SentimentBadge value={call.sentiment} />}
                  {call.qualification_band && call.qualification_band !== "not_assessed" ? (
                    <ScoreBadge score={call.score} band={call.qualification_band} />
                  ) : (
                    <DispositionBadge value={call.disposition} />
                  )}
                </span>
              </div>
              <div className="tnum mt-1 flex flex-wrap items-center gap-x-1.5 text-xs text-ink-muted">
                <span>{formatDateTime(call.started_at)}</span>
                {call.duration_seconds !== null && <span>· {formatDuration(call.duration_seconds)}</span>}
                {!compact && <span className="hidden sm:inline">· {call.phone_masked}</span>}
                {!compact && campaignName(call.campaign_id) && (
                  <span className="truncate font-sans">· {campaignName(call.campaign_id)}</span>
                )}
                {call.needs_human_review && <Badge tone="warning">Review</Badge>}
              </div>
              {!compact && call.summary && (
                <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-ink-secondary">{call.summary}</p>
              )}
            </button>
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------------------

const AMD_LABEL: Record<string, string> = {
  human: "A person answered",
  machine_end_beep: "Voicemail (beep detected)",
  machine_start: "Voicemail (machine start)",
  fax: "Fax machine",
};

function CallDetailPanel({
  callId,
  campaignName,
  onChanged,
}: {
  callId: string;
  campaignName: (id: string) => string | undefined;
  onChanged: () => void;
}) {
  const { data, loading, error, reload } = useAsync(() => api.call(callId), [callId]);

  if (loading) {
    return (
      <div className="space-y-3" aria-busy="true">
        <Skeleton className="h-28 rounded-xl" />
        <Card className="p-5">
          <SkeletonText lines={4} />
        </Card>
        <Skeleton className="h-64 rounded-xl" />
      </div>
    );
  }
  if (error || !data) return <ErrorNote message={error ?? "Call not found"} onRetry={reload} />;

  const toolCalls = data.tool_calls ?? [];
  const speech: DisplayTurn[] = data.transcript.map((t, i) => ({
    key: `d-${i}`,
    role: t.role,
    text: t.text,
    latencyMs: t.latency_ms ?? null,
    at: t.started_at,
  }));
  const turns = withTools(speech, toolCalls.map(toolTurnFromLog));
  const latencies = speech.filter((t) => t.latencyMs != null).map((t) => t.latencyMs as number);
  const refresh = () => {
    reload();
    onChanged();
  };

  return (
    <div className="space-y-3">
      <Card>
        <div className="flex flex-wrap items-start justify-between gap-3 px-5 py-4">
          <div className="min-w-0">
            <div className="flex flex-wrap items-center gap-2">
              <h2 className="truncate text-lg font-semibold tracking-tight text-ink">{data.contact_name}</h2>
              {data.is_simulation && <TestBadge />}
            </div>
            <p className="tnum mt-1 text-xs text-ink-muted">
              {data.phone_masked} · {formatDateTime(data.started_at)}
              {campaignName(data.campaign_id) && <span className="font-sans"> · {campaignName(data.campaign_id)}</span>}
            </p>
          </div>
          <div className="flex flex-wrap items-center gap-1.5">
            <SentimentBadge value={data.sentiment ?? data.outcome?.sentiment} title={data.outcome?.sentiment_reason} />
            {data.qualification_band && data.qualification_band !== "not_assessed" && (
              <ScoreBadge score={data.score} band={data.qualification_band} />
            )}
            <DispositionBadge value={data.disposition} />
          </div>
        </div>
        <div className="grid grid-cols-2 gap-4 border-t border-line px-5 py-3 sm:grid-cols-4">
          <Figure label="Talk time" value={formatDuration(data.duration_seconds)} />
          <Figure label="Turns" value={data.transcript.length} />
          <Figure label="Model cost" value={formatUsd(data.cost_usd, 4)} />
          <Figure
            label="Median reply"
            value={latencies.length ? `${(latencies.slice().sort((a, b) => a - b)[Math.floor(latencies.length / 2)] / 1000).toFixed(1)} s` : "—"}
          />
        </div>
      </Card>

      {data.needs_human_review && <ReviewCard call={data} onReviewed={refresh} />}

      <Card>
        <CardHeader title="Summary" subtitle="What the extractor read off the transcript" />
        <div className="space-y-4 px-5 py-4">
          {data.summary ? (
            <p className="text-sm leading-relaxed text-ink">{data.summary}</p>
          ) : (
            <p className="text-sm text-ink-muted">No summary — the call didn't produce an outcome.</p>
          )}

          {data.outcome?.appointment && (
            <div className="rounded-lg border border-good/25 bg-good/6 px-3 py-2.5">
              <p className="flex items-center gap-1.5 text-xs font-medium text-good">
                <IconCalendar size={13} /> Appointment agreed
              </p>
              <p className="mt-1 text-sm font-medium text-ink">{data.outcome.appointment.subject}</p>
              <p className="tnum mt-0.5 text-xs text-ink-secondary">
                {data.outcome.appointment.starts_at_local} ({data.outcome.appointment.timezone}) ·{" "}
                {data.outcome.appointment.duration_minutes} min
              </p>
            </div>
          )}

          {data.outcome && data.outcome.collected.length > 0 && (
            <div>
              <Eyebrow className="mb-2">Collected</Eyebrow>
              <dl className="divide-y divide-line rounded-lg border border-line">
                {data.outcome.collected.map((field) => (
                  <div key={field.name} className="flex items-start justify-between gap-4 px-3 py-2 text-sm">
                    <dt className="text-ink-secondary">{field.name}</dt>
                    <dd className="text-right font-medium text-ink">
                      {field.value}
                      {!field.verbatim && (
                        <Badge tone="warning" className="ml-2">
                          inferred
                        </Badge>
                      )}
                    </dd>
                  </div>
                ))}
              </dl>
            </div>
          )}

          {data.dispatch_result && (
            <div>
              <Eyebrow className="mb-2">Actions taken</Eyebrow>
              <ul className="space-y-1 text-xs text-ink-secondary">
                {data.dispatch_result.suppressed && <li className="font-medium text-critical">Added to the do-not-call list</li>}
                <li>
                  {data.dispatch_result.calendar_event_id
                    ? `Calendar event created (${data.dispatch_result.calendar_event_id})`
                    : "No calendar event"}
                </li>
                <li>
                  {data.dispatch_result.fields_written} {data.dispatch_result.fields_written === 1 ? "field" : "fields"} written to
                  records
                </li>
                {data.dispatch_result.errors.map((err, i) => (
                  <li key={i} className="text-critical">
                    {err}
                  </li>
                ))}
              </ul>
            </div>
          )}

          {data.amd_result && (
            <div className="flex items-center gap-2 text-xs">
              <span className="text-ink-muted">Answering machine detection:</span>
              <Badge tone={data.amd_result === "human" ? "good" : "warning"}>{AMD_LABEL[data.amd_result] ?? data.amd_result}</Badge>
            </div>
          )}
        </div>
      </Card>

      <ToolCallsCard calls={toolCalls} startedAt={data.started_at} skipped={data.dispatch_result?.mcp_actions_skipped} />

      {data.recording_url && (
        <Card>
          <CardHeader
            title="Recording"
            subtitle={data.recording_duration != null ? `${formatDuration(data.recording_duration)} long` : undefined}
          />
          <div className="px-5 py-4">
            <audio controls preload="none" className="w-full" src={api.recordingUrl(data.id)}>
              Your browser can't play this recording.
            </audio>
          </div>
        </Card>
      )}

      <Card>
        <CardHeader
          title="Transcript"
          subtitle={`${speech.length} turns${toolCalls.length ? ` · ${toolCalls.length} tool ${toolCalls.length === 1 ? "call" : "calls"}` : ""}`}
          action={<TranscriptActions callId={data.id} turns={turns} personName={data.contact_name} />}
        />
        {latencies.length > 1 && (
          <div className="border-b border-line px-5 py-4">
            <LatencyBars values={latencies} />
          </div>
        )}
        <div className="max-h-[32rem] overflow-y-auto px-4 py-5 sm:px-5">
          <TranscriptList turns={turns} personName={data.contact_name} empty="No conversation was recorded — the call didn't connect." />
        </div>
      </Card>

      <Followups call={data} onChanged={reload} />

      <ScorecardResult scores={data.scores} qualification={data.qualification} />

      {(data.cost_usd > 0 || data.conversation_model) && (
        <Card>
          <CardHeader title="What this call cost" subtitle="Model spend only — telephony is billed by your carrier." />
          <div className="grid grid-cols-2 gap-4 px-5 py-4 sm:grid-cols-4">
            <Figure label="Total" value={formatUsd(data.cost_usd, 4)} />
            <Figure label="Input tokens" value={data.input_tokens.toLocaleString()} />
            <Figure label="Output tokens" value={data.output_tokens.toLocaleString()} />
            <Figure label="Cached" value={data.cache_read_tokens.toLocaleString()} />
          </div>
          <p className="border-t border-line px-5 py-2.5 text-2xs text-ink-muted">
            {data.conversation_model ?? "—"} on the call · {data.extraction_model ?? "—"} after
          </p>
        </Card>
      )}
    </div>
  );
}

function ReviewCard({ call, onReviewed }: { call: CallDetail; onReviewed: () => void }) {
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState<"approve" | "dismiss" | null>(null);

  const submit = async (approve: boolean) => {
    setBusy(approve ? "approve" : "dismiss");
    try {
      await api.reviewCall(call.id, approve, note);
      setNote("");
      toast.success(approve ? "Approved — outcome written" : "Dismissed", `${call.contact_name}'s call left the review queue.`);
      onReviewed();
    } catch (err) {
      toast.error("Review not saved", (err as Error).message);
    } finally {
      setBusy(null);
    }
  };

  return (
    <Card className="border-warning/40">
      <div className="px-5 py-4">
        <p className="flex items-center gap-1.5 text-sm font-semibold text-warning">
          <IconReview size={15} /> Held for review
        </p>
        <p className="mt-1 text-xs leading-relaxed text-ink-secondary">{call.review_reason}</p>
        <Textarea
          className="mt-3 min-h-16"
          rows={2}
          placeholder="Optional note for the record…"
          value={note}
          onChange={(e) => setNote(e.target.value)}
          aria-label="Review note"
        />
        <div className="mt-3 flex flex-wrap gap-2">
          <Button onClick={() => submit(true)} loading={busy === "approve"} disabled={!!busy} icon={<IconCheck size={14} />}>
            Approve & write
          </Button>
          <Button variant="secondary" onClick={() => submit(false)} loading={busy === "dismiss"} disabled={!!busy}>
            Dismiss
          </Button>
        </div>
      </div>
    </Card>
  );
}

const FOLLOWUP_CHANNELS: Array<{ channel: FollowupChannel; label: string }> = [
  { channel: "sms", label: "SMS" },
  { channel: "whatsapp", label: "WhatsApp" },
];

// Outcomes nothing is sent for — mirrors compose_message() in followup.py.
const NO_FOLLOWUP = new Set(["do_not_call", "wrong_number", "failed"]);

function Followups({ call, onChanged }: { call: CallDetail; onChanged: () => void }) {
  const [sending, setSending] = useState<FollowupChannel | null>(null);

  const eligible = !!call.outcome && !NO_FOLLOWUP.has(call.disposition ?? "");
  if (!eligible && !call.sms_status && !call.whatsapp_status) return null;

  const send = async (channel: FollowupChannel, label: string) => {
    setSending(channel);
    try {
      const result = await api.resendFollowup(call.id, { sms: channel === "sms", whatsapp: channel === "whatsapp" });
      const outcome = result[channel];
      if (outcome?.error || outcome?.status === "failed") {
        toast.error(`${label} not sent`, outcome.error ?? "The carrier rejected it.");
      } else {
        toast.success(`${label} sent`, outcome ? `Status: ${outcome.status}` : undefined);
      }
      onChanged();
    } catch (err) {
      toast.error(`${label} not sent`, (err as Error).message);
    } finally {
      setSending(null);
    }
  };

  return (
    <Card>
      <CardHeader title="Follow-up messages" subtitle="Sent after the call. Statuses update as the carrier reports delivery." />
      <ul className="divide-y divide-line">
        {FOLLOWUP_CHANNELS.map(({ channel, label }) => {
          const status = channel === "sms" ? call.sms_status : call.whatsapp_status;
          const failure = call.followup_errors?.[channel];
          return (
            <li key={channel} className="flex flex-wrap items-center justify-between gap-2 px-5 py-3">
              <div className="flex min-w-0 flex-wrap items-center gap-2">
                {status ? <FollowupBadge channel={channel} status={status} /> : <span className="text-sm text-ink-secondary">{label}</span>}
                {!status && <span className="text-xs text-ink-muted">Not sent</span>}
                {failure && <p className="w-full text-xs text-critical">{failure}</p>}
              </div>
              {eligible && (
                <Button size="sm" variant="secondary" onClick={() => send(channel, label)} loading={sending === channel} disabled={sending !== null}>
                  {status ? "Resend" : "Send"}
                </Button>
              )}
            </li>
          );
        })}
      </ul>
    </Card>
  );
}
