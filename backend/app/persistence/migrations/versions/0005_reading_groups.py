"""Add versioned reading group persistence.

Revision ID: 0005_reading_groups
Revises: 0004_ielts_exam_profiles
"""
from alembic import op
import sqlalchemy as sa

revision = "0005_reading_groups"
down_revision = "0004_ielts_exam_profiles"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table("reading_rule_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("rules_version", sa.String(64), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False, unique=True),
        sa.Column("private_rules_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False))
    op.create_table("reading_group_versions",
        sa.Column("id", sa.String(64), primary_key=True),
        sa.Column("group_id", sa.String(64), nullable=False),
        sa.Column("question_type", sa.String(32), nullable=False),
        sa.Column("exam_variant", sa.String(32), nullable=False),
        sa.Column("content_version", sa.String(64), nullable=False),
        sa.Column("display_schema_version", sa.String(64), nullable=False),
        sa.Column("display_json", sa.JSON(), nullable=False),
        sa.Column("rule_version_id", sa.String(64), sa.ForeignKey("reading_rule_versions.id", ondelete="RESTRICT"), nullable=False),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("provenance_json", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("group_id", "content_hash", name="uq_reading_group_content"))
    op.create_index("ix_reading_group_versions_group_id", "reading_group_versions", ["group_id"])
    if op.get_bind().dialect.name == "sqlite":
        for table in ("reading_group_versions", "reading_rule_versions"):
            for action in ("UPDATE", "DELETE"):
                op.execute(f"CREATE TRIGGER prevent_{table}_{action.lower()} BEFORE {action} ON {table} BEGIN SELECT RAISE(ABORT, 'reading versions are immutable'); END")
        # SQLite supports adding nullable inline references without rebuilding
        # tables that are already referenced by historical learning records.
        op.execute("ALTER TABLE questions ADD COLUMN reading_group_version_id VARCHAR(64) REFERENCES reading_group_versions(id) ON DELETE RESTRICT")
        op.execute("ALTER TABLE learning_sessions ADD COLUMN current_group_version_id VARCHAR(64) REFERENCES reading_group_versions(id) ON DELETE RESTRICT")
        op.execute("ALTER TABLE attempts ADD COLUMN group_version_id VARCHAR(64) REFERENCES reading_group_versions(id) ON DELETE RESTRICT")
        for name, kind in (("structured_answer_json", sa.JSON()), ("group_snapshot_json", sa.JSON()),
                           ("item_evaluation_json", sa.JSON()), ("evaluation_rule_version", sa.String(64))):
            op.add_column("attempts", sa.Column(name, kind, nullable=True))
        return
    with op.batch_alter_table("questions") as batch:
        batch.add_column(sa.Column("reading_group_version_id", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_question_reading_group", "reading_group_versions", ["reading_group_version_id"], ["id"], ondelete="RESTRICT")
    with op.batch_alter_table("learning_sessions") as batch:
        batch.add_column(sa.Column("current_group_version_id", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_session_reading_group", "reading_group_versions", ["current_group_version_id"], ["id"], ondelete="RESTRICT")
    with op.batch_alter_table("attempts") as batch:
        batch.add_column(sa.Column("group_version_id", sa.String(64), nullable=True))
        batch.add_column(sa.Column("structured_answer_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("group_snapshot_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("item_evaluation_json", sa.JSON(), nullable=True))
        batch.add_column(sa.Column("evaluation_rule_version", sa.String(64), nullable=True))
        batch.create_foreign_key("fk_attempt_reading_group", "reading_group_versions", ["group_version_id"], ["id"], ondelete="RESTRICT")


def downgrade() -> None:
    if op.get_bind().dialect.name == "sqlite":
        for name in ("group_version_id", "structured_answer_json", "group_snapshot_json", "item_evaluation_json", "evaluation_rule_version"):
            op.execute(f"ALTER TABLE attempts DROP COLUMN {name}")
        op.execute("ALTER TABLE learning_sessions DROP COLUMN current_group_version_id")
        op.execute("ALTER TABLE questions DROP COLUMN reading_group_version_id")
        op.drop_index("ix_reading_group_versions_group_id", table_name="reading_group_versions")
        op.drop_table("reading_group_versions")
        op.drop_table("reading_rule_versions")
        return
    with op.batch_alter_table("attempts") as batch:
        batch.drop_constraint("fk_attempt_reading_group", type_="foreignkey")
        for name in ("group_version_id", "structured_answer_json", "group_snapshot_json", "item_evaluation_json", "evaluation_rule_version"):
            batch.drop_column(name)
    with op.batch_alter_table("learning_sessions") as batch:
        batch.drop_constraint("fk_session_reading_group", type_="foreignkey")
        batch.drop_column("current_group_version_id")
    with op.batch_alter_table("questions") as batch:
        batch.drop_constraint("fk_question_reading_group", type_="foreignkey")
        batch.drop_column("reading_group_version_id")
    op.drop_index("ix_reading_group_versions_group_id", table_name="reading_group_versions")
    op.drop_table("reading_group_versions")
    op.drop_table("reading_rule_versions")
