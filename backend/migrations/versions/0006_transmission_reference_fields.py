"""transmission: detector settings and reference taken

Revision ID: 0006
Revises: 0005

Same two fields as Ellipsometry (0003), for the analysis type(s) an admin
created for transmission measurements: any analysis type whose name contains
"transmission". Only a field whose key isn't there yet is added, so changes
an admin made are kept. The names it touched are written to the log.
"""
import logging

from alembic import op
import sqlalchemy as sa

revision = '0006'
down_revision = '0005'
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

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


def _rows(conn):
    return conn.execute(sa.select(analysis_types.c.id, analysis_types.c.name, analysis_types.c.parameter_schema)
                        .where(sa.func.lower(analysis_types.c.name).like("%transmission%"))).all()


def upgrade() -> None:
    conn = op.get_bind()
    for row in _rows(conn):
        schema = list(row.parameter_schema or [])
        present = {f.get("key") for f in schema}
        missing = [f for f in NEW_FIELDS if f["key"] not in present]
        if not missing:
            continue
        # Appended at the end: the type's own layout isn't known
        schema.extend(missing)
        conn.execute(analysis_types.update().where(analysis_types.c.id == row.id).values(parameter_schema=schema))
        log.info("Added detector/reference fields to analysis type %r", row.name)


def downgrade() -> None:
    conn = op.get_bind()
    for row in _rows(conn):
        schema = [f for f in (row.parameter_schema or []) if f.get("key") not in NEW_KEYS]
        conn.execute(analysis_types.update().where(analysis_types.c.id == row.id).values(parameter_schema=schema))
