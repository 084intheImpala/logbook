"""Film material becomes a shared dropdown list

Revision ID: 0013
Revises: 0012

The thin film form now picks the film from the "film_material" list (see
choices.py) instead of a free text box. The list starts with the films already
on samples. Spellings that only differ in case or surrounding spaces ("ZnO",
"zno ") are merged into the most used one, on the samples too, so filtering by
film finds them all.
"""
from collections import Counter

from alembic import op
import sqlalchemy as sa

revision = '0013'
down_revision = '0012'
branch_labels = None
depends_on = None

LIST = "film_material"

samples = sa.table("samples", sa.column("id", sa.Integer), sa.column("film_material", sa.String))
choice_options = sa.table("choice_options", sa.column("list", sa.String), sa.column("value", sa.String))


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.select(samples.c.id, samples.c.film_material)
                        .where(samples.c.film_material.is_not(None))).all()
    known = {v.lower(): v for v in conn.execute(
        sa.select(choice_options.c.value).where(choice_options.c.list == LIST)).scalars()}

    counts: dict[str, Counter] = {}
    for _, value in rows:
        if value.strip():
            counts.setdefault(value.strip().lower(), Counter())[value.strip()] += 1
    # Most used spelling; on a tie, the first alphabetically
    chosen = {key: known.get(key) or min(c, key=lambda v: (-c[v], v)) for key, c in counts.items()}

    for sample_id, value in rows:
        new = chosen.get(value.strip().lower()) if value.strip() else None
        if new != value:
            conn.execute(samples.update().where(samples.c.id == sample_id).values(film_material=new))
    new_options = [{"list": LIST, "value": v} for k, v in sorted(chosen.items()) if k not in known]
    if new_options:
        conn.execute(choice_options.insert(), new_options)


def downgrade() -> None:
    op.get_bind().execute(choice_options.delete().where(choice_options.c.list == LIST))
