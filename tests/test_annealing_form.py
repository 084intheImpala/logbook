"""Annealing's form: Where, then Furnace / RTA, then the equipment for that place
and method; and each parameter offered once when it differs per sample."""
import json
import re

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import ProcessStepType
from backend.params import scalar_fields, varied_params, vary_choices
from backend.seed import seed_types
from backend.seed_data import PROCESS_STEP_TYPES
from tests.loop import run

ANNEALING = next(t for t in PROCESS_STEP_TYPES if t["name"] == "Annealing")["parameter_schema"]


def test_each_key_is_varied_once():
    keys = [f["key"] for f in scalar_fields(ANNEALING)]
    assert len(keys) == len(set(keys))
    assert {"equipment", "temperature", "duration", "atmosphere", "ramp"} <= set(keys)


def test_vary_choices_know_their_method():
    when = {(f["key"], (w or {}).get("value")) for f, w in vary_choices(ANNEALING)}
    assert {("temperature", "Furnace"), ("temperature", "RTA"), ("ramp", "RTA"), ("equipment", None)} <= when
    assert ("ramp", "Furnace") not in when


def test_a_varied_temperature_is_read_once():
    params, _ = varied_params({"vary::7::temperature": "450"}, ANNEALING, 7)
    assert params == {"temperature": 450}


def _form(world, name):
    async def go():
        async with AsyncSessionLocal() as db:
            await seed_types(db)
            return (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == "Annealing"))).scalar_one()
    type_id = run(go())
    owner = world.user(name)
    sample = world.sample(owner)
    return type_id, world.client(owner).get(f"/samples/{sample.id}/steps/new").text


def test_equipment_comes_after_the_method_and_before_its_fields(world):
    type_id, html = _form(world, "anneal-order")
    block = html[html.index(f'data-type="{type_id}"'):]
    block = block[:block.index('class="type-fields')] if 'class="type-fields' in block else block
    where, method = html.index('name="location"'), block.index('name="p::method"')
    equipment, first_variant = block.index('name="p::equipment"'), block.index('data-variant-of=')
    assert where < html.index(f'data-type="{type_id}"')
    assert method < equipment < first_variant
    assert block.count('name="p::equipment"') == 1


def test_vary_list_tags_each_methods_fields(world):
    type_id, html = _form(world, "anneal-vary")
    fields = json.loads(re.search(r"const varyFields = (\{.*?\});\n", html).group(1))[str(type_id)]
    pairs = [(f["key"], (f["when"] or {}).get("value")) for f in fields]
    assert len(pairs) == len(set(pairs))
    assert ("temperature", "Furnace") in pairs and ("temperature", "RTA") in pairs
