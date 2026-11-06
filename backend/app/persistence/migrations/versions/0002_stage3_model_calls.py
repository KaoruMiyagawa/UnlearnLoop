"""Add Stage 3 model_calls table for redacted AI invocation audit logs.

Revision ID: 0002_stage3_model_calls
Revises: 0001_initial_stage2_schema
Create Date: 2026-11-06 16:22:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0002_stage3_model_calls"
down_revision: Union[str, None] = "0001_initial_stage2_schema"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "model_calls",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("diagnostic_case_id", sa.String(length=64), nullable=True),
        sa.Column("decision_event_id", sa.String(length=64), nullable=True),
        sa.Column("provider_name", sa.String(length=64), nullable=False),
        sa.Column("model_name", sa.String(length=100), nullable=False),
        sa.Column("prompt_version", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("latency_ms", sa.Integer(), nullable=False),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False),
        sa.Column("completion_tokens", sa.Integer(), nullable=False),
        sa.Column("total_tokens", sa.Integer(), nullable=False),
        sa.Column("attempt_count", sa.Integer(), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=True),
        sa.Column("redacted_summary", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("latency_ms >= 0", name="ck_model_calls_latency_nonneg"),
        sa.CheckConstraint("total_tokens >= 0", name="ck_model_calls_tokens_nonneg"),
        sa.ForeignKeyConstraint(
            ["decision_event_id"],
            ["decision_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["diagnostic_case_id"],
            ["diagnostic_cases.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_model_calls_diagnostic_case_id",
        "model_calls",
        ["diagnostic_case_id"],
        unique=False,
    )
    op.create_index(
        "ix_model_calls_session_id",
        "model_calls",
        ["session_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("model_calls")
