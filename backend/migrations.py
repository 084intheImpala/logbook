"""Idempotent schema upgrades for databases created by older versions.

create_all() only creates missing tables, so columns and constraints added
later are applied here on startup. Every step is safe to run repeatedly.
"""
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import engine
from backend.timeline import renumber


def _upgrade_schema(conn):
    insp = inspect(conn)

    def add_column(table: str, column: str, ddl_type: str):
        if column not in {c["name"] for c in insp.get_columns(table)}:
            conn.execute(text(f"ALTER TABLE {table} ADD COLUMN {column} {ddl_type}"))

    add_column("samples", "tags", "JSON")
    add_column("process_steps", "position", "INTEGER")
    add_column("analyses", "position", "INTEGER")
    add_column("samples", "cut_step_id", "INTEGER REFERENCES process_steps(id)")
    add_column("samples", "is_reference", "BOOLEAN NOT NULL DEFAULT false")

    # Sample names used to be unique; the id is now the only unique identifier.
    for uc in insp.get_unique_constraints("samples"):
        if uc["column_names"] == ["name"] and conn.dialect.name == "postgresql":
            conn.execute(text(f'ALTER TABLE samples DROP CONSTRAINT "{uc["name"]}"'))
    if "ix_samples_name" not in {ix["name"] for ix in insp.get_indexes("samples")}:
        conn.execute(text("CREATE INDEX ix_samples_name ON samples (name)"))
    if "ix_samples_cut_step_id" not in {ix["name"] for ix in insp.get_indexes("samples")}:
        conn.execute(text("CREATE INDEX ix_samples_cut_step_id ON samples (cut_step_id)"))


async def run_migrations(session: AsyncSession):
    async with engine.begin() as conn:
        await conn.run_sync(_upgrade_schema)

    # Give timeline entries created before `position` existed an order:
    # steps keep their step_order, analyses slot in by date.
    rows = await session.execute(text(
        "SELECT DISTINCT sample_id FROM process_steps WHERE position IS NULL "
        "UNION SELECT DISTINCT sample_id FROM analyses WHERE position IS NULL"
    ))
    sample_ids = [r[0] for r in rows]
    for sample_id in sample_ids:
        await renumber(session, sample_id, legacy=True)
    if sample_ids:
        await session.commit()
