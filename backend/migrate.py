"""Schema migrations (Alembic), applied on startup.

Databases created before migrations existed were built by create_all and
have no alembic_version table: they are stamped as the baseline revision
(their schema is exactly what the baseline creates) and then upgraded like
any other. New schema changes are written as migrations in
backend/migrations/versions; see the README.
"""
import asyncio
from pathlib import Path
from alembic import command
from alembic.config import Config
from sqlalchemy import inspect

from backend.database import engine

BASELINE = "0001"
_DIR = Path(__file__).resolve().parent / "migrations"


def _config() -> Config:
    cfg = Config()
    cfg.set_main_option("script_location", str(_DIR))
    return cfg


def _tables(sync_conn) -> set[str]:
    return set(inspect(sync_conn).get_table_names())


def _upgrade(has_tables_but_no_version: bool):
    cfg = _config()
    if has_tables_but_no_version:
        command.stamp(cfg, BASELINE)
    command.upgrade(cfg, "head")


async def migrate():
    async with engine.connect() as conn:
        tables = await conn.run_sync(_tables)
    legacy = "users" in tables and "alembic_version" not in tables
    # Alembic's env.py runs its own event loop, so keep it off ours.
    await asyncio.to_thread(_upgrade, legacy)
