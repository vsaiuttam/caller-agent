import { useState } from "react";
import {
  api,
  type CallDetail,
  type CallSummary,
  type QualificationBand,
} from "../api";
import { IconCalendar, IconCheck, IconDownload, IconFlask } from "../components/icons";
import { ScorecardResult } from "../components/Scorecard";
import {
  Button,
  Card,
  CardHeader,
  DispositionBadge,
  EmptyState,
  ErrorNote,
  PageWrapper,
  ScoreBadge,
  Skeleton,
  formatDateTime,
  formatDuration,
} from "../components/ui";
import { useAsync } from "../hooks";

export default function Calls({ reviewOnly = false }: { reviewOnly?: boolean }) {
  const [selected, setSelected] = useState<string | null>(null);
  const [showSimulations, setShowSimulations] = useState(false);
  const [sort, setSort] = useState<"recent" | "score">("recent");
  const [band, setBand] = useState<QualificationBand | "">("");

  const filters = {
    include_simulations: showSimulations,
    sort,
    ...(band ? { band } : {}),
    ...(reviewOnly ? { needs_review: true } : {}),
  } as const;

  const calls = useAsync(
    () => api.calls({ ...filters, limit: reviewOnly ? 200 : 100 }),
    [reviewOnly, showSimulations, sort, band],
  );

  const exportParams = filters;

  return (
    <PageWrapper className="mx-auto max-w-7xl px-3 py-4 sm:px-6 sm:py-5">
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">
            {reviewOnly ? "Review queue" : "Calls"}
          </h1>
          <p className="mt-0.5 max-w-3xl text-sm text-ink-muted">
            {reviewOnly
              ? "Calls the model wasn't confident enough to write automatically."
              : "Every call placed, most recent first."}
          </p>
        </div>

        <div className="flex flex-wrap items-center gap-2 sm:gap-3">
          <div className="flex items-center gap-1 rounded-lg border border-white/10 p-0.5">
            {(["recent", "score"] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                onClick={() => setSort(mode)}
                aria-pressed={sort === mode}
                className={`rounded-md px-3 py-1.5 text-xs font-medium transition-colors duration-150 ${
                  sort === mode
                    ? "bg-brand text-plane"
                    : "text-ink-secondary hover:bg-elevated hover:text-ink"
                }`}
              >
                {mode === "recent" ? "Recent" : "Ranked"}
              </button>
            ))}
          </div>

          <select
            value={band}
            onChange={(e) => setBand(e.target.value as QualificationBand | "")}
            className="rounded-xl border border-white/10 bg-white/5 px-3 py-1.5 text-xs outline-none transition focus:border-brand/50"
          >
            <option value="">All results</option>
            <option value="strong">Strong only</option>
            <option value="possible">Possible</option>
            <option value="weak">Weak</option>
            <option value="disqualified">Disqualified</option>
          </select>

          <label className="hidden cursor-pointer items-center gap-2 text-xs text-ink-secondary sm:flex">
            <input
              type="checkbox"
              checked={showSimulations}
              onChange={(e) => setShowSimulations(e.target.checked)}
              className="accent-[var(--color-brand)]"
            />
            Include test calls
          </label>
          <a
            href={api.callsExportUrl(exportParams)}
            className="ripple hidden items-center gap-2 rounded-lg border border-white/10 bg-elevated px-4 py-2 text-sm font-medium transition-colors hover:border-brand/30 sm:inline-flex"
          >
            <IconDownload size={15} />
            Export CSV
          </a>
        </div>
      </header>

      {calls.error && <ErrorNote message={calls.error} />}

      <div className="grid grid-cols-1 gap-4 lg:grid-cols-5">
        <Card className="overflow-hidden lg:col-span-2" hover={false}>
          <div className="max-h-[calc(100vh-13rem)] overflow-y-auto">
            {calls.loading ? (
              <div className="space-y-2 p-4">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-16 rounded-xl" />
                ))}
              </div>
            ) : !calls.data?.length ? (
              <EmptyState
                title={reviewOnly ? "Nothing to review" : "No calls yet"}
                hint={
                  reviewOnly
                    ? "Outcomes the model was confident about are written automatically."
                    : "Calls show up as soon as a campaign starts dialling."
                }
              />
            ) : (
              <ul className="divide-y divide-white/5">
                {calls.data.map((call) => (
                  <CallRow
                    key={call.id}
                    call={call}
                    active={selected === call.id}
                    onSelect={() => setSelected(call.id)}
                  />
                ))}
              </ul>
            )}
          </div>
        </Card>

        <div className="lg:col-span-3">
          {selected ? (
            <Detail
              callId={selected}
              onReviewed={() => {
                calls.reload();
                if (reviewOnly) setSelected(null);
              }}
            />
          ) : (
            <Card hover={false}>
              <EmptyState
                title="Select a call"
                hint="You'll see the full transcript, what the agent extracted, and whether it was written to your systems."
              />
            </Card>
          )}
        </div>
      </div>
    </PageWrapper>
  );
}

function CallRow({
  call,
  active,
  onSelect,
}: {
  call: CallSummary;
  active: boolean;
  onSelect: () => void;
}) {
  return (
    <li>
      <button
        onClick={onSelect}
        className={`w-full border-l-2 px-5 py-3.5 text-left transition-all duration-200 ${
          active
            ? "border-brand bg-brand/8"
            : "border-transparent hover:bg-white/3"
        }`}
      >
        <div className="flex items-center justify-between gap-3">
          <span className="flex min-w-0 items-center gap-1.5">
            {call.is_simulation && (
              <span
                className="flex shrink-0 items-center gap-1 rounded-lg border border-white/10 bg-white/5 px-1.5 py-0.5 text-[11px] font-medium text-ink-muted"
                title="Simulated call — excluded from all metrics"
              >
                <IconFlask size={10} /> Test
              </span>
            )}
            <span className="truncate text-sm font-semibold">{call.contact_name}</span>
          </span>
          {call.qualification_band ? (
            <ScoreBadge score={call.score} band={call.qualification_band} size="sm" />
          ) : (
            <DispositionBadge value={call.disposition} />
          )}
        </div>
        <div className="mt-1 flex flex-wrap items-center gap-1.5 text-xs text-ink-muted">
          <span className="tnum">{call.phone_masked}</span>
          <span>·</span>
          <span>{formatDateTime(call.started_at)}</span>
          {call.duration_seconds !== null && (
            <>
              <span>·</span>
              <span className="tnum">{formatDuration(call.duration_seconds)}</span>
            </>
          )}
          {call.cost_usd > 0 && (
            <>
              <span>·</span>
              <span className="tnum">${call.cost_usd.toFixed(4)}</span>
            </>
          )}
        </div>
        {call.summary && (
          <p className="mt-1.5 line-clamp-2 text-xs leading-relaxed text-ink-secondary">
            {call.summary}
          </p>
        )}
      </button>
    </li>
  );
}

function Detail({ callId, onReviewed }: { callId: string; onReviewed: () => void }) {
  const { data, loading, error, reload } = useAsync(() => api.call(callId), [callId]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);

  const submitReview = async (approve: boolean) => {
    setBusy(true);
    try {
      await api.reviewCall(callId, approve, note);
      setNote("");
      reload();
      onReviewed();
    } finally {
      setBusy(false);
    }
  };

  if (loading) {
    return (
      <div className="space-y-3">
        <Skeleton className="h-40 rounded-lg" />
        <Skeleton className="h-64 rounded-lg" />
      </div>
    );
  }
  if (error || !data) return <ErrorNote message={error ?? "Call not found"} />;

  return (
    <div className="space-y-3">
      {data.needs_human_review && (
        <Card className="!border-warning/30 !bg-warning/5" hover={false}>
          <div className="px-5 py-4">
            <p className="text-sm font-bold text-warning">Held for review</p>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
              {data.review_reason}
            </p>
            <textarea
              className="mt-3 w-full rounded-xl border border-white/10 bg-white/5 px-3.5 py-2.5 text-sm outline-none transition focus:border-brand/50 focus:ring-2 focus:ring-brand/20"
              rows={2}
              placeholder="Optional note for the record…"
              value={note}
              onChange={(e) => setNote(e.target.value)}
            />
            <div className="mt-3 flex gap-2">
              <Button onClick={() => submitReview(true)} disabled={busy}>
                <IconCheck /> Approve & write
              </Button>
              <Button variant="secondary" onClick={() => submitReview(false)} disabled={busy}>
                Dismiss
              </Button>
            </div>
          </div>
        </Card>
      )}

      <Outcome data={data} />

      <ScorecardResult scores={data.scores} qualification={data.qualification} />

      <Card hover={false}>
        <CardHeader title="Transcript" subtitle={`${data.transcript.length} turns`} />
        <div className="max-h-96 space-y-3 overflow-y-auto px-5 py-4">
          {data.transcript.length === 0 ? (
            <p className="py-6 text-center text-xs text-ink-muted">
              No conversation was recorded — the call didn't connect.
            </p>
          ) : (
            data.transcript.map((turn, i) => (
              <div
                key={i}
                className={turn.role === "assistant" ? "pr-4 sm:pr-10" : "pl-4 text-right sm:pl-10"}
              >
                <span className="text-[11px] font-medium text-ink-muted">
                  {turn.role === "assistant" ? "Agent" : data.contact_name}
                </span>
                <p
                  className={`mt-1 inline-block rounded-lg px-4 py-2.5 text-sm leading-relaxed ${
                    turn.role === "assistant"
                      ? "bg-brand/10 text-ink"
                      : "card-static"
                  }`}
                >
                  {turn.text}
                </p>
              </div>
            ))
          )}
        </div>
      </Card>
    </div>
  );
}

function Outcome({ data }: { data: CallDetail }) {
  const outcome = data.outcome;
  const dispatch = data.dispatch_result;

  return (
    <Card hover={false}>
      <CardHeader
        title="Outcome"
        subtitle={formatDateTime(data.started_at)}
        action={<DispositionBadge value={data.disposition} />}
      />
      <div className="space-y-4 px-5 py-4">
        {data.summary && <p className="text-sm leading-relaxed">{data.summary}</p>}

        {outcome?.appointment && (
          <div className="rounded-xl border border-white/10 bg-white/3 px-4 py-3">
            <p className="flex items-center gap-1.5 text-[11px] font-medium text-ink-muted">
              <IconCalendar size={13} /> Appointment agreed
            </p>
            <p className="mt-1.5 text-sm font-semibold">{outcome.appointment.subject}</p>
            <p className="tnum mt-0.5 text-sm text-ink-secondary">
              {outcome.appointment.starts_at_local} ({outcome.appointment.timezone}) ·{" "}
              {outcome.appointment.duration_minutes} min
            </p>
            {outcome.appointment.notes && (
              <p className="mt-1.5 text-xs text-ink-muted">{outcome.appointment.notes}</p>
            )}
          </div>
        )}

        {outcome && outcome.collected.length > 0 && (
          <div>
            <p className="mb-2 text-[11px] font-medium text-ink-muted">
              Collected
            </p>
            <dl className="space-y-2 text-sm">
              {outcome.collected.map((field) => (
                <div key={field.name} className="flex justify-between gap-4">
                  <dt className="text-ink-secondary">{field.name}</dt>
                  <dd className="text-right font-medium">
                    {field.value}
                    {!field.verbatim && (
                      <span className="ml-2 rounded-lg border border-warning/20 bg-warning/10 px-1.5 py-0.5 text-xs text-warning">
                        inferred
                      </span>
                    )}
                  </dd>
                </div>
              ))}
            </dl>
          </div>
        )}

        {dispatch && (
          <div className="border-t border-white/5 pt-3">
            <p className="mb-2 text-[11px] font-medium text-ink-muted">
              Actions taken
            </p>
            <ul className="space-y-1 text-xs text-ink-secondary">
              {dispatch.suppressed && (
                <li className="font-semibold text-critical">Added to do-not-call list</li>
              )}
              <li>
                {dispatch.calendar_event_id
                  ? `Calendar event created (${dispatch.calendar_event_id})`
                  : "No calendar event"}
              </li>
              <li>{dispatch.fields_written} fields written to records</li>
              {dispatch.errors.map((err, i) => (
                <li key={i} className="text-critical">
                  {err}
                </li>
              ))}
            </ul>
          </div>
        )}

        {/* Recording playback */}
        {data.recording_url && (
          <div className="border-t border-white/5 pt-3">
            <p className="mb-2 text-[11px] font-medium text-ink-muted">
              Call recording
            </p>
            <audio
              controls
              preload="none"
              className="w-full rounded-lg"
              src={`/api/calls/${data.id}/recording`}
            >
              Your browser does not support audio playback.
            </audio>
            {data.recording_duration != null && (
              <p className="mt-1 text-[11px] text-ink-muted">
                Duration: {formatDuration(data.recording_duration)}
              </p>
            )}
          </div>
        )}

        {/* AMD result */}
        {data.amd_result && (
          <div className="border-t border-white/5 pt-3">
            <p className="mb-1 text-[11px] font-medium text-ink-muted">
              Answering machine detection
            </p>
            <span
              className={`inline-block rounded-lg px-2 py-1 text-xs font-medium ${
                data.amd_result === "human"
                  ? "bg-success/10 text-success"
                  : "bg-warning/10 text-warning"
              }`}
            >
              {data.amd_result === "human"
                ? "Human answered"
                : data.amd_result === "machine_end_beep"
                  ? "Voicemail (beep detected)"
                  : data.amd_result === "machine_start"
                    ? "Voicemail (machine start)"
                    : data.amd_result === "fax"
                      ? "Fax machine"
                      : data.amd_result}
            </span>
          </div>
        )}

        {/* SMS follow-up status */}
        {data.sms_sid && (
          <div className="border-t border-white/5 pt-3">
            <p className="mb-1 text-[11px] font-medium text-ink-muted">
              SMS follow-up
            </p>
            <span className="inline-block rounded-lg bg-brand/10 px-2 py-1 text-xs font-medium text-brand">
              {data.sms_status === "sent" ? "Sent" : data.sms_status ?? "Sent"}
            </span>
            <span className="ml-2 text-[11px] text-ink-muted">SID: {data.sms_sid}</span>
          </div>
        )}

        {(data.cost_usd > 0 || data.conversation_model) && (
          <div className="border-t border-white/5 pt-3">
            <p className="mb-2 text-[11px] font-medium text-ink-muted">
              What this call cost
            </p>
            <div className="grid grid-cols-2 gap-x-4 gap-y-1.5 text-xs sm:grid-cols-4">
              <Ledger label="Total" value={`$${data.cost_usd.toFixed(4)}`} />
              <Ledger label="Input" value={data.input_tokens.toLocaleString()} />
              <Ledger label="Output" value={data.output_tokens.toLocaleString()} />
              <Ledger label="Cached" value={data.cache_read_tokens.toLocaleString()} />
            </div>
            <p className="mt-2 text-[11px] text-ink-muted">
              {data.conversation_model ?? "—"} on the call ·{" "}
              {data.extraction_model ?? "—"} after.
            </p>
          </div>
        )}
      </div>
    </Card>
  );
}

function Ledger({ label, value }: { label: string; value: string }) {
  return (
    <div>
      <p className="text-[11px] font-medium text-ink-muted">{label}</p>
      <p className="tnum font-semibold">{value}</p>
    </div>
  );
}
