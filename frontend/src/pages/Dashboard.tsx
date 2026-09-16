import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { api, type Disposition } from "../api";
import { ColumnChart, DonutChart, VolumeChart } from "../components/charts";
import {
  IconClock,
  IconCoin,
  IconPhone,
  IconReview,
  IconTrendUp,
} from "../components/icons";
import {
  Card,
  DeltaBadge,
  DispositionBadge,
  EmptyState,
  HeroStat,
  LiveDot,
  PageWrapper,
  Skeleton,
  formatDuration,
  formatTime,
} from "../components/ui";
import { useAsync, useLiveFeed, usePolling } from "../hooks";

export default function Dashboard() {
  const stats = usePolling(() => api.stats(), 10_000);
  const recent = useAsync(() => api.calls({ limit: 8 }));
  const { connected } = useLiveFeed();

  const pct = (n: number) => `${Math.round(n * 100)}%`;

  return (
    <PageWrapper className="px-6 py-5">
      {/* Header */}
      <header className="mb-5 flex flex-wrap items-end justify-between gap-4">
        <div>
          <h1 className="text-xl font-bold tracking-tight">Overview</h1>
          <p className="mt-0.5 text-sm text-ink-muted">
            Rolling 24 hours, compared with the previous 24.
          </p>
        </div>
        <div className="flex items-center gap-2 rounded-lg border border-white/10 px-3 py-1.5 text-xs">
          {connected ? (
            <>
              <LiveDot />
              <span className="text-ink-secondary">Live</span>
            </>
          ) : (
            <>
              <span className="h-1.5 w-1.5 rounded-full bg-ink-muted/40" />
              <span className="text-ink-muted">Reconnecting</span>
            </>
          )}
        </div>
      </header>

      {/* Row 1 — Hero stat + charts */}
      <div className="grid grid-cols-1 gap-3 lg:grid-cols-12">
        <div className="lg:col-span-3">
          {stats ? (
            <HeroStat
              label="Calls today"
              value={stats.calls_today.toLocaleString()}
              delta={stats.calls_delta}
              caption="since yesterday"
              icon={<IconTrendUp size={40} />}
            />
          ) : (
            <Skeleton className="h-full min-h-[200px]" />
          )}
        </div>

        <div className="lg:col-span-5">
          <Card>
            <PanelHead title="Call volume" hint="3-hour blocks" />
            <div className="px-4 pb-4">
              <ColumnChart data={stats?.volume_by_hour ?? []} />
            </div>
          </Card>
        </div>

        <div className="lg:col-span-4">
          <Card>
            <PanelHead title="Volume trend" hint="Hourly, last 24h" />
            <div className="px-2 pb-4">
              <VolumeChart data={stats?.volume_by_hour ?? []} />
            </div>
          </Card>
        </div>
      </div>

      {/* Row 2 — KPI strip */}
      <div className="mt-3 grid grid-cols-2 gap-2 lg:grid-cols-3 xl:grid-cols-6">
        <MiniStat
          label="Connect rate"
          value={stats ? pct(stats.connect_rate) : "\u2014"}
          hint="Reached a person"
        />
        <MiniStat
          label="Goal met"
          value={stats ? pct(stats.completion_rate) : "\u2014"}
          hint="Of calls connected"
        />
        <MiniStat
          label="Avg duration"
          value={stats ? formatDuration(stats.avg_duration_seconds) : "\u2014"}
          hint="Talk time"
          icon={<IconClock size={14} />}
        />
        <MiniStat
          label="On the line"
          value={stats?.calls_in_progress ?? "\u2014"}
          hint="Right now"
          icon={<IconPhone size={14} />}
          accent={(stats?.calls_in_progress ?? 0) > 0}
        />
        <MiniStat
          label="Model spend"
          value={stats ? `$${stats.spend_usd.toFixed(2)}` : "\u2014"}
          hint="Last 24h"
          icon={<IconCoin size={14} />}
          delta={stats?.spend_delta ?? null}
          deltaGoodDirection="down"
        />
        <MiniStat
          label="Cost per call"
          value={stats ? `$${stats.cost_per_connected_call_usd.toFixed(4)}` : "\u2014"}
          hint={
            stats
              ? `${Math.round(stats.cache_hit_rate * 100)}% prompt cache hit`
              : "Per connected call"
          }
          icon={<IconCoin size={14} />}
        />
      </div>

      {/* Row 3 — Recent calls + outcome donut */}
      <div className="mt-3 grid grid-cols-1 gap-3 lg:grid-cols-12">
        <div className="lg:col-span-8">
          <Card>
            <PanelHead
              title="Recent calls"
              hint={`${recent.data?.length ?? 0} most recent`}
              action={
                <Link
                  to="/calls"
                  className="text-xs font-medium text-brand transition-colors hover:text-brand-bright"
                >
                  View all
                </Link>
              }
            />
            {recent.loading ? (
              <div className="space-y-1.5 p-4">
                {[0, 1, 2, 3].map((i) => (
                  <Skeleton key={i} className="h-10" />
                ))}
              </div>
            ) : !recent.data?.length ? (
              <EmptyState
                title="No calls yet"
                hint="Start a campaign and calls appear here as they're placed."
              />
            ) : (
              <div className="overflow-x-auto">
                <table className="w-full text-sm">
                  <thead>
                    <tr className="border-b border-white/5 text-xs text-ink-muted">
                      <th className="px-5 py-2.5 text-left font-medium">Contact</th>
                      <th className="px-3 py-2.5 text-left font-medium">Phone</th>
                      <th className="px-3 py-2.5 text-left font-medium">Duration</th>
                      <th className="px-3 py-2.5 text-left font-medium">Time</th>
                      <th className="px-5 py-2.5 text-right font-medium">Outcome</th>
                    </tr>
                  </thead>
                  <tbody className="divide-y divide-white/5">
                    {recent.data.map((call) => (
                      <tr
                        key={call.id}
                        className="transition-colors hover:bg-elevated/50"
                      >
                        <td className="px-5 py-2.5 font-medium">{call.contact_name}</td>
                        <td className="tnum px-3 py-2.5 text-ink-secondary">
                          {call.phone_masked}
                        </td>
                        <td className="tnum px-3 py-2.5 text-ink-secondary">
                          {formatDuration(call.duration_seconds)}
                        </td>
                        <td className="tnum px-3 py-2.5 text-ink-muted">
                          {formatTime(call.started_at)}
                        </td>
                        <td className="px-5 py-2.5 text-right">
                          <DispositionBadge value={call.disposition as Disposition} />
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
            )}
          </Card>
        </div>

        <div className="lg:col-span-4">
          <Card>
            <PanelHead
              title="Outcomes"
              hint="Last 24 hours"
              action={
                (stats?.pending_review ?? 0) > 0 ? (
                  <Link
                    to="/review"
                    className="flex items-center gap-1 text-xs font-medium text-warning transition-colors hover:opacity-80"
                  >
                    <IconReview size={13} />
                    {stats!.pending_review} to review
                  </Link>
                ) : null
              }
            />
            <div className="px-5 py-5">
              <DonutChart
                breakdown={stats?.disposition_breakdown ?? {}}
                centerLabel="calls"
              />
            </div>
          </Card>
        </div>
      </div>
    </PageWrapper>
  );
}

// ---------------------------------------------------------------------------
// Sub-components
// ---------------------------------------------------------------------------

function PanelHead({
  title,
  hint,
  action,
}: {
  title: string;
  hint?: string;
  action?: ReactNode;
}) {
  return (
    <div className="flex items-center justify-between gap-3 px-5 py-3">
      <div>
        <h2 className="text-sm font-semibold tracking-tight">{title}</h2>
        {hint && <p className="mt-0.5 text-xs text-ink-muted">{hint}</p>}
      </div>
      {action}
    </div>
  );
}

function MiniStat({
  label,
  value,
  hint,
  icon,
  accent = false,
  delta,
  deltaGoodDirection = "up",
}: {
  label: string;
  value: string | number;
  hint?: string;
  icon?: ReactNode;
  accent?: boolean;
  delta?: number | null;
  deltaGoodDirection?: "up" | "down";
}) {
  return (
    <Card className={`px-3.5 py-3 ${accent ? "!border-brand/25" : ""}`}>
      <div className="flex items-center justify-between">
        <p className="text-[11px] font-medium text-ink-muted">{label}</p>
        {icon && <span className="text-ink-muted/50">{icon}</span>}
      </div>
      <div className="mt-1.5 flex items-baseline gap-2">
        <p className={`tnum text-xl font-bold tracking-tight ${accent ? "text-brand-bright" : ""}`}>
          {value}
        </p>
        {delta !== undefined && (
          <DeltaBadge value={delta} goodDirection={deltaGoodDirection} />
        )}
      </div>
      {hint && <p className="mt-0.5 text-[11px] text-ink-muted">{hint}</p>}
    </Card>
  );
}
