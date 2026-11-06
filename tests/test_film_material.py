"""Film material on thin film samples is a shared dropdown list."""
import importlib.util

import sqlalchemy as sa
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import ChoiceOption, Sample
from tests.loop import run


def films():
    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ChoiceOption.value)
                                     .where(ChoiceOption.list == "film_material"))).scalars().all()
    return run(go())


def reload(sample_id):
    async def go():
        async with AsyncSessionLocal() as db:
            return await db.get(Sample, sample_id)
    return run(go())


def new_thin_film(world, client, film):
    r = client.post("/samples/new", data={"sample_type": "thin_film", "substrate_id": str(world.substrate().id),
                                          "film_material": film})
    assert r.status_code == 303, r.text[:300]
    return reload(int(r.headers["location"].rsplit("/", 1)[1]))


def test_form_offers_the_list(world):
    c = world.client(world.user("film-form"))
    new_thin_film(world, c, "Ga2O3-form")
    html = c.get("/samples/new").text
    assert '<select name="film_material"' in html and '<option value="Ga2O3-form"' in html


def test_new_film_is_added_once_and_spelled_like_the_list(world):
    c = world.client(world.user("film-new"))
    first = new_thin_film(world, c, " TiN-new ")
    second = new_thin_film(world, c, "tin-NEW")
    assert first.film_material == second.film_material == "TiN-new"
    assert films().count("TiN-new") == 1 and "tin-NEW" not in films()


def test_editing_uses_the_list_spelling(world):
    owner = world.user("film-edit")
    c = world.client(owner)
    new_thin_film(world, c, "ZnO-edit")
    sample = world.sample(owner, sample_type="thin_film", substrate_id=world.substrate().id)
    r = c.post(f"/samples/{sample.id}/edit", data={"sample_type": "thin_film", "substrate_id": str(sample.substrate_id),
                                                   "film_material": "zno-edit"})
    assert r.status_code == 303
    assert reload(sample.id).film_material == "ZnO-edit"


def test_other_types_dont_add_to_the_list(world):
    c = world.client(world.user("film-bulk"))
    r = c.post("/samples/new", data={"sample_type": "bulk", "substrate_id": str(world.substrate().id),
                                     "film_material": "NotAFilm"})
    assert r.status_code == 303
    assert "NotAFilm" not in films()


def test_migration_fills_the_list_and_merges_spellings():
    spec = importlib.util.spec_from_file_location("migration_0013", "backend/migrations/versions/0013_film_material_list.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)

    engine = sa.create_engine("sqlite://")
    with engine.begin() as conn:
        conn.execute(sa.text("CREATE TABLE samples (id INTEGER, film_material TEXT)"))
        conn.execute(sa.text("CREATE TABLE choice_options (list TEXT, value TEXT)"))
        conn.execute(sa.text("INSERT INTO samples VALUES (1, 'ZnO'), (2, 'zno '), (3, 'ZnO'), (4, NULL), (5, '  '),"
                             " (6, 'tin'), (7, 'Ga2O3')"))
        conn.execute(sa.text("INSERT INTO choice_options VALUES ('film_material', 'TiN'), ('target', 'Ga2O3')"))
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        stored = dict(conn.execute(sa.text("SELECT id, film_material FROM samples")).all())
        listed = conn.execute(sa.text("SELECT value FROM choice_options WHERE list = 'film_material'")).scalars().all()
    assert stored == {1: "ZnO", 2: "ZnO", 3: "ZnO", 4: None, 5: None, 6: "TiN", 7: "Ga2O3"}
    assert sorted(listed) == ["Ga2O3", "TiN", "ZnO"]
