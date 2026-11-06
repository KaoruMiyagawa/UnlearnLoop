"""Programmatic Alembic migration runner for initializing empty or test databases."""

from pathlib import Path

from alembic import command
from alembic.config import Config
from sqlalchemy import Engine

BACKEND_DIR = Path(__file__).resolve().parent.parent.parent


def get_alembic_config(database_url: str | None = None) -> Config:
    """Build an Alembic Config pointing to backend/alembic.ini."""
    cfg = Config(str(BACKEND_DIR / "alembic.ini"))
    cfg.set_main_option("path_separator", "os")
    cfg.set_main_option(
        "script_location",
        str(BACKEND_DIR / "app" / "persistence" / "migrations"),
    )
    if database_url:
        cfg.set_main_option("sqlalchemy.url", database_url)
    return cfg


def upgrade_database(
    *,
    database_url: str | None = None,
    engine: Engine | None = None,
    revision: str = "head",
) -> None:
    """Apply Alembic migrations up to `revision` without overwriting existing data."""
    cfg = get_alembic_config(database_url)
    if engine is not None:
        with engine.begin() as connection:
            cfg.attributes["connection"] = connection
            command.upgrade(cfg, revision)
    else:
        command.upgrade(cfg, revision)
