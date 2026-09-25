/**
 * A finished rehearsal or test call, read top to bottom: the three numbers
 * that matter, the conversation, follow-ups, the scorecard, and what the
 * extractor wrote. Shared by the simulator, the browser mic and the live
 * console so every kind of test reads the same way.
 */

import type { ReactNode } from "react";
import type { FollowupChannel, FollowupResult, SimulationResult } from "../api";
import { formatMs, formatUsd } from "../format";
import { LatencyBars } from "./charts";
import { IconBolt, IconCoin, IconShield } from "./icons";
import OutcomeCard from "./OutcomeCard";
import { ScorecardResult } from "./Scorecard";
import { TranscriptList, type DisplayTurn } from "./Transcript";
import { Card, CardHeader, FollowupBadge, cx } from "./ui";

export function resultTurns(result: SimulationResult): DisplayTurn[] {
  return result.turns.map((t, i) => ({
    key: `r-${i}`,
    role: t.role,
    text: t.text,
    latencyMs: t.role === "assistant" ? t.first_chunk_ms : null,
  }));
}

export function ResultFigures({ result, third }: { result: SimulationResult; third?: ReactNode }) {
  const latency = result.median_first_chunk_ms;
  return (
    <div className="grid gap-3 sm:grid-cols-3">
      <FigureCard
        label="Median reply time"
        value={latency === null ? "—" : formatMs(latency)}
        hint={
          latency === null
            ? "No agent turns to measure"
            : latency < 800
              ? "Feels immediate on a call"
              : "An audible pause — try a faster model or lower effort"
        }
        warn={latency !== null && latency >= 800}
        icon={<IconBolt size={15} />}
      />
      <FigureCard
        label="Cost of this call"
        value={formatUsd(result.usage.cost_usd, 4)}
        hint={`${result.usage.input_tokens.toLocaleString()} in · ${result.usage.output_tokens.toLocaleString()} out`}
        icon={<IconCoin size={15} />}
      />
      {third ?? (
        <FigureCard
          label="Prompt cache hits"
          value={`${Math.round(result.usage.cache_hit_rate * 100)}%`}
          hint="Prompt input served from cache"
          icon={<IconShield size={15} />}
        />
      )}
    </div>
  );
}

export function FigureCard({
  label,
  value,
  hint,
  icon,
  warn = false,
}: {
  label: string;
  value: ReactNode;
  hint: ReactNode;
  icon: ReactNode;
  warn?: boolean;
}) {
  return (
    <Card className={cx("px-4 py-3.5", warn && "border-warning/40")}>
      <div className="flex items-start justify-between">
        <p className="text-xs font-medium text-ink-muted">{label}</p>
        <span className={warn ? "text-warning" : "text-ink-muted/70"}>{icon}</span>
      </div>
      <p className="tnum mt-1.5 text-xl font-semibold leading-none text-ink">{value}</p>
      <p className="mt-1.5 text-xs leading-relaxed text-ink-muted">{hint}</p>
    </Card>
  );
}

export function FollowupList({ followups }: { followups: Partial<Record<FollowupChannel, FollowupResult>> }) {
  const list = Object.values(followups).filter((f): f is FollowupResult => !!f);
  if (!list.length) return null;
  return (
    <Card>
      <CardHeader
        title="Follow-up messages"
        subtitle="Status at send time. The call record updates as Twilio reports delivery."
      />
      <ul className="space-y-2 px-5 py-4">
        {list.map((f) => (
          <li key={f.channel} className="flex flex-wrap items-center gap-2">
            <FollowupBadge channel={f.channel} status={f.status} />
            {f.error && <span className="text-xs text-critical">{f.error}</span>}
          </li>
        ))}
      </ul>
    </Card>
  );
}

export default function CallResult({
  result,
  personName,
  transcriptSubtitle,
  outcomeSubtitle,
  footnotes,
  thirdFigure,
}: {
  result: SimulationResult;
  personName: string;
  transcriptSubtitle?: string;
  outcomeSubtitle?: string;
  footnotes: string[];
  thirdFigure?: ReactNode;
}) {
  const turns = resultTurns(result);
  const latencies = turns.filter((t) => t.latencyMs != null).map((t) => t.latencyMs as number);

  return (
    <div className="space-y-3">
      <ResultFigures result={result} third={thirdFigure} />

      <Card>
        <CardHeader
          title="Transcript"
          subtitle={transcriptSubtitle ?? `Ended because ${result.ended_because}.`}
        />
        <div className="px-4 py-5 sm:px-5">
          <TranscriptList turns={turns} personName={personName} />
        </div>
        {latencies.length > 1 && (
          <div className="border-t border-line px-5 py-4">
            <LatencyBars values={latencies} />
          </div>
        )}
      </Card>

      {result.followups && <FollowupList followups={result.followups} />}

      <ScorecardResult scores={result.outcome.scores} qualification={result.qualification} />

      <OutcomeCard outcome={result.outcome} subtitle={outcomeSubtitle} footnotes={footnotes} />
    </div>
  );
}
