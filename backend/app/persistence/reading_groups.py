"""Explicit importer for immutable, server-owned reading content versions."""
import hashlib
import json
from typing import Any

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.domain.reading_groups import HeadingAnswerKey, MatchingHeadingsGroup
from app.persistence.models import ReadingGroupVersion, ReadingRuleVersion


def _digest(value: Any) -> str:
    data = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(data.encode("utf-8")).hexdigest()


def import_matching_headings(session: Session, *, display: dict[str, Any],
                             private_rules: dict[str, Any], exam_variant: str,
                             provenance: dict[str, Any]) -> ReadingGroupVersion:
    """Validate and deduplicate immutable content; caller owns the transaction."""
    if exam_variant not in {"academic", "general_training"}:
        raise ValueError("Unsupported exam variant")
    if not all(isinstance(provenance.get(k), str) and provenance[k].strip()
               for k in ("source", "license")):
        raise ValueError("Content source and license are required")
    if private_rules.get("diagnostics", {}).get("role") in {"transfer_check", "review"}:
        independence = provenance.get("independence_review")
        if (
            not isinstance(independence, dict)
            or not isinstance(independence.get("independence_id"), str)
            or not independence["independence_id"].strip()
            or not isinstance(independence.get("independent_from_group_ids"), list)
            or not independence["independent_from_group_ids"]
            or not isinstance(independence.get("independence_basis"), str)
            or not independence["independence_basis"].strip()
        ):
            raise ValueError("Transfer and review content requires an auditable independence record")
    group = MatchingHeadingsGroup.model_validate(display)
    key = HeadingAnswerKey.model_validate(private_rules)
    items, options = {i.id for i in group.items}, {o.id for o in group.options}
    if (set(key.answers) != items or set(key.explanations) != items
            or not set(key.answers.values()) <= options
            or (not group.allow_reuse and len(set(key.answers.values())) != len(items))):
        raise ValueError("Invalid private rules for this group")
    if key.diagnostics:
        key.diagnostics.validate_for(group, key.answers)
    public = group.model_dump(mode="json")
    rules = key.model_dump(mode="json", exclude_none=True)
    rule_hash = _digest(rules)
    rule = session.scalar(select(ReadingRuleVersion).where(ReadingRuleVersion.content_hash == rule_hash))
    if rule is None:
        rule = ReadingRuleVersion(id="rr_" + rule_hash[:32], rules_version=key.rules_version,
                                  content_hash=rule_hash, private_rules_json=rules)
        session.add(rule)
        session.flush()
    payload = {"display": public, "exam_variant": exam_variant,
               "provenance": provenance, "rule_hash": rule_hash}
    content_hash = _digest(payload)
    existing = session.scalar(select(ReadingGroupVersion).where(
        ReadingGroupVersion.group_id == group.id, ReadingGroupVersion.content_hash == content_hash))
    if existing is not None:
        return existing
    version = ReadingGroupVersion(id="rg_" + content_hash[:32], group_id=group.id,
                                  question_type=group.question_type, exam_variant=exam_variant,
                                  content_version=group.passage.content_version,
                                  display_schema_version=group.display_schema_version,
                                  display_json=public, rule_version_id=rule.id,
                                  content_hash=content_hash, provenance_json=dict(provenance))
    session.add(version)
    session.flush()
    return version
