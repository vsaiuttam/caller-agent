/**
 * Pre-call heads-up (§6): a short SMS or WhatsApp a few minutes before the
 * agent rings, so the call isn't a surprise. Blocked, with the reason and a
 * link to the fix, when the channel isn't set up on the server.
 */

import { useRef } from "react";
import { Link } from "react-router-dom";
import type { PrecallChannel } from "../../api";
import { IconAlert } from "../icons";
import { Card, CardHeader, Field, Input, Segmented, Switch, Textarea, cx } from "../ui";
import { useBuilder } from "./context";
import { DEFAULT_PRECALL } from "./draft";

const VARIABLES = [
  { name: "name", hint: "The contact's first name", sample: "Ananya" },
  { name: "company", hint: "Your company (the campaign name if unset)", sample: "" },
  { name: "minutes", hint: "Minutes until the call", sample: "" },
  { name: "agent", hint: "The agent's name", sample: "Priya" },
];

const LEADS = [5, 10, 15, 30];
const CHANNEL_LABEL: Record<PrecallChannel, string> = { sms: "SMS", whatsapp: "WhatsApp" };

export function PrecallSettings() {
  const { draft, setForm, health } = useBuilder();
  const f = draft.form;
  const box = useRef<HTMLTextAreaElement>(null);
  const channel: PrecallChannel = f.precall_channel === "whatsapp" ? "whatsapp" : "sms";
  const message = f.precall_message ?? DEFAULT_PRECALL;
  const lead = f.precall_lead_minutes ?? 10;

  // Unknown health (still loading) counts as configured, so nothing flickers.
  const ready: Record<PrecallChannel, boolean> = {
    sms: health ? !!health.checks.sms : true,
    whatsapp: health ? !!health.checks.whatsapp : true,
  };
  const none = !ready.sms && !ready.whatsapp;
  const channelMissing = !ready[channel];

  const insert = (name: string) => {
    const el = box.current;
    const token = `{${name}}`;
    if (!el) {
      setForm({ precall_message: message + token });
      return;
    }
    const start = el.selectionStart ?? message.length;
    const end = el.selectionEnd ?? message.length;
    const next = message.slice(0, start) + token + message.slice(end);
    setForm({ precall_message: next });
    requestAnimationFrame(() => {
      el.focus();
      el.setSelectionRange(start + token.length, start + token.length);
    });
  };

  const preview = message
    .replaceAll("{name}", "Ananya")
    .replaceAll("{company}", f.name.trim() || "your company")
    .replaceAll("{minutes}", String(lead))
    .replaceAll("{agent}", "Priya");
  const unknown = [...message.matchAll(/\{(\w+)\}/g)].map((m) => m[1]).filter((n) => !VARIABLES.some((v) => v.name === n));
  const unicode = /[^\u0000-\u007f]/.test(preview);
  const perPart = unicode ? 70 : 160;
  const parts = Math.max(1, Math.ceil(preview.length / perPart));
  const noOptOut = !/stop/i.test(message);

  return (
    <Card>
      <CardHeader title="Heads-up before the call" subtitle="A short message a few minutes before the agent rings, so the call is expected. Retries don't send another within 12 hours." />
      <div className="space-y-5 px-5 py-5">
        <Switch
          checked={!!f.precall_enabled}
          disabled={none && !f.precall_enabled}
          onChange={(on) => setForm({ precall_enabled: on, ...(on && channelMissing && ready.whatsapp ? { precall_channel: "whatsapp" } : {}) })}
          label="Send a heads-up message"
          description={
            none ? (
              <span className="text-ink-secondary">
                Neither SMS nor WhatsApp is set up on this server, so there's nothing to send it with.{" "}
                <Link to="/app/integrations?tab=messaging" className="font-medium text-brand hover:underline">
                  Set up messaging
                </Link>
              </span>
            ) : (
              "Sent through the same numbers as follow-ups."
            )
          }
        />

        {f.precall_enabled && (
          <>
            <div className="grid gap-4 sm:grid-cols-2">
              <Field label="Channel" group>
                <Segmented
                  label="Channel"
                  value={channel}
                  onChange={(v) => setForm({ precall_channel: v })}
                  options={(["sms", "whatsapp"] as const).map((c) => ({
                    value: c,
                    label: (
                      <>
                        {CHANNEL_LABEL[c]}
                        {!ready[c] && <IconAlert size={11} className="text-warning" />}
                      </>
                    ),
                    title: ready[c] ? undefined : `${CHANNEL_LABEL[c]} isn't set up`,
                  }))}
                />
              </Field>
              <Field label="How long before the call" group hint="2 to 240 minutes.">
                <div className="flex flex-wrap items-center gap-2">
                  <Input
                    type="number"
                    min={2}
                    max={240}
                    value={lead}
                    onChange={(e) => setForm({ precall_lead_minutes: Math.min(240, Math.max(2, Math.round(Number(e.target.value) || 2))) })}
                    className="tnum w-20"
                    aria-label="Minutes before the call"
                  />
                  <span className="text-xs text-ink-muted">min</span>
                  {LEADS.map((m) => (
                    <button
                      key={m}
                      type="button"
                      onClick={() => setForm({ precall_lead_minutes: m })}
                      className={cx("h-7 rounded-md px-2 text-xs font-medium transition-colors", lead === m ? "bg-subtle-strong text-ink" : "text-ink-muted hover:bg-subtle hover:text-ink")}
                    >
                      {m}
                    </button>
                  ))}
                </div>
              </Field>
            </div>

            {channelMissing && (
              <p role="alert" className="flex items-start gap-1.5 rounded-lg border border-critical/25 bg-critical/6 px-3 py-2 text-xs text-ink-secondary">
                <IconAlert size={13} className="mt-0.5 shrink-0 text-critical" />
                <span>
                  {CHANNEL_LABEL[channel]} isn't set up on this server, so launching is blocked until it is or you switch channel.{" "}
                  <Link to="/app/integrations?tab=messaging" className="font-medium text-brand hover:underline">
                    Set up {CHANNEL_LABEL[channel]}
                  </Link>
                </span>
              </p>
            )}

            <Field label="Message" error={unknown.length ? `Unknown variable${unknown.length > 1 ? "s" : ""}: ${unknown.map((u) => `{${u}}`).join(", ")}` : null}>
              <Textarea ref={box} value={message} onChange={(e) => setForm({ precall_message: e.target.value })} className="min-h-20" />
            </Field>
            <div className="-mt-3 flex flex-wrap items-center gap-1.5">
              <span className="text-2xs text-ink-muted">Insert:</span>
              {VARIABLES.map((v) => (
                <button
                  key={v.name}
                  type="button"
                  onClick={() => insert(v.name)}
                  title={v.hint}
                  className="h-6 rounded-md border border-line bg-subtle px-1.5 font-mono text-2xs text-ink-secondary transition-colors hover:border-line-strong hover:text-ink"
                >
                  {`{${v.name}}`}
                </button>
              ))}
              {message !== DEFAULT_PRECALL && (
                <button type="button" onClick={() => setForm({ precall_message: DEFAULT_PRECALL })} className="ml-auto text-2xs font-medium text-brand hover:underline">
                  Reset to default
                </button>
              )}
            </div>

            <div className="rounded-lg border border-line bg-subtle/50 px-4 py-3">
              <div className="flex items-baseline justify-between gap-2">
                <p className="text-2xs font-medium uppercase tracking-wider text-ink-muted">They'll receive</p>
                {channel === "sms" && (
                  <p className="tnum text-2xs text-ink-muted">
                    {preview.length} chars · {parts} SMS part{parts === 1 ? "" : "s"}
                  </p>
                )}
              </div>
              <p className="mt-1.5 text-sm leading-relaxed text-ink">{preview}</p>
              {noOptOut && <p className="mt-2 text-xs text-warning">Add an opt-out line, like “Reply STOP to opt out”.</p>}
            </div>

            <p className="text-xs leading-relaxed text-ink-muted">
              {channel === "sms"
                ? "In India, promotional and service SMS must match a DLT-registered template. Register this wording with your operator before launch, or messages may be dropped."
                : "Outside the WhatsApp Sandbox, business-initiated messages need a template approved by Meta. Use wording that matches an approved template."}
            </p>
          </>
        )}
      </div>
    </Card>
  );
}
