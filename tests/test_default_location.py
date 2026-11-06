"""Each step and analysis type has a place where it's usually done; a new entry's Where starts there."""
import importlib.util
import json
import re

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import AnalysisType, ChoiceOption, ProcessStepType
from backend.seed import seed_types
from backend.seed_data import ANALYSIS_TYPES, CHOICE_OPTIONS, PROCESS_STEP_TYPES
from tests.loop import run

PLACES = {t["name"]: t["default_location"] for t in PROCESS_STEP_TYPES + ANALYSIS_TYPES}


def _seed():
    async def go():
        async with AsyncSessionLocal() as db:
            await seed_types(db)
    run(go())


def _type(model, name):
    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(model).where(model.name == name))).scalar_one()
    return run(go())


def test_usual_places():
    inesc = {"CMP", "Deposition", "Etching", "Lithography", "Ellipsometry", "Hall / 4-probe", "Profilometry", "SEM"}
    assert {name for name, place in PLACES.items() if place == "INESC MN"} == inesc
    assert PLACES["AFM"] == "FCUL"
    assert PLACES["TEM"] is None and PLACES["XPS"] is None
    assert all(place == "CTN" for name, place in PLACES.items() if name not in inesc | {"AFM", "TEM", "XPS"})
    assert {p for p in PLACES.values() if p} <= set(CHOICE_OPTIONS["location"])


def test_type_options_carry_their_place(world):
    _seed()
    owner = world.user("place-form")
    sample = world.sample(owner)
    html = world.client(owner).get(f"/samples/{sample.id}/analyses/new").text
    afm = _type(AnalysisType, "AFM")
    tem = _type(AnalysisType, "TEM")
    assert re.search(rf'<option value="{afm.id}" data-place="FCUL"', html)
    assert re.search(rf'<option value="{tem.id}" data-place=""', html)
    assert "usualPlace" in html


def test_editing_keeps_the_entrys_own_place(world):
    _seed()
    owner = world.user("place-edit")
    sample = world.sample(owner)
    client = world.client(owner)
    dep = _type(ProcessStepType, "Deposition")
    assert client.post(f"/samples/{sample.id}/steps/new",
                       data={"type_id": str(dep.id), "location": "CTN"}).status_code == 303
    page = client.get(f"/samples/{sample.id}").text
    step_id = re.search(rf"/samples/{sample.id}/steps/(\d+)/edit", page).group(1)
    html = client.get(f"/samples/{sample.id}/steps/{step_id}/edit").text
    assert re.search(r'<option value="CTN" selected', html)
    assert "usualPlace" not in html


def test_admin_sets_the_place(world):
    _seed()
    admin = world.user("place-admin", admin=True)
    raman = _type(AnalysisType, "Raman")
    client = world.client(admin)
    assert 'name="default_location"' in client.get("/admin/").text
    r = client.post(f"/admin/analysis-types/{raman.id}/edit", data={
        "name": "Raman", "description": raman.description or "", "default_location": "FCUL",
        "parameter_schema_json": json.dumps(raman.parameter_schema)})
    assert r.status_code == 303
    assert _type(AnalysisType, "Raman").default_location == "FCUL"
    client.post(f"/admin/analysis-types/{raman.id}/edit", data={
        "name": "Raman", "description": raman.description or "", "default_location": "",
        "parameter_schema_json": json.dumps(raman.parameter_schema)})
    assert _type(AnalysisType, "Raman").default_location is None
    client.post(f"/admin/analysis-types/{raman.id}/edit", data={
        "name": "Raman", "description": raman.description or "", "default_location": "CTN",
        "parameter_schema_json": json.dumps(raman.parameter_schema)})


def test_migration_sets_places_and_adds_fcul():
    spec = importlib.util.spec_from_file_location("migration_0014", "backend/migrations/versions/0014_default_location.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE process_step_types (name TEXT)"))
        conn.execute(sa.text("CREATE TABLE analysis_types (name TEXT)"))
        conn.execute(sa.text("CREATE TABLE choice_options (list TEXT, value TEXT)"))
        conn.execute(sa.text("INSERT INTO process_step_types VALUES ('Deposition'), ('Annealing'), ('My own step')"))
        conn.execute(sa.text("INSERT INTO analysis_types VALUES ('AFM'), ('XPS'), ('Raman')"))
        conn.execute(sa.text("INSERT INTO choice_options VALUES ('location', 'CTN'), ('location', 'INESC MN')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        steps = dict(conn.execute(sa.text("SELECT name, default_location FROM process_step_types")).all())
        analyses = dict(conn.execute(sa.text("SELECT name, default_location FROM analysis_types")).all())
        places = conn.execute(sa.text("SELECT value FROM choice_options WHERE list = 'location'")).scalars().all()
    assert steps == {"Deposition": "INESC MN", "Annealing": "CTN", "My own step": "CTN"}
    assert analyses == {"AFM": "FCUL", "XPS": None, "Raman": "CTN"}
    assert sorted(places) == ["CTN", "FCUL", "INESC MN"]
    assert migration.DEFAULT_LOCATIONS == {k: v for k, v in PLACES.items() if v != "CTN"}
