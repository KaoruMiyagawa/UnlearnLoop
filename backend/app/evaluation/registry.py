"""Explicit domain-to-evaluator mapping. Unknown domains fail closed."""
from app.domain.exceptions import DomainRuleViolationError
from app.evaluation.ielts_reading_evaluator import IeltsReadingEvaluator
from app.evaluation.rule_evaluator import RuleEvaluator

_PYTHON = RuleEvaluator()
_IELTS_READING = IeltsReadingEvaluator()


def evaluator_for_domain(domain_code: str):
    if domain_code == "python":
        return _PYTHON
    if domain_code in {"ielts_academic", "ielts_general_training"}:
        return _IELTS_READING
    raise DomainRuleViolationError(f"No objective evaluator is configured for domain '{domain_code}'.")
