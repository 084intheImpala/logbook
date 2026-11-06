"""Planned entries, and the target thickness and rate a deposition's duration is worked out from

Revision ID: 0016
Revises: 0015

Steps and analyses get a `planned` flag (planned, not done yet). The
Deposition schema gets two fields, put before Duration: Target thickness and
"Rate used for the time"; the form works the duration out from them. Existing
databases keep the schema they were seeded with (admins may have edited it),
so the fields are inserted here rather than the schema replaced; a schema that
already has them is left alone.
"""
from alembic import op
import sqlalchemy as sa

revision = '0016'
down_revision = '0015'
branch_labels = None
depends_on = None

NEW_FIELDS = [
    {"key": "target_thickness", "label": "Target thickness", "type": "number", "unit": "nm"},
    {"key": "rate_used", "label": "Rate used for the time", "type": "number", "unit": "nm/min",
     "placeholder": "last known rate, or typed"},
]

step_types = sa.table("process_step_types", sa.column("id", sa.Integer), sa.column("name", sa.String),
                      sa.column("parameter_schema", sa.JSON))


def upgrade() -> None:
    for table in ("process_steps", "analyses"):
        op.add_column(table, sa.Column("planned", sa.Boolean(), server_default=sa.false(), nullable=False))
    conn = op.get_bind()
    row = conn.execute(sa.select(step_types.c.id, step_types.c.parameter_schema)
                       .where(step_types.c.name == "Deposition")).first()
    if row is None or row.parameter_schema is None:
        return   # a new database: seed.py adds the Deposition type with the fields
    schema = list(row.parameter_schema)
    keys = {f.get("key") for f in schema}
    new = [f for f in NEW_FIELDS if f["key"] not in keys]
    if not new:
        return
    at = next((i for i, f in enumerate(schema) if f.get("key") == "duration"), len(schema))
    conn.execute(step_types.update().where(step_types.c.id == row.id)
                 .values(parameter_schema=schema[:at] + new + schema[at:]))


def downgrade() -> None:
    for table in ("process_steps", "analyses"):
        op.drop_column(table, "planned")
