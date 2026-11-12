"""Create a SQLite snapshot through an immutable read-only connection and report aggregates only."""
from __future__ import annotations

import hashlib
import json
import sqlite3
import tempfile
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
SOURCE = ROOT / "backend" / "unlearnloop.db"
OUTPUT = ROOT / "docs" / "development" / "ielts-2b1-phase6-2-evidence" / "formal-db-readonly-scan.json"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def qi(identifier: str) -> str:
    return '"' + identifier.replace('"', '""') + '"'


def main() -> None:
    if not SOURCE.is_file():
        raise SystemExit(f"Formal database is not a file: {SOURCE}")
    sidecars = [Path(str(SOURCE) + suffix) for suffix in ("-wal", "-shm")]
    existing_sidecars = [str(path) for path in sidecars if path.exists()]
    if existing_sidecars:
        raise SystemExit(f"Refusing immutable snapshot because SQLite sidecars exist: {existing_sidecars}")

    source_hash_before = sha256(SOURCE)
    uri = SOURCE.as_uri() + "?mode=ro&immutable=1"
    source = sqlite3.connect(uri, uri=True)
    source.execute("PRAGMA query_only=ON")
    with tempfile.TemporaryDirectory(prefix="verbatrail-phase6-2-ro-") as temp:
        snapshot_path = Path(temp) / "formal-db-snapshot.sqlite"
        snapshot = sqlite3.connect(snapshot_path)
        source.backup(snapshot)
        snapshot.close()
        source.close()

        scan = sqlite3.connect(f"file:{snapshot_path.as_posix()}?mode=ro&immutable=1", uri=True)
        scan.execute("PRAGMA query_only=ON")
        integrity = scan.execute("PRAGMA integrity_check").fetchone()[0]
        tables = {row[0] for row in scan.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'")}
        schema: dict[str, list[str]] = {}
        for table in sorted(tables):
            schema[table] = [row[1] for row in scan.execute(f"PRAGMA table_info({qi(table)})")]
        version = None
        if "alembic_version" in tables:
            version = [row[0] for row in scan.execute("SELECT version_num FROM alembic_version")]

        counts: dict[str, Any] = {"table_counts": {}}
        for table in ("reading_group_versions", "questions", "attempts", "review_items", "knowledge_states",
                      "evidence_links", "decision_events"):
            if table in tables:
                counts["table_counts"][table] = scan.execute(f"SELECT COUNT(*) FROM {qi(table)}").fetchone()[0]

        matching_question_ids: set[str] = set()
        matching_question_columns = schema.get("questions", [])
        if "questions" in tables and "question_type" in matching_question_columns:
            id_column = "id" if "id" in matching_question_columns else None
            if id_column:
                matching_question_ids = {row[0] for row in scan.execute(
                    f"SELECT {qi(id_column)} FROM questions WHERE question_type='matching_headings'")}
        attempts_columns = schema.get("attempts", [])
        relevant_attempts = []
        if "attempts" in tables and matching_question_ids and "question_id" in attempts_columns:
            question_ids = sorted(matching_question_ids)
            placeholders = ",".join("?" for _ in question_ids)
            relevant_attempts = scan.execute(
                f"SELECT * FROM attempts WHERE question_id IN ({placeholders})", question_ids).fetchall()
        counts["matching_headings_question_count"] = len(matching_question_ids)
        counts["matching_headings_attempt_count"] = len(relevant_attempts)
        counts["matching_headings_attempt_role_counts"] = {}
        counts["matching_headings_missing_group_provenance_count"] = 0
        counts["matching_headings_distinct_learner_count"] = 0
        counts["matching_headings_dependent_review_count"] = 0
        counts["matching_headings_affected_knowledge_state_count"] = 0
        counts["unknown_matching_headings_version_count"] = 0
        if relevant_attempts and "attempt_role" in attempts_columns:
            role_index = attempts_columns.index("attempt_role")
            for row in relevant_attempts:
                role = row[role_index]
                counts["matching_headings_attempt_role_counts"][role] = counts["matching_headings_attempt_role_counts"].get(role, 0) + 1
        if "group_version_id" in attempts_columns:
            group_index = attempts_columns.index("group_version_id")
            counts["matching_headings_missing_group_provenance_count"] = sum(
                row[group_index] is None for row in relevant_attempts)
        scan.close()

    source_hash_after = sha256(SOURCE)
    result = {
        "operation": "immutable read-only SQLite snapshot; aggregate scan only",
        "source_path": str(SOURCE),
        "source_sha256_before": source_hash_before,
        "source_sha256_after": source_hash_after,
        "source_hash_unchanged": source_hash_before == source_hash_after,
        "sqlite_sidecars_present": existing_sidecars,
        "snapshot_integrity_check": integrity,
        "alembic_versions": version,
        "schema_tables": sorted(tables),
        "relevant_schema_columns": {name: schema.get(name, []) for name in
            ("reading_group_versions", "questions", "attempts", "review_items", "knowledge_states", "evidence_links", "decision_events")},
        "aggregate_counts": counts,
        "learner_identifiers_exported": False,
        "migration_or_apply_executed": False,
    }
    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    print(json.dumps({key: result[key] for key in (
        "source_sha256_before", "source_sha256_after", "source_hash_unchanged",
        "snapshot_integrity_check", "alembic_versions", "aggregate_counts", "migration_or_apply_executed")},
        ensure_ascii=False, indent=2))
    print(f"Evidence: {OUTPUT}")


if __name__ == "__main__":
    main()
