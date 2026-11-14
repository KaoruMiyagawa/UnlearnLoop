"""Add metadata for speaking practice; audio stays in the browser."""

from alembic import op
import sqlalchemy as sa

revision = "0009_speaking_practice"
down_revision = "0008_writing_revisions"
branch_labels = None
depends_on = None


def upgrade():
    op.create_table(
        "speaking_practices",
        sa.Column("recording_id", sa.String(64), primary_key=True),
        sa.Column("session_id", sa.String(64), sa.ForeignKey("learning_sessions.id"), nullable=False),
        sa.Column("prompt_id", sa.String(64), nullable=False),
        sa.Column("prompt_version", sa.String(64), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("duration_seconds", sa.Float(), nullable=False),
        sa.Column("recorded_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("self_check", sa.JSON(), nullable=False),
        sa.Column("evaluation_status", sa.String(32), nullable=False),
        sa.Column("evidence_type", sa.String(32), nullable=False),
    )
    op.create_index("ix_speaking_practices_session_id", "speaking_practices", ["session_id"])


def downgrade():
    op.drop_index("ix_speaking_practices_session_id", table_name="speaking_practices")
    op.drop_table("speaking_practices")
