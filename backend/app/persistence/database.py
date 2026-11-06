"""SQLAlchemy 2.x DeclarativeBase, engine/session factory, and transaction boundaries."""

from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from sqlalchemy import Engine, create_engine, event
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings, get_settings


class Base(DeclarativeBase):
    """Base class for all SQLAlchemy ORM models."""


def _enable_sqlite_foreign_keys(dbapi_connection: Any, _connection_record: Any) -> None:
    """Enforce SQLite foreign key integrity on every opened connection."""
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.close()


def create_db_engine(
    settings: Settings | None = None,
    database_url: str | None = None,
) -> Engine:
    """Create a SQLAlchemy Engine with SQLite foreign keys explicitly enabled."""
    resolved_url = database_url or (settings or get_settings()).database_url
    is_sqlite = resolved_url.startswith("sqlite")
    connect_args = {"check_same_thread": False} if is_sqlite else {}

    engine = create_engine(
        resolved_url,
        connect_args=connect_args,
        future=True,
    )
    if is_sqlite:
        event.listen(engine, "connect", _enable_sqlite_foreign_keys)
    return engine


def create_session_factory(
    engine: Engine | None = None,
) -> sessionmaker[Session]:
    """Create a SQLAlchemy session factory."""
    bound_engine = engine or create_db_engine()
    return sessionmaker(
        bind=bound_engine,
        autoflush=False,
        autocommit=False,
        expire_on_commit=False,
    )


@contextmanager
def transactional_session(
    session_factory: sessionmaker[Session],
) -> Iterator[Session]:
    """Explicit transaction boundary: commit on clean exit, rollback on error."""
    session = session_factory()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()
