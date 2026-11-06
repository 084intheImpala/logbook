import asyncio
from alembic import context
from sqlalchemy.ext.asyncio import create_async_engine

from backend.config import settings
from backend.database import Base
from backend import models  # noqa: register every table on Base.metadata

target_metadata = Base.metadata


def _run(connection):
    context.configure(connection=connection, target_metadata=target_metadata, compare_type=True)
    with context.begin_transaction():
        context.run_migrations()


async def _run_online():
    engine = create_async_engine(settings.DATABASE_URL)
    async with engine.connect() as conn:
        await conn.run_sync(_run)
    await engine.dispose()


asyncio.run(_run_online())
