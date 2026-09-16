/**
 * Two views of the same scorecard: editing one, and reading a result.
 *
 * `ScorecardEditor` builds the criteria a campaign is judged on.
 * `ScorecardResult` shows how one call rated against them, with the evidence.
 *
 * The evidence is the part that earns its space. A score nobody can check is a
 * score nobody trusts, and the first question anyone asks about a rejected
 * candidate is "why" — so every rating carries the line from the transcript it
 * came from, and a rating with no evidence is shown as never-covered rather
 * than dressed up as a judgement.
 */

import type { CriterionScore, Qualification, ScoreCriterion } from "../api";
import { IconCheck, IconClose, IconShield } from "./icons";
import { Card, CardHeader, ScoreBadge, inputClass } from "./ui";

// ---------------------------------------------------------------------------
// Editing
// ---------------------------------------------------------------------------

export function ScorecardEditor({
  value,
  onChange,
  disabled = false,
}: {
  value: ScoreCriterion[];
  onChange: (next: ScoreCriterion[]) => void;
  disabled?: boolean;
}) {
  const update = (index: number, patch: Partial<ScoreCriterion>) =>
    onChange(value.map((c, i) => (i === index ? { ...c, ...patch } : c)));

  const add = () =>
    onChange([...value, { name: "", description: "", weight: 3, knockout: false }]);

  const remove = (index: number) => onChange(value.filter((_, i) => i !== index));

  return (
    <div className="space-y-2.5">
      {value.length === 0 && (
        <p className="text-xs leading-relaxed text-ink-muted">
          Nothing scored yet. Add criteria to turn this campaign's calls into a
          ranked list — screening candidates or qualifying leads. Leave it empty
          for informational calls like reminders and confirmations.
        </p>
      )}

      {value.map((criterion, index) => (
        <div key={index} className="rounded-lg border border-white/10 px-3 py-2.5">
          <div className="flex items-start gap-2">
            <input
              value={criterion.name}
              onChange={(e) => update(index, { name: e.target.value })}
              placeholder="Criterion, e.g. Notice period"
              disabled={disabled}
              className="min-w-0 flex-1 rounded-md border border-white/10 bg-surface px-2 py-1 text-sm outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/15"
            />
            <button
              type="button"
              onClick={() => remove(index)}
              disabled={disabled}
              aria-label={`Remove ${criterion.name || "criterion"}`}
              className="mt-1 text-ink-muted transition hover:text-critical"
            >
              <IconClose size={14} />
            </button>
          </div>

          <input
            value={criterion.description}
            onChange={(e) => update(index, { description: e.target.value })}
            placeholder="What good looks like — how you'd brief a person"
            disabled={disabled}
            className="mt-1.5 w-full rounded-md border border-white/10 bg-surface px-2 py-1 text-xs outline-none transition focus:border-brand focus:ring-2 focus:ring-brand/15"
          />

          <div className="mt-2 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 text-[11px] text-ink-secondary">
              Weight
              <select
                value={criterion.weight}
                onChange={(e) => update(index, { weight: Number(e.target.value) })}
                disabled={disabled}
                className="rounded border border-white/10 bg-surface px-1.5 py-0.5 text-[11px]"
              >
                {[1, 2, 3, 4, 5].map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex cursor-pointer items-center gap-1.5 text-[11px] text-ink-secondary">
              <input
                type="checkbox"
                checked={criterion.knockout}
                onChange={(e) => update(index, { knockout: e.target.checked })}
                disabled={disabled}
                className="accent-[var(--color-brand)]"
              />
              Required
            </label>

            {criterion.knockout && (
              <span className="text-[11px] text-critical">
                Failing this disqualifies, whatever else the call showed
              </span>
            )}
          </div>

          {/* The trap this catches is a real one, found on a live call: a
              required criterion reading "has the experience the role requires"
              gave the model no number, so it passed a candidate with two years
              against a five-year bar. A vague requirement doesn't fail safe —
              it approves everyone. */}
          {criterion.knockout && !hasThreshold(criterion.description) && (
            <p className="mt-2 rounded-md border border-warning/35 bg-warning/8 px-2 py-1.5 text-[11px] leading-relaxed text-ink-secondary">
              <span className="font-medium text-warning">Say what the bar is.</span>{" "}
              A required criterion with no concrete standard — a number of years,
              a budget, a location — can't be judged, so it will be held for
              review instead of rejecting anyone.
            </p>
          )}
        </div>
      ))}

      <button
        type="button"
        onClick={add}
        disabled={disabled}
        className={`${inputClass} mt-0 cursor-pointer border-dashed text-left text-xs text-ink-secondary transition hover:border-brand hover:text-ink disabled:cursor-not-allowed disabled:opacity-40`}
      >
        + Add criterion
      </button>
    </div>
  );
}

/**
 * A rough test for "this description states a checkable bar".
 *
 * Deliberately shallow — it looks for a digit or a currency amount, which is
 * what almost every real threshold contains. It's a nudge, not a validator:
 * blocking on it would be wrong (some genuine requirements are qualitative)
 * and a false negative here costs nothing but an extra line of advice.
 */
function hasThreshold(description: string): boolean {
  return /\d/.test(description) || /[₹$€£]/.test(description);
}

// ---------------------------------------------------------------------------
// Reading a result
// ---------------------------------------------------------------------------

const RATING_LABEL = [
  "Never came up",
  "Falls short",
  "Partially meets",
  "Meets",
  "Exceeds",
];

export function ScorecardResult({
  scores,
  qualification,
}: {
  scores: CriterionScore[];
  qualification: Qualification | null;
}) {
  if (!qualification || qualification.band === "not_assessed") return null;

  return (
    <Card>
      <CardHeader
        title="Scorecard"
        subtitle={qualification.reasons}
        action={
          <ScoreBadge score={qualification.score} band={qualification.band} />
        }
      />

      <div className="p-5">
        {qualification.band === "disqualified" && (
          <div className="mb-4 rounded-lg border border-critical/30 bg-critical/6 px-3 py-2.5">
            <p className="flex items-center gap-1.5 text-xs font-medium text-critical">
              <IconShield size={13} /> Failed a required criterion
            </p>
            <p className="mt-1 text-xs leading-relaxed text-ink-secondary">
              {qualification.disqualified_by}
            </p>
          </div>
        )}

        {scores.length === 0 ? (
          <p className="text-xs text-ink-muted">No criteria were rated on this call.</p>
        ) : (
          <div className="space-y-2.5">
            {scores.map((entry) => {
              const covered = entry.rating > 0;
              return (
                <div
                  key={entry.name}
                  className="border-b border-white/10-soft pb-2.5 last:border-0 last:pb-0"
                >
                  <div className="flex items-baseline justify-between gap-3">
                    <span className="text-sm font-medium">{entry.name}</span>
                    <span
                      className={`shrink-0 text-xs ${
                        !covered
                          ? "text-ink-muted"
                          : entry.met
                            ? "text-good"
                            : "text-critical"
                      }`}
                    >
                      {covered && entry.met && (
                        <IconCheck size={12} className="mr-1 inline" />
                      )}
                      {RATING_LABEL[entry.rating] ?? "—"}
                    </span>
                  </div>

                  {entry.evidence ? (
                    // Quoted, because this is what the person said and the
                    // distinction between their words and the model's summary
                    // is the whole basis for trusting the rating.
                    <p className="mt-1 border-l-2 border-white/10 pl-2.5 text-xs italic leading-relaxed text-ink-secondary">
                      “{entry.evidence}”
                    </p>
                  ) : (
                    <p className="mt-1 text-xs text-ink-muted">
                      Not established on the call.
                    </p>
                  )}
                </div>
              );
            })}
          </div>
        )}
      </div>
    </Card>
  );
}
