"""Versioned, deterministic Error DNA for Matching Headings."""

from hashlib import sha256

from sqlalchemy import select, update

from app.application.exceptions import InvalidSessionOperationError
from app.decision.schemas import DiagnosticStepResult
from app.decision.tools import AgentToolExecutor
from app.domain.enums import (
    DiagnosticCaseStatus as CaseStatus,
    EvidenceRelation,
    EvidenceSourceType,
    HypothesisStatus,
    InterventionAction,
    QuestionRole,
    QuestionType,
    SessionStatus,
    UncertaintyLevel,
)
from app.domain.reading_groups import (
    HeadingAnswerKey,
    HeadingDiagnostics,
    MATCHING_HEADINGS_DIAGNOSTIC_VERSION as VERSION,
    MATCHING_HEADINGS_PROTOCOL as PROTOCOL,
    MatchingHeadingsGroup,
)
from app.persistence.models import Attempt, DecisionEvent, DiagnosticCase, LearningSession, Question, ReadingGroupVersion, ReadingRuleVersion, ReviewItem
from app.persistence.repositories import LearningRepository


HYPOTHESES = {
    "main_idea_vs_detail": "段落主旨与局部细节混淆",
    "surface_keyword_matching": "表面关键词匹配，忽略整段含义",
}
UNCERTAINTY = "本轮题目提供有限证据。候选原因未经确认，仍需独立验证。"
STEP_ACTION = "matching_headings_step"


def published_rules(db, group: ReadingGroupVersion) -> HeadingDiagnostics | None:
    """Read only validated, immutable rule metadata. Invalid content is ineligible."""
    rule = db.get(ReadingRuleVersion, group.rule_version_id)
    if rule is None:
        return None
    try:
        key = HeadingAnswerKey.model_validate(rule.private_rules_json)
        display = MatchingHeadingsGroup.model_validate(group.display_json)
        if key.diagnostics:
            key.diagnostics.validate_for(display, key.answers)
        return key.diagnostics
    except (ValueError, KeyError):
        return None


def attempt_protocol(attempt: Attempt) -> tuple[str | None, str | None]:
    snapshot = attempt.question_snapshot_json or {}
    return snapshot.get("diagnostic_protocol"), snapshot.get("diagnostic_version")


def supported_protocol(attempt: Attempt) -> bool:
    snapshot = attempt.question_snapshot_json or {}
    return (
        attempt.group_version_id is not None
        and snapshot.get("question_type") == QuestionType.MATCHING_HEADINGS.value
        and attempt_protocol(attempt) == (PROTOCOL, VERSION)
    )


class MatchingHeadingsRules:
    def __init__(self, repo: LearningRepository):
        self.repo = repo
        self.db = repo.session

    def _observe(self, case, attempt, item_id, links, source, reason):
        result = attempt.item_evaluation_json
        item = next(item for item in attempt.group_snapshot_json["items"] if item["id"] == item_id)
        observation = {
            "attempt_id": attempt.id,
            "item_id": item_id,
            "paragraph_id": item["paragraph_id"],
            "question_id": attempt.question_id,
            "group_version_id": attempt.group_version_id,
            "rule_version_id": result["rule_version_id"],
            "evaluation_rule_version": attempt.evaluation_rule_version,
            "diagnostic_protocol": PROTOCOL,
            "diagnostic_version": VERSION,
            "selected_heading_id": attempt.structured_answer_json[item_id],
            "is_correct": result["correct_by_item"][item_id],
        }
        event = self.repo.append_decision_event(
            session_id=attempt.session_id, diagnostic_case_id=case.id,
            event_type="reading_item_observation", action="observe_matching_heading_item",
            reason=reason, to_state=case.status, uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
            payload_json={"observation": observation},
        )
        for hypothesis, relation in links:
            self.repo.record_evidence(
                hypothesis_id=hypothesis.id, attempt_id=attempt.id, decision_event_id=event.id,
                source_ref=f"mh:{event.id}", source_type=source, relation=relation,
                summary=reason, reliability_note="同一次作答中的题项观察不视为独立能力验证。",
            )

    def observe_initial(self, case: DiagnosticCase, attempt: Attempt, rules: HeadingDiagnostics) -> bool:
        wrong_items = {
            item: rules.distractors.get(item, {}).get(attempt.structured_answer_json[item], [])
            for item, correct in attempt.item_evaluation_json["correct_by_item"].items() if not correct
        }
        candidates = {code for codes in wrong_items.values() for code in codes}
        hypotheses = {
            code: self.repo.add_hypothesis(
                diagnostic_case_id=case.id, error_code=code, name=HYPOTHESES[code],
                description="所选干扰标题与此解释相容，需要追问区分。",
                confidence=0.35, status=HypothesisStatus.CANDIDATE, missing_evidence_desc=UNCERTAINTY,
            )
            for code in sorted(candidates)
        }
        if any(not codes for codes in wrong_items.values()):
            hypotheses["insufficient_evidence"] = self.repo.add_hypothesis(
                diagnostic_case_id=case.id, error_code="insufficient_evidence", name="证据不足",
                description="有错误题项没有已审核的原因映射。",
                confidence=0, status=HypothesisStatus.INSUFFICIENT_EVIDENCE,
                missing_evidence_desc=UNCERTAINTY,
            )
        for item_id, codes in wrong_items.items():
            self._observe(
                case, attempt, item_id,
                [(hypotheses[code], EvidenceRelation.NEUTRAL) for code in sorted(set(codes or ["insufficient_evidence"]))],
                EvidenceSourceType.INITIAL_ATTEMPT,
                "本题项匹配错误。该观察仅用于提出候选解释。" if codes else "本题项匹配错误，暂无已审核原因映射。",
            )
        if candidates:
            self.repo.transition_diagnostic_case(
                case, CaseStatus.HYPOTHESES_GENERATED, action="matching_headings_candidates",
                reason=UNCERTAINTY, uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
            )
            self.repo.transition_diagnostic_case(
                case, CaseStatus.NEEDS_EVIDENCE, action="matching_headings_needs_probe",
                reason=UNCERTAINTY, uncertainty_note=UNCERTAINTY,
                uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
            )
        return bool(candidates)

    def observe_followup(self, case: DiagnosticCase, attempt: Attempt, rules: HeadingDiagnostics) -> None:
        hypotheses = {h.error_code: h for h in case.hypotheses}
        for item_id, probe in rules.probes.items():
            relation = EvidenceRelation(probe.relations.get(attempt.structured_answer_json[item_id], "neutral"))
            hypothesis = hypotheses.get(probe.target)
            links = [(hypothesis, relation)] if hypothesis else []
            note = {
                EvidenceRelation.SUPPORTS: "追问表现与该候选原因相容。",
                EvidenceRelation.CONTRADICTS: "追问表现削弱该候选原因。",
                EvidenceRelation.NEUTRAL: "此选择不足以区分该候选原因。",
            }[relation]
            self._observe(case, attempt, item_id, links, EvidenceSourceType.FOLLOWUP_RESPONSE, note)
        by_hypothesis = {}
        for evidence in self.repo.list_evidence_for_case(case.id):
            if evidence.source_type == EvidenceSourceType.FOLLOWUP_RESPONSE.value:
                by_hypothesis.setdefault(evidence.hypothesis_id, set()).add(evidence.relation)
        for hypothesis in hypotheses.values():
            if hypothesis.error_code not in rules.targets:
                continue
            relations = by_hypothesis.get(hypothesis.id, set()) - {EvidenceRelation.NEUTRAL.value}
            if relations == {EvidenceRelation.SUPPORTS.value}:
                status, confidence = HypothesisStatus.SUPPORTED, 0.65
            elif relations == {EvidenceRelation.CONTRADICTS.value}:
                status, confidence = HypothesisStatus.LOWERED, 0.2
            else:
                status, confidence = HypothesisStatus.INSUFFICIENT_EVIDENCE, 0.35
            self.repo.update_hypothesis(
                hypothesis, new_status=status, new_confidence=confidence,
                reason=UNCERTAINTY, missing_evidence_desc=UNCERTAINTY,
            )
        self.repo.transition_diagnostic_case(
            case, CaseStatus.HYPOTHESES_UPDATED, action="matching_headings_probe_evaluated",
            reason=UNCERTAINTY, uncertainty_note=UNCERTAINTY,
            uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
        )

    def compatible_task(self, session, source, question, group, targets):
        rules = published_rules(self.db, group)
        return (
            question.topic_id == session.topic_id
            and question.question_type == QuestionType.MATCHING_HEADINGS.value
            and group.question_type == question.question_type
            and group.exam_variant == session.exam_variant
            and source.task_versions.get(question.id) == group.id
            and rules is not None
            and (rules.protocol, rules.version) == (source.protocol, source.version)
            and rules.source_group_id == source.source_group_id
            and rules.role == question.question_role
            and set(rules.targets) == set(targets)
        )

    def select_independent_task(self, session, case, role: QuestionRole, *, exclude_review_item_id: str | None = None):
        """Select an explicitly reviewed transfer/review task for one supported cause."""
        trigger = case.trigger_attempt
        source_group = self.db.get(ReadingGroupVersion, trigger.group_version_id) if trigger.group_version_id else None
        source = published_rules(self.db, source_group) if source_group else None
        if (
            not supported_protocol(trigger) or source is None
            or (source.protocol, source.version) != attempt_protocol(trigger)
            or trigger.question_snapshot_json.get("rule_version_id") != source_group.rule_version_id
            or source.role != QuestionRole.INITIAL.value
            or source_group.exam_variant != session.exam_variant
        ):
            return None
        hypotheses = {h.error_code: h.status for h in case.hypotheses if h.error_code in source.targets}
        supported = [code for code, status in hypotheses.items() if status == HypothesisStatus.SUPPORTED.value]
        if len(supported) != 1 or any(
            status != HypothesisStatus.LOWERED.value
            for code, status in hypotheses.items() if code != supported[0]
        ):
            return None
        target = supported[0]
        attempts = self.repo.list_attempts_for_session(session.id)
        if role == QuestionRole.TRANSFER_CHECK:
            practices = [a for a in attempts if a.attempt_role == QuestionRole.TARGETED_PRACTICE.value]
            if not practices or practices[-1].is_correct is not True:
                return None
        used_question_ids = {attempt.question_id for attempt in attempts}
        used_group_ids = {source_group.group_id}
        for attempt in attempts:
            prior_group = self.db.get(ReadingGroupVersion, attempt.group_version_id) if attempt.group_version_id else None
            if prior_group is not None:
                used_group_ids.add(prior_group.group_id)
        used_passage_ids = set()
        for attempt in attempts:
            snapshot = attempt.group_snapshot_json or {}
            passage_id = (snapshot.get("passage") or {}).get("id")
            if passage_id:
                used_passage_ids.add(passage_id)
        historical_attempts = self.db.scalars(
            select(Attempt).join(LearningSession, Attempt.session_id == LearningSession.id)
            .where(LearningSession.learner_id == session.learner_id,
                   LearningSession.topic_id == session.topic_id)
        ).all()
        used_question_ids.update(a.question_id for a in historical_attempts)
        for prior_attempt in historical_attempts:
            prior_group = self.db.get(ReadingGroupVersion, prior_attempt.group_version_id) if prior_attempt.group_version_id else None
            if prior_group is not None:
                used_group_ids.add(prior_group.group_id)
            passage_id = (prior_attempt.group_snapshot_json or {}).get("passage", {}).get("id")
            if passage_id:
                used_passage_ids.add(passage_id)
        assigned_group_ids = self.db.scalars(
            select(LearningSession.current_group_version_id).where(
                LearningSession.learner_id == session.learner_id,
                LearningSession.topic_id == session.topic_id,
                LearningSession.current_group_version_id.is_not(None),
            )
        ).all()
        for version_id in assigned_group_ids:
            assigned_group = self.db.get(ReadingGroupVersion, version_id)
            if assigned_group is not None:
                used_group_ids.add(assigned_group.group_id)
                assigned_passage_id = assigned_group.display_json.get("passage", {}).get("id")
                if assigned_passage_id:
                    used_passage_ids.add(assigned_passage_id)
        if role == QuestionRole.REVIEW and case:
            state = self.repo.get_knowledge_state(session.learner_id, session.topic_id)
            related = self.db.scalars(select(ReviewItem).where(
                ReviewItem.learner_id == session.learner_id,
                ReviewItem.topic_id == session.topic_id,
                ReviewItem.knowledge_state_id == (state.id if state else None),
            )).all()
            for item in related:
                if item.id == exclude_review_item_id:
                    continue
                if item.question_id:
                    used_question_ids.add(item.question_id)
                prior_group = self.db.get(ReadingGroupVersion, item.group_version_id) if item.group_version_id else None
                if prior_group is not None:
                    used_group_ids.add(prior_group.group_id)
                    prior_passage_id = prior_group.display_json.get("passage", {}).get("id")
                    if prior_passage_id:
                        used_passage_ids.add(prior_passage_id)
                if item.review_session_id:
                    for prior_attempt in self.repo.list_attempts_for_session(item.review_session_id):
                        prior_group = self.db.get(ReadingGroupVersion, prior_attempt.group_version_id) if prior_attempt.group_version_id else None
                        if prior_group is not None:
                            used_group_ids.add(prior_group.group_id)
                        prior_passage_id = (prior_attempt.group_snapshot_json or {}).get("passage", {}).get("id")
                        if prior_passage_id:
                            used_passage_ids.add(prior_passage_id)

        for question in self.repo.list_questions_for_topic(session.topic_id, role=role):
            if question.id in used_question_ids or question.question_type != QuestionType.MATCHING_HEADINGS.value:
                continue
            group = self.db.get(ReadingGroupVersion, question.reading_group_version_id) if question.reading_group_version_id else None
            rules = published_rules(self.db, group) if group else None
            if (
                group is None or rules is None
                or source.task_versions.get(question.id) != group.id
                or group.exam_variant != session.exam_variant
                or group.question_type != QuestionType.MATCHING_HEADINGS.value
                or rules.role != role.value
                or (rules.protocol, rules.version) != (source.protocol, source.version)
                or rules.source_group_id != source.source_group_id
                or rules.targets != [target]
            ):
                continue
            independence = group.provenance_json.get("independence_review", {})
            basis_groups = set(independence.get("independent_from_group_ids", []))
            passage_id = group.display_json.get("passage", {}).get("id")
            if (
                not independence.get("independence_id")
                or not independence.get("independence_basis")
                or not basis_groups.issuperset({source_group.group_id, *(self.db.get(ReadingGroupVersion, a.group_version_id).group_id
                                                                           for a in attempts if a.group_version_id
                                                                           and self.db.get(ReadingGroupVersion, a.group_version_id))})
                or not passage_id or passage_id in used_passage_ids
                or group.id in used_group_ids
            ):
                continue
            return question, group, target, source
        return None

    def task_matches(self, session, case, question, group, role, target):
        trigger = case.trigger_attempt
        source_group = self.db.get(ReadingGroupVersion, trigger.group_version_id) if trigger.group_version_id else None
        source = published_rules(self.db, source_group) if source_group else None
        task_rules = published_rules(self.db, group) if group else None
        if not supported_protocol(trigger) or source is None or task_rules is None or group is None:
            return False
        independence = group.provenance_json.get("independence_review", {})
        return (
            question.topic_id == session.topic_id
            and question.question_type == QuestionType.MATCHING_HEADINGS.value
            and question.question_role == role.value
            and group.exam_variant == session.exam_variant
            and group.id == source.task_versions.get(question.id)
            and (source.protocol, source.version) == attempt_protocol(trigger)
            and (task_rules.protocol, task_rules.version) == (source.protocol, source.version)
            and task_rules.role == role.value and task_rules.targets == [target]
            and task_rules.source_group_id == source.source_group_id
            and bool(independence.get("independence_id"))
            and bool(independence.get("independence_basis"))
            and source_group.group_id in independence.get("independent_from_group_ids", [])
        )

    def _choose(self, session, source, role, targets, answered_ids):
        for question in self.repo.list_questions_for_topic(session.topic_id, role=role):
            if question.id in answered_ids or not question.reading_group_version_id:
                continue
            group = self.db.get(ReadingGroupVersion, question.reading_group_version_id)
            if group and self.compatible_task(session, source, question, group, targets):
                return question, group
        return None

    def step(self, session, case, *, idempotency_key, settings):
        # The same write lock is used by structured submissions. Re-read state
        # after acquiring it so parallel clicks cannot dispatch two questions.
        self.db.execute(
            update(LearningSession).where(LearningSession.id == session.id)
            .values(updated_at=LearningSession.updated_at).execution_options(synchronize_session=False)
        )
        self.db.refresh(session)
        self.db.refresh(case)
        trigger = case.trigger_attempt
        group = self.db.get(ReadingGroupVersion, trigger.group_version_id) if trigger.group_version_id else None
        source = published_rules(self.db, group) if group else None
        if (
            not supported_protocol(trigger) or source is None or source.role != QuestionRole.INITIAL.value
            or attempt_protocol(trigger) != (source.protocol, source.version)
            or group.exam_variant != session.exam_variant
            or trigger.question_snapshot_json.get("rule_version_id") != group.rule_version_id
        ):
            raise InvalidSessionOperationError(
                "Insufficient evidence: no supported Matching Headings diagnostic protocol for this attempt.",
                current_state=case.status,
            )
        key = None
        if idempotency_key:
            key = "mh-step:" + sha256(f"{case.id}\0{idempotency_key}".encode()).hexdigest()
            replay = self.db.scalar(select(DecisionEvent).where(DecisionEvent.idempotency_key == key))
            if replay:
                return DiagnosticStepResult.model_validate(replay.payload_json["result"])

        if session.status not in {SessionStatus.DIAGNOSING.value, SessionStatus.INTERVENING.value}:
            raise InvalidSessionOperationError("This diagnostic session is not active.", current_state=session.status)
        attempts = self.repo.list_attempts_for_session(session.id)
        last = attempts[-1]
        previous = next((e for e in case.decision_events
                         if e.action == STEP_ACTION and e.payload_json.get("attempt_id") == last.id), None)
        if previous:
            if key:
                self.repo.append_decision_event(
                    session_id=session.id, diagnostic_case_id=case.id,
                    event_type="diagnostic_step_replayed", action="matching_headings_step_alias",
                    reason="Replay the recorded decision for the same attempt.", to_state=case.status,
                    uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                    idempotency_key=key, payload_json=previous.payload_json,
                )
            return DiagnosticStepResult.model_validate(previous.payload_json["result"])

        answered = {attempt.question_id for attempt in attempts}
        if session.current_question_id and session.current_question_id not in answered:
            raise InvalidSessionOperationError("Answer the dispatched question before continuing.", current_state=case.status)
        candidates = {h.error_code: h.status for h in case.hypotheses if h.error_code in source.targets}
        followup_turns = self.repo.get_case_followup_turn_count(case.id)
        selected = None
        action = "matching_headings_insufficient_evidence"
        reason = "当前证据不足以分配针对性训练。"
        intervention = None
        if last.attempt_role == QuestionRole.INITIAL.value and candidates:
            if followup_turns < settings.max_diagnostic_followup_turns:
                selected = self._choose(session, source, QuestionRole.DIAGNOSTIC_FOLLOWUP, source.targets, answered)
            reason = "用两个独立题项区分局部细节偏差与表面关键词偏差。" if selected else "没有与固定协议匹配的可用追问题。"
            action = "select_diagnostic_followup" if selected else "matching_headings_followup_unavailable"
            intervention = InterventionAction.ASK_FOLLOWUP if selected else None
        elif last.attempt_role == QuestionRole.DIAGNOSTIC_FOLLOWUP.value:
            supported = [code for code, status in candidates.items() if status == HypothesisStatus.SUPPORTED.value]
            if len(supported) == 1 and all(
                candidates.get(code) == HypothesisStatus.LOWERED.value
                for code in source.targets if code != supported[0]
            ):
                selected = self._choose(session, source, QuestionRole.TARGETED_PRACTICE, supported, answered)
                reason = (
                    f"追问支持「{HYPOTHESES[supported[0]]}」并削弱另一候选，派发对应训练。"
                    if selected else "没有与已支持原因和固定协议匹配的可用训练题。"
                )
                action = "assign_targeted_practice" if selected else "matching_headings_practice_unavailable"
                intervention = InterventionAction.TARGETED_PRACTICE if selected else None
        elif last.attempt_role == QuestionRole.TARGETED_PRACTICE.value:
            action = "matching_headings_transfer_pending" if last.is_correct else "matching_headings_practice_incomplete"
            reason = "本次训练通过，仍待独立迁移验证。" if last.is_correct else "本次训练未通过，候选原因仍待进一步验证。"

        if selected:
            question, selected_group = selected
            dispatch = AgentToolExecutor(self.repo).dispatch_reading_group(
                session=session, case=case, attempt=last, question=question, group=selected_group,
                expected_version=source.task_versions[question.id],
                targets=published_rules(self.db, selected_group).targets, reason=reason, uncertainty_note=UNCERTAINTY,
            )
        else:
            question = selected_group = None
            if last.attempt_role != QuestionRole.TARGETED_PRACTICE.value and case.status != CaseStatus.INSUFFICIENT_EVIDENCE.value:
                case.selected_intervention = None
                dispatch = self.repo.transition_diagnostic_case(
                    case, CaseStatus.INSUFFICIENT_EVIDENCE, action=action, reason=reason,
                    uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE, uncertainty_note=reason,
                )
            else:
                dispatch = self.repo.append_decision_event(
                    session_id=session.id, diagnostic_case_id=case.id, event_type="diagnostic_rule_outcome",
                    action=action, reason=reason, to_state=case.status,
                    uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
                )
        result = DiagnosticStepResult(
            session_id=session.id, diagnostic_case_id=case.id, attempt_id=last.id, case_status=case.status,
            executed_tool=action, selected_intervention=intervention,
            selected_question_id=question.id if question else None,
            selected_group_version_id=selected_group.id if selected_group else None,
            uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
            uncertainty_note=UNCERTAINTY if selected else reason,
            followup_turns_used=self.repo.get_case_followup_turn_count(case.id),
            max_followup_turns=settings.max_diagnostic_followup_turns, tokens_used_in_case=0,
            session_token_budget=settings.diagnostic_session_token_budget, decision_event_id=dispatch.id,
            degraded_mode=not selected and last.attempt_role != QuestionRole.TARGETED_PRACTICE.value,
            degradation_reason=reason if not selected and last.attempt_role != QuestionRole.TARGETED_PRACTICE.value else None,
            hypotheses_snapshot=[{
                "id": h.id, "error_code": h.error_code, "name": h.name, "status": h.status,
                "confidence": h.confidence, "missing_evidence_desc": h.missing_evidence_desc,
            } for h in case.hypotheses],
        )
        self.repo.append_decision_event(
            session_id=session.id, diagnostic_case_id=case.id, event_type="diagnostic_step_completed",
            action=STEP_ACTION, reason=reason, to_state=case.status, idempotency_key=key,
            uncertainty_level=UncertaintyLevel.INSUFFICIENT_EVIDENCE,
            payload_json={"attempt_id": last.id, "result": result.model_dump(mode="json")},
        )
        return result
