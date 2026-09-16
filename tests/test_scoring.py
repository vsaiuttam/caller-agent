"""Tests for qualification scoring.

This decides which candidates get interviewed and which leads get worked, so
the properties that matter are: a knockout is absolute, a weight actually
weighs, an unanswered criterion is not silently a pass, and the same input
gives the same number twice.

Runs standalone (`python tests/test_scoring.py`) or under pytest. No API key
and no network — none of this touches a model, which is the point of it.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from src.voiceagent.models import (  # noqa: E402
    CriterionScore,
    QualificationBand,
    ScoreCriterion,
)
from src.voiceagent.scoring import STRONG, qualify, rescore  # noqa: E402


def criterion(name: str, weight: int = 1, knockout: bool = False) -> ScoreCriterion:
    return ScoreCriterion(name=name, weight=weight, knockout=knockout)


def score(name: str, rating: int, met: bool = True, evidence: str = "said so") -> CriterionScore:
    return CriterionScore(name=name, rating=rating, met=met, evidence=evidence)


def test_no_scorecard_is_not_a_zero() -> None:
    """Most campaigns score nothing. That is 'not assessed', not 'terrible'.

    A delivery confirmation scoring 0 would sort below every failed candidate
    in a ranked queue and make the whole column meaningless.
    """
    result = qualify([], [])
    assert result.band is QualificationBand.NOT_ASSESSED
    assert result.score == 0


def test_a_failed_knockout_disqualifies_whatever_else_happened() -> None:
    """Someone who cannot do the job does not get a high score for interviewing well."""
    criteria = [
        criterion("Meets minimum experience", weight=5, knockout=True),
        criterion("Communication", weight=1),
    ]
    scores = [
        score("Meets minimum experience", rating=1, met=False, evidence="Two years, needs five"),
        score("Communication", rating=4),
    ]

    result = qualify(criteria, scores)

    assert result.band is QualificationBand.DISQUALIFIED
    assert result.disqualified_by == "Meets minimum experience"
    assert result.score == 0
    # The reason has to carry the evidence, or a recruiter has to open the
    # transcript to find out why somebody was cut.
    assert "Two years" in result.reasons


def test_an_unestablished_knockout_holds_rather_than_rejects() -> None:
    """A hard requirement nobody asked about must not reject the person.

    Found live: a criterion written as "has the experience the role requires"
    gave the model no threshold, so it passed a candidate with two years against
    a five-year bar. The prompt now tells it to rate 0 when the standard is
    missing — and rating 0 has to mean "not established", not "failed", or the
    fix would swap silent approvals for silent rejections, which is worse
    because nobody ever sees the candidates it drops.
    """
    criteria = [criterion("Meets minimum experience", weight=5, knockout=True)]
    scores = [score("Meets minimum experience", rating=0, met=False, evidence="")]

    result = qualify(criteria, scores)

    assert result.band is not QualificationBand.DISQUALIFIED
    assert "Confirm before proceeding" in result.reasons
    assert "Meets minimum experience" in result.reasons


def test_an_unestablished_knockout_caps_the_verdict() -> None:
    """Everything else can be perfect; it still isn't 'strong' if the bar went unchecked."""
    criteria = [
        criterion("Location workable", weight=1, knockout=True),
        criterion("Core skill depth", weight=5),
    ]
    scores = [
        score("Location workable", rating=0, met=False, evidence=""),
        score("Core skill depth", rating=4),
    ]

    result = qualify(criteria, scores)

    assert result.band is QualificationBand.POSSIBLE
    assert result.score >= STRONG  # the number is high; the verdict is held back


def test_a_met_knockout_does_not_disqualify() -> None:
    criteria = [criterion("Location workable", knockout=True), criterion("Depth", weight=3)]
    scores = [score("Location workable", rating=3), score("Depth", rating=3)]

    assert qualify(criteria, scores).band is not QualificationBand.DISQUALIFIED


def test_weights_actually_weigh() -> None:
    """Scoring well on what matters must beat scoring well on what doesn't."""
    criteria = [criterion("Core skill", weight=5), criterion("Nice to have", weight=1)]

    strong_where_it_counts = qualify(
        criteria, [score("Core skill", 4), score("Nice to have", 1)]
    )
    strong_where_it_doesnt = qualify(
        criteria, [score("Core skill", 1), score("Nice to have", 4)]
    )

    assert strong_where_it_counts.score > strong_where_it_doesnt.score


def test_an_unaddressed_criterion_is_not_a_pass_and_says_so() -> None:
    """Rating 0 means the call never got there — and the queue must show that.

    Otherwise a badly-prompted campaign looks like a batch of weak candidates,
    and the prompt never gets fixed.
    """
    criteria = [criterion("Budget"), criterion("Timeline")]
    scores = [score("Budget", rating=3), score("Timeline", rating=0, met=False, evidence="")]

    result = qualify(criteria, scores)

    assert result.score < 100
    assert "Timeline" in result.reasons


def test_meeting_everything_is_strong_and_failing_everything_is_not() -> None:
    criteria = [criterion("A", weight=2), criterion("B", weight=2)]

    exceeds = qualify(criteria, [score("A", 4), score("B", 4)])
    meets = qualify(criteria, [score("A", 3), score("B", 3)])
    falls_short = qualify(criteria, [score("A", 1), score("B", 1)])

    assert exceeds.score == 100
    assert exceeds.band is QualificationBand.STRONG
    assert meets.band is QualificationBand.STRONG
    assert falls_short.band is QualificationBand.WEAK
    assert exceeds.score > meets.score > falls_short.score


def test_criteria_the_model_skipped_are_left_out_of_the_denominator() -> None:
    """A missing rating is our bug, not evidence about the person.

    Counting it as zero would punish a candidate for a model slip, which is
    the kind of unfairness nobody would ever find by looking at the score.
    """
    criteria = [criterion("Rated"), criterion("Never returned by the model")]
    result = qualify(criteria, [score("Rated", rating=4)])

    assert result.score == 100
    assert "1 of 2 criteria" in result.reasons


def test_names_match_case_insensitively() -> None:
    """The model echoes criterion names back, and case drifts. It must not matter."""
    criteria = [criterion("Notice Period", weight=3)]
    result = qualify(criteria, [score("notice period", rating=4)])

    assert result.score == 100


def test_removing_a_criterion_rescores_cleanly() -> None:
    """Stored ratings outlive the scorecard that produced them.

    Ratings are kept per criterion precisely so weights can change later; a
    dropped criterion must fall out of the maths rather than corrupt it.
    """
    stored = [
        score("Kept", rating=4).model_dump(),
        score("Since removed", rating=0, met=False).model_dump(),
    ]
    result = rescore([criterion("Kept")], stored)

    assert result.score == 100
    assert result.band is QualificationBand.STRONG


def test_scoring_is_deterministic() -> None:
    criteria = [criterion("A", weight=3), criterion("B", weight=2, knockout=True)]
    scores = [score("A", 2), score("B", 3)]

    assert qualify(criteria, scores) == qualify(criteria, scores)


# ---------------------------------------------------------------------------


def _run_all() -> int:
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    failures = 0

    for test in tests:
        try:
            test()
        except Exception as exc:  # noqa: BLE001
            failures += 1
            print(f"FAIL  {test.__name__}: {type(exc).__name__}: {exc}")
        else:
            print(f"pass  {test.__name__}")

    print(f"\n{len(tests) - failures}/{len(tests)} passed")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(_run_all())
