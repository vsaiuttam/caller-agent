/**
 * What the extractor read off a transcript.
 *
 * Shared by both rehearsal modes — a scripted persona run and a live
 * microphone call produce the same `Outcome`, and reading them side by side
 * is only useful if they are laid out identically.
 */

import type { Outcome } from "../api";
import { IconShield } from "./icons";
import { Card, CardHeader } from "./ui";

export default function OutcomeCard({
  outcome,
  subtitle = "The same model and prompt a real call would use, on this transcript.",
  footnotes = [],
}: {
  outcome: Outcome;
  subtitle?: string;
  footnotes?: string[];
}) {
  return (
    <Card>
      <CardHeader title="What the extractor read" subtitle={subtitle} />
      <div className="space-y-4 p-5">
        <p className="text-sm leading-relaxed text-ink-secondary">{outcome.summary}</p>

        {outcome.needs_human_review && (
          <div className="rounded-lg border border-warning/35 bg-warning/8 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-xs font-medium text-warning">
              <IconShield size={13} /> Flagged for review
            </p>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
              {outcome.review_reason ||
                "The extractor was not confident enough to write this through."}
            </p>
          </div>
        )}

        {outcome.collected.length > 0 ? (
          <div className="overflow-x-auto">
            <table className="w-full text-left text-sm">
              <thead className="text-xs uppercase tracking-wide text-ink-muted">
                <tr className="border-b border-[var(--surface-border)]">
                  <th className="pb-2 pr-4 font-medium">Field</th>
                  <th className="pb-2 pr-4 font-medium">Value</th>
                  <th className="pb-2 font-medium">Source</th>
                </tr>
              </thead>
              <tbody>
                {outcome.collected.map((f) => (
                  <tr key={f.name} className="border-b border-[var(--surface-border)]-soft last:border-0">
                    <td className="py-2 pr-4 text-ink-secondary">{f.name}</td>
                    <td className="py-2 pr-4 font-medium">{f.value}</td>
                    <td className="py-2 text-xs text-ink-muted">
                      {/* Inferred values are the ones worth checking — they
                          were never actually said out loud. */}
                      {f.verbatim ? "Said on the call" : "Inferred"}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">Nothing was collected on this call.</p>
        )}

        {outcome.appointment && (
          <div className="rounded-lg border border-good/30 bg-good/8 px-3 py-2.5 text-xs">
            <p className="font-medium text-good">Appointment agreed</p>
            <p className="mt-1 text-ink-secondary">
              {outcome.appointment.starts_at_local} ({outcome.appointment.timezone}) ·{" "}
              {outcome.appointment.duration_minutes} min · {outcome.appointment.subject}
            </p>
          </div>
        )}

        {footnotes.length > 0 && (
          <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-[var(--surface-border)] pt-3 text-[11px] text-ink-muted">
            {footnotes.map((note) => (
              <span key={note}>{note}</span>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
