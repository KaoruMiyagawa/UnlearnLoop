"""Alembic migration environment for UnlearnLoop."""

from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, event, pool

from app.config import get_settings
from app.persistence import models as _models  # noqa: F401 - register ORM metadata
from app.persistence.database import Base

config = context.config

if config.config_file_name is not None and config.get_section("loggers") is not None:
    fileConfig(config.config_file_name)

target_metadata = Base.metadata


def get_database_url() -> str:
    """Resolve database URL from Alembic config override or app settings."""
    configured_url = config.get_main_option("sqlalchemy.url")
    if configured_url:
        return configured_url
    return get_settings().database_url


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = get_database_url()
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        render_as_batch=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = config.attributes.get("connection", None)

    if connectable is None:
        configuration = config.get_section(config.config_ini_section, {})
        configuration["sqlalchemy.url"] = get_database_url()
        connectable = engine_from_config(
            configuration,
            prefix="sqlalchemy.",
            poolclass=pool.NullPool,
        )
        if configuration["sqlalchemy.url"].startswith("sqlite"):
            @event.listens_for(connectable, "connect")
            def _enable_fk(dbapi_conn, _conn_record):  # type: ignore[no-untyped-def]
                cursor = dbapi_conn.cursor()
                cursor.execute("PRAGMA foreign_keys=ON")
                cursor.close()

        with connectable.connect() as connection:
            context.configure(
                connection=connection,
                target_metadata=target_metadata,
                render_as_batch=True,
            )
            with context.begin_transaction():
                context.run_migrations()
    else:
        context.configure(
            connection=connectable,
            target_metadata=target_metadata,
            render_as_batch=True,
        )
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
