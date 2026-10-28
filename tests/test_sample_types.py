"""Sample types (thin film, bulk, project) and the ID prompt after a type change."""
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Sample, Suggestion
from tests.loop import run


def reload(sample_id):
    async def go():
        async with AsyncSessionLocal() as db:
            return await db.get(Sample, sample_id)
    return run(go())


def new_project_sample(client, project, **extra):
    return client.post("/samples/new", data={"sample_type": "project", "project_id": str(project.id),
                                             "description": "bought", **extra})


def edit(client, sample, **fields):
    data = {"sample_type": sample.sample_type, "substrate_id": str(sample.substrate_id or ""),
            "project_id": str(sample.project_id or ""), "description": sample.description or "", **fields}
    return client.post(f"/samples/{sample.id}/edit", data=data)


def test_project_sample_is_numbered_under_the_project_code(world):
    owner, project = world.user("typ-owner"), world.project()
    c = world.client(owner)
    r = new_project_sample(c, project)
    assert r.status_code == 303, r.text[:300]
    sample = reload(int(r.headers["location"].rsplit("/", 1)[1]))
    assert sample.sample_type == "project" and sample.code.startswith(f"{project.code}-")
    assert "ID given" not in c.get(f"/samples/{sample.id}").text


def test_project_sample_needs_a_project_and_a_description(world):
    c = world.client(world.user("typ-need"))
    project = world.project()
    assert c.post("/samples/new", data={"sample_type": "project", "description": "x"}).status_code == 400
    assert c.post("/samples/new", data={"sample_type": "project", "project_id": str(project.id)}).status_code == 400


def test_old_types_are_no_longer_offered(world):
    html = world.client(world.user("typ-form")).get("/samples/new").text
    assert 'value="project"' in html and 'value="thin_film"' in html and 'value="bulk"' in html
    assert 'value="commercial"' not in html and 'value="collaboration"' not in html
    assert "A sample we deposited ourselves" in html or "Uma amostra que depositámos" in html


def test_tab_is_called_partners(world):
    html = world.client(world.user("typ-tab")).get("/projects/").text
    assert "Partners" in html or "Parceiros" in html


def make_thin_film(world, owner):
    return world.sample(owner, sample_type="thin_film", substrate_id=world.substrate().id)


def test_no_prompt_between_thin_film_and_bulk(world):
    owner = world.user("typ-bulk")
    sample = make_thin_film(world, owner)
    c = world.client(owner)
    assert edit(c, sample, sample_type="bulk").status_code == 303
    assert "code-prompt" not in c.get(f"/samples/{sample.id}").text


def test_user_is_asked_to_keep_the_id_or_ask_an_admin(world):
    owner, project = world.user("typ-user"), world.project()
    sample = make_thin_film(world, owner)
    c = world.client(owner)
    assert edit(c, sample, sample_type="project", project_id=str(project.id), description="sent").status_code == 303
    page = c.get(f"/samples/{sample.id}").text
    assert "code-prompt" in page and f"/samples/{sample.id}/ask-recode" in page
    assert f"/samples/{sample.id}/recode" not in page          # users can't change IDs
    assert "code-prompt" not in c.get(f"/samples/{sample.id}").text   # asked once

    assert c.post(f"/samples/{sample.id}/ask-recode").status_code == 303

    async def asked():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Suggestion).where(Suggestion.user_id == owner.id))).scalars().all()
    (suggestion,) = run(asked())
    assert sample.code in suggestion.text and project.code in suggestion.text
    assert reload(sample.id).code == sample.code                      # nothing changed by itself


def test_admin_is_offered_the_new_id_and_can_take_it(world):
    admin, owner, project = world.user("typ-admin", admin=True), world.user("typ-adm-owner"), world.project()
    sample = make_thin_film(world, owner)
    c = world.client(admin)
    assert edit(c, sample, sample_type="project", project_id=str(project.id), description="sent").status_code == 303
    page = c.get(f"/samples/{sample.id}").text
    assert "code-prompt" in page and f"{project.code}-{sample.code.split('-')[1]}-001" in page
    assert f'value="project:{project.id}"' in page
    r = c.post(f"/samples/{sample.id}/recode", data={"prefix": f"project:{project.id}"})
    assert r.status_code == 303
    assert reload(sample.id).code.startswith(f"{project.code}-")
    assert reload(sample.id).previous_codes == [sample.code]


def test_changing_project_asks_again_but_a_plain_edit_does_not(world):
    owner, a, b = world.user("typ-move"), world.project(), world.project()
    sample = world.sample(owner, sample_type="project", project_id=a.id, description="x")
    c = world.client(owner)
    assert edit(c, sample, description="changed").status_code == 303
    assert "code-prompt" not in c.get(f"/samples/{sample.id}").text
    assert edit(c, sample, project_id=str(b.id)).status_code == 303
    assert "code-prompt" in c.get(f"/samples/{sample.id}").text


def test_ask_recode_needs_edit_access(world):
    owner, other = world.user("typ-ask-owner"), world.user("typ-ask-other")
    sample = world.sample(owner)
    assert world.client(other).post(f"/samples/{sample.id}/ask-recode").status_code == 403


def test_visibility_can_be_changed_when_editing(world):
    owner, mate = world.user("vis-owner"), world.user("vis-mate")
    sample = world.sample(owner, visibility="personal", sample_type="project", project_id=world.project().id, description="x")
    c = world.client(owner)
    assert 'name="visibility"' in c.get(f"/samples/{sample.id}/edit").text
    assert edit(c, sample, visibility="public").status_code == 303
    assert reload(sample.id).visibility == "public"
    assert edit(c, sample, visibility="nonsense").status_code == 303
    assert reload(sample.id).visibility == "public"
    # someone who can edit but doesn't own it neither sees nor changes it
    shared = world.sample(owner, shared_edit=[mate], visibility="personal", sample_type="project",
                          project_id=world.project().id, description="x")
    m = world.client(mate)
    assert 'name="visibility"' not in m.get(f"/samples/{shared.id}/edit").text
    assert edit(m, shared, visibility="public").status_code == 303
    assert reload(shared.id).visibility == "personal"
