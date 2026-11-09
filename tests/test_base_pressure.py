"""Base pressure in 10⁻⁶ Torr: the field, and migration 0019 converting what
was typed in mTorr or Torr."""
import importlib.util
import json

import pytest
import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations

from backend.i18n import translate
from backend.seed_data import PROCESS_STEP_TYPES


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0019", "backend/migrations/versions/0019_base_pressure_unit.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_the_field_is_in_1e_6_torr():
    deposition = next(t for t in PROCESS_STEP_TYPES if t["name"] == "Deposition")
    field = next(f for f in deposition["parameter_schema"] if f["key"] == "base_pressure")
    assert field["unit"] == "×10⁻⁶ Torr"
    assert translate("pt", field["placeholder"]) == "ex.: 2 para 2×10⁻⁶ Torr"


@pytest.mark.parametrize("typed, expected", [
    (1e-6, 1), ("5e-7", 0.5), (2.5e-6, 2.5), (1e-7, 0.1), (1e-8, 0.01), (2e-5, 20),   # Torr
    (1e-3, 1), (5e-4, 0.5), (1e-4, 0.1), ("2,5e-3", 2.5), (0.01, 10),                # mTorr
    (2, 2), (0.5, 0.5), (0.1, 0.1), (30, 30),                                          # already 10⁻⁶ Torr
])
def test_values_are_read_as_whichever_unit_puts_them_nearest_1e_6_torr(typed, expected):
    assert _migration().convert(typed) == pytest.approx(expected)


@pytest.mark.parametrize("typed", ["about 1e-6", "", 0, -1, True, None])
def test_what_isnt_a_pressure_is_left(typed):
    assert _migration().convert(typed) is None


def test_the_migration_converts_deposition_values_and_relabels_the_field():
    migration = _migration()
    schema = [{"key": "machine", "type": "choice"},
              {"key": "base_pressure", "type": "number", "unit": "mTorr", "placeholder": "e.g. 1e-4"}]
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE process_step_types (id INTEGER, name TEXT, parameter_schema JSON)"))
        conn.execute(sa.text("CREATE TABLE process_steps (id INTEGER, step_type_id INTEGER, parameters JSON)"))
        conn.execute(sa.text("INSERT INTO process_step_types VALUES (1, 'Deposition', :s), (2, 'Annealing', '[]')"),
                     {"s": json.dumps(schema)})
        rows = [(1, 1, {"base_pressure": 1e-6, "power": 100}), (2, 1, {"base_pressure": 5e-4}),
                (3, 1, {"base_pressure": "about 1e-6"}), (4, 1, {"power": 50}), (5, 1, None),
                (6, 2, {"base_pressure": 1e-6})]
        for row in rows:
            conn.execute(sa.text("INSERT INTO process_steps VALUES (:i, :t, :p)"),
                         {"i": row[0], "t": row[1], "p": json.dumps(row[2])})
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        params = {i: json.loads(p) for i, p in conn.execute(sa.text("SELECT id, parameters FROM process_steps"))}
        field = json.loads(conn.execute(sa.text("SELECT parameter_schema FROM process_step_types WHERE id = 1"))
                           .scalar_one())[1]
        assert params[1] == {"base_pressure": 1, "power": 100}
        assert params[2] == {"base_pressure": 0.5}
        assert params[3] == {"base_pressure": "about 1e-6"}   # not a number: left as typed
        assert params[4] == {"power": 50} and params[5] is None
        assert params[6] == {"base_pressure": 1e-6}           # not a deposition
        assert field["unit"] == "×10⁻⁶ Torr" and field["placeholder"] == "e.g. 2 for 2×10⁻⁶ Torr"

        with Operations.context(MigrationContext.configure(conn)):
            migration.downgrade()
        params = {i: json.loads(p) for i, p in conn.execute(sa.text("SELECT id, parameters FROM process_steps"))}
        assert params[1]["base_pressure"] == 1e-3 and params[2]["base_pressure"] == 5e-4
