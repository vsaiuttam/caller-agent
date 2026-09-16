/**
 * Hand-rolled SVG charts. No charting dependency — two forms is not worth
 * 200kB, and the mark specs are easier to honour directly than to fight a
 * library's defaults into.
 *
 * Forms follow the data's job:
 *   - Volume over time  → area, single series, sequential hue (no legend: the
 *                         title names the series)
 *   - Outcome magnitude → ranked horizontal bars. Deliberately NOT a donut:
 *                         part-to-whole with 5+ long-named categories is a
 *                         documented anti-pattern, and ranked bars read
 *                         accurately at a glance where slices don't.
 *
 * Both ship a hover layer, because an SVG chart that can be interactive
 * should be.
 */

import { useMemo, useState } from "react";
import type { HourBucket } from "../api";

// ---------------------------------------------------------------------------
// Area chart — 24h call volume
// ---------------------------------------------------------------------------

const AREA_W = 720;
const AREA_H = 200;
const PAD = { top: 16, right: 12, bottom: 26, left: 34 };

export function VolumeChart({ data }: { data: HourBucket[] }) {
  const [hover, setHover] = useState<number | null>(null);

  if (data.length === 0) {
    return <ChartEmpty message="No calls in the last 24 hours." />;
  }

  const plotW = AREA_W - PAD.left - PAD.right;
  const plotH = AREA_H - PAD.top - PAD.bottom;

  const peak = Math.max(...data.map((d) => d.total), 1);
  // Round the axis ceiling up to something readable rather than the raw peak,
  // so gridlines land on whole numbers.
  const ceiling = niceCeiling(peak);

  const x = (i: number) => PAD.left + (i / Math.max(1, data.length - 1)) * plotW;
  const y = (v: number) => PAD.top + plotH - (v / ceiling) * plotH;

  const linePath = data.map((d, i) => `${i ? "L" : "M"}${x(i)},${y(d.total)}`).join(" ");
  const areaPath = `${linePath} L${x(data.length - 1)},${PAD.top + plotH} L${x(0)},${
    PAD.top + plotH
  } Z`;

  const ticks = [0, ceiling / 2, ceiling];
  const active = hover === null ? null : data[hover];

  return (
    <div className="relative">
      <svg
        viewBox={`0 0 ${AREA_W} ${AREA_H}`}
        className="w-full"
        role="img"
        aria-label="Call volume over the last 24 hours"
        onMouseLeave={() => setHover(null)}
      >
        <defs>
          <linearGradient id="volume-fill" x1="0" y1="0" x2="0" y2="1">
            <stop offset="0%" stopColor="var(--color-brand)" stopOpacity="0.20" />
            <stop offset="100%" stopColor="var(--color-brand)" stopOpacity="0.02" />
          </linearGradient>
        </defs>

        {/* Recessive grid — hairlines, never competing with the data */}
        {ticks.map((t) => (
          <g key={t}>
            <line
              x1={PAD.left}
              x2={AREA_W - PAD.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--color-line)"
              strokeWidth="1"
            />
            <text
              x={PAD.left - 8}
              y={y(t) + 3.5}
              textAnchor="end"
              className="tnum"
              fontSize="10"
              fill="var(--color-ink-muted)"
            >
              {Math.round(t)}
            </text>
          </g>
        ))}

        <path d={areaPath} fill="url(#volume-fill)" />
        <path
          d={linePath}
          fill="none"
          stroke="var(--color-brand)"
          strokeWidth="2"
          strokeLinecap="round"
          strokeLinejoin="round"
        />

        {/* Hour labels every 4th bucket, so they never collide */}
        {data.map((d, i) =>
          i % 4 === 0 ? (
            <text
              key={d.hour}
              x={x(i)}
              y={AREA_H - 8}
              textAnchor="middle"
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
            <line
              className="crosshair-line"
              x1={x(hover)}
              x2={x(hover)}
              y1={PAD.top}
              y2={PAD.top + plotH}
            />
            {/* 2px surface ring keeps the marker legible over the fill */}
            <circle
              cx={x(hover)}
              cy={y(data[hover].total)}
              r="5"
              fill="var(--color-brand)"
              stroke="var(--color-surface)"
              strokeWidth="2"
            />
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
        <div
          className="pointer-events-none absolute top-2 rounded-lg border border-line bg-surface px-2.5 py-1.5 shadow-sm"
          style={{
            left: `${(x(hover!) / AREA_W) * 100}%`,
            transform: "translateX(-50%)",
          }}
        >
          <p className="tnum text-xs font-medium">{active.label}</p>
          <p className="tnum mt-0.5 text-xs text-ink-secondary">
            {active.total} {active.total === 1 ? "call" : "calls"} · {active.connected}{" "}
            connected
          </p>
        </div>
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
// Ranked horizontal bars — outcome breakdown
// ---------------------------------------------------------------------------

/** Outcome → status role. Status ships with a label, never colour alone. */
const OUTCOME_STATUS: Record<string, { label: string; tone: string }> = {
  completed: { label: "Completed", tone: "var(--color-good)" },
  partial: { label: "Partial", tone: "var(--color-warning)" },
  callback_requested: { label: "Callback", tone: "var(--color-warning)" },
  declined: { label: "Declined", tone: "var(--color-serious)" },
  do_not_call: { label: "Do not call", tone: "var(--color-critical)" },
  failed: { label: "Failed", tone: "var(--color-critical)" },
  voicemail: { label: "Voicemail", tone: "var(--color-ink-muted)" },
  no_answer: { label: "No answer", tone: "var(--color-ink-muted)" },
  wrong_number: { label: "Wrong number", tone: "var(--color-ink-muted)" },
};

// Sequential ramp, darkest for the largest bar. One hue carries magnitude;
// the status dot beside the label carries meaning.
const RAMP = [
  "var(--color-ramp-5)",
  "var(--color-ramp-4)",
  "var(--color-ramp-3)",
  "var(--color-ramp-2)",
  "var(--color-ramp-1)",
];

export function OutcomeBars({ breakdown }: { breakdown: Record<string, number> }) {
  const entries = Object.entries(breakdown).sort((a, b) => b[1] - a[1]);

  if (entries.length === 0) {
    return <ChartEmpty message="No completed calls yet." />;
  }

  const max = Math.max(...entries.map(([, n]) => n));
  const total = entries.reduce((sum, [, n]) => sum + n, 0);

  return (
    <ul className="space-y-3">
      {entries.map(([key, count], i) => {
        const meta = OUTCOME_STATUS[key] ?? {
          label: key.replace(/_/g, " "),
          tone: "var(--color-ink-muted)",
        };
        const width = (count / max) * 100;

        return (
          <li key={key}>
            <div className="mb-1.5 flex items-center justify-between gap-3">
              <span className="flex items-center gap-2 text-sm">
                <span
                  className="h-2 w-2 shrink-0 rounded-full"
                  style={{ background: meta.tone }}
                  aria-hidden
                />
                <span className="text-ink-secondary">{meta.label}</span>
              </span>
              {/* Direct-labelled: every bar carries its own value, so no
                  legend and no axis reading is needed. */}
              <span className="tnum shrink-0 text-sm font-medium">
                {count}
                <span className="ml-1.5 text-xs font-normal text-ink-muted">
                  {Math.round((count / total) * 100)}%
                </span>
              </span>
            </div>
            <div className="h-2 overflow-hidden rounded-sm bg-line/60">
              {/* Rounded data-end, square baseline end */}
              <div
                className="h-full rounded-r-[4px] transition-[width] duration-500"
                style={{ width: `${width}%`, background: RAMP[Math.min(i, RAMP.length - 1)] }}
              />
            </div>
          </li>
        );
      })}
    </ul>
  );
}

// ---------------------------------------------------------------------------

function ChartEmpty({ message }: { message: string }) {
  return (
    <div className="flex h-40 items-center justify-center">
      <p className="text-xs text-ink-muted">{message}</p>
    </div>
  );
}

// ---------------------------------------------------------------------------
// Column chart — volume grouped into wider buckets
// ---------------------------------------------------------------------------

const BAR_W = 460;
const BAR_H = 190;
const BAR_PAD = { top: 14, right: 8, bottom: 24, left: 30 };

export function ColumnChart({
  data,
  groupHours = 3,
}: {
  data: HourBucket[];
  groupHours?: number;
}) {
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
            <line
              x1={BAR_PAD.left}
              x2={BAR_W - BAR_PAD.right}
              y1={y(t)}
              y2={y(t)}
              stroke="var(--color-line)"
              strokeWidth="1"
            />
            <text
              x={BAR_PAD.left - 7}
              y={y(t) + 3.5}
              textAnchor="end"
              className="tnum"
              fontSize="9"
              fill="var(--color-ink-muted)"
            >
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
              {/* Wider transparent hit target than the bar itself */}
              <rect
                x={cx - slot / 2}
                y={BAR_PAD.top}
                width={slot}
                height={plotH}
                fill="transparent"
              />
              <rect
                x={cx - barW / 2}
                y={top}
                width={barW}
                height={height}
                rx="4"
                fill={hover === i ? "var(--color-ramp-2)" : "var(--color-ramp-3)"}
                className="transition-[fill]"
              />
              <text
                x={cx}
                y={BAR_H - 7}
                textAnchor="middle"
                className="tnum"
                fontSize="9"
                fill="var(--color-ink-muted)"
              >
                {d.label}
              </text>
            </g>
          );
        })}
      </svg>

      {hover !== null && (
        <div
          className="pointer-events-none absolute top-1 rounded-lg border border-line bg-raised px-2.5 py-1.5"
          style={{
            left: `${((BAR_PAD.left + slot * hover + slot / 2) / BAR_W) * 100}%`,
            transform: "translateX(-50%)",
          }}
        >
          <p className="tnum text-xs font-medium">{grouped[hover].label}</p>
          <p className="tnum mt-0.5 text-xs text-ink-secondary">
            {grouped[hover].total} calls · {grouped[hover].connected} connected
          </p>
        </div>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------
// Donut — outcome composition
// ---------------------------------------------------------------------------

/**
 * Capped at five segments with the tail folded into "Other", and every
 * segment direct-labelled in the legend with its count and share. An
 * unlabelled donut with a long tail is unreadable; this constraint is what
 * makes the form defensible here.
 *
 * Segments use the single lavender ramp ordered by size — magnitude carried
 * by one hue, which sidesteps the colour-separation problem a categorical
 * palette would create at this segment count.
 */
const MAX_SEGMENTS = 5;

export function DonutChart({
  breakdown,
  centerLabel,
  centerValue,
}: {
  breakdown: Record<string, number>;
  centerLabel?: string;
  centerValue?: string;
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
  if (total === 0) return <ChartEmpty message="No completed calls yet." />;

  const R = 54;
  const STROKE = 18;
  const circumference = 2 * Math.PI * R;
  // 2px surface gap between segments, per the mark spec.
  const GAP = 2;

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

  return (
    <div className="flex flex-col items-center gap-4 sm:flex-row sm:items-center sm:gap-5">
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
              <span className="tnum text-lg font-semibold">
                {Math.round(arcs[hover].fraction * 100)}%
              </span>
              <span className="max-w-[86px] text-center text-[10px] leading-tight text-ink-muted">
                {labelFor(arcs[hover].key)}
              </span>
            </>
          ) : (
            <>
              <span className="tnum text-lg font-semibold">{centerValue ?? total}</span>
              <span className="text-[10px] text-ink-muted">{centerLabel ?? "calls"}</span>
            </>
          )}
        </div>
      </div>

      <ul className="w-full space-y-1.5">
        {arcs.map((arc, i) => (
          <li
            key={arc.key}
            className="flex items-center justify-between gap-2 text-xs"
            onMouseEnter={() => setHover(i)}
            onMouseLeave={() => setHover(null)}
          >
            <span className="flex min-w-0 items-center gap-2">
              <span
                className="h-2.5 w-2.5 shrink-0 rounded-sm"
                style={{ background: arc.colour }}
                aria-hidden
              />
              <span className="truncate text-ink-secondary">{labelFor(arc.key)}</span>
            </span>
            <span className="tnum shrink-0 font-medium">{arc.count}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function labelFor(key: string): string {
  return (
    OUTCOME_STATUS[key]?.label ??
    key.replace(/_/g, " ").replace(/^\w/, (c) => c.toUpperCase())
  );
}
