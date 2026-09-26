/**
 * One call on the line, as a compact card: the agent's face in the call's
 * current state, who it's with, and how long it has been going.
 */

import type { LiveCallInfo } from "../../api";
import { formatDuration } from "../../format";
import { AgentAvatar, type AgentState } from "../AgentAvatar";
import { TestBadge, cx } from "../ui";

export function liveAvatarState(state: string): AgentState {
  if (state === "speaking" || state === "listening" || state === "thinking") return state;
  if (state === "working") return "thinking";
  if (state === "ended") return "ended";
  return "ringing";
}

export function liveStateLabel(state: string): string {
  switch (state) {
    case "speaking":
      return "Agent speaking";
    case "listening":
      return "Listening";
    case "thinking":
      return "Thinking";
    case "working":
      return "Using a tool";
    case "ended":
      return "Wrapping up";
    default:
      return "Ringing";
  }
}

export function LiveCallCard({
  call,
  campaignName,
  now,
  selected = false,
  onSelect,
  animated = true,
}: {
  call: LiveCallInfo;
  campaignName?: string;
  now: number;
  selected?: boolean;
  onSelect: () => void;
  animated?: boolean;
}) {
  const elapsed = Math.max(0, (now - new Date(call.started_at).getTime()) / 1000);
  const turns = Array.isArray(call.turns) ? call.turns.length : call.turns;
  return (
    <button
      type="button"
      onClick={onSelect}
      aria-pressed={selected}
      className={cx(
        "card card-interactive flex w-full items-center gap-3 px-3.5 py-3 text-left",
        selected && "!border-brand/50 ring-2 ring-brand/15",
      )}
    >
      <AgentAvatar state={liveAvatarState(call.state)} size="sm" animated={animated} />
      <span className="min-w-0 flex-1">
        <span className="flex items-center gap-1.5">
          <span className="truncate text-sm font-semibold text-ink">{call.contact_name || "Unknown"}</span>
          {call.is_test && <TestBadge />}
        </span>
        <span className="mt-0.5 block truncate text-xs text-ink-muted">
          {liveStateLabel(call.state)}
          {campaignName ? ` · ${campaignName}` : ""}
          {turns ? ` · ${turns} turns` : ""}
        </span>
      </span>
      <span className="tnum shrink-0 text-sm font-medium text-ink-secondary">{formatDuration(elapsed)}</span>
    </button>
  );
}
