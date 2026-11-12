"""Version-specific evidence validity registration and deterministic reconciliation."""
from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.domain.enums import (
    AttemptEvaluationStatus,
    EvidenceValidityStatus,
    KnowledgeMasteryStatus,
    QuestionRole,
    QuestionType,
    ReviewStatus,
)
from app.persistence.models import (
    Attempt,
    DiagnosticCase,
    DecisionEvent,
    EvidenceLink,
    EvidenceValidityEvent,
    KnowledgeState,
    LearningSession,
    Question,
    ReadingGroupVersion,
    ReadingRuleVersion,
    ReviewItem,
)

REGISTRY_PATH = Path(__file__).parents[1] / "content" / "matching_headings_evidence_validity_registry.json"
SOURCE = "IELTS-2B.1 Phase 6.1 reviewed validity registry"


@dataclass(frozen=True)
class RegisteredVersion:
    registry_entry: dict[str, Any]
    group: ReadingGroupVersion
    rule: ReadingRuleVersion


def load_registry() -> dict[str, Any]:
    return json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))


def latest_validity(
    session: Session, target_type: str, target_id: str
) -> EvidenceValidityEvent | None:
    return session.scalar(
        select(EvidenceValidityEvent)
        .where(
            EvidenceValidityEvent.target_type == target_type,
            EvidenceValidityEvent.target_id == target_id,
        )
        .order_by(EvidenceValidityEvent.audited_at.desc(), EvidenceValidityEvent.id.desc())
        .limit(1)
    )


def _exact_versions(session: Session, entry: dict[str, Any]) -> list[RegisteredVersion]:
    rows = session.execute(
        select(ReadingGroupVersion, ReadingRuleVersion)
        .join(ReadingRuleVersion, ReadingRuleVersion.id == ReadingGroupVersion.rule_version_id)
        .where(
            ReadingGroupVersion.group_id == entry["group_id"],
            ReadingGroupVersion.content_version == entry["content_version"],
            ReadingRuleVersion.rules_version == entry["rules_version"],
        )
    ).all()
    return [RegisteredVersion(entry, group, rule) for group, rule in rows]


def _is_matching_transfer_or_review(attempt: Attempt) -> bool:
    return attempt.attempt_role in {
        QuestionRole.TRANSFER_CHECK.value,
        QuestionRole.REVIEW.value,
    } and (
        attempt.question_snapshot_json.get("question_type") == QuestionType.MATCHING_HEADINGS.value
        or (attempt.question is not None and attempt.question.question_type == QuestionType.MATCHING_HEADINGS.value)
        or attempt.group_version_id is not None
    )


def evidence_status(session: Session, target_type: str, target_id: str) -> str:
    event = latest_validity(session, target_type, target_id)
    direct_status = event.status if event else None
    if target_type == "reading_group_version":
        group = session.get(ReadingGroupVersion, target_id)
        registry_status = EvidenceValidityStatus.ELIGIBLE.value
        if group:
            rules = session.get(ReadingRuleVersion, group.rule_version_id)
            if rules:
                registry = load_registry()
                group_entries = [entry for entry in registry["entries"] if entry["group_id"] == group.group_id]
                matched = next((entry for entry in group_entries
                    if entry["content_version"] == group.content_version
                    and entry["rules_version"] == rules.rules_version), None)
                if matched:
                    registry_status = matched["status"]
                elif group_entries:
                    registry_status = EvidenceValidityStatus.REVIEW_REQUIRED.value
        statuses = [status for status in (direct_status, registry_status)
                    if status and status != EvidenceValidityStatus.ELIGIBLE.value]
        if EvidenceValidityStatus.INVALIDATED.value in statuses:
            return EvidenceValidityStatus.INVALIDATED.value
        if EvidenceValidityStatus.REVIEW_REQUIRED.value in statuses:
            return EvidenceValidityStatus.REVIEW_REQUIRED.value
        return EvidenceValidityStatus.ELIGIBLE.value
    if target_type == "attempt":
        attempt = session.get(Attempt, target_id)
        if attempt:
            if _is_matching_transfer_or_review(attempt) and not attempt.group_version_id:
                inferred = EvidenceValidityStatus.REVIEW_REQUIRED.value
                if direct_status == EvidenceValidityStatus.INVALIDATED.value:
                    return direct_status
                return direct_status if direct_status not in (None, EvidenceValidityStatus.ELIGIBLE.value) else inferred
            if attempt.group_version_id:
                inherited = evidence_status(session, "reading_group_version", attempt.group_version_id)
                if inherited != EvidenceValidityStatus.ELIGIBLE.value:
                    return inherited
        return direct_status or EvidenceValidityStatus.ELIGIBLE.value
    if target_type == "evidence_link":
        evidence = session.get(EvidenceLink, target_id)
        if evidence and evidence.attempt_id:
            inherited = evidence_status(session, "attempt", evidence.attempt_id)
            if inherited != EvidenceValidityStatus.ELIGIBLE.value:
                return inherited
        return direct_status or EvidenceValidityStatus.ELIGIBLE.value
    if target_type == "review_item":
        item = session.get(ReviewItem, target_id)
        if direct_status == EvidenceValidityStatus.INVALIDATED.value:
            return direct_status
        if item and (item.group_version_id or item.trigger_attempt_id or item.attempt_id):
            refs = [item.group_version_id, item.trigger_attempt_id, item.attempt_id]
            for kind, ref in (("reading_group_version", refs[0]), ("attempt", refs[1]), ("attempt", refs[2])):
                if ref and evidence_status(session, kind, ref) != EvidenceValidityStatus.ELIGIBLE.value:
                    return evidence_status(session, kind, ref)
        return direct_status or EvidenceValidityStatus.ELIGIBLE.value
    return direct_status or EvidenceValidityStatus.ELIGIBLE.value


def evidence_reason(session: Session, target_type: str, target_id: str) -> str | None:
    event = latest_validity(session, target_type, target_id)
    return event.reason if event else None


def effective_knowledge_status(session: Session, state: KnowledgeState) -> str:
    """Do not expose a stored mastery label supported only by invalid history."""
    if not state.last_transfer_attempt_id:
        return state.status
    status = evidence_status(session, "attempt", state.last_transfer_attempt_id)
    if status == EvidenceValidityStatus.ELIGIBLE.value:
        return state.status
    last = session.get(Attempt, state.last_transfer_attempt_id)
    if last is None:
        return KnowledgeMasteryStatus.INSUFFICIENT_EVIDENCE.value
    candidates = session.scalars(
        select(Attempt).join(LearningSession, Attempt.session_id == LearningSession.id)
        .join(Question, Attempt.question_id == Question.id)
        .where(
            LearningSession.learner_id == state.learner_id,
            LearningSession.topic_id == state.topic_id,
            Question.question_type == QuestionType.MATCHING_HEADINGS.value,
            Attempt.attempt_role == QuestionRole.TRANSFER_CHECK.value,
            Attempt.evaluation_status == AttemptEvaluationStatus.EVALUATED.value,
            Attempt.is_correct.is_(True),
        ).order_by(Attempt.submitted_at.desc())
    ).all()
    if any(candidate.id != state.last_transfer_attempt_id
           and evidence_status(session, "attempt", candidate.id) == EvidenceValidityStatus.ELIGIBLE.value
           for candidate in candidates):
        return KnowledgeMasteryStatus.TRANSFER_VERIFIED.value
    return KnowledgeMasteryStatus.INSUFFICIENT_EVIDENCE.value


def build_reconciliation_plan(session: Session) -> dict[str, Any]:
    """Build an exact-version plan. No mutation occurs in this function."""
    registry = load_registry()
    resolved: list[RegisteredVersion] = []
    unresolved: list[dict[str, Any]] = []
    for entry in registry["entries"]:
        matches = _exact_versions(session, entry)
        if len(matches) == 1:
            resolved.append(matches[0])
        elif len(matches) == 0:
            unresolved.append({**entry, "match_status": "not_present"})
        else:
            unresolved.append({**entry, "match_status": "ambiguous_exact_tuple", "matching_version_ids": [m.group.id for m in matches]})

    invalid_versions = {
        item.group.id: item for item in resolved
        if item.registry_entry["status"] == EvidenceValidityStatus.INVALIDATED.value
    }
    eligible_versions = {
        item.group.id: item for item in resolved
        if item.registry_entry["status"] == EvidenceValidityStatus.ELIGIBLE.value
    }
    invalid_attempts: dict[str, RegisteredVersion] = {}
    review_required_attempts: set[str] = set()
    ambiguous_version_ids = {
        version_id
        for entry in unresolved
        if entry.get("match_status") == "ambiguous_exact_tuple"
        for version_id in entry.get("matching_version_ids", [])
    }
    registered_group_ids = {entry["group_id"] for entry in registry["entries"]}
    for attempt in session.scalars(select(Attempt)).all():
        if not _is_matching_transfer_or_review(attempt):
            continue
        if attempt.group_version_id in invalid_versions:
            invalid_attempts[attempt.id] = invalid_versions[attempt.group_version_id]
        elif attempt.group_version_id in eligible_versions:
            continue
        elif attempt.group_version_id in ambiguous_version_ids or (
            attempt.group_version_id and session.get(ReadingGroupVersion, attempt.group_version_id) is None
        ):
            review_required_attempts.add(attempt.id)
        elif attempt.group_version_id:
            group = session.get(ReadingGroupVersion, attempt.group_version_id)
            if group and group.group_id in registered_group_ids:
                # Known content family but an unregistered immutable version/rule
                # pair: hold for provenance review rather than infer by ID/date.
                review_required_attempts.add(attempt.id)
        elif not attempt.group_version_id:
            snapshot = attempt.group_snapshot_json or {}
            q_snapshot = attempt.question_snapshot_json or {}
            group_id = snapshot.get("group_id") or q_snapshot.get("group_id")
            content_version = snapshot.get("content_version") or q_snapshot.get("content_version")
            rules_version = snapshot.get("rules_version") or q_snapshot.get("rules_version")
            explicit = next((entry for entry in registry["entries"] if (
                group_id == entry["group_id"]
                and content_version == entry["content_version"]
                and rules_version == entry["rules_version"]
            )), None)
            # If a legacy matching attempt has no immutable group-version FK,
            # snapshots can help locate a registry tuple, but a missing or
            # incomplete snapshot is still provenance uncertainty. Never infer
            # eligibility from a question ID or timestamp alone.
            if explicit or _is_matching_transfer_or_review(attempt):
                review_required_attempts.add(attempt.id)

    # Follow review provenance edges transitively: a review depending on an
    # invalid transfer, and later review cycles depending on that review, are
    # not independent evidence.
    invalid_reviews: dict[str, RegisteredVersion | None] = {}
    changed = True
    while changed:
        changed = False
        for item in session.scalars(select(ReviewItem)).all():
            if item.id in invalid_reviews:
                continue
            own_invalid = item.group_version_id in invalid_versions
            trigger_invalid = item.trigger_attempt_id in invalid_attempts or item.trigger_attempt_id in review_required_attempts
            result_invalid = item.attempt_id in invalid_attempts or item.attempt_id in review_required_attempts
            if own_invalid or trigger_invalid or result_invalid:
                invalid_reviews[item.id] = invalid_versions.get(item.group_version_id)
                changed = True
                if item.attempt_id:
                    result = session.get(Attempt, item.attempt_id)
                    if result and _is_matching_transfer_or_review(result) and result.id not in invalid_attempts:
                        invalid_attempts[result.id] = invalid_versions.get(item.group_version_id) or invalid_versions.get(
                            session.get(ReviewItem, item.id).group_version_id
                        )

    affected_states: list[dict[str, Any]] = []
    for state in session.scalars(select(KnowledgeState)).all():
        if not state.last_transfer_attempt_id:
            continue
        last = session.get(Attempt, state.last_transfer_attempt_id)
        if last and (last.id in invalid_attempts or last.id in review_required_attempts):
            affected_states.append({"id": state.id, "learner_id": state.learner_id,
                                    "topic_id": state.topic_id, "before_status": state.status,
                                    "last_transfer_attempt_id": last.id,
                                    "proposed_status": KnowledgeMasteryStatus.INSUFFICIENT_EVIDENCE.value})

    version_actions = []
    for item in resolved:
        replacement = next((candidate.group.id for candidate in resolved
                            if candidate.registry_entry["group_id"] == item.registry_entry["group_id"]
                            and candidate.registry_entry["content_version"] == item.registry_entry.get("replacement_content_version")), None)
        version_actions.append({
            "group_version_id": item.group.id,
            "group_id": item.group.group_id,
            "content_hash": item.group.content_hash,
            "content_version": item.group.content_version,
            "rules_version": item.rule.rules_version,
            "status": item.registry_entry["status"],
            "reason": item.registry_entry["reason"],
            "replacement_group_version_id": replacement,
        })
    return {
        "registry_version": registry["registry_version"],
        "source": registry["source"],
        "versions": version_actions,
        "unresolved_registry_entries": unresolved,
        "attempts_invalidated": sorted(invalid_attempts),
        "attempts_review_required": sorted(review_required_attempts),
        "review_items_invalidated": sorted(invalid_reviews),
        "knowledge_states": affected_states,
        "counts": {
            "versions": len(version_actions), "attempts_invalidated": len(invalid_attempts),
            "attempts_review_required": len(review_required_attempts),
            "review_items_invalidated": len(invalid_reviews), "knowledge_states": len(affected_states),
        },
    }


def _append_validity_event(
    session: Session, *, target_type: str, target_id: str, status: str,
    reason: str, source: str, key: str, group_version: ReadingGroupVersion | None = None,
    rules_version: str | None = None, replacement: ReadingGroupVersion | None = None,
    refs: dict[str, Any] | None = None,
) -> EvidenceValidityEvent:
    existing = session.scalar(select(EvidenceValidityEvent).where(EvidenceValidityEvent.idempotency_key == key))
    if existing:
        return existing
    record = EvidenceValidityEvent(
        id=f"evv_{uuid4().hex[:16]}", target_type=target_type, target_id=target_id,
        status=status, group_version_id=group_version.id if group_version else None,
        content_hash=group_version.content_hash if group_version else None,
        content_version=group_version.content_version if group_version else None,
        rules_version=rules_version, reason=reason, source=source,
        replacement_group_version_id=replacement.id if replacement else None,
        affected_refs_json=refs or {}, idempotency_key=key,
        audited_at=datetime.now(timezone.utc),
    )
    try:
        # Isolate the unique-key race so a retry can read the winning audit row
        # without discarding the caller's surrounding reconciliation transaction.
        with session.begin_nested():
            session.add(record)
            session.flush()
        return record
    except IntegrityError:
        existing = session.scalar(select(EvidenceValidityEvent).where(EvidenceValidityEvent.idempotency_key == key))
        if existing:
            return existing
        raise


def _append_reconciliation_event(session: Session, state: KnowledgeState,
                                 *, invalid_attempt_ids: list[str],
                                 before_status: str, after_status: str,
                                 reason: str) -> DecisionEvent:
    key = f"evidence-reconcile:phase6.1:{state.id}:{','.join(sorted(invalid_attempt_ids))}"
    existing = session.scalar(select(DecisionEvent).where(DecisionEvent.idempotency_key == key))
    if existing:
        return existing
    event = DecisionEvent(
        id=f"evt_{uuid4().hex[:16]}", session_id=session.get(Attempt, invalid_attempt_ids[0]).session_id,
        event_type="evidence_validity_reconciled", from_state=before_status,
        to_state=after_status, action="reconcile_learning_state",
        reason=reason, uncertainty_level="insufficient_evidence",
        payload_json={"knowledge_state_id": state.id, "invalidated_attempt_ids": sorted(invalid_attempt_ids),
                      "status_before": before_status, "status_after": after_status},
        idempotency_key=key, created_at=datetime.now(timezone.utc),
    )
    try:
        with session.begin_nested():
            session.add(event)
            session.flush()
        return event
    except IntegrityError:
        existing = session.scalar(select(DecisionEvent).where(DecisionEvent.idempotency_key == key))
        if existing:
            return existing
        raise


def apply_reconciliation(session: Session, plan: dict[str, Any] | None = None) -> dict[str, Any]:
    """Apply a previously reviewed plan in the caller's isolated transaction."""
    plan = plan or build_reconciliation_plan(session)
    group_by_id = {item.group.id: item for item in [
        version for entry in load_registry()["entries"] for version in _exact_versions(session, entry)
    ]}
    for item in plan["versions"]:
        exact = group_by_id[item["group_version_id"]]
        replacement = session.get(ReadingGroupVersion, item["replacement_group_version_id"]) if item["replacement_group_version_id"] else None
        key = f"phase6.1:version:{exact.group.id}:{item['status']}"
        affected_attempt_ids = sorted(set(plan["attempts_invalidated"]) | set(plan["attempts_review_required"]))
        affected_attempt_ids = [attempt_id for attempt_id in affected_attempt_ids
            if (attempt := session.get(Attempt, attempt_id)) is not None
            and attempt.group_version_id == exact.group.id]
        _append_validity_event(
            session, target_type="reading_group_version", target_id=exact.group.id,
            status=item["status"], reason=item["reason"], source=SOURCE, key=key,
            group_version=exact.group, rules_version=exact.rule.rules_version,
            replacement=replacement, refs={"registry_source": plan["source"],
                "registry_version": plan["registry_version"],
                "affected_attempt_ids": affected_attempt_ids},
        )

    invalid_group_ids = {v["group_version_id"]: v for v in plan["versions"] if v["status"] == EvidenceValidityStatus.INVALIDATED.value}
    for attempt_id in plan["attempts_invalidated"]:
        attempt = session.get(Attempt, attempt_id)
        group_info = invalid_group_ids.get(attempt.group_version_id) if attempt else None
        group = session.get(ReadingGroupVersion, attempt.group_version_id) if attempt and attempt.group_version_id else None
        refs = _attempt_dependency_refs(session, attempt) if attempt else {}
        _append_validity_event(
            session, target_type="attempt", target_id=attempt_id,
            status=EvidenceValidityStatus.INVALIDATED.value,
            reason="Attempt result is preserved as historically recorded but cannot support current ability or retention because its immutable task version is invalidated.",
            source=SOURCE, key=f"phase6.1:attempt:{attempt_id}:invalidated",
            group_version=group,
            rules_version=(session.get(ReadingRuleVersion, group.rule_version_id).rules_version if group else None),
            replacement=(session.get(ReadingGroupVersion, group_info.get("replacement_group_version_id")) if group_info and group_info.get("replacement_group_version_id") else None),
            refs=refs,
        )
    for attempt_id in plan["attempts_review_required"]:
        attempt = session.get(Attempt, attempt_id)
        refs = _attempt_dependency_refs(session, attempt) if attempt else {}
        snapshot = (attempt.group_snapshot_json or {}) if attempt else {}
        q_snapshot = (attempt.question_snapshot_json or {}) if attempt else {}
        refs["unresolved_group_provenance"] = {
            "group_id": snapshot.get("group_id") or q_snapshot.get("group_id"),
            "content_version": snapshot.get("content_version") or q_snapshot.get("content_version"),
            "rules_version": snapshot.get("rules_version") or q_snapshot.get("rules_version"),
        }
        _append_validity_event(
            session, target_type="attempt", target_id=attempt_id,
            status=EvidenceValidityStatus.REVIEW_REQUIRED.value,
            reason="Matching Headings transfer/review attempt lacks a resolvable immutable group version; it is not used to claim ability until provenance is reviewed.",
            source=SOURCE, key=f"phase6.1:attempt:{attempt_id}:review-required",
            refs=refs,
        )

    # Preserve EvidenceLinks as historical records while marking their current
    # evidentiary fitness through the same append-only ledger.
    for attempt_id, status, reason in [
        *((attempt_id, EvidenceValidityStatus.INVALIDATED.value,
           "Evidence link depends on an Attempt scored with an invalidated immutable reading version.")
          for attempt_id in plan["attempts_invalidated"]),
        *((attempt_id, EvidenceValidityStatus.REVIEW_REQUIRED.value,
           "Evidence link depends on an Attempt whose immutable reading version provenance requires review.")
          for attempt_id in plan["attempts_review_required"]),
    ]:
        attempt = session.get(Attempt, attempt_id)
        if not attempt:
            continue
        for link in session.scalars(select(EvidenceLink).where(EvidenceLink.attempt_id == attempt.id)).all():
            group = session.get(ReadingGroupVersion, attempt.group_version_id) if attempt.group_version_id else None
            rule = session.get(ReadingRuleVersion, group.rule_version_id) if group else None
            _append_validity_event(
                session, target_type="evidence_link", target_id=link.id, status=status,
                reason=reason, source=SOURCE,
                key=f"phase6.1:evidence-link:{link.id}:{status}", group_version=group,
                rules_version=rule.rules_version if rule else None,
                refs={"attempt_id": attempt.id, "hypothesis_id": link.hypothesis_id,
                      "decision_event_id": link.decision_event_id,
                      "source_ref": link.source_ref},
            )

    for review_id in plan["review_items_invalidated"]:
        item = session.get(ReviewItem, review_id)
        group = session.get(ReadingGroupVersion, item.group_version_id) if item and item.group_version_id else None
        attempt = session.get(Attempt, item.attempt_id) if item and item.attempt_id else None
        _append_validity_event(
            session, target_type="review_item", target_id=review_id,
            status=EvidenceValidityStatus.INVALIDATED.value,
            reason="This ReviewItem depends on an invalidated transfer or review result; historical completion is retained but its retention claim is not current evidence.",
            source=SOURCE, key=f"phase6.1:review:{review_id}:invalidated",
            group_version=group,
            rules_version=(session.get(ReadingRuleVersion, group.rule_version_id).rules_version if group else None),
            refs={"trigger_attempt_id": item.trigger_attempt_id if item else None,
                  "attempt_id": item.attempt_id if item else None,
                  "review_session_id": item.review_session_id if item else None},
        )

    # Recompute only states whose last Matching Headings transfer was affected.
    # Other topics (including the legacy Python stable path) are never touched.
    state_results = []
    invalid_ids = set(plan["attempts_invalidated"]) | set(plan["attempts_review_required"])
    for state_plan in plan["knowledge_states"]:
        state = session.get(KnowledgeState, state_plan["id"])
        if state is None:
            continue
        invalid_attempt_ids = [aid for aid in invalid_ids
                               if (attempt := session.get(Attempt, aid)) is not None
                               and attempt.session.learner_id == state.learner_id
                               and attempt.session.topic_id == state.topic_id]
        if not invalid_attempt_ids:
            continue
        candidates = session.scalars(
            select(Attempt).join(LearningSession, Attempt.session_id == LearningSession.id)
            .join(Question, Attempt.question_id == Question.id)
            .where(
                LearningSession.learner_id == state.learner_id,
                LearningSession.topic_id == state.topic_id,
                Question.question_type == QuestionType.MATCHING_HEADINGS.value,
                Attempt.attempt_role == QuestionRole.TRANSFER_CHECK.value,
                Attempt.evaluation_status == AttemptEvaluationStatus.EVALUATED.value,
                Attempt.is_correct.is_(True),
            ).order_by(Attempt.submitted_at.desc())
        ).all()
        valid_alternate = next((candidate for candidate in candidates
                                if candidate.id not in invalid_ids
                                and evidence_status(session, "attempt", candidate.id) == EvidenceValidityStatus.ELIGIBLE.value), None)
        before = state.status
        if valid_alternate:
            after = KnowledgeMasteryStatus.TRANSFER_VERIFIED.value
            reason = "An independent eligible Matching Headings transfer remains available; invalid historical evidence was excluded."
            state.last_transfer_attempt_id = valid_alternate.id
        else:
            after = KnowledgeMasteryStatus.INSUFFICIENT_EVIDENCE.value
            reason = "Historical Matching Headings transfer evidence was invalidated or requires provenance review; no independent eligible transfer remains. Revalidation is pending, and this is not attributed to learner ability."
            # Keep the historical pointer for traceability and to recover the
            # exam variant for the revalidation entry point. The current status
            # is corrected below, and all consumers resolve this pointer through
            # evidence_status() before treating it as proof.
        desired_transfer_id = valid_alternate.id if valid_alternate else state_plan["last_transfer_attempt_id"]
        if before != after or state.last_transfer_attempt_id != desired_transfer_id:
            decision = _append_reconciliation_event(
                session, state, invalid_attempt_ids=invalid_attempt_ids,
                before_status=before, after_status=after, reason=reason,
            )
            state.status = after
            state.last_transfer_attempt_id = desired_transfer_id
            state.transition_reason = reason
            state.last_decision_event_id = decision.id
            state.updated_at = datetime.now(timezone.utc)
            _append_validity_event(
                session, target_type="knowledge_state", target_id=state.id,
                status=(EvidenceValidityStatus.ELIGIBLE.value if valid_alternate
                        else EvidenceValidityStatus.REVIEW_REQUIRED.value),
                reason=reason, source=SOURCE,
                key=f"phase6.1:knowledge-state:{state.id}:{','.join(sorted(invalid_attempt_ids))}",
                group_version=(session.get(ReadingGroupVersion, valid_alternate.group_version_id)
                               if valid_alternate and valid_alternate.group_version_id else None),
                rules_version=(session.get(ReadingRuleVersion, session.get(ReadingGroupVersion, valid_alternate.group_version_id).rule_version_id).rules_version
                               if valid_alternate and valid_alternate.group_version_id else None),
                refs={"invalidated_attempt_ids": sorted(invalid_attempt_ids),
                      "decision_event_id": decision.id,
                      "last_transfer_attempt_id": state.last_transfer_attempt_id},
            )
            state_results.append({"knowledge_state_id": state.id, "before": before,
                                  "after": after, "valid_transfer_attempt_id": state.last_transfer_attempt_id,
                                  "decision_event_id": decision.id})

    session.flush()
    return {"applied": True, "knowledge_state_changes": state_results,
            "reconciliation_counts": plan["counts"]}


def _attempt_dependency_refs(session: Session, attempt: Attempt) -> dict[str, Any]:
    """Collect stable downstream references without rewriting historical events."""
    cases = session.scalars(select(DiagnosticCase).where(DiagnosticCase.trigger_attempt_id == attempt.id)).all()
    evidence = session.scalars(select(EvidenceLink).where(EvidenceLink.attempt_id == attempt.id)).all()
    reviews = session.scalars(select(ReviewItem).where(
        (ReviewItem.trigger_attempt_id == attempt.id) | (ReviewItem.attempt_id == attempt.id)
    )).all()
    decisions = session.scalars(select(DecisionEvent).where(DecisionEvent.session_id == attempt.session_id)).all()
    referenced_decisions = []
    for event in decisions:
        payload = event.payload_json or {}
        if attempt.id in {
            payload.get("attempt_id"), payload.get("transfer_attempt_id"),
            payload.get("trigger_attempt_id"), payload.get("replaced_attempt_id"),
        }:
            referenced_decisions.append(event.id)
    return {
        "question_id": attempt.question_id,
        "session_id": attempt.session_id,
        "attempt_role": attempt.attempt_role,
        "diagnostic_case_ids": [case.id for case in cases],
        "evidence_link_ids": [link.id for link in evidence],
        "review_item_ids": [item.id for item in reviews],
        "decision_event_ids": referenced_decisions,
    }
