/**
 * Cost estimates from POST /api/estimate: a debounced hook, the stacked
 * per-call breakdown, and the compact chip the campaign builder shows.
 */

import { useEffect, useRef, useState } from "react";
import { api, isMissing, type Estimate, type EstimateRequest } from "../../api";
import { IconAlert, IconCoin } from "../icons";
import { Skeleton, Tooltip, cx } from "../ui";
import { COMPONENTS, SERIES_BG, isUnknown, money } from "./meta";

export type EstimateState =
  | { status: "idle" }
  | { status: "loading"; previous: Estimate | null }
  | { status: "ready"; estimate: Estimate }
  | { status: "unavailable" }
  | { status: "error"; message: string };

/** Re-estimates 400ms after the inputs stop changing. */
export function useEstimate(request: EstimateRequest | null): EstimateState {
  const [state, setState] = useState<EstimateState>({ status: "idle" });
  const last = useRef<Estimate | null>(null);
  const key = request ? JSON.stringify(request) : "";

  useEffect(() => {
    if (!request) {
      setState({ status: "idle" });
      return;
    }
    let cancelled = false;
    setState({ status: "loading", previous: last.current });
    const timer = window.setTimeout(() => {
      api
        .estimateCost(request)
        .then((estimate) => {
          if (cancelled) return;
          last.current = estimate;
          setState({ status: "ready", estimate });
        })
        .catch((err) => {
          if (cancelled) return;
          setState(isMissing(err) ? { status: "unavailable" } : { status: "error", message: (err as Error).message });
        });
    }, 400);
    return () => {
      cancelled = true;
      window.clearTimeout(timer);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [key]);

  return state;
}

export const estimateOf = (state: EstimateState): Estimate | null =>
  state.status === "ready" ? state.estimate : state.status === "loading" ? state.previous : null;

/**
 * One horizontal bar per call: each component's share, 2px gaps between
 * segments, and a legend that names every segment with its value (the colour
 * is never the only label). Unknown components are listed, never drawn as $0.
 */
export function CostBreakdown({ estimate, calls }: { estimate: Estimate; calls?: number }) {
  const parts = COMPONENTS.map((c, i) => ({
    ...c,
    value: estimate.per_call[c.key],
    unknown: isUnknown(estimate, c.key),
    color: SERIES_BG[i],
  }));
  const known = parts.filter((p) => !p.unknown && (p.value ?? 0) > 0);
  const total = known.reduce((sum, p) => sum + (p.value ?? 0), 0);

  return (
    <div>
      <div className="flex h-3 w-full gap-[2px] overflow-hidden rounded-full bg-subtle" role="img" aria-label={`Cost per call: ${known.map((p) => `${p.label} ${money(p.value)}`).join(", ")}`}>
        {known.map((p) => (
          <span
            key={p.key}
            title={`${p.label}: ${money(p.value)} per call (${Math.round(((p.value ?? 0) / total) * 100)}%)`}
            className={cx("h-full min-w-[3px] transition-[flex-grow] duration-300", p.color)}
            style={{ flexGrow: p.value ?? 0, flexBasis: 0 }}
          />
        ))}
      </div>
      <dl className="mt-3 grid grid-cols-1 gap-x-6 gap-y-1.5 sm:grid-cols-2">
        {parts.map((p) => (
          <div key={p.key} className="flex items-center justify-between gap-3 text-xs">
            <dt className="flex min-w-0 items-center gap-2 text-ink-secondary">
              <span className={cx("h-2.5 w-2.5 shrink-0 rounded-sm", p.unknown ? "border border-dashed border-line-control" : p.color)} aria-hidden />
              <span className="truncate" title={p.hint}>
                {p.label}
              </span>
            </dt>
            <dd className="tnum font-medium text-ink">
              {p.unknown ? (
                <span className="inline-flex items-center gap-1 text-warning">
                  <IconAlert size={11} /> Price not set
                </span>
              ) : (
                <>
                  {money(p.value)}
                  {calls ? <span className="ml-1.5 font-normal text-ink-muted">· {money((p.value ?? 0) * calls)}</span> : null}
                </>
              )}
            </dd>
          </div>
        ))}
      </dl>
    </div>
  );
}

/** "≈ $0.043 / call" with the list total under it. For the builder's rail and step 2. */
export function CostChip({ state, calls, className = "" }: { state: EstimateState; calls: number; className?: string }) {
  const estimate = estimateOf(state);
  if (state.status === "idle") return null;
  if (state.status === "unavailable") {
    return <span className={cx("text-xs text-ink-muted", className)}>Cost estimate needs a server update</span>;
  }
  if (state.status === "error") {
    return (
      <span className={cx("inline-flex items-center gap-1 text-xs text-ink-muted", className)} title={state.message}>
        <IconAlert size={12} /> No estimate
      </span>
    );
  }
  if (!estimate) return <Skeleton className={cx("h-6 w-32", className)} />;
  const partial = estimate.unknown.length > 0;
  const perCall = estimate.per_call.total;
  return (
    <span
      className={cx(
        "inline-flex max-w-full flex-wrap items-center gap-x-1.5 gap-y-0.5 rounded-full border border-line bg-subtle px-2.5 py-1 text-xs transition-opacity",
        state.status === "loading" && "opacity-60",
        className,
      )}
      aria-live="polite"
    >
      <IconCoin size={12} className="text-ink-muted" />
      <span className="tnum font-semibold text-ink">{perCall === null ? "Unknown" : `≈ ${money(perCall)}`}</span>
      <span className="text-ink-muted">per call</span>
      {calls > 0 && estimate.for_calls.total !== null && (
        <span className="tnum text-ink-muted">
          · {money(estimate.for_calls.total)} for {calls.toLocaleString()}
        </span>
      )}
      {partial && (
        <Tooltip content={`Not included: ${estimate.unknown.join(", ")} (price not set)`}>
          <span tabIndex={0} className="inline-flex items-center text-warning" aria-label="Some prices are unknown">
            <IconAlert size={12} />
          </span>
        </Tooltip>
      )}
    </span>
  );
}
