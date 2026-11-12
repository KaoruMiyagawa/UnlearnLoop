"""Pin Matching Headings review provenance and trigger attempt.

Revision ID: 0006_matching_headings_review_provenance
Revises: 0005_reading_groups
"""
from alembic import op
import sqlalchemy as sa

revision = "0006_matching_headings_review_provenance"
down_revision = "0005_reading_groups"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("review_items") as batch:
        batch.add_column(sa.Column("trigger_attempt_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("group_version_id", sa.String(64), nullable=True))
        batch.create_foreign_key(
            "fk_review_items_trigger_attempt_id_attempts", "attempts",
            ["trigger_attempt_id"], ["id"], ondelete="RESTRICT",
        )
        batch.create_foreign_key(
            "fk_review_items_group_version_id_reading_group_versions", "reading_group_versions",
            ["group_version_id"], ["id"], ondelete="RESTRICT",
        )


def downgrade() -> None:
    with op.batch_alter_table("review_items") as batch:
        batch.drop_constraint("fk_review_items_group_version_id_reading_group_versions", type_="foreignkey")
        batch.drop_constraint("fk_review_items_trigger_attempt_id_attempts", type_="foreignkey")
        batch.drop_column("group_version_id")
        batch.drop_column("trigger_attempt_id")
