/**
 * One reading of /api/health, shared by the top bar's health pill and the
 * console footer so they never disagree.
 */

import type { Health } from "../../api";

export type StatusTone = "good" | "warning" | "critical" | "muted";

export interface SystemStatus {
  tone: StatusTone;
  label: string;
  detail: string;
}

export function systemStatus(health: Health | null, error: string | null): SystemStatus {
  if (!health) {
    return error
      ? { tone: "critical", label: "API unreachable", detail: error }
      : { tone: "muted", label: "Checking…", detail: "Asking the server what's connected." };
  }
  if (!health.ok) return { tone: "critical", label: "Degraded", detail: "The database isn't answering." };
  if (!health.can_run_simulations) {
    return { tone: "warning", label: "No model", detail: "No model provider key is set, so nothing can talk." };
  }
  if (!health.can_place_calls) {
    return { tone: "warning", label: "Demo mode", detail: "Telephony is mocked: rehearsals work, real calls don't." };
  }
  return { tone: "good", label: "Operational", detail: "Model provider and telephony are connected." };
}

export const STATUS_DOT: Record<StatusTone, string> = {
  good: "bg-good",
  warning: "bg-warning",
  critical: "bg-critical",
  muted: "bg-ink-muted/50",
};
