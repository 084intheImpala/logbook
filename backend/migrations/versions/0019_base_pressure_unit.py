"""Base pressure in 10⁻⁶ Torr instead of mTorr

Revision ID: 0019
Revises: 0018

A deposition's base pressure is usually around 10⁻⁶ Torr, so the field's unit
becomes "×10⁻⁶ Torr" (a value of 2 means 2×10⁻⁶ Torr). The field asked for
mTorr, but people also typed it in Torr (1e-6), so each stored value is read
as whichever of Torr, mTorr or 10⁻⁶ Torr puts it nearest 10⁻⁶ Torr
(`convert`), which takes, as typed:
    below ~3.2e-5        Torr      (1e-6 → 1, 5e-7 → 0.5)
    ~3.2e-5 to ~0.032    mTorr     (1e-3 → 1, 1e-4 → 0.1)
    ~0.032 and above     already ×10⁻⁶ Torr (left as it is)
Values that end up outside 0.01–100 (10⁻⁸–10⁻⁴ Torr), and values that aren't
numbers (left as typed), are logged to be checked by hand.

The schema field is relabelled where it still says mTorr (admins may have
edited it). Downgrading turns the values back into mTorr.
"""
import logging
import math

from alembic import op
import sqlalchemy as sa

revision = '0019'
down_revision = '0018'
branch_labels = None
depends_on = None

log = logging.getLogger("alembic.runtime.migration")

KEY = "base_pressure"
UNIT = "×10⁻⁶ Torr"
PLACEHOLDER = "e.g. 2 for 2×10⁻⁶ Torr"
OLD_UNIT, OLD_PLACEHOLDER = "mTorr", "e.g. 1e-4"
FACTORS = (1, 1e3, 1e6)        # already ×10⁻⁶ Torr, mTorr, Torr
PLAUSIBLE = (0.01, 100)        # 10⁻⁸ to 10⁻⁴ Torr

step_types = sa.table("process_step_types", sa.column("id", sa.Integer), sa.column("name", sa.String),
                      sa.column("parameter_schema", sa.JSON))
steps = sa.table("process_steps", sa.column("id", sa.Integer), sa.column("step_type_id", sa.Integer),
                 sa.column("parameters", sa.JSON))


def _number(value) -> float | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        return float(value)
    try:
        return float(str(value).strip().replace(",", "."))
    except ValueError:
        return None


def convert(value) -> float | None:
    """A base pressure as typed (Torr, mTorr or ×10⁻⁶ Torr) in ×10⁻⁶ Torr,
    or None if it isn't a positive number."""
    number = _number(value)
    if number is None or not math.isfinite(number) or number <= 0:
        return None
    best = min(FACTORS, key=lambda f: abs(math.log10(number * f)))
    return float(f"{number * best:.4g}")


def _deposition(conn):
    return conn.execute(sa.select(step_types.c.id, step_types.c.parameter_schema)
                        .where(step_types.c.name == "Deposition")).first()


def _relabel(conn, row, unit, placeholder, from_unit):
    schema = [dict(f) for f in row.parameter_schema or []]
    changed = False
    for f in schema:
        if f.get("key") == KEY and f.get("unit") == from_unit:
            f["unit"], f["placeholder"], changed = unit, placeholder, True
    if changed:
        conn.execute(step_types.update().where(step_types.c.id == row.id).values(parameter_schema=schema))


def _rewrite(conn, type_id, change):
    rows = conn.execute(sa.select(steps.c.id, steps.c.parameters).where(steps.c.step_type_id == type_id)).all()
    for step_id, params in rows:
        if not params or params.get(KEY) in (None, ""):
            continue
        new = change(step_id, params[KEY])
        if new is not None and new != params[KEY]:
            conn.execute(steps.update().where(steps.c.id == step_id).values(parameters=dict(params) | {KEY: new}))


def upgrade() -> None:
    conn = op.get_bind()
    row = _deposition(conn)
    if row is None:
        return   # a new database: seed.py adds the Deposition type with the new unit
    _relabel(conn, row, UNIT, PLACEHOLDER, OLD_UNIT)

    def change(step_id, value):
        new = convert(value)
        if new is None:
            log.warning("Base pressure of process step %s isn't a number (%r): left as typed, check it", step_id, value)
        elif not PLAUSIBLE[0] <= new <= PLAUSIBLE[1]:
            log.warning("Base pressure of process step %s: %r became %g ×10⁻⁶ Torr, out of the usual range: check it",
                        step_id, value, new)
        else:
            log.info("Base pressure of process step %s: %r → %g ×10⁻⁶ Torr", step_id, value, new)
        return new
    _rewrite(conn, row.id, change)


def downgrade() -> None:
    conn = op.get_bind()
    row = _deposition(conn)
    if row is None:
        return
    _relabel(conn, row, OLD_UNIT, OLD_PLACEHOLDER, UNIT)
    _rewrite(conn, row.id, lambda _, value: float(f"{n / 1e3:.4g}") if (n := _number(value)) else None)
