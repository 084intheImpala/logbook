"""The CMP process type: its fields, dropdowns and Portuguese labels."""
import importlib.util
import json
import re

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.i18n import translate
from backend.models import ChoiceOption, ProcessStep, ProcessStepType
from backend.params import schema_keys, validate_schema
from backend.seed import seed_types
from backend.seed_data import CHOICE_OPTIONS, PROCESS_STEP_TYPES
from tests.loop import run

CMP = next(t for t in PROCESS_STEP_TYPES if t["name"] == "CMP")


def _fields(schema):
    for field in schema:
        yield field
        yield from _fields(field.get("fields") or [])


def test_schema_is_valid_and_has_only_the_fields_in_use():
    assert validate_schema(CMP["parameter_schema"]) is None
    assert schema_keys(CMP["parameter_schema"]) == {
        "equipment", "slurry", "dilution", "slurry_flow", "pad", "force_mode", "force", "rotation", "carrier_speed",
        "platen_speed", "duration", "thickness_removed", "removal_rate"}


def test_typical_recipe_is_the_default():
    defaults = {f["key"]: f["default"] for f in CMP["parameter_schema"] if "default" in f}
    assert defaults == {"slurry": "SF1 Polishing Solutions", "pad": "Chemomet", "force_mode": "Central", "force": 20,
                        "rotation": "Same direction", "carrier_speed": 30, "platen_speed": 30}


def test_slurry_and_pad_have_one_option_each():
    assert CHOICE_OPTIONS["cmp_slurry"] == ["SF1 Polishing Solutions"]
    assert CHOICE_OPTIONS["cmp_pad"] == ["Chemomet"]


def test_every_label_and_placeholder_is_translated():
    for field in _fields(CMP["parameter_schema"]):
        for text in (field["label"], field.get("placeholder")):
            if text:
                assert translate("pt", text) != text


def test_existing_databases_get_the_type_and_its_lists_on_startup(world):
    async def go():
        async with AsyncSessionLocal() as db:
            await seed_types(db)
            cmp_type = (await db.execute(select(ProcessStepType).where(ProcessStepType.name == "CMP"))).scalar_one()
            pads = (await db.execute(select(ChoiceOption.value).where(ChoiceOption.list == "cmp_pad"))).scalars().all()
            return cmp_type.parameter_schema, pads
    schema, pads = run(go())
    assert schema == CMP["parameter_schema"]
    assert pads == ["Chemomet"]


def test_new_form_starts_with_the_typical_recipe(world):
    run(_seed())
    owner = world.user("cmp-owner")
    sample = world.sample(owner)
    html = world.client(owner).get(f"/samples/{sample.id}/steps/new").text
    assert "Velocidade da cabeça" in html and "Aplicação da força" in html
    assert re.search(r'name="p::force"[^>]*value="20"', html)
    assert re.search(r'value="Chemomet" selected', html)


def test_editing_doesnt_fill_in_what_was_left_empty(world):
    run(_seed())
    owner = world.user("cmp-editor")
    sample = world.sample(owner)
    client = world.client(owner)
    client.post(f"/samples/{sample.id}/steps/new", data={"type_id": run(_cmp_id()), "p::dilution": "1:10"})

    async def step_id():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStep.id).where(ProcessStep.sample_id == sample.id))).scalar_one()
    html = client.get(f"/samples/{sample.id}/steps/{run(step_id())}/edit").text
    assert re.search(r'name="p::force"[^>]*value=""', html)


def test_saving_a_cmp_step_keeps_its_parameters(world):
    run(_seed())
    owner = world.user("cmp-saver")
    sample = world.sample(owner)
    client = world.client(owner)

    response = client.post(f"/samples/{sample.id}/steps/new", data={
        "type_id": run(_cmp_id()), "p::slurry": "OtherSlurry", "p::pad": "NewPad", "p::force": "30",
        "p::platen_speed": "60", "p::duration": "2:30", "p::rotation": "Same direction"})
    assert response.status_code == 303

    async def saved():
        async with AsyncSessionLocal() as db:
            step = (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample.id))).scalar_one()
            pads = (await db.execute(select(ChoiceOption.value).where(ChoiceOption.list == "cmp_pad"))).scalars().all()
            return step.parameters, pads
    params, pads = run(saved())
    assert params["slurry"] == "OtherSlurry" and params["force"] == 30 and params["duration"] == "2:30"
    assert params["rotation"] == "Same direction"
    assert "NewPad" in pads


def test_migration_replaces_the_schema_and_empties_the_lists():
    path = "backend/migrations/versions/0012_cmp_typical_recipe.py"
    spec = importlib.util.spec_from_file_location("migration_0012", path)
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE process_step_types (name TEXT, parameter_schema JSON)"))
        conn.execute(sa.text("CREATE TABLE choice_options (list TEXT, value TEXT)"))
        conn.execute(sa.text("INSERT INTO process_step_types VALUES ('CMP', '[]'), ('Etching', '[]')"))
        conn.execute(sa.text("INSERT INTO choice_options VALUES ('cmp_slurry', 'Ceria'), ('cmp_pad', 'IC1000'),"
                             " ('atmosphere', 'Ar')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        schemas = dict(conn.execute(sa.text("SELECT name, parameter_schema FROM process_step_types")).all())
        lists = conn.execute(sa.text("SELECT list FROM choice_options")).scalars().all()
    assert json.loads(schemas["CMP"]) == CMP["parameter_schema"]
    assert schemas["Etching"] == "[]"
    assert lists == ["atmosphere"]


async def _cmp_id():
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == "CMP"))).scalar_one()


async def _seed():
    async with AsyncSessionLocal() as db:
        await seed_types(db)
