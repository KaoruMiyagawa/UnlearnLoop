"""Persistence layer: SQLAlchemy foundation and migration hooks.

Note: Business tables (KnowledgeTopic, LearningSession, DiagnosticCase, etc.)
are intentionally deferred to Stage 2 per ROADMAP.md.
"""

from app.persistence.database import Base, create_db_engine, create_session_factory

__all__ = ["Base", "create_db_engine", "create_session_factory"]
