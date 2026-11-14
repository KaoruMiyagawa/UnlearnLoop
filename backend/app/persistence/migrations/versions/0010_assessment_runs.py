"""Add assessment workflow state without duplicating learning evidence."""
from alembic import op
import sqlalchemy as sa

revision = "0010_assessment_runs"
down_revision = "0009_speaking_practice"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "assessment_runs",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("learner_id", sa.String(64), nullable=False),
        sa.Column("assessment_version", sa.String(64), nullable=False),
        sa.Column("idempotency_key", sa.String(128), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True)),
        sa.UniqueConstraint("learner_id", "idempotency_key", name="uq_assessment_run_learner_key"),
        sa.CheckConstraint("status IN ('in_progress', 'completed')", name="ck_assessment_run_status"),
    )
    op.create_index("ix_assessment_runs_learner_id", "assessment_runs", ["learner_id"])
    op.create_table(
        "assessment_tasks",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("run_id", sa.String(64), sa.ForeignKey("assessment_runs.id", ondelete="CASCADE"), nullable=False),
        sa.Column("skill_id", sa.String(24), nullable=False),
        sa.Column("status", sa.String(24), nullable=False),
        sa.Column("evidence_source", sa.String(32)),
        sa.Column("evidence_reference", sa.String(64)),
        sa.UniqueConstraint("run_id", "skill_id", name="uq_assessment_task_run_skill"),
        sa.CheckConstraint("skill_id IN ('listening', 'speaking', 'reading', 'writing')", name="ck_assessment_task_skill"),
        sa.CheckConstraint("status IN ('not_started', 'in_progress', 'skipped', 'completed')", name="ck_assessment_task_status"),
        sa.CheckConstraint("status != 'completed' OR (evidence_source IS NOT NULL AND evidence_reference IS NOT NULL)", name="ck_assessment_task_completed_evidence"),
        sa.CheckConstraint("(evidence_source IS NULL AND evidence_reference IS NULL) OR (evidence_source IS NOT NULL AND evidence_reference IS NOT NULL)", name="ck_assessment_task_evidence_pair"),
    )
    op.create_index("ix_assessment_tasks_run_id", "assessment_tasks", ["run_id"])


def downgrade():
    op.drop_index("ix_assessment_tasks_run_id", table_name="assessment_tasks")
    op.drop_table("assessment_tasks")
    op.drop_index("ix_assessment_runs_learner_id", table_name="assessment_runs")
    op.drop_table("assessment_runs")
