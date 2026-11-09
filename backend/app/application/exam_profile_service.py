"""Exam catalogue and learner goal persistence for the first IELTS slice."""

from sqlalchemy.orm import Session

from app.api.v1.schemas import (
    ExamCatalogEntryResponse,
    ExamPreparationProfileResponse,
    ExamPreparationProfileUpdate,
)
from app.application.exceptions import EntityNotFoundError
from app.domain.exams import (
    EXAM_CATALOG,
    EXAM_CATALOG_VERSION,
    ExamAvailability,
    domain_for_variant,
    get_exam_definition,
)
from app.domain.exceptions import DomainRuleViolationError
from app.persistence.models import ExamPreparationProfile, utc_now

SKILLS = ("listening", "reading", "writing", "speaking")


class ExamProfileService:
    def __init__(self, session: Session) -> None:
        self.session = session

    def list_catalog(self) -> list[ExamCatalogEntryResponse]:
        return [
            ExamCatalogEntryResponse(
                code=item.code.value,
                label=item.label,
                base_variant=item.base_variant,
                scoring_system=item.scoring_system,
                availability=item.availability.value,
                purpose=item.purpose,
                spec_version=EXAM_CATALOG_VERSION,
            )
            for item in EXAM_CATALOG
        ]

    def get_profile(self, learner_id: str) -> ExamPreparationProfileResponse:
        row = self.session.get(ExamPreparationProfile, learner_id)
        if row is None:
            # Return a default view; only an explicit PUT persists a user's selection.
            return self._response(
                learner_id=learner_id,
                exam_variant="academic",
                target_overall_band=8.0,
                target_skill_bands={skill: 8.0 for skill in SKILLS},
                exam_date=None,
                actual_level_status="not_assessed",
                spec_version=EXAM_CATALOG_VERSION,
                selection_persisted=False,
            )
        return self._response(
            learner_id=row.learner_id,
            exam_variant=row.exam_variant,
            target_overall_band=row.target_overall_band,
            target_skill_bands=row.target_skill_bands,
            target_outcome=row.target_outcome,
            exam_date=row.exam_date,
            actual_level_status=row.actual_level_status,
            spec_version=row.spec_version,
            selection_persisted=True,
        )

    def update_profile(
        self, learner_id: str, payload: ExamPreparationProfileUpdate
    ) -> ExamPreparationProfileResponse:
        definition = get_exam_definition(payload.exam_variant)
        if definition is None:
            raise DomainRuleViolationError("Unknown IELTS exam variant.")
        if definition.availability != ExamAvailability.AVAILABLE or domain_for_variant(payload.exam_variant) is None:
            raise DomainRuleViolationError(
                f"{definition.label} is planned and cannot be selected yet."
            )
        row = self.session.get(ExamPreparationProfile, learner_id)
        if row is None:
            row = ExamPreparationProfile(
                learner_id=learner_id,
                exam_variant=payload.exam_variant,
                goal_type="band",
                spec_version=EXAM_CATALOG_VERSION,
            )
            self.session.add(row)
        row.exam_variant = payload.exam_variant
        row.goal_type = "band"
        row.target_overall_band = payload.target_overall_band
        row.target_skill_bands = dict(payload.target_skill_bands)
        row.target_outcome = None
        row.exam_date = payload.exam_date
        row.actual_level_status = "not_assessed"
        row.spec_version = EXAM_CATALOG_VERSION
        row.updated_at = utc_now()
        self.session.flush()
        response = self.get_profile(learner_id)
        self.session.commit()
        return response

    @staticmethod
    def _response(
        *, learner_id: str, exam_variant: str,
        target_overall_band: float | None,
        target_skill_bands: dict[str, float] | None,
        exam_date=None, target_outcome: str | None = None,
        actual_level_status: str, spec_version: str,
        selection_persisted: bool = True,
    ) -> ExamPreparationProfileResponse:
        definition = get_exam_definition(exam_variant)
        if definition is None:
            raise EntityNotFoundError("ExamVariant", exam_variant)
        return ExamPreparationProfileResponse(
            learner_id=learner_id,
            selection_persisted=selection_persisted,
            exam_variant=exam_variant,
            selection_status=definition.availability.value,
            goal_type="pass" if definition.scoring_system == "pass_fail" else "band",
            target_overall_band=target_overall_band,
            target_skill_bands=target_skill_bands,
            target_outcome=target_outcome,
            exam_date=exam_date,
            actual_level_status=actual_level_status,
            current_skill_bands={skill: None for skill in SKILLS},
            spec_version=spec_version,
        )
