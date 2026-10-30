"""The CMP process type: its fields, dropdowns and Portuguese labels."""
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


def test_schema_is_valid_and_has_the_recipe_fields():
    assert validate_schema(CMP["parameter_schema"]) is None
    assert {"equipment", "slurry", "pad", "force", "platen_speed", "carrier_speed", "duration",
            "slurry_flow", "conditioning_details"} <= schema_keys(CMP["parameter_schema"])


def test_dropdowns_have_starting_values():
    assert CHOICE_OPTIONS["cmp_slurry"] and CHOICE_OPTIONS["cmp_pad"]


def test_every_label_and_placeholder_is_translated():
    for field in _fields(CMP["parameter_schema"]):
        for text in (field["label"], field.get("placeholder")):
            if text and text != "pH":
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
    assert "IC1000" in pads


def test_form_offers_the_cmp_fields(world):
    run(_seed())
    owner = world.user("cmp-owner")
    sample = world.sample(owner)
    html = world.client(owner).get(f"/samples/{sample.id}/steps/new").text
    assert "Tipo de slurry" in html and "Condicionamento do pad" in html


def test_saving_a_cmp_step_keeps_its_parameters(world):
    run(_seed())
    owner = world.user("cmp-saver")
    sample = world.sample(owner)
    client = world.client(owner)

    async def cmp_id():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == "CMP"))).scalar_one()

    response = client.post(f"/samples/{sample.id}/steps/new", data={
        "type_id": run(cmp_id()), "p::slurry": "Ceria", "p::pad": "NewPad", "p::force": "30",
        "p::platen_speed": "60", "p::duration": "2:30", "p::conditioning": "on",
        "p::conditioning_details": "ex situ"})
    assert response.status_code == 303

    async def saved():
        async with AsyncSessionLocal() as db:
            step = (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample.id))).scalar_one()
            pads = (await db.execute(select(ChoiceOption.value).where(ChoiceOption.list == "cmp_pad"))).scalars().all()
            return step.parameters, pads
    params, pads = run(saved())
    assert params["slurry"] == "Ceria" and params["force"] == 30 and params["duration"] == "2:30"
    assert params["conditioning"] is True and params["conditioning_details"] == "ex situ"
    assert "NewPad" in pads


async def _seed():
    async with AsyncSessionLocal() as db:
        await seed_types(db)
