"""Add durable, attempt-backed review scheduling fields.

Revision ID: 0003_evidence_based_reviews
Revises: 0002_stage3_model_calls
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0003_evidence_based_reviews"
down_revision: Union[str, None] = "0002_stage3_model_calls"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_index(
        "uq_review_attempt_session_question",
        "attempts",
        ["session_id", "question_id"],
        unique=True,
        sqlite_where=sa.text("attempt_role = 'review'"),
        postgresql_where=sa.text("attempt_role = 'review'"),
    )
    op.add_column("review_items", sa.Column("schedule_key", sa.String(length=160), nullable=True))
    op.add_column("review_items", sa.Column("review_stage", sa.Integer(), server_default="0", nullable=False))
    op.add_column("review_items", sa.Column("review_session_id", sa.String(length=64), nullable=True))
    op.add_column("review_items", sa.Column("question_id", sa.String(length=64), nullable=True))
    op.add_column("review_items", sa.Column("attempt_id", sa.String(length=64), nullable=True))
    op.add_column("review_items", sa.Column("decision_event_id", sa.String(length=64), nullable=True))
    op.add_column("review_items", sa.Column("retention_verified", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("review_items", sa.Column("retention_eligible", sa.Boolean(), server_default=sa.false(), nullable=False))
    op.add_column("review_items", sa.Column("knowledge_state_id", sa.String(length=64), nullable=True))
    with op.batch_alter_table("review_items") as batch:
        batch.create_unique_constraint("uq_review_items_schedule_key", ["schedule_key"])
        batch.create_unique_constraint("uq_review_items_review_session_id", ["review_session_id"])
        batch.create_foreign_key("fk_review_items_review_session_id_learning_sessions", "learning_sessions", ["review_session_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_review_items_question_id_questions", "questions", ["question_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_review_items_attempt_id_attempts", "attempts", ["attempt_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_review_items_decision_event_id_decision_events", "decision_events", ["decision_event_id"], ["id"], ondelete="RESTRICT")
        batch.create_foreign_key("fk_review_items_knowledge_state_id_knowledge_states", "knowledge_states", ["knowledge_state_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    with op.batch_alter_table("review_items") as batch:
        batch.drop_constraint("fk_review_items_decision_event_id_decision_events", type_="foreignkey")
        batch.drop_constraint("fk_review_items_knowledge_state_id_knowledge_states", type_="foreignkey")
        batch.drop_constraint("fk_review_items_attempt_id_attempts", type_="foreignkey")
        batch.drop_constraint("fk_review_items_question_id_questions", type_="foreignkey")
        batch.drop_constraint("fk_review_items_review_session_id_learning_sessions", type_="foreignkey")
        batch.drop_constraint("uq_review_items_review_session_id", type_="unique")
        batch.drop_constraint("uq_review_items_schedule_key", type_="unique")
        for column in ("knowledge_state_id", "retention_eligible", "retention_verified", "decision_event_id", "attempt_id", "question_id", "review_session_id", "review_stage", "schedule_key"):
            batch.drop_column(column)
    op.drop_index("uq_review_attempt_session_question", table_name="attempts")
