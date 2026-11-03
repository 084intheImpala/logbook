"""The Cleaning process type: where (the entry's Where) and details."""
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.i18n import translate
from backend.models import ProcessStep, ProcessStepType
from backend.params import schema_keys, validate_schema
from backend.seed import seed_types
from backend.seed_data import PROCESS_STEP_TYPES
from tests.loop import run

CLEANING = next(t for t in PROCESS_STEP_TYPES if t["name"] == "Cleaning")


def test_schema_only_asks_for_details():
    assert validate_schema(CLEANING["parameter_schema"]) is None
    assert schema_keys(CLEANING["parameter_schema"]) == {"details"}


def test_label_and_placeholder_are_translated():
    field = CLEANING["parameter_schema"][0]
    assert translate("pt", field["label"]) == "Detalhes"
    assert translate("pt", field["placeholder"]) != field["placeholder"]


def test_form_offers_the_details_field(world):
    run(_seed())
    owner = world.user("cleaning-owner")
    sample = world.sample(owner)
    html = world.client(owner).get(f"/samples/{sample.id}/steps/new").text
    assert "Cleaning" in html and "banho de ultrassons" in html


def test_saving_a_cleaning_step_keeps_where_and_details(world):
    run(_seed())
    owner = world.user("cleaning-saver")
    sample = world.sample(owner)

    async def cleaning_id():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == "Cleaning"))).scalar_one()

    response = world.client(owner).post(f"/samples/{sample.id}/steps/new", data={
        "type_id": run(cleaning_id()), "location": "CTN", "p::details": "Acetone, IPA, 5 min each"})
    assert response.status_code == 303

    async def saved():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample.id))).scalar_one()
    step = run(saved())
    assert step.location == "CTN"
    assert step.parameters["details"] == "Acetone, IPA, 5 min each"


async def _seed():
    async with AsyncSessionLocal() as db:
        await seed_types(db)
