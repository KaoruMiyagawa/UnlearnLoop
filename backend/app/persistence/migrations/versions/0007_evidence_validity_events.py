"""Add append-only evidence validity audit events.

Revision ID: 0007_evidence_validity_events
Revises: 0006_matching_headings_review_provenance
"""
from alembic import op
import sqlalchemy as sa


revision = "0007_evidence_validity_events"
down_revision = "0006_matching_headings_review_provenance"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "evidence_validity_events",
        sa.Column("id", sa.String(length=64), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("group_version_id", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("content_version", sa.String(length=64), nullable=True),
        sa.Column("rules_version", sa.String(length=64), nullable=True),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("source", sa.String(length=256), nullable=False),
        sa.Column("replacement_group_version_id", sa.String(length=64), nullable=True),
        sa.Column("affected_refs_json", sa.JSON(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=192), nullable=False),
        sa.Column("audited_at", sa.DateTime(timezone=True), nullable=False),
        sa.CheckConstraint(
            "status IN ('eligible', 'invalidated', 'review_required')",
            name="ck_evidence_validity_status",
        ),
        sa.ForeignKeyConstraint(
            ["group_version_id"], ["reading_group_versions.id"],
            name="fk_evidence_validity_group_version", ondelete="RESTRICT",
        ),
        sa.ForeignKeyConstraint(
            ["replacement_group_version_id"], ["reading_group_versions.id"],
            name="fk_evidence_validity_replacement_group_version", ondelete="RESTRICT",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("idempotency_key", name="uq_evidence_validity_idempotency_key"),
    )
    op.create_index(
        "ix_evidence_validity_target", "evidence_validity_events",
        ["target_type", "target_id", "audited_at"], unique=False,
    )
    if op.get_bind().dialect.name == "sqlite":
        for action in ("UPDATE", "DELETE"):
            op.execute(
                f"CREATE TRIGGER prevent_evidence_validity_events_{action.lower()} "
                f"BEFORE {action} ON evidence_validity_events "
                "BEGIN SELECT RAISE(ABORT, 'evidence validity events are append-only'); END"
            )


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        op.execute("DROP TRIGGER IF EXISTS prevent_evidence_validity_events_update")
        op.execute("DROP TRIGGER IF EXISTS prevent_evidence_validity_events_delete")
    op.drop_index("ix_evidence_validity_target", table_name="evidence_validity_events")
    op.drop_table("evidence_validity_events")
