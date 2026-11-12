"""Dry-run or explicitly apply Phase 6.1 evidence reconciliation to an isolated SQLite copy."""
from __future__ import annotations

import argparse
import hashlib
import json
import shutil
from pathlib import Path
import sys
from uuid import uuid4

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sqlalchemy import text

from app.application.evidence_validity import apply_reconciliation, build_reconciliation_plan
from app.persistence.database import create_db_engine, create_session_factory


FORMAL_DATABASE = (Path(__file__).resolve().parents[1] / "unlearnloop.db").resolve()
APPLY_CONFIRMATION = "APPLY_PHASE6_1_TO_ISOLATED_SQLITE_ONLY"


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _sqlite_path(database_url: str) -> Path:
    if not database_url.startswith("sqlite:///"):
        raise ValueError("Phase 6.1 apply accepts SQLite only.")
    raw = database_url[len("sqlite:///"):]
    path = Path(raw)
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    return path


def _require_at_head(engine) -> None:
    with engine.connect() as connection:
        tables = set(connection.scalars(text("SELECT name FROM sqlite_master WHERE type='table'")).all())
        if "alembic_version" not in tables:
            raise RuntimeError("Database is not migrated. Upgrade an isolated copy before running this command.")
        revision = connection.scalar(text("SELECT version_num FROM alembic_version"))
        if revision != "0007_evidence_validity_events":
            raise RuntimeError(f"Expected Alembic head 0007_evidence_validity_events; found {revision!r}.")


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--database-url", required=True, help="Already-migrated SQLite URL. Never use the formal database.")
    parser.add_argument("--apply", action="store_true", help="Apply the reviewed dry-run plan.")
    parser.add_argument("--confirm", default="", help=f"Must equal {APPLY_CONFIRMATION} for --apply.")
    args = parser.parse_args()

    path = _sqlite_path(args.database_url)
    if path.resolve() == FORMAL_DATABASE or not path.exists():
        raise SystemExit("Refusing to run against the formal SQLite or a missing database file.")
    if args.apply:
        if args.confirm != APPLY_CONFIRMATION:
            raise SystemExit("Apply requires explicit --confirm APPLY_PHASE6_1_TO_ISOLATED_SQLITE_ONLY.")
        if "phase6-1" not in str(path).lower():
            raise SystemExit("Apply is restricted to a database path containing 'phase6-1' for isolation verification.")

    engine = create_db_engine(database_url=args.database_url)
    _require_at_head(engine)
    factory = create_session_factory(engine)
    with factory() as session:
        plan = build_reconciliation_plan(session)
        if not args.apply:
            print(json.dumps({"mode": "dry_run", "database": str(path), "plan": plan}, ensure_ascii=False, indent=2))
            return

    # Acquire SQLite's reserved write lock before the final plan and backup so
    # concurrent apply processes serialize and each sees the prior committed run.
    with factory() as session:
        session.connection().exec_driver_sql("BEGIN IMMEDIATE")
        plan = build_reconciliation_plan(session)
        backup = path.with_suffix(path.suffix + f".phase6-1-preapply-{uuid4().hex[:10]}.bak")
        shutil.copy2(path, backup)
        before_hash = sha256(path)
        if sha256(backup) != before_hash:
            raise RuntimeError("Pre-apply backup verification failed; no changes were applied.")
        result = apply_reconciliation(session, plan)
        session.commit()
        print(json.dumps({"mode": "apply", "database": str(path), "backup": str(backup),
                          "backup_sha256": before_hash, "plan": plan, "result": result},
                         ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
