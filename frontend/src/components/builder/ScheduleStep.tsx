import type { ReactNode } from "react";
import { Link } from "react-router-dom";
import { Card, CardHeader, Field, Input, Select, Switch } from "../ui";
import { chipClass } from "./AgentStep";
import { useBuilder } from "./context";
import { DAY_NAMES, hour } from "./draft";
import { PrecallSettings } from "./PrecallSettings";

const HOURS = Array.from({ length: 25 }, (_, h) => h);

export function ScheduleStep() {
  const { draft, setForm, health } = useBuilder();
  const f = draft.form;
  const days = f.calling_days;
  const setDays = (next: number[]) => setForm({ calling_days: [...new Set(next)].sort() });

  return (
    <div className="space-y-4">
      <Card>
        <CardHeader title="Calling window" subtitle="Evaluated in each contact's own timezone, so nobody is rung at night." />
        <div className="space-y-5 px-5 py-5">
          <div className="grid grid-cols-2 gap-3 sm:max-w-sm">
            <Field label="From">
              <Select value={f.calling_hours_start} onChange={(e) => setForm({ calling_hours_start: Number(e.target.value) })}>
                {HOURS.slice(0, 24).map((h) => (
                  <option key={h} value={h}>
                    {hour(h)}
                  </option>
                ))}
              </Select>
            </Field>
            <Field label="Until" error={f.calling_hours_end <= f.calling_hours_start ? "Must be after the start." : null}>
              <Select value={f.calling_hours_end} onChange={(e) => setForm({ calling_hours_end: Number(e.target.value) })}>
                {HOURS.slice(1).map((h) => (
                  <option key={h} value={h}>
                    {h === 24 ? "24:00 (midnight)" : hour(h)}
                  </option>
                ))}
              </Select>
            </Field>
          </div>

          <Field label="Days" group error={days.length === 0 ? "Pick at least one day." : null}>
            <div className="flex flex-wrap items-center gap-1.5">
              {[1, 2, 3, 4, 5, 6, 7].map((d) => {
                const on = days.includes(d);
                return (
                  <button key={d} type="button" aria-pressed={on} onClick={() => setDays(on ? days.filter((x) => x !== d) : [...days, d])} className={chipClass(on)}>
                    {DAY_NAMES[d]}
                  </button>
                );
              })}
              <span className="mx-1 h-5 w-px bg-line" aria-hidden />
              <button type="button" onClick={() => setDays([1, 2, 3, 4, 5])} className="text-xs font-medium text-brand hover:underline">
                Weekdays
              </button>
              <button type="button" onClick={() => setDays([1, 2, 3, 4, 5, 6, 7])} className="text-xs font-medium text-brand hover:underline">
                Every day
              </button>
            </div>
          </Field>

          <div className="grid grid-cols-1 gap-3 sm:grid-cols-3">
            <Field label="Attempts per contact" hint="Retries no-answers and busy lines.">
              <Input type="number" min={1} max={10} value={f.max_attempts} onChange={(e) => setForm({ max_attempts: clamp(e.target.value, 1, 10) })} className="tnum" />
            </Field>
            <Field label="Lines at once" hint="Calls placed in parallel.">
              <Input type="number" min={1} max={100} value={f.max_concurrent_calls} onChange={(e) => setForm({ max_concurrent_calls: clamp(e.target.value, 1, 100) })} className="tnum" />
            </Field>
            <Field label="Spend cap (USD)" optional hint="Pauses the campaign when model spend reaches it.">
              <Input
                type="number"
                min={0}
                placeholder="No cap"
                className="tnum"
                value={f.budget_usd ?? ""}
                onChange={(e) => setForm({ budget_usd: e.target.value === "" ? null : Math.max(0, Number(e.target.value)) })}
              />
            </Field>
          </div>
        </div>
      </Card>

      <PrecallSettings />

      <Card>
        <CardHeader title="After the call" subtitle="A thank-you with any booked appointment, or a missed-call note. Never after an opt-out." />
        <div className="space-y-4 px-5 py-5">
          <Switch
            checked={f.sms_followup}
            onChange={(v) => setForm({ sms_followup: v })}
            label="SMS follow-up"
            description={channelNote(health?.checks.sms, "SMS")}
          />
          <Switch
            checked={f.whatsapp_followup}
            onChange={(v) => setForm({ whatsapp_followup: v })}
            label="WhatsApp follow-up"
            description={channelNote(health?.checks.whatsapp, "WhatsApp")}
          />
          <Field label="Webhook URL" optional hint="POSTed once per completed call, signed when WEBHOOK_SIGNING_SECRET is set.">
            <Input type="url" placeholder="https://…" value={f.webhook_url ?? ""} onChange={(e) => setForm({ webhook_url: e.target.value || null })} />
          </Field>
        </div>
      </Card>
    </div>
  );
}

function channelNote(configured: boolean | undefined, label: string): ReactNode {
  if (configured !== false) return undefined;
  return (
    <>
      {label} isn't set up on this server, so nothing is sent.{" "}
      <Link to="/app/integrations?tab=messaging" className="font-medium text-brand hover:underline">
        Set up {label}
      </Link>
    </>
  );
}

function clamp(text: string, min: number, max: number): number {
  const n = Math.round(Number(text));
  return Number.isNaN(n) ? min : Math.min(max, Math.max(min, n));
}
