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
import { IconCheck, IconClose, IconPlus, IconShield } from "./icons";
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
        <div key={index} className="rounded-lg border border-line bg-subtle/40 p-3">
          <div className="flex items-start gap-2">
            <input
              value={criterion.name}
              onChange={(e) => update(index, { name: e.target.value })}
              placeholder="Criterion, e.g. Notice period"
              aria-label="Criterion name"
              disabled={disabled}
              className={`${inputClass} h-8 min-w-0 flex-1`}
            />
            <button
              type="button"
              onClick={() => remove(index)}
              disabled={disabled}
              aria-label={`Remove ${criterion.name || "criterion"}`}
              className="mt-1 rounded-md p-1 text-ink-muted transition-colors hover:bg-critical/10 hover:text-critical"
            >
              <IconClose size={14} />
            </button>
          </div>

          <input
            value={criterion.description}
            onChange={(e) => update(index, { description: e.target.value })}
            placeholder="What good looks like — how you'd brief a person"
            aria-label="What good looks like"
            disabled={disabled}
            className={`${inputClass} mt-2 h-8 text-xs`}
          />

          <div className="mt-2.5 flex flex-wrap items-center gap-3">
            <label className="flex items-center gap-1.5 text-2xs font-medium text-ink-secondary">
              Weight
              <select
                value={criterion.weight}
                onChange={(e) => update(index, { weight: Number(e.target.value) })}
                disabled={disabled}
                className="h-7 rounded-md border border-line-strong bg-surface px-1.5 text-2xs text-ink"
              >
                {[1, 2, 3, 4, 5].map((w) => (
                  <option key={w} value={w}>
                    {w}
                  </option>
                ))}
              </select>
            </label>

            <label className="flex cursor-pointer items-center gap-1.5 text-2xs font-medium text-ink-secondary">
              <input
                type="checkbox"
                checked={criterion.knockout}
                onChange={(e) => update(index, { knockout: e.target.checked })}
                disabled={disabled}
                className="h-3.5 w-3.5 accent-[var(--color-brand)]"
              />
              Required
            </label>

            {criterion.knockout && (
              <span className="text-2xs text-critical">
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
            <p className="mt-2 rounded-md border border-warning/30 bg-warning/8 px-2.5 py-1.5 text-2xs leading-relaxed text-ink-secondary">
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
        className="flex h-9 w-full items-center gap-1.5 rounded-md border border-dashed border-line-strong px-3 text-left text-xs font-medium text-ink-secondary transition-colors hover:border-brand hover:text-ink disabled:cursor-not-allowed disabled:opacity-40"
      >
        <IconPlus size={14} /> Add criterion
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
          <div className="mb-4 rounded-lg border border-critical/25 bg-critical/6 px-3 py-2.5">
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
          <div className="space-y-3">
            {scores.map((entry) => {
              const covered = entry.rating > 0;
              return (
                <div key={entry.name} className="border-b border-line pb-3 last:border-0 last:pb-0">
                  <div className="flex items-center justify-between gap-3">
                    <span className="text-sm font-medium text-ink">{entry.name}</span>
                    <span
                      className={`flex shrink-0 items-center gap-2 text-xs ${
                        !covered ? "text-ink-muted" : entry.met ? "text-good" : "text-critical"
                      }`}
                    >
                      {/* Four pips: the rating at a glance, the label for certainty. */}
                      <span className="flex gap-0.5" aria-hidden>
                        {[1, 2, 3, 4].map((pip) => (
                          <span
                            key={pip}
                            className={`h-1.5 w-3 rounded-full ${pip <= entry.rating ? "bg-current" : "bg-line-strong"}`}
                          />
                        ))}
                      </span>
                      {covered && entry.met && <IconCheck size={12} />}
                      {RATING_LABEL[entry.rating] ?? "—"}
                    </span>
                  </div>

                  {entry.evidence ? (
                    // Quoted, because this is what the person said and the
                    // distinction between their words and the model's summary
                    // is the whole basis for trusting the rating.
                    <p className="mt-1.5 border-l-2 border-line-strong pl-2.5 text-xs italic leading-relaxed text-ink-secondary">
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
