"""Planned entries (on the timeline, left out of search, exports and rates
until marked done), the deposition duration calculator's last known rate,
and the search page's parameter filters only offering parameters in use."""
import importlib.util
import json
import re

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.i18n import translate
from backend.models import AnalysisType, ProcessStep, ProcessStepType
from backend.seed_data import PROCESS_STEP_TYPES
from tests.loop import run

DEPOSITION = next(t for t in PROCESS_STEP_TYPES if t["name"] == "Deposition")


async def _type_id(model, name):
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(model.id).where(model.name == name))).scalar_one()


def _deposit(client, sample, planned=False, date=None, **params):
    data = {"type_id": run(_type_id(ProcessStepType, "Deposition"))} | {f"p::{k}": v for k, v in params.items()}
    if planned:
        data["planned"] = "1"
    if date:
        data["performed_at"] = date
    r = client.post(f"/samples/{sample.id}/steps/new", data=data)
    assert r.status_code == 303
    return r


def _steps(sample):
    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample.id)
                                     .order_by(ProcessStep.id))).scalars().all()
    return run(go())


def _entries(html):
    start = html.index('id="technique-entries"')
    return html[start:html.index("</section>", start)]


def test_the_deposition_has_the_calculator_fields_before_the_duration():
    keys = [f["key"] for f in DEPOSITION["parameter_schema"]]
    assert keys.index("target_thickness") + 1 == keys.index("rate_used") == keys.index("duration") - 1
    for f in DEPOSITION["parameter_schema"]:
        if f["key"] in ("target_thickness", "rate_used"):
            assert translate("pt", f["label"]) != f["label"]
            assert f["unit"] in ("nm", "nm/min")


def test_plan_a_step_form_starts_planned(world):
    owner = world.user("plan-form")
    sample = world.sample(owner)
    client = world.client(owner)
    assert "Planear um passo" in client.get(f"/samples/{sample.id}").text
    html = client.get(f"/samples/{sample.id}/steps/new?planned=1").text
    assert "Planear um passo de processo" in html
    assert re.search(r'name="planned" value="1" checked', html)
    assert "/steps/last-rate" in html   # the calculator, for depositions
    html = client.get(f"/samples/{sample.id}/steps/new").text
    assert not re.search(r'name="planned" value="1" checked', html)


def test_a_planned_step_is_on_the_timeline_but_not_in_search_or_exports(world):
    owner = world.user("plan-owner")
    sample = world.sample(owner)
    client = world.client(owner)
    _deposit(client, sample, planned=True, date="2030-01-15", machine="PlanMachine1", target_thickness="100",
             rate_used="5", duration="20:00")
    step = _steps(sample)[0]
    assert step.planned and step.parameters["rate_used"] == 5 and step.parameters["target_thickness"] == 100

    html = client.get(f"/samples/{sample.id}").text
    assert "Planeado" in html and "para 2030-01-15" in html
    assert f"/samples/{sample.id}/steps/{step.id}/edit?done=1" in html and "Marcar como feito" in html

    search = client.get("/search", params={"technique": "Deposition", "q": sample.code}).text
    assert sample.code not in _entries(search)
    assert "PlanMachine1" not in client.get("/search/export.csv", params={"q": sample.code}).text

    # Marking it done: the form comes unticked, saving puts it in search
    form = client.get(f"/samples/{sample.id}/steps/{step.id}/edit?done=1").text
    assert "Marcar uma entrada planeada como feita" in form
    assert not re.search(r'name="planned" value="1" checked', form)
    r = client.post(f"/samples/{sample.id}/steps/{step.id}/edit", data={
        "type_id": step.step_type_id, "performed_at": "2030-01-16", "p::machine": "PlanMachine1",
        "p::duration": "20:00", "p::base_pressure": "1e-4"})
    assert r.status_code == 303
    assert not _steps(sample)[0].planned
    assert "Marcar como feito" not in client.get(f"/samples/{sample.id}").text
    assert sample.code in _entries(client.get("/search", params={"technique": "Deposition"}).text)
    assert "PlanMachine1" in client.get("/search/export.csv", params={"q": sample.code}).text


def test_a_planned_deposition_isnt_measured(world):
    owner = world.user("plan-measure")
    sample = world.sample(owner)
    client = world.client(owner)
    _deposit(client, sample, planned=True, duration="10:00")
    r = client.post(f"/samples/{sample.id}/analyses/new", data={
        "type_id": run(_type_id(AnalysisType, "Profilometry")), "p::thickness": "100"})
    assert r.status_code == 303
    html = client.get(f"/samples/{sample.id}").text
    assert "Contada para a taxa de deposição" not in html and 'id="rate-prompt"' not in html


def test_the_last_known_rate_matches_the_conditions_filled_in(world):
    owner = world.user("plan-rate")
    client = world.client(owner)
    old, new, other, planned = (world.sample(owner) for _ in range(4))
    conditions = {"machine": "RateMachine9", "target": "Ga2O3", "power": "100"}
    _deposit(client, old, date="2026-01-10", deposition_rate="4", **conditions)
    _deposit(client, new, date="2026-03-10", deposition_rate="6", **conditions)
    _deposit(client, other, date="2026-05-10", deposition_rate="9", **conditions | {"power": "150"})
    _deposit(client, planned, planned=True, date="2026-06-10", rate_used="1", **conditions)

    url = f"/samples/{planned.id}/steps/last-rate"
    found = client.get(url, params={"p::machine": "RateMachine9", "p::target": "ga2o3", "p::power": "100"}).json()
    assert found["rate"] == 6 and new.code in found["message"] and "2026-03-10" in found["message"]
    assert found["url"] == f"/samples/{new.id}#step-{_steps(new)[0].id}"
    # Empty conditions match anything: the latest with this machine is the 150 W one
    assert client.get(url, params={"p::machine": "RateMachine9"}).json()["rate"] == 9
    none = client.get(url, params={"p::machine": "RateMachine9", "p::power": "42"}).json()
    assert none["rate"] is None and "Nenhuma deposição" in none["message"]
    assert client.get(url).json()["rate"] is None

    # Someone who can't see these samples doesn't get their rates
    stranger = world.client(world.user("plan-stranger"))
    stranger_sample = world.sample(world.user("plan-stranger-owner"))
    r = stranger.get(f"/samples/{stranger_sample.id}/steps/last-rate", params={"p::machine": "RateMachine9"})
    assert r.status_code == 403 or r.json()["rate"] is None


def test_search_only_offers_filters_for_parameters_in_use(world):
    owner = world.user("plan-filters")
    sample = world.sample(owner)
    client = world.client(owner)
    _deposit(client, sample, machine="FilterMachine3", power="80")
    html = client.get("/search", params={"technique": "Deposition", "q": sample.code}).text
    assert 'name="min.power"' in html and 'name="pf.machine"' in html
    assert 'name="pf.station"' not in html and 'name="min.target_thickness"' not in html
    # A filter in use stays offered even if nothing has it
    html = client.get("/search", params={"technique": "Deposition", "q": sample.code, "pf.station": "x"}).text
    assert 'name="pf.station"' in html


def test_migration_adds_the_column_and_inserts_the_fields_before_the_duration():
    path = "backend/migrations/versions/0016_planned_entries.py"
    spec = importlib.util.spec_from_file_location("migration_0016", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    old = [{"key": "power", "label": "Power", "type": "number"},
           {"key": "duration", "label": "Duration", "type": "duration"},
           {"key": "notes_by_admin", "label": "Admin's own", "type": "text"}]
    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE process_step_types (id INTEGER PRIMARY KEY, name TEXT, parameter_schema JSON)"))
        for table in ("process_steps", "analyses"):
            conn.execute(sa.text(f"CREATE TABLE {table} (id INTEGER PRIMARY KEY)"))
            conn.execute(sa.text(f"INSERT INTO {table} (id) VALUES (1)"))
        conn.execute(sa.text("INSERT INTO process_step_types VALUES (1, 'Deposition', :s), (2, 'Etching', '[]')"),
                     {"s": json.dumps(old)})
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        schemas = dict(conn.execute(sa.text("SELECT name, parameter_schema FROM process_step_types")).all())
        planned = conn.execute(sa.text("SELECT planned FROM process_steps")).scalar_one()
    keys = [f["key"] for f in json.loads(schemas["Deposition"])]
    assert keys == ["power", "target_thickness", "rate_used", "duration", "notes_by_admin"]
    assert schemas["Etching"] == "[]"
    assert planned in (0, False)
