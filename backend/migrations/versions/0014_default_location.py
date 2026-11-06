"""Where each step and analysis type is usually done

Revision ID: 0014
Revises: 0013

A new entry's Where starts at its type's default_location (until then every
type started at CTN). The defaults are those in seed_data.DEFAULT_LOCATIONS,
copied here so later edits to seed_data don't change what this migration
did; types not listed get CTN, admin-made ones too. FCUL is added to the
Where list for AFM.
"""
from alembic import op
import sqlalchemy as sa

revision = '0014'
down_revision = '0013'
branch_labels = None
depends_on = None

DEFAULT_LOCATIONS = {
    "Deposition": "INESC MN", "Etching": "INESC MN", "Lithography": "INESC MN", "CMP": "INESC MN",
    "Ellipsometry": "INESC MN", "Hall / 4-probe": "INESC MN", "Profilometry": "INESC MN", "SEM": "INESC MN",
    "AFM": "FCUL",
    "TEM": None, "XPS": None,
}
NEW_PLACES = ["FCUL"]
TABLES = ("process_step_types", "analysis_types")

choice_options = sa.table("choice_options", sa.column("list", sa.String), sa.column("value", sa.String))


def upgrade() -> None:
    for name in TABLES:
        op.add_column(name, sa.Column("default_location", sa.String(length=120), nullable=True))
    conn = op.get_bind()
    for name in TABLES:
        types = sa.table(name, sa.column("name", sa.String), sa.column("default_location", sa.String))
        conn.execute(types.update().values(default_location="CTN"))
        for type_name, place in DEFAULT_LOCATIONS.items():
            conn.execute(types.update().where(types.c.name == type_name).values(default_location=place))
    places = {v.lower() for v in conn.execute(
        sa.select(choice_options.c.value).where(choice_options.c.list == "location")).scalars()}
    # Only on databases that already have places; seed.py fills an empty list with all of them
    if places:
        new = [{"list": "location", "value": p} for p in NEW_PLACES if p.lower() not in places]
        if new:
            conn.execute(choice_options.insert(), new)


def downgrade() -> None:
    for name in TABLES:
        op.drop_column(name, "default_location")
