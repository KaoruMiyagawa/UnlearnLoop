# Learner model contract 1.0

`GET /api/v1/learner-model?learner_id=...` is a read-only projection of the existing Learn records. `learner_id` defaults to `default_learner` and has 1–64 characters. This local development convention filters data; it is not authentication or authorization. The response identifies language `en`, and always includes listening, speaking, reading and writing. `assessment_status: observed` means a bounded, eligible exercise result exists; it is not a skill level. `not_assessed` includes practice without an applicable evaluation. Evidence includes its learner, skill, competency (a topic identifier or the relevant expression dimension), type, source, reference, validity, method, content version, timestamp, observation and limitations. The list may contain invalidated or review-required records for audit; consumers must only use eligible observed records as evidence. Activity records are not quality assessments. Evidence levels describe available kinds of observations, not a progression, a score, or mastery.

`learning_goal` is separately sourced from ExamPreparationProfile and is never evidence of actual ability. No overall band is inferred.

## Consumer contract for future systems

- Discover can consume `language_code`, `skill_id`, `competency_id`, the evidence records and limitations to identify a possible learning resource need. Absence of evidence does not prove a weakness. No recommendation is made by this API.
- Adapt can consume the separately labelled `learning_goal`, eligible observations, unassessed skills and non-eligible evidence to plan a future assessment. A proposed reassessment direction must reference the underlying skill/competency and reason (unknown, invalidated, or review required), remain a proposal, and be validated with the learner. This release makes no autonomous decisions.
- Both consumers must preserve evidence references, validity and limits; they must not convert these levels or goal bands into an inferred IELTS score. Contract changes require a new `contract_version`.
