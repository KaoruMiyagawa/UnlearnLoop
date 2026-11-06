"""Persistence layer: SQLAlchemy 2.x ORM models, repositories, migrations, and seeding."""

from app.persistence.database import (
    Base,
    create_db_engine,
    create_session_factory,
    transactional_session,
)
from app.persistence.migrations_runner import get_alembic_config, upgrade_database
from app.persistence.models import (
    Attempt,
    DecisionEvent,
    DiagnosticCase,
    EvidenceLink,
    Hypothesis,
    KnowledgeState,
    KnowledgeTopic,
    KnowledgeTopicDependency,
    LearningMaterial,
    LearningSession,
    ModelCall,
    Question,
    ReviewItem,
)
from app.persistence.repositories import LearningRepository
from app.persistence.seed import (
    DEFAULT_PYTHON_PACK_PATH,
    SeedSummary,
    import_content_pack,
    load_content_pack_file,
)

__all__ = [
    "Attempt",
    "Base",
    "DEFAULT_PYTHON_PACK_PATH",
    "DecisionEvent",
    "DiagnosticCase",
    "EvidenceLink",
    "Hypothesis",
    "KnowledgeState",
    "KnowledgeTopic",
    "KnowledgeTopicDependency",
    "LearningMaterial",
    "LearningRepository",
    "LearningSession",
    "ModelCall",
    "Question",
    "ReviewItem",
    "SeedSummary",
    "create_db_engine",
    "create_session_factory",
    "get_alembic_config",
    "import_content_pack",
    "load_content_pack_file",
    "transactional_session",
    "upgrade_database",
]
