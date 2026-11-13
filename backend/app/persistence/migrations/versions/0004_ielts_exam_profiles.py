"""Add exam-goal profiles and version snapshots for new sessions.

Revision ID: 0004_ielts_exam_profiles
Revises: 0003_evidence_based_reviews
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0004_ielts_exam_profiles"
down_revision: Union[str, None] = "0003_evidence_based_reviews"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("learning_sessions", sa.Column("exam_variant", sa.String(length=32), nullable=True))
    op.add_column("learning_sessions", sa.Column("exam_spec_version", sa.String(length=64), nullable=True))
    op.create_table(
        "exam_preparation_profiles",
        sa.Column("learner_id", sa.String(length=64), primary_key=True),
        sa.Column("exam_variant", sa.String(length=32), nullable=False),
        sa.Column("goal_type", sa.String(length=16), nullable=False, server_default="band"),
        sa.Column("target_overall_band", sa.Float(), nullable=True),
        sa.Column("target_skill_bands", sa.JSON(), nullable=True),
        sa.Column("target_outcome", sa.String(length=16), nullable=True),
        sa.Column("exam_date", sa.Date(), nullable=True),
        sa.Column("actual_level_status", sa.String(length=24), nullable=False, server_default="not_assessed"),
        sa.Column("spec_version", sa.String(length=64), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "goal_type = 'band' AND target_overall_band IS NOT NULL AND target_outcome IS NULL "
            "OR goal_type = 'pass' AND target_overall_band IS NULL AND target_outcome = 'pass'",
            name="ck_exam_profile_goal_matches_scoring_system",
        ),
        sa.CheckConstraint(
            "actual_level_status IN ('not_assessed', 'assessed')",
            name="ck_exam_profile_actual_level_status",
        ),
    )


def downgrade() -> None:
    op.drop_table("exam_preparation_profiles")
    op.drop_column("learning_sessions", "exam_spec_version")
    op.drop_column("learning_sessions", "exam_variant")
