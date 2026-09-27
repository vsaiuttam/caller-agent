import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { IconAlert, IconArrowRight, IconCheck, IconFlask, IconInfo } from "../icons";
import { CostBreakdown, estimateOf } from "../models/estimate";
import { money } from "../models/meta";
import { Button, Card, CardHeader, NotAvailable, Skeleton, cx } from "../ui";
import { languageName, useBuilder, type Blocker } from "./context";
import { daysLabel, greetingPreview, hour, type StepId } from "./draft";
import { useModelLabel, voiceLabel } from "./SummaryRail";

export function ReviewStep() {
  const { draft, blockers, languages, estimate, contactCount, goTo, campaign } = useBuilder();
  const f = draft.form;
  const est = estimateOf(estimate);
  const modelLabel = useModelLabel();
  const blocking = blockers.filter((b) => b.level === "block");
  const tools = (f.mcp_tools?.length ?? 0) + (f.mcp_post_call_tools?.length ?? 0);

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader
          title={blocking.length ? "Before you launch" : "Ready to launch"}
          subtitle={
            blocking.length
              ? "Launching is blocked until these are fixed. You can save a draft any time."
              : "Nothing blocks this campaign. Launching starts dialling inside the calling window."
          }
        />
        <ul className="divide-y divide-line">
          {blockers.length === 0 && (
            <li className="flex items-center gap-3 px-5 py-4 text-sm text-ink-secondary">
              <span className="flex h-7 w-7 items-center justify-center rounded-full bg-good/12 text-good">
                <IconCheck size={14} />
              </span>
              Telephony, a model provider, contacts and a calling window are all in place.
            </li>
          )}
          {blockers.map((b) => (
            <BlockerRow key={b.id} blocker={b} goTo={goTo} />
          ))}
        </ul>
      </Card>

      <Card>
        <CardHeader title="Summary" subtitle="Everything this campaign will do. Edit any part." />
        <dl className="divide-y divide-line text-sm">
          <Section label="Basics" step="basics" goTo={goTo}>
            <p className="font-medium text-ink">{f.name || "Untitled"}</p>
            <p className="mt-0.5 text-xs leading-relaxed text-ink-secondary">{f.goal || "No goal yet"}</p>
          </Section>
          <Section label="Agent" step="agent" goTo={goTo}>
            <p className="text-ink">
              {languageName(languages, f.language)} · {voiceLabel(f.voice)} · {modelLabel}
            </p>
            <p className="mt-1 text-xs italic leading-relaxed text-ink-secondary">“{greetingPreview(f.greeting, f.name, draft.contacts[0]?.full_name)}”</p>
          </Section>
          <Section label="Tools" step="tools" goTo={goTo}>
            <p className="text-ink">
              {tools ? `${f.mcp_tools?.length ?? 0} during the call, ${f.mcp_post_call_tools?.length ?? 0} after` : "No tools"}
            </p>
          </Section>
          <Section label="Contacts" step="contacts" goTo={goTo}>
            <p className="tnum text-ink">
              {contactCount.toLocaleString()} contact{contactCount === 1 ? "" : "s"}
              {draft.contacts.length > 0 && campaign ? ` (${draft.contacts.length.toLocaleString()} new, imported on save)` : ""}
            </p>
          </Section>
          <Section label="Schedule" step="schedule" goTo={goTo}>
            <p className="text-ink">
              {daysLabel(f.calling_days)}, {hour(f.calling_hours_start)} to {hour(f.calling_hours_end)} · {f.max_attempts} attempts · {f.max_concurrent_calls} lines
            </p>
            <p className="mt-0.5 text-xs text-ink-secondary">
              {f.precall_enabled ? `Heads-up by ${f.precall_channel === "whatsapp" ? "WhatsApp" : "SMS"} ${f.precall_lead_minutes} min before. ` : "No heads-up message. "}
              Follow-ups: {[f.sms_followup && "SMS", f.whatsapp_followup && "WhatsApp"].filter(Boolean).join(" and ") || "none"}.
              {f.budget_usd != null && ` Spend cap ${money(f.budget_usd)}.`}
            </p>
          </Section>
        </dl>
      </Card>

      <Card>
        <CardHeader title="What it will cost" subtitle={contactCount ? `Per call, then for ${contactCount.toLocaleString()} contacts. Every contact is assumed to connect once.` : "Per call. Add contacts to see the total."} />
        <div className="px-5 py-5">
          {estimate.status === "unavailable" ? (
            <NotAvailable>The full-call estimate arrives with the next server update.</NotAvailable>
          ) : estimate.status === "error" ? (
            <p className="text-sm text-ink-muted">{estimate.message}</p>
          ) : !est ? (
            <Skeleton className="h-24" />
          ) : (
            <div className={cx(estimate.status === "loading" && "opacity-60")}>
              <p className="tnum text-2xl font-semibold tracking-tight text-ink">
                {money(est.per_call.total)} <span className="text-sm font-normal text-ink-muted">per call</span>
                {contactCount > 0 && est.for_calls.total !== null && (
                  <span className="ml-3 text-base font-medium text-ink-secondary">· {money(est.for_calls.total)} total</span>
                )}
              </p>
              <div className="mt-4">
                <CostBreakdown estimate={est} calls={contactCount || undefined} />
              </div>
              {est.assumptions.length > 0 && (
                <ul className="mt-4 list-disc space-y-0.5 pl-4 text-xs text-ink-muted">
                  {est.assumptions.map((a) => (
                    <li key={a}>{a}</li>
                  ))}
                </ul>
              )}
            </div>
          )}
        </div>
      </Card>

      {campaign && (
        <p className="flex items-center gap-2 text-xs text-ink-muted">
          <IconFlask size={13} /> Rehearse it first:{" "}
          <Link to={`/app/test-lab?campaign=${campaign.id}`} className="font-medium text-brand hover:underline">
            open this campaign in the test lab
          </Link>
        </p>
      )}
    </div>
  );
}

function BlockerRow({ blocker: b, goTo }: { blocker: Blocker; goTo: (s: StepId) => void }) {
  const block = b.level === "block";
  const fix = b.fix;
  return (
    <li className="flex flex-wrap items-start gap-3 px-5 py-3.5">
      <span className={cx("mt-0.5 flex h-7 w-7 shrink-0 items-center justify-center rounded-full", block ? "bg-critical/10 text-critical" : "bg-info/10 text-info")}>
        {block ? <IconAlert size={14} /> : <IconInfo size={14} />}
      </span>
      <div className="min-w-0 flex-1">
        <p className="text-sm font-medium text-ink">{b.title}</p>
        {b.detail && <p className="mt-0.5 text-xs leading-relaxed text-ink-muted">{b.detail}</p>}
      </div>
      {fix.to ? (
        <Link to={fix.to} className="inline-flex h-8 shrink-0 items-center gap-1 rounded-md px-2.5 text-xs font-medium text-brand hover:bg-brand/8">
          {fix.label} <IconArrowRight size={12} />
        </Link>
      ) : (
        <Button
          size="sm"
          variant="ghost"
          className="shrink-0 !text-brand"
          iconRight={<IconArrowRight size={12} />}
          onClick={() => (fix.action ? fix.action() : fix.step && goTo(fix.step))}
        >
          {fix.label}
        </Button>
      )}
    </li>
  );
}

function Section({ label, step, goTo, children }: { label: string; step: StepId; goTo: (s: StepId) => void; children: ReactNode }) {
  return (
    <div className="grid grid-cols-[5.5rem_minmax(0,1fr)_auto] items-start gap-3 px-5 py-3.5 sm:grid-cols-[7rem_minmax(0,1fr)_auto]">
      <dt className="text-xs font-medium text-ink-muted">{label}</dt>
      <dd className="min-w-0">{children}</dd>
      <button type="button" onClick={() => goTo(step)} className="rounded text-xs font-medium text-brand hover:underline">
        Edit
      </button>
    </div>
  );
}
