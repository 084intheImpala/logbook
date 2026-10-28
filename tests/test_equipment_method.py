"""Equipment that only suits one method: AnnealSYS is RTA only."""
from sqlalchemy import select

from backend.choices import option_methods, remember
from backend.database import AsyncSessionLocal
from backend.models import ChoiceOption
from backend.params import located_methods
from tests.loop import run

ANNEALING = [
    {"key": "equipment", "type": "choice", "list": "annealing_equipment", "located": True},
    {"key": "method", "type": "variant", "options": [{"value": "Furnace", "fields": []}, {"value": "RTA", "fields": []}]},
]


def test_located_methods_follow_the_chosen_method():
    assert located_methods(ANNEALING, {"method": "RTA"}) == {"annealing_equipment": "RTA"}
    assert located_methods(ANNEALING, {}) == {}
    assert located_methods([ANNEALING[0]], {"method": "RTA"}) == {}      # no Method choice next to it


def test_new_equipment_is_filed_under_the_chosen_method(world):
    async def go():
        async with AsyncSessionLocal() as db:
            await remember(db, [("annealing_equipment", "TubeFurnace9")], None, "CTN",
                           {"annealing_equipment"}, {"annealing_equipment": "Furnace"})
            await db.commit()
            return (await option_methods(db))["annealing_equipment"]
    assert run(go())["TubeFurnace9"] == "Furnace"


def test_form_marks_each_equipment_with_its_method(world):
    async def add():
        async with AsyncSessionLocal() as db:
            db.add(ChoiceOption(list="annealing_equipment", value="AnnealSYS-test", location="CTN", applies_to="RTA"))
            await db.commit()
    run(add())
    owner = world.user("eq-owner")
    sample = world.sample(owner)
    html = world.client(owner).get(f"/samples/{sample.id}/steps/new").text
    assert 'data-method="RTA"' in html and "AnnealSYS-test" in html
    assert 'data-by="p::method"' in html


def test_migration_data_fix_is_a_prefix_match():
    # the 0011 migration tags AnnealSYS (any spelling after it) as RTA only
    import re
    sql = open("backend/migrations/versions/0011_equipment_method.py").read()
    assert re.search(r"lower\(value\) LIKE 'annealsys%'", sql)
