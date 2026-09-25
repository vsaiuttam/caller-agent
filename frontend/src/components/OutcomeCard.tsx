/**
 * What the extractor read off a transcript.
 *
 * Shared by every rehearsal mode — a scripted persona run, a live microphone
 * call and a real test call produce the same `Outcome`, and reading them side
 * by side is only useful if they are laid out identically.
 */

import type { Outcome } from "../api";
import { IconCalendar, IconShield } from "./icons";
import { Card, CardHeader, DispositionBadge, SentimentBadge } from "./ui";

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
      <CardHeader
        title="What the extractor read"
        subtitle={subtitle}
        action={
          <>
            <SentimentBadge value={outcome.sentiment} title={outcome.sentiment_reason} />
            <DispositionBadge value={outcome.disposition} />
          </>
        }
      />
      <div className="space-y-4 p-5">
        <p className="text-sm leading-relaxed text-ink">{outcome.summary}</p>

        {outcome.needs_human_review && (
          <div className="rounded-lg border border-warning/30 bg-warning/8 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-xs font-medium text-warning">
              <IconShield size={13} /> Held for review
            </p>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
              {outcome.review_reason || "The extractor was not confident enough to write this through."}
            </p>
          </div>
        )}

        {outcome.appointment && (
          <div className="rounded-lg border border-good/25 bg-good/6 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-xs font-medium text-good">
              <IconCalendar size={13} /> Appointment agreed
            </p>
            <p className="mt-1 text-sm font-medium text-ink">{outcome.appointment.subject}</p>
            <p className="tnum mt-0.5 text-xs text-ink-secondary">
              {outcome.appointment.starts_at_local} ({outcome.appointment.timezone}) ·{" "}
              {outcome.appointment.duration_minutes} min
            </p>
            {outcome.appointment.notes && <p className="mt-1 text-xs text-ink-muted">{outcome.appointment.notes}</p>}
          </div>
        )}

        {outcome.collected.length > 0 ? (
          <div className="overflow-x-auto rounded-lg border border-line">
            <table className="data-table">
              <thead>
                <tr>
                  <th>Field</th>
                  <th>Value</th>
                  <th>Source</th>
                </tr>
              </thead>
              <tbody>
                {outcome.collected.map((f) => (
                  <tr key={f.name}>
                    <td className="text-ink-secondary">{f.name}</td>
                    <td className="font-medium text-ink">{f.value}</td>
                    <td className="text-xs">
                      {/* Inferred values are the ones worth checking — they
                          were never actually said out loud. */}
                      {f.verbatim ? (
                        <span className="text-ink-muted">Said on the call</span>
                      ) : (
                        <span className="text-warning">Inferred</span>
                      )}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        ) : (
          <p className="text-xs text-ink-muted">Nothing was collected on this call.</p>
        )}

        {footnotes.length > 0 && (
          <div className="flex flex-wrap gap-x-5 gap-y-1 border-t border-line pt-3 text-2xs text-ink-muted">
            {footnotes.map((note) => (
              <span key={note}>{note}</span>
            ))}
          </div>
        )}
      </div>
    </Card>
  );
}
