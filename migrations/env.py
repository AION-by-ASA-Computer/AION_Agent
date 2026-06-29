from logging.config import fileConfig
import os
import re

from sqlalchemy import engine_from_config
from sqlalchemy import pool

from alembic import context


def _to_sync_db_url(url: str) -> str:
    """Converti un URL DB async in sync, per Alembic.

    Alembic e' sincrono: passandogli un URL con driver async (aiosqlite,
    asyncpg) si ottiene ``sqlalchemy.exc.MissingGreenlet`` quando si chiama
    ``connectable.connect()``. L'app runtime continua a usare l'URL async
    originale; qui convertiamo SOLO per la migrazione.

    Mapping:
      sqlite+aiosqlite://...       -> sqlite://...
      postgresql+asyncpg://...     -> postgresql+psycopg2://...
      postgresql+psycopg://...     -> invariato (psycopg3 funziona sia sync)
      mysql+aiomysql://...         -> mysql+pymysql://...
    """
    if not url:
        return url
    url = re.sub(r"^sqlite\+aiosqlite(://|:)", r"sqlite\1", url)
    url = re.sub(r"^postgresql\+asyncpg(://|:)", r"postgresql+psycopg2\1", url)
    url = re.sub(r"^mysql\+aiomysql(://|:)", r"mysql+pymysql\1", url)
    return url


# this is the Alembic Config object, which provides
# access to the values within the .ini file in use.
config = context.config
db_url = _to_sync_db_url((os.getenv("AION_DB_URL") or "").strip())
if db_url:
    config.set_main_option("sqlalchemy.url", db_url)

# Interpret the config file for Python logging.
# This line sets up loggers basically.
if config.config_file_name is not None:
    fileConfig(config.config_file_name, disable_existing_loggers=False)

# add your model's MetaData object here
# for 'autogenerate' support
from src.data.models import Base
target_metadata = Base.metadata

def include_object(object, name, type_, reflected, compare_to):
    if type_ == "table" and name not in target_metadata.tables:
        return False
    return True

# other values from the config, defined by the needs of env.py,
# can be acquired:
# my_important_option = config.get_main_option("my_important_option")
# ... etc.


def run_migrations_offline() -> None:
    """Run migrations in 'offline' mode.

    This configures the context with just a URL
    and not an Engine, though an Engine is acceptable
    here as well.  By skipping the Engine creation
    we don't even need a DBAPI to be available.

    Calls to context.execute() here emit the given string to the
    script output.

    """
    url = config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        include_object=include_object,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    """Run migrations in 'online' mode.

    In this scenario we need to create an Engine
    and associate a connection with the context.

    """
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
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
