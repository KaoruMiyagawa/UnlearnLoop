"""Interpretable heuristic scoring for discriminating diagnostic follow-up questions.

Per ARCHITECTURE.md Section 6:
- A follow-up question scores higher when it can distinguish between multiple active
  competing hypotheses (`target_error_codes` overlap), has low cognitive cost (`difficulty`),
  and has not already been asked in the current session.
"""

from dataclasses import dataclass

from app.persistence.models import Question


@dataclass(frozen=True)
class FollowupCandidateScore:
    """Interpretable heuristic score for a candidate diagnostic follow-up question."""

    question_id: str
    score: float
    matched_error_codes: list[str]
    already_asked: bool
    rationale: str


def rank_followup_questions(
    candidate_questions: list[Question],
    *,
    active_error_codes: set[str],
    already_asked_question_ids: set[str],
) -> list[FollowupCandidateScore]:
    """Rank diagnostic follow-up questions by discrimination power and cost."""
    scored: list[FollowupCandidateScore] = []

    for q in candidate_questions:
        rubric = q.evaluation_rubric or {}
        target_codes = [str(c) for c in (rubric.get("target_error_codes") or [])]
        matched = [c for c in target_codes if c in active_error_codes]
        already_asked = q.id in already_asked_question_ids

        # Base discrimination score: +2.0 per active competing hypothesis covered
        overlap_score = len(matched) * 2.0
        # Bonus if it distinguishes >= 2 active hypotheses simultaneously
        if len(matched) >= 2:
            overlap_score += 1.0
        # Low-cost bonus inversely proportional to question difficulty
        cost_bonus = 0.5 / max(1, q.difficulty)
        # Heavy penalty if already asked in this session
        repeat_penalty = -10.0 if already_asked else 0.0

        total_score = round(overlap_score + cost_bonus + repeat_penalty, 3)
        disc_rationale = str(
            rubric.get("discriminating_rationale")
            or f"覆盖候选假设 {matched or target_codes}，难度 {q.difficulty}。"
        )
        scored.append(
            FollowupCandidateScore(
                question_id=q.id,
                score=total_score,
                matched_error_codes=matched,
                already_asked=already_asked,
                rationale=disc_rationale,
            )
        )

    scored.sort(key=lambda item: (-item.score, item.question_id))
    return scored
