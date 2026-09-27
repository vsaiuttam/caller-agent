/**
 * "Why isn't it calling?" The dialler's state for a campaign, from
 * GET /api/campaigns/{id}/dialer: a pill for lists, a card with the reason,
 * progress and blockers (each with its fix) for the campaign page.
 */

import { useEffect, useState } from "react";
import { Link } from "react-router-dom";
import { api, isMissing, type Campaign, type CampaignStatus, type DialerState, type DialerStatus } from "../../api";
import { formatDateTime } from "../../format";
import { IconAlert, IconArrowRight, IconClock } from "../icons";
import { Badge, Card, Skeleton, StatusBadge, cx, type Tone } from "../ui";

export const DIALER_META: Record<DialerState, { label: string; tone: Tone; pulse?: boolean }> = {
  dialing: { label: "Dialling", tone: "good", pulse: true },
  waiting_window: { label: "Waiting for window", tone: "info" },
  paused: { label: "Paused", tone: "warning" },
  draft: { label: "Draft", tone: "neutral" },
  completed: { label: "Completed", tone: "neutral" },
  blocked: { label: "Blocked", tone: "critical" },
  asleep_risk: { label: "May be asleep", tone: "warning" },
};

/** States the campaign's own status already answers, without asking the server. */
const LOCAL: Partial<Record<CampaignStatus, DialerState>> = { draft: "draft", paused: "paused", completed: "completed" };

type Result = { status: DialerStatus | null; loading: boolean; unavailable: boolean; reload: () => void };

/**
 * The dialler state. Running campaigns are asked (and re-asked every 20s);
 * drafts, paused and completed campaigns are answered locally unless `always`.
 */
export function useDialer(campaign: Pick<Campaign, "id" | "status" | "dialer"> | null, always = false): Result {
  const [status, setStatus] = useState<DialerStatus | null>(campaign?.dialer ?? null);
  const [loading, setLoading] = useState(false);
  const [unavailable, setUnavailable] = useState(false);
  const [nonce, setNonce] = useState(0);
  const ask = !!campaign && !campaign.dialer && (always || campaign.status === "running");

  useEffect(() => {
    if (!campaign || !ask) {
      setStatus(campaign?.dialer ?? null);
      return;
    }
    let cancelled = false;
    const load = () => {
      if (document.hidden) return;
      setLoading(true);
      api
        .dialer(campaign.id)
        .then((s) => !cancelled && setStatus(s))
        .catch((err) => {
          if (!cancelled && isMissing(err)) setUnavailable(true);
        })
        .finally(() => !cancelled && setLoading(false));
    };
    load();
    const id = window.setInterval(load, 20_000);
    return () => {
      cancelled = true;
      window.clearInterval(id);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [campaign?.id, campaign?.status, ask, nonce]);

  return { status, loading, unavailable, reload: () => setNonce((n) => n + 1) };
}

export function DialerPill({ campaign, status }: { campaign: Pick<Campaign, "status">; status: DialerStatus | null }) {
  const state: DialerState | undefined = status?.state ?? LOCAL[campaign.status];
  if (!state) return <StatusBadge status={campaign.status} />;
  const meta = DIALER_META[state];
  return (
    <Badge tone={meta.tone} dot pulse={meta.pulse} title={status?.reason}>
      {meta.label}
    </Badge>
  );
}

/** Where a blocker sentence gets fixed. The server writes plain sentences, so match loosely. */
export function fixFor(blocker: string, campaignId: string): { label: string; to: string } | null {
  const b = blocker.toLowerCase();
  if (/telephon|twilio|telnyx|phone number/.test(b)) return { label: "Set up telephony", to: "/app/integrations?tab=telephony" };
  if (/provider|model|llm|api key/.test(b)) return { label: "Add a provider", to: "/app/ai-models?add=1" };
  if (/contact/.test(b)) return { label: "Add contacts", to: `/app/campaigns/${campaignId}?tab=contacts` };
  if (/window|hour|day|schedule/.test(b)) return { label: "Change the schedule", to: `/app/campaigns/${campaignId}/edit?step=schedule` };
  if (/sms|whatsapp|messag/.test(b)) return { label: "Set up messaging", to: "/app/integrations?tab=messaging" };
  if (/budget|spend|cap/.test(b)) return { label: "Raise the spend cap", to: `/app/campaigns/${campaignId}/edit?step=schedule` };
  return null;
}

export function DialerCard({ campaign, dialer }: { campaign: Campaign; dialer: Result }) {
  const s = dialer.status;
  if (dialer.unavailable || (!s && !dialer.loading && campaign.status !== "running")) {
    // No dialler endpoint yet: say what we can from the campaign itself.
    return (
      <Card className="px-5 py-4">
        <div className="flex items-center gap-2.5">
          <StatusBadge status={campaign.status} />
          <p className="text-sm text-ink-secondary">
            {campaign.status === "running"
              ? "Calling inside each contact's window."
              : campaign.status === "draft"
                ? "Not launched yet."
                : campaign.status === "paused"
                  ? "Paused. No new calls are placed."
                  : "Finished."}
          </p>
        </div>
      </Card>
    );
  }
  if (!s) return <Skeleton className="h-28 rounded-xl" />;

  const meta = DIALER_META[s.state];
  const total = s.pending + s.in_progress + s.done + s.failed;
  const parts = [
    { label: "Done", value: s.done, className: "bg-good" },
    { label: "On the line", value: s.in_progress, className: "bg-brand" },
    { label: "Failed", value: s.failed, className: "bg-critical" },
    { label: "Waiting", value: s.pending, className: "bg-line-strong" },
  ];

  return (
    <Card className={cx("overflow-hidden", s.state === "blocked" && "border-critical/40")}>
      <div className="flex flex-wrap items-start gap-3 px-5 py-4">
        <span
          className={cx(
            "mt-0.5 flex h-9 w-9 shrink-0 items-center justify-center rounded-lg",
            meta.tone === "good" ? "bg-good/12 text-good" : meta.tone === "critical" ? "bg-critical/10 text-critical" : meta.tone === "warning" ? "bg-warning/12 text-warning" : "bg-subtle text-ink-muted",
          )}
        >
          {s.state === "blocked" || s.state === "asleep_risk" ? <IconAlert size={17} /> : <IconClock size={17} />}
        </span>
        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-center gap-2">
            <p className="text-sm font-semibold text-ink">Dialler</p>
            <DialerPill campaign={campaign} status={s} />
          </div>
          <p className="mt-1 text-sm leading-relaxed text-ink-secondary">{s.reason}</p>
          {s.next_window_start && s.state !== "dialing" && (
            <p className="mt-0.5 text-xs text-ink-muted">Next window opens {formatDateTime(s.next_window_start)}.</p>
          )}
        </div>
      </div>

      {total > 0 && (
        <div className="border-t border-line px-5 py-3.5">
          <div className="flex h-2 w-full gap-[2px] overflow-hidden rounded-full bg-subtle" role="img" aria-label={parts.map((p) => `${p.label} ${p.value}`).join(", ")}>
            {parts
              .filter((p) => p.value > 0)
              .map((p) => (
                <span key={p.label} className={cx("h-full transition-[flex-grow] duration-500", p.className)} style={{ flexGrow: p.value, flexBasis: 0 }} />
              ))}
          </div>
          <dl className="mt-2 flex flex-wrap gap-x-5 gap-y-1 text-xs">
            {parts.map((p) => (
              <div key={p.label} className="flex items-center gap-1.5">
                <span className={cx("h-2 w-2 rounded-sm", p.className)} aria-hidden />
                <dt className="text-ink-muted">{p.label}</dt>
                <dd className="tnum font-medium text-ink">{p.value.toLocaleString()}</dd>
              </div>
            ))}
          </dl>
        </div>
      )}

      {s.blockers.length > 0 && (
        <ul className="divide-y divide-line border-t border-line bg-critical/4">
          {s.blockers.map((b) => {
            const fix = fixFor(b, campaign.id);
            return (
              <li key={b} className="flex flex-wrap items-center justify-between gap-2 px-5 py-2.5 text-sm">
                <span className="flex items-center gap-2 text-ink">
                  <IconAlert size={13} className="shrink-0 text-critical" /> {b}
                </span>
                {fix && (
                  <Link to={fix.to} className="inline-flex items-center gap-1 text-xs font-medium text-brand hover:underline">
                    {fix.label} <IconArrowRight size={12} />
                  </Link>
                )}
              </li>
            );
          })}
        </ul>
      )}
    </Card>
  );
}
