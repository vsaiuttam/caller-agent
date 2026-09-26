/**
 * Hand-rolled SVG charts. No charting dependency — five small forms are not
 * worth 200kB, and the mark specs are easier to honour directly than to
 * fight a library's defaults into.
 *
 * Forms follow the data's job:
 *   - Volume over time     → area, one series, the brand hue (the title names it)
 *   - Volume by time block → columns, for reading individual blocks
 *   - Outcome composition  → donut capped at five segments, every segment
 *                            direct-labelled with its count
 *   - Sentiment            → one stacked bar with a labelled legend
 *   - Per-turn latency     → bars coloured by how the wait feels, with the
 *                            0.8 s "feels immediate" line drawn in
 *
 * Every chart has a hover layer, and every value is also printed somewhere
 * as text, so nothing depends on hovering or on colour alone.
 */

import { useMemo, useState } from "react";
import type { HourBucket, Sentiment } from "../api";
import { formatMs } from "../format";

// ---------------------------------------------------------------------------
// Area chart — 24h call volume
// ---------------------------------------------------------------------------

const AREA_W = 720;
const AREA_H = 200;
const PAD = { top: 16, right: 12, bottom: 26, left: 34 };

export function VolumeChart({ data }: { data: HourBucket[] }) {
  const [hover, setHover] = useState<number | null>(null);

  if (data.length === 0) return <ChartEmpty message="No calls in the last 24 hours." />;

  const plotW = AREA_W - PAD.left - PAD.right;
  const plotH = AREA_H - PAD.top - PAD.bottom;
  // Round the axis ceiling up to something readable rather than the raw
  // peak, so gridlines land on whole numbers.
  const ceiling = niceCeiling(Math.max(...data.map((d) => d.total), 1));

  const x = (i: number) => PAD.left + (i / Math.max(1, data.length - 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - (v / ceiling) * plotH;

  const linePath = data.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.total)}`).join(" ");
  const areaPath = `${linePath} L${x(data.length - 1)},${PAD.top + plotH} L${x(0)},${PAD.top + plotH} Z`;
  const active = hover === null ? null : data[hover];

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${AREA_W} ${AREA_H}`}
        className="w-full"
        role="img"
        aria-label={`Call volume over the last 24 hours, peaking at ${Math.max(...data.map((d) => d.total))} calls in an hour`}
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="volume-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-brand)" stopOpacity="0.22" />
            <stop offset="100%" stopColor="var(--color-brand)" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Recessive grid — hairlines, never competing with the data */}
        {[0, ceiling / 2, ceiling].map((t) => (
          <g key={t}>
            <line x1={PAD.left} x2={AREA_W - PAD.right} y1={y(t)} y2={y(t)} stroke="var(--color-line)" strokeWidth="1" />
            <text x={PAD.left - 8} y={y(t) + 3.5} textAnchor="end" className="tnum" fontSize="10" fill="var(--color-ink-muted)">
              {Math.round(t)}
            </text>
          </g>
        ))}

        <path d={areaPath} fill="url(#volume-fill)" />
        <path d={linePath} fill="none" stroke="var(--color-brand)" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round" />

        {/* Hour labels every 4th bucket, so they never collide; the edge
            labels anchor inward so they aren't clipped. */}
        {data.map((d, i) =>
          i % 4 === 0 ? (
            <text
              key={d.hour}
              x={x(i)}
              y={AREA_H - 8}
              textAnchor={i === 0 ? "start" : i >= data.length - 2 ? "end" : "middle"}
              className="tnum"
              fontSize="10"
              fill="var(--color-ink-muted)"
            >
              {d.label}
            </text>
          ) : null,
        )}

        {hover !== null && (
          <>
            <line className="crosshair-line" x1={x(hover)} x2={x(hover)} y1={PAD.top} y2={PAD.top + plotH} />
            {/* 2px surface ring keeps the marker legible over the fill */}
            <circle cx={x(hover)} cy={y(data[hover].total)} r="5" fill="var(--color-brand)" stroke="var(--color-surface)" strokeWidth="2" />
          </>
        )}

        {/* Hit targets wider than the marks */}
        {data.map((d, i) => (
          <rect
            key={d.hour}
            x={x(i) - plotW / data.length / 2}
            y={PAD.top}
            width={plotW / data.length}
            height={plotH}
            fill="transparent"
            onMouseEnter={() => setHover(i)}
          />
        ))}
      </svg>

      {active && (
        <ChartTip left={`${(x(hover!) / AREA_W) * 100}%`}>
          <p className="tnum text-xs font-medium text-ink">{active.label}</p>
          <p className="tnum mt-0.5 text-xs text-ink-secondary">
            {active.total} {active.total === 1 ? "call" : "calls"} · {active.connected} connected
          </p>
        </ChartTip>
      )}
    </div>
  );
}

function niceCeiling(peak: number): number {
  if (peak <= 4) return 4;
  const magnitude = 10 ** Math.floor(Math.log10(peak));
  return Math.ceil(peak / magnitude) * magnitude;
}

// ---------------------------------------------------------------------------
// Column chart — volume grouped into wider buckets
// ---------------------------------------------------------------------------

const BAR_W = 460;
const BAR_H = 190;
const BAR_PAD = { top: 14, right: 8, bottom: 24, left: 30 };

export function ColumnChart({ data, groupHours = 3 }: { data: HourBucket[]; groupHours?: number }) {
  const [hover, setHover] = useState<number | null>(null);

  // 24 hourly columns are too thin to read. Grouping into 3-hour blocks keeps
  // the bars wide enough to hit and label.
  const grouped = useMemo(() => {
    const out: { label: string; total: number; connected: number }[] = [];
    for (let i = 0; i < data.length; i += groupHours) {
      const slice = data.slice(i, i + groupHours);
      if (!slice.length) continue;
      out.push({
        label: slice[0].label,
        total: slice.reduce((s, d) => s + d.total, 0),
        connected: slice.reduce((s, d) => s + d.connected, 0),
      });
    }
    return out;
  }, [data, groupHours]);

  if (grouped.length === 0) return <ChartEmpty message="No data yet." />;

  const plotW = BAR_W - BAR_PAD.left - BAR_PAD.right;
  const plotH = BAR_H - BAR_PAD.top - BAR_PAD.bottom;
  const ceiling = niceCeiling(Math.max(...grouped.map((d) => d.total), 1));
  const slot = plotW / grouped.length;
  const barW = Math.min(22, slot * 0.55);
  const y = (v: number) => BAR_PAD.top + plotH - (v / ceiling) * plotH;

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${BAR_W} ${BAR_H}`}
        className="w-full"
        role="img"
        aria-label="Call volume by time of day"
        onMouseLeave={() => setHover(null)}
      >
        {[0, ceiling / 2, ceiling].map((t) => (
          <g key={t}>
            <line x1={BAR_PAD.left} x2={BAR_W - BAR_PAD.right} y1={y(t)} y2={y(t)} stroke="var(--color-line)" strokeWidth="1" />
            <text x={BAR_PAD.left - 7} y={y(t) + 3.5} textAnchor="end" className="tnum" fontSize="9" fill="var(--color-ink-muted)">
              {Math.round(t)}
            </text>
          </g>
        ))}

        {grouped.map((d, i) => {
          const cx = BAR_PAD.left + slot * i + slot / 2;
          const top = y(d.total);
          const height = Math.max(0, BAR_PAD.top + plotH - top);
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              <rect x={cx - slot / 2} y={BAR_PAD.top} width={slot} height={plotH} fill="transparent" />
              <rect
                x={cx - barW / 2}
                y={top}
                width={barW}
                height={height}
                rx="4"
                fill={hover === i ? "var(--color-ramp-1)" : "var(--color-ramp-2)"}
                className="transition-[fill]"
              />
              <text x={cx} y={BAR_H - 7} textAnchor="middle" className="tnum" fontSize="9" fill="var(--color-ink-muted)">
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>

      {hover !== null && (
        <ChartTip left={`${((BAR_PAD.left + slot * hover + slot / 2) / BAR_W) * 100}%`}>
          <p className="tnum text-xs font-medium text-ink">{grouped[hover].label}</p>
          <p className="tnum mt-0.5 text-xs text-ink-secondary">
            {grouped[hover].total} calls · {grouped[hover].connected} connected
          </p>
        </ChartTip>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Donut — outcome composition
// ---------------------------------------------------------------------------

/** Outcome keys → display labels for the legend. */
const OUTCOME_LABEL: Record<string, string> = {
  completed: "Completed",
  partial: "Partial",
  callback_requested: "Callback",
  declined: "Declined",
  do_not_call: "Do not call",
  failed: "Failed",
  voicemail: "Voicemail",
  no_answer: "No answer",
  wrong_number: "Wrong number",
  other: "Other",
};

/**
 * Capped at five segments with the tail folded into "Other", and every
 * segment direct-labelled in the legend with its count. An unlabelled donut
 * with a long tail is unreadable; this constraint is what makes the form
 * defensible here. Segments use one sequential ramp ordered by size —
 * magnitude carried by one hue.
 */
const MAX_SEGMENTS = 5;

export function DonutChart({
  breakdown,
  centerLabel = "calls",
}: {
  breakdown: Record<string, number>;
  centerLabel?: string;
}) {
  const [hover, setHover] = useState<number | null>(null);

  const segments = useMemo(() => {
    const sorted = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);
    if (sorted.length <= MAX_SEGMENTS) return sorted;
    const head = sorted.slice(0, MAX_SEGMENTS - 1);
    const tail = sorted.slice(MAX_SEGMENTS - 1).reduce((s, [, n]) => s + n, 0);
    return [...head, ["other", tail] as [string, number]];
  }, [breakdown]);

  const total = segments.reduce((s, [, n]) => s + n, 0);
  if (total === 0) return <ChartEmpty message="No finished calls in the last 24 hours." />;

  const R = 54;
  const STROKE = 18;
  const circumference = 2 * Math.PI * R;
  const GAP = 2; // surface gap between segments

  let offset = 0;
  const arcs = segments.map(([key, count], i) => {
    const fraction = count / total;
    const length = Math.max(0, fraction * circumference - GAP);
    const arc = {
      key,
      count,
      fraction,
      dash: `${length} ${circumference - length}`,
      offset: -offset,
      colour: `var(--color-ramp-${Math.min(i + 1, 5)})`,
    };
    offset += fraction * circumference;
    return arc;
  });

  const label = (key: string) => OUTCOME_LABEL[key] ?? key.replace(/_/g, " ");

  return (
    // Lays out by the space the card gives it, not the viewport: at 1024px the
    // outcomes card is narrow even though the screen is wide.
    <div className="@container">
    <div className="flex flex-col items-center gap-5 @xs:flex-row">
      <div className="relative shrink-0">
        <svg width="140" height="140" viewBox="0 0 140 140" role="img" aria-label="Outcome breakdown">
          <g transform="rotate(-90 70 70)">
            {arcs.map((arc, i) => (
              <circle
                key={arc.key}
                cx="70"
                cy="70"
                r={R}
                fill="none"
                stroke={arc.colour}
                strokeWidth={hover === i ? STROKE + 3 : STROKE}
                strokeDasharray={arc.dash}
                strokeDashoffset={arc.offset}
                className="cursor-pointer transition-[stroke-width]"
                onMouseEnter={() => setHover(i)}
                onMouseLeave={() => setHover(null)}
              />
            ))}
          </g>
        </svg>
        <div className="pointer-events-none absolute inset-0 flex flex-col items-center justify-center">
          {hover !== null ? (
            <>
              <span className="tnum text-lg font-semibold text-ink">{Math.round(arcs[hover].fraction * 100)}%</span>
              <span className="max-w-[86px] text-center text-[10px] leading-tight text-ink-muted">{label(arcs[hover].key)}</span>
            </>
          ) : (
            <>
              <span className="tnum text-lg font-semibold text-ink">{total}</span>
              <span className="text-[10px] text-ink-muted">{centerLabel}</span>
            </>
          )}
        </div>
      </div>

      <ul className="w-full min-w-0 space-y-1.5">
        {arcs.map((arc, i) => (
          <li
            key={arc.key}
            className="flex items-center justify-between gap-2 rounded px-1 text-xs"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="flex min-w-0 items-center gap-2">
              <span className="h-2.5 w-2.5 shrink-0 rounded-sm" style={{ background: arc.colour }} aria-hidden />
              <span className="truncate text-ink-secondary">{label(arc.key)}</span>
            </span>
            <span className="tnum shrink-0 font-medium text-ink">
              {arc.count}
              <span className="ml-1.5 font-normal text-ink-muted">{Math.round(arc.fraction * 100)}%</span>
            </span>
          </li>
        ))}
      </ul>
    </div>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Sentiment — one stacked bar
// ---------------------------------------------------------------------------

const SENTIMENT_ORDER: Array<{ key: Sentiment; label: string; colour: string }> = [
  { key: "positive", label: "Positive", colour: "var(--color-good)" },
  { key: "neutral", label: "Neutral", colour: "var(--color-line-strong)" },
  { key: "negative", label: "Negative", colour: "var(--color-critical)" },
];

export function SentimentBar({ breakdown }: { breakdown: Partial<Record<Sentiment, number>> }) {
  const total = SENTIMENT_ORDER.reduce((s, o) => s + (breakdown[o.key] ?? 0), 0);
  if (total === 0) return <ChartEmpty message="Sentiment appears once calls have been read." compact />;

  return (
    <div>
      <div className="flex h-3 gap-0.5 overflow-hidden rounded-full" role="img" aria-label="Sentiment breakdown">
        {SENTIMENT_ORDER.map(({ key, colour }) => {
          const n = breakdown[key] ?? 0;
          return n ? (
            <div
              key={key}
              className="h-full transition-[width] duration-500 first:rounded-l-full last:rounded-r-full"
              style={{ width: `${(n / total) * 100}%`, background: colour }}
            />
          ) : null;
        })}
      </div>
      <ul className="mt-3 grid grid-cols-3 gap-2">
        {SENTIMENT_ORDER.map(({ key, label, colour }) => {
          const n = breakdown[key] ?? 0;
          return (
            <li key={key}>
              <span className="flex items-center gap-1.5 text-2xs text-ink-muted">
                <span className="h-2 w-2 rounded-sm" style={{ background: colour }} aria-hidden />
                {label}
              </span>
              <span className="tnum mt-0.5 block text-sm font-semibold text-ink">
                {n}
                <span className="ml-1 text-xs font-normal text-ink-muted">{Math.round((n / total) * 100)}%</span>
              </span>
            </li>
          );
        })}
      </ul>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Per-turn latency
// ---------------------------------------------------------------------------

// Wide viewBox so the chart doesn't balloon in a wide card.
const LAT_W = 520;
const LAT_H = 104;
const LAT_PAD = { top: 12, right: 4, bottom: 18, left: 4 };
const FEELS_IMMEDIATE_MS = 800;

export function LatencyBars({ values }: { values: number[] }) {
  const [hover, setHover] = useState<number | null>(null);
  if (!values.length) return <ChartEmpty message="No agent replies were timed on this call." compact />;

  const plotW = LAT_W - LAT_PAD.left - LAT_PAD.right;
  const plotH = LAT_H - LAT_PAD.top - LAT_PAD.bottom;
  const ceiling = Math.max(1500, ...values) * 1.1;
  const slot = plotW / Math.max(values.length, 6);
  const barW = Math.min(18, slot * 0.6);
  const y = (ms: number) => LAT_PAD.top + plotH - (ms / ceiling) * plotH;
  const colour = (ms: number) =>
    ms < FEELS_IMMEDIATE_MS ? "var(--color-good)" : ms < 1500 ? "var(--color-warning)" : "var(--color-critical)";

  const sorted = [...values].sort((a, b) => a - b);
  const median = sorted[Math.floor(sorted.length / 2)];

  return (
    <div className="relative">
      <div className="mb-2 flex items-baseline justify-between text-xs text-ink-muted">
        <span>
          Median <span className="tnum font-semibold text-ink">{formatMs(median)}</span> across {values.length}{" "}
          {values.length === 1 ? "reply" : "replies"}
        </span>
        <span className="tnum">slowest {formatMs(sorted[sorted.length - 1])}</span>
      </div>
      <svg
        viewBox={`0 0 ${LAT_W} ${LAT_H}`}
        className="w-full"
        role="img"
        aria-label={`Reply latency per turn. Median ${formatMs(median)}.`}
        onMouseLeave={() => setHover(null)}
      >
        <line
          x1={LAT_PAD.left}
          x2={LAT_W - LAT_PAD.right}
          y1={y(FEELS_IMMEDIATE_MS)}
          y2={y(FEELS_IMMEDIATE_MS)}
          stroke="var(--color-good)"
          strokeOpacity="0.5"
          strokeDasharray="3 3"
        />
        <text x={LAT_W - LAT_PAD.right} y={y(FEELS_IMMEDIATE_MS) - 4} textAnchor="end" fontSize="11" fill="var(--color-ink-muted)">
          0.8 s
        </text>
        {values.map((ms, i) => {
          const cx = LAT_PAD.left + slot * i + slot / 2;
          return (
            <g key={i} onMouseEnter={() => setHover(i)}>
              <rect x={cx - slot / 2} y={LAT_PAD.top} width={slot} height={plotH} fill="transparent" />
              <rect
                x={cx - barW / 2}
                y={y(ms)}
                width={barW}
                height={Math.max(2, LAT_PAD.top + plotH - y(ms))}
                rx="3"
                fill={colour(ms)}
                opacity={hover === null || hover === i ? 1 : 0.45}
                className="transition-opacity"
              />
              <text x={cx} y={LAT_H - 4} textAnchor="middle" className="tnum" fontSize="11" fill="var(--color-ink-muted)">
                {i + 1}
              </text>
            </g>
          );
        })}
      </svg>
      {hover !== null && (
        <ChartTip left={`${((LAT_PAD.left + slot * hover + slot / 2) / LAT_W) * 100}%`} top="1.5rem">
          <p className="tnum text-xs font-medium text-ink">
            Reply {hover + 1} · {formatMs(values[hover])}
          </p>
        </ChartTip>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------

function ChartTip({ left, top = "0.25rem", children }: { left: string; top?: string; children: React.ReactNode }) {
  return (
    <div
      className="pointer-events-none absolute z-10 rounded-lg border border-line bg-raised px-2.5 py-1.5 elev-2"
      style={{ left, top, transform: "translateX(-50%)" }}
    >
      {children}
    </div>
  );
}

function ChartEmpty({ message, compact = false }: { message: string; compact?: boolean }) {
  return (
    <div className={`flex items-center justify-center ${compact ? "h-16" : "h-40"}`}>
      <p className="text-xs text-ink-muted">{message}</p>
    </div>
  );
}
