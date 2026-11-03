"""CMP: only the fields in use, the typical recipe as defaults, one slurry and pad

Revision ID: 0012
Revises: 0011

Existing databases keep the CMP schema they were seeded with (seed.py only adds
types that are missing), so it's replaced here. The slurry and pad lists are
emptied and seed.py, which runs right after the migrations, fills them with the
single value each. Stored parameters aren't touched: values of removed fields
stay on existing entries.
"""
from alembic import op
import sqlalchemy as sa

revision = '0012'
down_revision = '0011'
branch_labels = None
depends_on = None

SCHEMA = [
    {"key": "equipment", "label": "Equipment", "type": "choice", "list": "cmp_equipment", "located": True},
    {"key": "slurry", "label": "Slurry type", "type": "choice", "list": "cmp_slurry",
     "default": "SF1 Polishing Solutions"},
    {"key": "dilution", "label": "Dilution", "type": "text", "placeholder": "e.g. 1:10 with DI water"},
    {"key": "slurry_flow", "label": "Slurry flow", "type": "number", "unit": ""},
    {"key": "pad", "label": "Pad type", "type": "choice", "list": "cmp_pad", "default": "Chemomet"},
    {"key": "force_mode", "label": "Force application", "type": "choice", "list": "cmp_force_mode",
     "default": "Central"},
    {"key": "force", "label": "Force", "type": "number", "unit": "N", "default": 20},
    {"key": "rotation", "label": "Rotation", "type": "choice", "list": "cmp_rotation", "default": "Same direction"},
    {"key": "carrier_speed", "label": "Head speed", "type": "number", "unit": "rpm", "default": 30},
    {"key": "platen_speed", "label": "Base speed", "type": "number", "unit": "rpm", "default": 30},
    {"key": "duration", "label": "Time", "type": "duration", "unit": "min:s", "placeholder": "e.g. 12:30"},
    {"key": "thickness_removed", "label": "Thickness removed", "type": "number", "unit": "nm",
     "placeholder": "if known"},
    {"key": "removal_rate", "label": "Removal rate", "type": "number", "unit": "nm/min", "placeholder": "if known"},
]

step_types = sa.table("process_step_types", sa.column("name", sa.String), sa.column("parameter_schema", sa.JSON))
choice_options = sa.table("choice_options", sa.column("list", sa.String))


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(step_types.update().where(step_types.c.name == "CMP").values(parameter_schema=SCHEMA))
    conn.execute(choice_options.delete().where(choice_options.c.list.in_(("cmp_slurry", "cmp_pad"))))


def downgrade() -> None:
    pass   # the old schema and dropdown values aren't kept
