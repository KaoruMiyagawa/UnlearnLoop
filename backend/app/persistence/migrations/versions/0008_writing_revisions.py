"""Persist writing drafts and immutable submissions."""

from alembic import op
import sqlalchemy as sa

revision = "0008_writing_revisions"
down_revision = "0007_evidence_validity_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "writing_drafts",
        sa.Column("session_id", sa.String(64), sa.ForeignKey("learning_sessions.id"), primary_key=True),
        sa.Column("task_snapshot", sa.JSON(), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_table(
        "writing_revisions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("writing_drafts.session_id"), nullable=False),
        sa.Column("number", sa.Integer(), nullable=False),
        sa.Column("source_revision_id", sa.String(64), sa.ForeignKey("writing_revisions.id")),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("base_version", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(100), nullable=False),
        sa.Column("feedback", sa.JSON(), nullable=False),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("session_id", "number", name="uq_writing_revision_number"),
        sa.UniqueConstraint("session_id", "idempotency_key", name="uq_writing_revision_key"),
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER writing_revisions_no_{action.lower()} "
                f"BEFORE {action} ON writing_revisions "
                "BEGIN SELECT RAISE(ABORT, 'writing revisions are immutable'); END"
            )


def downgrade() -> None:
    op.drop_table("writing_revisions")
    op.drop_table("writing_drafts")
