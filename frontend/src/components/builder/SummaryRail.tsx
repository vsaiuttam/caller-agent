import type { ReactNode } from "react";
import { AgentAvatar } from "../AgentAvatar";
import { IconAlert, IconCheck } from "../icons";
import { estimateOf } from "../models/estimate";
import { money } from "../models/meta";
import { Card, Skeleton, cx } from "../ui";
import { languageName, useBuilder } from "./context";
import { daysLabel, hour, type StepId } from "./draft";

export const voiceLabel = (voice: string | null | undefined) =>
  voice ? voice.replace(/[_-]/g, " ").replace(/^./, (c) => c.toUpperCase()) : "Default voice";

export function useModelLabel(): string {
  const { draft, providers } = useBuilder();
  const f = draft.form;
  const provider = providers?.find((p) => p.id === f.conversation_provider_id);
  if (!provider && !f.conversation_model) return "Workspace default";
  return [provider?.label ?? "Default provider", f.conversation_model ?? "recommended model"].join(" · ");
}

/** The builder's sticky summary: what this campaign is, and what it will cost. */
export function SummaryRail() {
  const { draft, languages, estimate, contactCount, blockers, goTo } = useBuilder();
  const f = draft.form;
  const est = estimateOf(estimate);
  const modelLabel = useModelLabel();
  const toFix = blockers.filter((b) => b.level === "block");
  const tools = (f.mcp_tools?.length ?? 0) + (f.mcp_post_call_tools?.length ?? 0);

  return (
    <Card className="overflow-hidden">
      <div className="flex items-center gap-3 border-b border-line px-4 py-3.5">
        <AgentAvatar state={toFix.length ? "thinking" : "idle"} size="sm" animated={false} />
        <div className="min-w-0">
          <p className="truncate text-sm font-semibold text-ink">{f.name.trim() || "Untitled campaign"}</p>
          <p className="truncate text-xs text-ink-muted">{f.goal.trim() || "No goal yet"}</p>
        </div>
      </div>

      <dl className="divide-y divide-line text-xs">
        <Row label="Language" step="agent" onEdit={goTo}>
          {languageName(languages, f.language)}
        </Row>
        <Row label="Voice" step="agent" onEdit={goTo}>
          {voiceLabel(f.voice)}
        </Row>
        <Row label="Model" step="agent" onEdit={goTo}>
          {modelLabel}
        </Row>
        <Row label="Tools" step="tools" onEdit={goTo}>
          {tools ? `${tools} selected` : "None"}
        </Row>
        <Row label="Contacts" step="contacts" onEdit={goTo}>
          <span className={cx("tnum", !contactCount && "text-warning")}>{contactCount ? contactCount.toLocaleString() : "None yet"}</span>
        </Row>
        <Row label="When" step="schedule" onEdit={goTo}>
          {daysLabel(f.calling_days)}, {hour(f.calling_hours_start)} to {hour(f.calling_hours_end)}
        </Row>
        {f.precall_enabled && (
          <Row label="Heads-up" step="schedule" onEdit={goTo}>
            {f.precall_channel === "whatsapp" ? "WhatsApp" : "SMS"}, {f.precall_lead_minutes} min before
          </Row>
        )}
      </dl>

      <div className="border-t border-line bg-subtle/50 px-4 py-3.5">
        <p className="text-2xs font-medium uppercase tracking-wider text-ink-muted">Estimated cost</p>
        {estimate.status === "unavailable" ? (
          <p className="mt-1 text-xs text-ink-muted">Needs a server update.</p>
        ) : estimate.status === "error" ? (
          <p className="mt-1 text-xs text-ink-muted" title={estimate.message}>
            Couldn't estimate right now.
          </p>
        ) : !est ? (
          <Skeleton className="mt-2 h-10 w-full" />
        ) : (
          <div className={cx("mt-1.5 grid grid-cols-2 gap-3 transition-opacity", estimate.status === "loading" && "opacity-60")} aria-live="polite">
            <div>
              <p className="tnum text-lg font-semibold leading-tight text-ink">{money(est.per_call.total)}</p>
              <p className="text-2xs text-ink-muted">per call</p>
            </div>
            <div>
              <p className="tnum text-lg font-semibold leading-tight text-ink">{contactCount ? money(est.for_calls.total) : "—"}</p>
              <p className="text-2xs text-ink-muted">{contactCount ? `for ${contactCount.toLocaleString()} contacts` : "add contacts for a total"}</p>
            </div>
            {est.unknown.length > 0 && (
              <p className="col-span-2 flex items-start gap-1 text-2xs text-warning">
                <IconAlert size={11} className="mt-0.5 shrink-0" /> Not counted: {est.unknown.join(", ")} (price not set)
              </p>
            )}
          </div>
        )}
      </div>

      <button
        type="button"
        onClick={() => goTo("review")}
        className={cx(
          "flex w-full items-center gap-2 border-t border-line px-4 py-3 text-left text-xs font-medium transition-colors hover:bg-subtle",
          toFix.length ? "text-warning" : "text-good",
        )}
      >
        {toFix.length ? <IconAlert size={13} /> : <IconCheck size={13} />}
        {toFix.length ? `${toFix.length} ${toFix.length === 1 ? "thing" : "things"} to fix before launch` : "Ready to launch"}
      </button>
    </Card>
  );
}

function Row({ label, step, onEdit, children }: { label: string; step: StepId; onEdit: (s: StepId) => void; children: ReactNode }) {
  return (
    <div className="group flex items-baseline justify-between gap-3 px-4 py-2">
      <dt className="shrink-0 text-ink-muted">{label}</dt>
      <dd className="min-w-0 text-right">
        <button type="button" onClick={() => onEdit(step)} className="max-w-full truncate rounded text-right font-medium text-ink hover:text-brand" title={`Edit ${label.toLowerCase()}`}>
          {children}
        </button>
      </dd>
    </div>
  );
}
