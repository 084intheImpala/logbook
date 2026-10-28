"""ellipsometry: detector settings and reference taken

Revision ID: 0003
Revises: 0002

Existing databases keep the Ellipsometry schema they were seeded with (seed.py
only adds types that are missing), so the new fields are added here. Admins can
edit schemas, so this only inserts a field whose key isn't there yet, and
leaves the rest as it is.
"""
from alembic import op
import sqlalchemy as sa

revision = '0003'
down_revision = '0002'
branch_labels = None
depends_on = None

NEW_FIELDS = [
    {"key": "detector_settings", "label": "Detector settings", "type": "longtext",
     "placeholder": "Gain, integration time, slit width, …"},
    {"key": "reference", "label": "Reference taken", "type": "check", "fields": [
        {"key": "reference_details", "label": "Reference details", "type": "longtext",
         "placeholder": "What was used as reference (air, bare substrate, …) and when it was taken"},
    ]},
]
NEW_KEYS = [f["key"] for f in NEW_FIELDS]

analysis_types = sa.table("analysis_types", sa.column("id", sa.Integer), sa.column("name", sa.String),
                          sa.column("parameter_schema", sa.JSON))


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(sa.select(analysis_types.c.id, analysis_types.c.parameter_schema)
                       .where(analysis_types.c.name == "Ellipsometry")).first()
    if row is None:   # deleted or renamed by an admin: nothing to update
        return
    schema = list(row.parameter_schema or [])
    present = {f.get("key") for f in schema}
    missing = [f for f in NEW_FIELDS if f["key"] not in present]
    if not missing:
        return
    # Before the optical model if it's there, so the long free-text field stays last
    at = next((i for i, f in enumerate(schema) if f.get("key") == "model"), len(schema))
    schema[at:at] = missing
    conn.execute(analysis_types.update().where(analysis_types.c.id == row.id).values(parameter_schema=schema))


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(sa.select(analysis_types.c.id, analysis_types.c.parameter_schema)
                       .where(analysis_types.c.name == "Ellipsometry")).first()
    if row is None or not row.parameter_schema:
        return
    schema = [f for f in row.parameter_schema if f.get("key") not in NEW_KEYS]
    conn.execute(analysis_types.update().where(analysis_types.c.id == row.id).values(parameter_schema=schema))
