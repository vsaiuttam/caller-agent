"""Turn per-criterion ratings into one number a person can sort by.

Pure functions, no model calls, no I/O — the same shape as `scheduler.py`, and
for the same reason: this decides which candidates get interviewed and which
leads get worked, so it has to be inspectable and it has to give the same
answer twice.

Why not ask the model for the score directly? Three reasons, all of which show
up in practice:

  - **Comparability.** A model asked for "a score out of 100" drifts. Two
    identical calls a month apart score differently, and a ranked queue built
    on that is quietly worthless.
  - **Re-scoring.** Weights change once you have seen fifty calls. Deriving the
    score here means yesterday's calls can be re-ranked under today's weights
    without re-running extraction against a paid API.
  - **Argument.** When a hiring manager asks why a candidate scored 62, the
    answer is arithmetic over rated criteria with quotes attached, not "the
    model said so".

The model's job is the part only it can do: reading a transcript and judging
whether someone met a criterion, with evidence. The arithmetic is ours.
"""

from __future__ import annotations

from .models import (
    CallContext,
    CallOutcome,
    CriterionScore,
    Qualification,
    QualificationBand,
    ScoreCriterion,
)

# Ratings run 0-4. Anything not addressed on the call scores 0 and drags the
# result down, which is deliberate: a criterion nobody got to is not a pass.
MAX_RATING = 4

# Band thresholds, in points. Chosen so "meets every criterion" (rating 3
# throughout = 75) lands at the top of `possible` and tips into `strong` as
# soon as anything is exceeded. A queue where everything is "strong" sorts
# nothing.
STRONG = 75
POSSIBLE = 50
WEAK = 25


def qualify(
    criteria: list[ScoreCriterion], scores: list[CriterionScore]
) -> Qualification:
    """Weighted verdict for one call.

    Criteria the model failed to rate are treated as unrated rather than as
    zero — a missing entry is our bug or a model slip, and neither is evidence
    about the person. Criteria it rated but the campaign no longer defines are
    ignored, so removing a criterion re-scores cleanly.
    """
    if not criteria:
        return Qualification(
            band=QualificationBand.NOT_ASSESSED,
            reasons="This campaign scores nothing — the call was informational.",
        )

    by_name = {s.name.strip().lower(): s for s in scores}
    unverified: list[str] = []

    # A failed knockout ends it. Reported before the arithmetic because the
    # number is irrelevant once someone is out on a hard requirement, and a
    # disqualified person shown as "71" invites someone to argue with it.
    for criterion in criteria:
        if not criterion.knockout:
            continue
        score = by_name.get(criterion.name.strip().lower())
        if score is None:
            continue

        # Rating 0 means the call never established it — which is not the same
        # as failing it. Disqualifying on a question nobody asked would reject
        # good candidates for a prompt's shortcoming, invisibly and at scale.
        # It is held for a human instead.
        if score.rating == 0:
            unverified.append(criterion.name)
            continue

        if not score.met:
            return Qualification(
                score=0,
                band=QualificationBand.DISQUALIFIED,
                disqualified_by=criterion.name,
                reasons=(
                    f"Did not meet the required criterion “{criterion.name}”"
                    + (f": {score.evidence}" if score.evidence else ".")
                ),
            )

    earned = 0
    possible = 0
    rated = 0
    unaddressed: list[str] = []

    for criterion in criteria:
        score = by_name.get(criterion.name.strip().lower())
        if score is None:
            continue  # never rated; excluded from the denominator entirely
        rated += 1
        possible += criterion.weight * MAX_RATING
        earned += criterion.weight * max(0, min(MAX_RATING, score.rating))
        if score.rating == 0:
            unaddressed.append(criterion.name)

    if not rated or possible == 0:
        return Qualification(
            band=QualificationBand.NOT_ASSESSED,
            reasons="Nothing on the scorecard was covered on this call.",
        )

    points = round(100 * earned / possible)
    band = _band(points)

    # A required criterion the call never established caps the verdict. Calling
    # someone "strong" on a scorecard whose hard requirement was never checked
    # is precisely the confident-but-wrong answer this system is built to avoid.
    if unverified and band is QualificationBand.STRONG:
        band = QualificationBand.POSSIBLE

    return Qualification(
        score=points,
        band=band,
        reasons=_explain(points, rated, len(criteria), unaddressed, unverified),
    )


def _band(points: int) -> QualificationBand:
    if points >= STRONG:
        return QualificationBand.STRONG
    if points >= POSSIBLE:
        return QualificationBand.POSSIBLE
    if points >= WEAK:
        return QualificationBand.WEAK
    return QualificationBand.NOT_ASSESSED if points == 0 else QualificationBand.WEAK


def _explain(
    points: int,
    rated: int,
    total: int,
    unaddressed: list[str],
    unverified: list[str],
) -> str:
    """One sentence a human can act on without opening the transcript."""
    parts = [f"Scored {points} across {rated} of {total} criteria."]
    if unverified:
        # Loudest, because it is the one that should stop someone acting on the
        # number: a hard requirement went unchecked.
        parts.append(
            f"Required criteria never established: {', '.join(unverified)}. Confirm before proceeding."
        )
    if unaddressed:
        listed = ", ".join(unaddressed[:3])
        more = f" and {len(unaddressed) - 3} more" if len(unaddressed) > 3 else ""
        # Called out because it is the difference between "they are weak" and
        # "the call never got there" — the second is fixable with a better
        # prompt, and blaming the person for it would hide that.
        parts.append(f"Never covered on the call: {listed}{more}.")
    return " ".join(parts)


def qualify_outcome(context: CallContext, outcome: CallOutcome) -> Qualification:
    """Score a freshly extracted outcome against its campaign's criteria."""
    return qualify(context.scorecard, outcome.scores)


def rescore(criteria: list[ScoreCriterion], stored: list[dict]) -> Qualification:
    """Re-run scoring over ratings already on disk, under current weights.

    The reason the ratings are stored per criterion rather than as a single
    number: change a weight and every past call can be re-ranked for free.
    """
    return qualify(criteria, [CriterionScore.model_validate(s) for s in stored])
