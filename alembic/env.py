import os
import sys
from logging.config import fileConfig

from alembic import context
from dotenv import load_dotenv
from geoalchemy2.alembic_helpers import include_object as geoalchemy2_include_object
from geoalchemy2.alembic_helpers import render_item, writer
from sqlalchemy import engine_from_config, pool

# Make the "app" package (backend/app) importable.
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "backend"))

load_dotenv()

from app.database import Base  # noqa: E402
import app.models  # noqa: E402,F401  (registers every model on Base.metadata)

# this is the Alembic Config object, which provides access to values
# within the .ini file in use.
config = context.config

database_url = os.getenv("DATABASE_URL")
if database_url:
    config.set_main_option("sqlalchemy.url", database_url)

# Interpret the config file for Python logging.
if config.config_file_name is not None:
    fileConfig(config.config_file_name)

# metadata target used for 'autogenerate' support.
target_metadata = Base.metadata


def include_object(obj, name, obj_type, reflected, compare_to):
    """Filter objects considered by autogenerate.

    Combines GeoAlchemy2's filter (PostGIS system tables like
    spatial_ref_sys) with a filter for tables reflected from the database
    that have no corresponding model, such as the tiger_geocoder / topology
    tables the postgis/postgis image creates in the public schema. Without
    this, autogenerate would emit DROP TABLE statements for them.
    """
    if obj_type == "table" and reflected and compare_to is None:
        return False
    return geoalchemy2_include_object(obj, name, obj_type, reflected, compare_to)


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode."""
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
        render_item=render_item,
        process_revision_directives=writer,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode."""
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            include_object=include_object,
            render_item=render_item,
            process_revision_directives=writer,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
