"""Versioned product catalogue for IELTS preparation modes.

UKVI variants share Academic/General Training test structures. Availability here
describes this product's implementation, not the official test's availability.
"""

from dataclasses import dataclass
from enum import StrEnum


class ExamVariant(StrEnum):
    ACADEMIC = "academic"
    GENERAL_TRAINING = "general_training"
    UKVI_ACADEMIC = "ukvi_academic"
    UKVI_GENERAL_TRAINING = "ukvi_general_training"
    LIFE_SKILLS_A1 = "life_skills_a1"
    LIFE_SKILLS_A2 = "life_skills_a2"
    LIFE_SKILLS_B1 = "life_skills_b1"


class ExamAvailability(StrEnum):
    AVAILABLE = "available"
    PLANNED = "planned"


@dataclass(frozen=True)
class ExamDefinition:
    code: ExamVariant
    label: str
    base_variant: str | None
    scoring_system: str
    availability: ExamAvailability
    purpose: str


EXAM_CATALOG_VERSION = "ielts-spec-catalog-2026-03"

EXAM_CATALOG: tuple[ExamDefinition, ...] = (
    ExamDefinition(ExamVariant.ACADEMIC, "IELTS Academic", "academic", "band", ExamAvailability.AVAILABLE, "study"),
    ExamDefinition(ExamVariant.GENERAL_TRAINING, "IELTS General Training", "general_training", "band", ExamAvailability.AVAILABLE, "migration_or_work"),
    ExamDefinition(ExamVariant.UKVI_ACADEMIC, "IELTS for UKVI Academic", "academic", "band", ExamAvailability.PLANNED, "uk_visa_secure_test"),
    ExamDefinition(ExamVariant.UKVI_GENERAL_TRAINING, "IELTS for UKVI General Training", "general_training", "band", ExamAvailability.PLANNED, "uk_visa_secure_test"),
    ExamDefinition(ExamVariant.LIFE_SKILLS_A1, "IELTS Life Skills A1", None, "pass_fail", ExamAvailability.PLANNED, "life_skills"),
    ExamDefinition(ExamVariant.LIFE_SKILLS_A2, "IELTS Life Skills A2", None, "pass_fail", ExamAvailability.PLANNED, "life_skills"),
    ExamDefinition(ExamVariant.LIFE_SKILLS_B1, "IELTS Life Skills B1", None, "pass_fail", ExamAvailability.PLANNED, "life_skills"),
)


AVAILABLE_VARIANTS = frozenset(
    definition.code
    for definition in EXAM_CATALOG
    if definition.availability == ExamAvailability.AVAILABLE
)


def get_exam_definition(code: str) -> ExamDefinition | None:
    return next((definition for definition in EXAM_CATALOG if definition.code == code), None)


def domain_for_variant(code: str) -> str | None:
    definition = get_exam_definition(code)
    if definition is None or definition.code not in AVAILABLE_VARIANTS:
        return None
    return f"ielts_{definition.base_variant}"
