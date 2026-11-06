"""SQLAlchemy 2.x DeclarativeBase and engine/session factory hooks."""

from sqlalchemy import Engine, create_engine
from sqlalchemy.orm import DeclarativeBase, Session, sessionmaker

from app.config import Settings, get_settings


class Base(DeclarativeBase):
    """Base class for all Stage 2+ SQLAlchemy ORM models."""


def create_db_engine(settings: Settings | None = None) -> Engine:
    """Create a SQLAlchemy Engine from application settings without side effects."""
    resolved = settings or get_settings()
    connect_args = (
        {"check_same_thread": False}
        if resolved.database_url.startswith("sqlite")
        else {}
    )
    return create_engine(
        resolved.database_url,
        connect_args=connect_args,
        future=True,
    )


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
