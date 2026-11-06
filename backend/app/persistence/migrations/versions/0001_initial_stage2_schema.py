"""Initial Stage 2 domain schema migration.

Revision ID: 0001_initial_stage2_schema
Revises: None
Create Date: 2026-11-06 15:55:00
"""

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0001_initial_stage2_schema"
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "knowledge_topics",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("slug", sa.String(length=100), nullable=False),
        sa.Column("domain_code", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("difficulty_level", sa.Integer(), nullable=False),
        sa.Column("common_error_patterns", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("slug"),
    )
    op.create_index(
        "ix_knowledge_topics_domain_code",
        "knowledge_topics",
        ["domain_code"],
        unique=False,
    )

    op.create_table(
        "knowledge_topic_dependencies",
        sa.Column("topic_id", sa.String(length=64), nullable=False),
        sa.Column("prerequisite_topic_id", sa.String(length=64), nullable=False),
        sa.CheckConstraint(
            "topic_id != prerequisite_topic_id",
            name="ck_topic_dependency_not_self",
        ),
        sa.ForeignKeyConstraint(
            ["prerequisite_topic_id"],
            ["knowledge_topics.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["knowledge_topics.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("topic_id", "prerequisite_topic_id"),
    )

    op.create_table(
        "learning_materials",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("topic_id", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=200), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("content_body", sa.Text(), nullable=False),
        sa.Column("content_format", sa.String(length=32), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["knowledge_topics.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_materials_topic_id",
        "learning_materials",
        ["topic_id"],
        unique=False,
    )

    op.create_table(
        "questions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("topic_id", sa.String(length=64), nullable=False),
        sa.Column("material_id", sa.String(length=64), nullable=True),
        sa.Column("parent_question_id", sa.String(length=64), nullable=True),
        sa.Column("question_role", sa.String(length=32), nullable=False),
        sa.Column("question_type", sa.String(length=32), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("context_snippet", sa.Text(), nullable=True),
        sa.Column("standard_answer", sa.Text(), nullable=False),
        sa.Column("answer_explanation", sa.Text(), nullable=False),
        sa.Column("evaluation_rubric", sa.JSON(), nullable=False),
        sa.Column("difficulty", sa.Integer(), nullable=False),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint("difficulty >= 1", name="ck_questions_difficulty_positive"),
        sa.CheckConstraint("version >= 1", name="ck_questions_version_positive"),
        sa.ForeignKeyConstraint(
            ["material_id"],
            ["learning_materials.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["parent_question_id"],
            ["questions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["knowledge_topics.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_questions_question_role",
        "questions",
        ["question_role"],
        unique=False,
    )
    op.create_index(
        "ix_questions_topic_id",
        "questions",
        ["topic_id"],
        unique=False,
    )

    op.create_table(
        "learning_sessions",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("topic_id", sa.String(length=64), nullable=False),
        sa.Column("current_question_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["current_question_id"],
            ["questions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["knowledge_topics.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_learning_sessions_learner_id",
        "learning_sessions",
        ["learner_id"],
        unique=False,
    )
    op.create_index(
        "ix_learning_sessions_topic_id",
        "learning_sessions",
        ["topic_id"],
        unique=False,
    )

    op.create_table(
        "attempts",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("question_id", sa.String(length=64), nullable=False),
        sa.Column("question_version", sa.Integer(), nullable=False),
        sa.Column("question_snapshot_json", sa.JSON(), nullable=False),
        sa.Column("attempt_role", sa.String(length=32), nullable=False),
        sa.Column("submitted_answer", sa.Text(), nullable=False),
        sa.Column("is_correct", sa.Boolean(), nullable=True),
        sa.Column("evaluation_status", sa.String(length=32), nullable=False),
        sa.Column("evaluation_summary", sa.Text(), nullable=True),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("submitted_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["question_id"],
            ["questions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_attempts_question_id",
        "attempts",
        ["question_id"],
        unique=False,
    )
    op.create_index(
        "ix_attempts_session_id",
        "attempts",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "diagnostic_cases",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("trigger_attempt_id", sa.String(length=64), nullable=False),
        sa.Column("topic_id", sa.String(length=64), nullable=False),
        sa.Column("current_followup_question_id", sa.String(length=64), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("uncertainty_note", sa.Text(), nullable=True),
        sa.Column("selected_intervention", sa.String(length=32), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["current_followup_question_id"],
            ["questions.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["knowledge_topics.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["trigger_attempt_id"],
            ["attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_diagnostic_cases_session_id",
        "diagnostic_cases",
        ["session_id"],
        unique=False,
    )
    op.create_index(
        "ix_diagnostic_cases_topic_id",
        "diagnostic_cases",
        ["topic_id"],
        unique=False,
    )

    op.create_table(
        "hypotheses",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("diagnostic_case_id", sa.String(length=64), nullable=False),
        sa.Column("error_code", sa.String(length=64), nullable=False),
        sa.Column("name", sa.String(length=200), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("missing_evidence_desc", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_hypotheses_confidence_range",
        ),
        sa.ForeignKeyConstraint(
            ["diagnostic_case_id"],
            ["diagnostic_cases.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "diagnostic_case_id",
            "error_code",
            name="uq_hypothesis_case_error_code",
        ),
    )
    op.create_index(
        "ix_hypotheses_diagnostic_case_id",
        "hypotheses",
        ["diagnostic_case_id"],
        unique=False,
    )

    op.create_table(
        "decision_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=False),
        sa.Column("diagnostic_case_id", sa.String(length=64), nullable=True),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("from_state", sa.String(length=64), nullable=True),
        sa.Column("to_state", sa.String(length=64), nullable=False),
        sa.Column("action", sa.String(length=64), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("uncertainty_level", sa.String(length=32), nullable=False),
        sa.Column("payload_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=128), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
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
        sa.UniqueConstraint("idempotency_key"),
    )
    op.create_index(
        "ix_decision_events_diagnostic_case_id",
        "decision_events",
        ["diagnostic_case_id"],
        unique=False,
    )
    op.create_index(
        "ix_decision_events_session_id",
        "decision_events",
        ["session_id"],
        unique=False,
    )

    op.create_table(
        "evidence_links",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("hypothesis_id", sa.String(length=64), nullable=False),
        sa.Column("attempt_id", sa.String(length=64), nullable=True),
        sa.Column("decision_event_id", sa.String(length=64), nullable=True),
        sa.Column("source_type", sa.String(length=32), nullable=False),
        sa.Column("source_ref", sa.String(length=128), nullable=False),
        sa.Column("relation", sa.String(length=32), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("reliability_note", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(source_ref)) > 0",
            name="ck_evidence_links_source_ref_nonempty",
        ),
        sa.CheckConstraint(
            "length(trim(summary)) > 0",
            name="ck_evidence_links_summary_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["attempt_id"],
            ["attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["decision_event_id"],
            ["decision_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["hypotheses.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_evidence_links_hypothesis_id",
        "evidence_links",
        ["hypothesis_id"],
        unique=False,
    )

    op.create_table(
        "knowledge_states",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("topic_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("unresolved_error_codes", sa.JSON(), nullable=False),
        sa.Column("last_evidence_id", sa.String(length=64), nullable=True),
        sa.Column("last_decision_event_id", sa.String(length=64), nullable=False),
        sa.Column("last_transfer_attempt_id", sa.String(length=64), nullable=True),
        sa.Column("transition_reason", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "length(trim(transition_reason)) > 0",
            name="ck_knowledge_states_reason_nonempty",
        ),
        sa.ForeignKeyConstraint(
            ["last_decision_event_id"],
            ["decision_events.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_evidence_id"],
            ["evidence_links.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["last_transfer_attempt_id"],
            ["attempts.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["knowledge_topics.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "learner_id",
            "topic_id",
            name="uq_knowledge_state_learner_topic",
        ),
    )
    op.create_index(
        "ix_knowledge_states_learner_id",
        "knowledge_states",
        ["learner_id"],
        unique=False,
    )
    op.create_index(
        "ix_knowledge_states_topic_id",
        "knowledge_states",
        ["topic_id"],
        unique=False,
    )

    op.create_table(
        "review_items",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("learner_id", sa.String(length=64), nullable=False),
        sa.Column("topic_id", sa.String(length=64), nullable=False),
        sa.Column("session_id", sa.String(length=64), nullable=True),
        sa.Column("hypothesis_id", sa.String(length=64), nullable=True),
        sa.Column("trigger_reason", sa.Text(), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("scheduled_for", sa.DateTime(timezone=True), nullable=False),
        sa.Column("completed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("review_outcome", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.ForeignKeyConstraint(
            ["hypothesis_id"],
            ["hypotheses.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["session_id"],
            ["learning_sessions.id"],
            ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["topic_id"],
            ["knowledge_topics.id"],
            ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_review_items_learner_id",
        "review_items",
        ["learner_id"],
        unique=False,
    )
    op.create_index(
        "ix_review_items_topic_id",
        "review_items",
        ["topic_id"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_table("review_items")
    op.drop_table("knowledge_states")
    op.drop_table("evidence_links")
    op.drop_table("decision_events")
    op.drop_table("hypotheses")
    op.drop_table("diagnostic_cases")
    op.drop_table("attempts")
    op.drop_table("learning_sessions")
    op.drop_table("questions")
    op.drop_table("learning_materials")
    op.drop_table("knowledge_topic_dependencies")
    op.drop_table("knowledge_topics")
