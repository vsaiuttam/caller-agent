/**
 * Overview — today at a glance: getting set up, who's on the line, the KPIs
 * against yesterday, where volume and outcomes are heading, and the most
 * recent conversations.
 */

import { useMemo } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, type CallSummary } from "../api";
import { useAuth } from "../auth";
import { AgentAvatar } from "../components/AgentAvatar";
import { ColumnChart, DonutChart, SentimentBar, VolumeChart } from "../components/charts";
import { LiveCallCard } from "../components/live/LiveCallCard";
import {
  IconArrowRight,
  IconCheck,
  IconClock,
  IconCoin,
  IconPhone,
  IconPlus,
  IconReview,
  IconTrendUp,
  IconUsers,
} from "../components/icons";
import {
  Badge,
  ButtonLink,
  Card,
  CardHeader,
  DispositionBadge,
  EmptyState,
  ErrorNote,
  Page,
  PageHeader,
  Segmented,
  SentimentBadge,
  Skeleton,
  Stat,
  TestBadge,
  cx,
} from "../components/ui";
import { useHealth, useLiveCalls } from "../data";
import { formatDuration, formatPercent, formatRelative, formatUsd } from "../format";
import { useAsync, useDocumentTitle, useEventStream, useLocalStorage, useNow, usePolling } from "../hooks";

export default function Dashboard() {
  useDocumentTitle("Overview");
  const stats = usePolling(() => api.stats(), 15_000);
  const recent = useAsync(() => api.calls({ limit: 8 }), []);
  const s = stats.data;

  // A finished call changes the recent list; refresh it without a spinner.
  useEventStream((event) => {
    if (event.type === "call.extracted" || event.type === "call.failed") recent.reload();
  });

  return (
    <Page width="wide">
      <PageHeader
        title={greeting()}
        description="Rolling 24 hours, compared with the 24 before. Test calls are never counted."
        actions={
          <>
            <ButtonLink to="/app/test-lab/phone" variant="secondary" icon={<IconPhone size={14} />}>
              Test call
            </ButtonLink>
            <ButtonLink to="/app/campaigns/new" icon={<IconPlus size={14} />}>
              New campaign
            </ButtonLink>
          </>
        }
      />

      <Onboarding />

      <LiveStrip />

      {stats.error && !s && (
        <div className="mb-4">
          <ErrorNote message={stats.error} onRetry={stats.reload} title="Couldn't load today's numbers" />
        </div>
      )}

      {/* KPIs */}
      <div className="grid grid-cols-2 gap-3 md:grid-cols-3 xl:grid-cols-6">
        <Stat label="Calls today" value={s?.calls_today.toLocaleString() ?? "—"} delta={s?.calls_delta} loading={!s} icon={<IconPhone size={15} />} />
        <Stat
          label="Connect rate"
          value={s ? formatPercent(s.connect_rate) : "—"}
          delta={s?.connect_rate_delta}
          hint="Reached a person"
          loading={!s}
          icon={<IconUsers size={15} />}
        />
        <Stat label="Goal met" value={s ? formatPercent(s.completion_rate) : "—"} hint="Of calls connected" loading={!s} icon={<IconCheck size={15} />} />
        <Stat
          label="Avg talk time"
          value={s ? formatDuration(s.avg_duration_seconds) : "—"}
          delta={s?.avg_duration_delta}
          loading={!s}
          icon={<IconClock size={15} />}
        />
        <Stat
          label="Model spend"
          value={s ? formatUsd(s.spend_usd) : "—"}
          delta={s?.spend_delta}
          deltaGoodDirection="down"
          loading={!s}
          icon={<IconCoin size={15} />}
        />
        <Stat
          label="Cost per call"
          value={s ? formatUsd(s.cost_per_connected_call_usd, 4) : "—"}
          hint={s ? `${Math.round(s.cache_hit_rate * 100)}% prompt cache hits` : "Per connected call"}
          loading={!s}
          icon={<IconTrendUp size={15} />}
        />
      </div>

      {/* Volume + outcomes */}
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-12">
        <VolumeCard data={s?.volume_by_hour} className="lg:col-span-8" />
        <Card className="lg:col-span-4">
          <CardHeader
            title="Outcomes"
            subtitle="Last 24 hours"
            action={
              (s?.pending_review ?? 0) > 0 && (
                <Link to="/app/review" className="flex items-center gap-1 text-xs font-medium text-warning hover:underline">
                  <IconReview size={13} /> {s!.pending_review} to review
                </Link>
              )
            }
          />
          <div className="px-5 py-5">
            {s ? <DonutChart breakdown={s.disposition_breakdown} /> : <Skeleton className="h-36" />}
          </div>
        </Card>
      </div>

      {/* Recent calls + sentiment */}
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-12">
        <Card className="overflow-hidden lg:col-span-8">
          <CardHeader
            title="Recent calls"
            subtitle="The latest conversations, newest first"
            action={
              <Link to="/app/calls" className="flex items-center gap-1 text-xs font-medium text-brand hover:underline">
                View all <IconArrowRight size={12} />
              </Link>
            }
          />
          <RecentCalls calls={recent.data} loading={recent.loading} error={recent.error} onRetry={recent.reload} />
        </Card>

        <div className="space-y-3 lg:col-span-4">
          <Card>
            <CardHeader title="Sentiment" subtitle="How people felt, across real calls" />
            <div className="px-5 py-4">
              {!s ? (
                <Skeleton className="h-16" />
              ) : s.sentiment_breakdown ? (
                <SentimentBar breakdown={s.sentiment_breakdown} />
              ) : (
                <p className="py-3 text-xs text-ink-muted">Sentiment arrives with the v2 backend.</p>
              )}
            </div>
          </Card>
          <Card className="px-5 py-4">
            <div className="flex items-center justify-between gap-3">
              <div>
                <p className="text-xs font-medium text-ink-muted">Review queue</p>
                <p className="tnum mt-1 text-2xl font-semibold text-ink">{s ? s.pending_review : "—"}</p>
                <p className="mt-1 text-xs text-ink-muted">Outcomes the model wasn't sure enough to write.</p>
              </div>
              <ButtonLink to="/app/review" size="sm" variant="secondary">
                Review
              </ButtonLink>
            </div>
          </Card>
        </div>
      </div>
    </Page>
  );
}

function greeting(): string {
  const hour = new Date().getHours();
  return hour < 12 ? "Good morning" : hour < 17 ? "Good afternoon" : "Good evening";
}

// ---------------------------------------------------------------------------

function VolumeCard({ data, className }: { data: Parameters<typeof VolumeChart>[0]["data"] | undefined; className: string }) {
  const [view, setView] = useLocalStorage<"trend" | "blocks">("samvaad.overview.volume", "trend");
  return (
    <Card className={className}>
      <CardHeader
        title="Call volume"
        subtitle={view === "trend" ? "Hourly, last 24 hours" : "In 3-hour blocks"}
        action={
          <Segmented
            label="Volume view"
            size="sm"
            value={view}
            onChange={setView}
            options={[
              { value: "trend", label: "Trend" },
              { value: "blocks", label: "Blocks" },
            ]}
          />
        }
      />
      <div className="px-3 pb-3 pt-4 sm:px-4">
        {!data ? <Skeleton className="h-44" /> : view === "trend" ? <VolumeChart data={data} /> : <ColumnChart data={data} />}
      </div>
    </Card>
  );
}

function RecentCalls({
  calls,
  loading,
  error,
  onRetry,
}: {
  calls: CallSummary[] | null;
  loading: boolean;
  error: string | null;
  onRetry: () => void;
}) {
  const navigate = useNavigate();
  const now = useNow(60_000);
  if (loading) {
    return (
      <div className="space-y-2 p-5">
        {[0, 1, 2, 3].map((i) => (
          <Skeleton key={i} className="h-9" />
        ))}
      </div>
    );
  }
  if (error) return <div className="p-5"><ErrorNote message={error} onRetry={onRetry} /></div>;
  if (!calls?.length) {
    return (
      <EmptyState
        compact
        title="No calls yet"
        hint="Start a campaign, or place a test call — conversations land here the moment they finish."
        action={<ButtonLink to="/app/test-lab/phone" size="sm">Place a test call</ButtonLink>}
      />
    );
  }
  return (
    <div className="overflow-x-auto">
      <table className="data-table">
        <thead>
          <tr>
            <th>Contact</th>
            <th>Outcome</th>
            <th className="hidden sm:table-cell">Sentiment</th>
            <th className="hidden md:table-cell">Talk time</th>
            <th className="text-right">When</th>
          </tr>
        </thead>
        <tbody>
          {calls.map((call) => (
            <tr key={call.id} className="cursor-pointer" onClick={() => navigate(`/app/calls?call=${call.id}`)}>
              <td>
                <Link to={`/app/calls?call=${call.id}`} className="flex items-center gap-2 font-medium text-ink hover:underline" onClick={(e) => e.stopPropagation()}>
                  <span className="truncate">{call.contact_name}</span>
                  {call.is_simulation && <TestBadge />}
                </Link>
              </td>
              <td>
                <DispositionBadge value={call.disposition} />
              </td>
              <td className="hidden sm:table-cell">
                <SentimentBadge value={call.sentiment} />
              </td>
              <td className="tnum hidden text-ink-secondary md:table-cell">{formatDuration(call.duration_seconds)}</td>
              <td className="whitespace-nowrap text-right text-xs text-ink-muted">{formatRelative(call.started_at, now)}</td>
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  );
}

// ---------------------------------------------------------------------------

function LiveStrip() {
  const { calls } = useLiveCalls();
  const navigate = useNavigate();
  const now = useNow(1000, calls.length > 0);
  if (!calls.length) {
    return (
      <Card className="mb-5 flex items-center gap-3 px-4 py-3">
        <AgentAvatar state="idle" size="sm" />
        <p className="min-w-0 flex-1 text-sm text-ink-secondary">
          <span className="font-medium text-ink">Nobody's on the line.</span>{" "}
          <span className="hidden sm:inline">Calls appear here the moment they're dialled.</span>
        </p>
        <Link to="/app/live" className="shrink-0 text-xs font-medium text-brand hover:underline">
          Live view
        </Link>
      </Card>
    );
  }
  return (
    <section aria-label="Calls on the line" className="mb-5">
      <div className="mb-2 flex items-center justify-between">
        <h2 className="flex items-center gap-2 text-sm font-semibold text-ink">
          On the line now
          <Badge tone="good" dot pulse>
            {calls.length}
          </Badge>
        </h2>
        <Link to="/app/live" className="flex items-center gap-1 text-xs font-medium text-brand hover:underline">
          Open Live <IconArrowRight size={12} />
        </Link>
      </div>
      <div className="grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
        {calls.slice(0, 6).map((call) => (
          <LiveCallCard key={call.call_id} call={call} now={now} onSelect={() => navigate(`/app/live?call=${call.call_id}`)} />
        ))}
      </div>
    </section>
  );
}

// ---------------------------------------------------------------------------

interface Step {
  id: string;
  title: string;
  hint: string;
  done: boolean;
  to: string;
  cta: string;
}

/** Integrations → Services: where the environment-configured pieces are explained. */
const SERVICES = "/app/settings?tab=services";

/** The first-run checklist, driven by /api/health and what exists already. */
function Onboarding() {
  const { health } = useHealth();
  const auth = useAuth();
  const [hidden, setHidden] = useLocalStorage("samvaad.onboarding.hidden", false);
  const campaigns = useAsync(() => api.campaigns(), []);
  const tests = useAsync(() => api.calls({ include_simulations: true, limit: 100 }), []);

  const steps = useMemo<Step[] | null>(() => {
    if (!health || campaigns.loading || tests.loading) return null;
    const mode = health.telephony_mode.toLowerCase();
    return [
      {
        id: "model",
        title: "Connect a model provider",
        hint: health.provider_label ? `Using ${health.provider_label}` : "Gemini, Anthropic or OpenAI key",
        done: !!health.checks.model_provider,
        to: SERVICES,
        cta: "Set up",
      },
      {
        id: "telephony",
        title: "Connect telephony",
        hint: mode === "twilio" || mode === "telnyx" ? `${mode[0].toUpperCase()}${mode.slice(1)} is set` : "Twilio or Telnyx",
        done: !!health.checks.telephony && (mode === "twilio" || mode === "telnyx"),
        to: SERVICES,
        cta: "Set up",
      },
      {
        id: "campaign",
        title: "Create your first campaign",
        hint: "Start from a template in a minute",
        done: (campaigns.data?.length ?? 0) > 0,
        to: "/app/templates",
        cta: "Browse templates",
      },
      // Only on backends that report connected apps.
      ...(health.mcp_servers === undefined
        ? []
        : [
            {
              id: "apps",
              title: "Connect an app (MCP)",
              hint: health.mcp_servers
                ? `${health.mcp_servers} connected`
                : "Let the agent check calendars and update your CRM",
              done: health.mcp_servers > 0,
              to: "/app/settings?connect=1",
              cta: "Connect",
            },
          ]),
      {
        id: "test",
        title: "Place a test call",
        hint: "Ring your own phone and watch it live",
        done: (tests.data ?? []).some((c) => c.is_simulation),
        to: "/app/test-lab/phone",
        cta: "Call me",
      },
      {
        id: "followups",
        title: "Turn on follow-ups",
        hint: "SMS or WhatsApp after every call",
        done: !!health.checks.sms || !!health.checks.whatsapp,
        to: SERVICES,
        cta: "Set up",
      },
      {
        id: "auth",
        title: "Lock the console",
        hint: "Set ADMIN_PASSWORD so only your team can dial",
        done: health.auth_enabled ?? auth.phase === "signed-in",
        to: SERVICES,
        cta: "How",
      },
    ];
  }, [health, campaigns.data, campaigns.loading, tests.data, tests.loading, auth.phase]);

  if (hidden) return null;
  if (!steps) return <Skeleton className="mb-5 h-40 rounded-xl" />;

  const done = steps.filter((s) => s.done).length;
  if (done === steps.length) return null;

  return (
    <Card className="mb-5 overflow-hidden">
      <div className="flex flex-col gap-5 p-5 sm:flex-row sm:items-start">
        <AgentAvatar state="idle" size="md" className="hidden sm:block" />
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-start justify-between gap-3">
            <div>
              <h2 className="text-base font-semibold tracking-tight text-ink">Let's get you calling</h2>
              <p className="mt-0.5 text-sm text-ink-secondary">
                {done} of {steps.length} done — each step unlocks a little more of the console.
              </p>
            </div>
            <button
              type="button"
              onClick={() => setHidden(true)}
              className="rounded-md px-2 py-1 text-xs font-medium text-ink-muted transition-colors hover:bg-subtle hover:text-ink"
            >
              Hide checklist
            </button>
          </div>
          <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-subtle-strong" role="progressbar" aria-valuemin={0} aria-valuemax={steps.length} aria-valuenow={done} aria-label="Setup progress">
            <div className="h-full rounded-full bg-brand transition-[width] duration-700 ease-[var(--ease-out)]" style={{ width: `${(done / steps.length) * 100}%` }} />
          </div>
          <ol className="mt-4 grid gap-2 sm:grid-cols-2 xl:grid-cols-3">
            {steps.map((step) => (
              <li
                key={step.id}
                className={cx(
                  "flex items-start gap-3 rounded-lg border px-3 py-2.5",
                  step.done ? "border-line bg-subtle/50" : "border-line-strong bg-surface",
                )}
              >
                <span
                  className={cx(
                    "mt-0.5 flex h-5 w-5 shrink-0 items-center justify-center rounded-full",
                    step.done ? "bg-good text-white" : "border border-line-strong",
                  )}
                  aria-hidden
                >
                  {step.done && <IconCheck size={11} />}
                </span>
                <span className="min-w-0 flex-1">
                  <span className={cx("block text-sm font-medium", step.done ? "text-ink-muted line-through decoration-ink-muted/40" : "text-ink")}>
                    {step.title}
                    <span className="sr-only">{step.done ? " (done)" : " (to do)"}</span>
                  </span>
                  <span className="mt-0.5 block text-xs text-ink-muted">{step.hint}</span>
                </span>
                {!step.done && (
                  <Link to={step.to} className="shrink-0 text-xs font-medium text-brand hover:underline">
                    {step.cta}
                  </Link>
                )}
              </li>
            ))}
          </ol>
        </div>
      </div>
    </Card>
  );
}
