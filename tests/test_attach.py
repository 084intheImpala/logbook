"""Add files tab: find entries across samples and attach the same files to all."""
from datetime import date, timedelta

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Analysis, AnalysisType, Attachment, ProcessStep, ProcessStepType
from backend.seed import seed_types
from tests.loop import run

YESTERDAY = date.today() - timedelta(days=1)


def _entry(sample, type_name, performer, day=YESTERDAY, analysis=False, notes=None):
    async def make():
        async with AsyncSessionLocal() as db:
            await seed_types(db)
            if analysis:
                type_id = (await db.execute(select(AnalysisType.id).where(AnalysisType.name == type_name))).scalar_one()
                entry = Analysis(sample_id=sample.id, analysis_type_id=type_id, position=1, performed_at=day,
                                 performer_id=performer.id if performer else None, notes=notes)
            else:
                type_id = (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == type_name))).scalar_one()
                entry = ProcessStep(sample_id=sample.id, step_type_id=type_id, position=1, performed_at=day,
                                    performer_id=performer.id if performer else None, notes=notes)
            db.add(entry)
            await db.commit()
            return entry.id, type_id
    return run(make())


def _attachments(kind, ids):
    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Attachment).where(Attachment.entity_type == kind,
                                                              Attachment.entity_id.in_(ids)))).scalars().all()
    return run(go())


def test_finds_my_annealings_from_yesterday_but_not_others(world):
    me, other = world.user("attach-me"), world.user("attach-other")
    mine, theirs = world.sample(me), world.sample(other)
    anneal, anneal_type = _entry(mine, "Annealing", me, notes="mine-yesterday")
    old, _ = _entry(mine, "Annealing", me, day=YESTERDAY - timedelta(days=5), notes="mine-older")
    _entry(mine, "Deposition", me, notes="mine-deposition")
    _entry(mine, "Annealing", other, notes="by-a-colleague")
    _entry(theirs, "Annealing", other, notes="not-my-sample")

    html = world.client(me).get("/attach", params={
        "searched": "1", "mine": "1", "type": f"step:{anneal_type}",
        "date_from": YESTERDAY.isoformat(), "date_to": YESTERDAY.isoformat()}).text
    assert f'value="step:{anneal}"' in html and "mine-yesterday" in html
    for hidden in ("mine-older", "mine-deposition", "by-a-colleague", "not-my-sample"):
        assert hidden not in html


def test_done_by_me_is_on_by_default_and_can_be_unticked(world):
    me, colleague = world.user("attach-default"), world.user("attach-colleague")
    sample = world.sample(me)
    _entry(sample, "Annealing", colleague, notes="colleague-did-it")
    client = world.client(me)
    assert "colleague-did-it" not in client.get("/attach").text
    assert "colleague-did-it" in client.get("/attach", params={"searched": "1"}).text


def test_one_upload_goes_to_entries_on_several_samples(world):
    me = world.user("attach-many")
    first, second = world.sample(me), world.sample(me)
    step_id, _ = _entry(first, "Ion Implantation", me)
    other_step, _ = _entry(second, "Ion Implantation", me)
    analysis_id, _ = _entry(second, "SEM", me, analysis=True)

    response = world.client(me).post("/attach", data={
        "entry": [f"step:{step_id}", f"step:{other_step}", f"analysis:{analysis_id}"], "searched": "1"},
        files=[("files", ("recipe.txt", b"dose 1e15", "text/plain"))])
    assert response.status_code == 303 and response.headers["location"].startswith("/attach?")

    steps = _attachments("step", [step_id, other_step])
    analyses = _attachments("analysis", [analysis_id])
    assert len(steps) == 2 and len(analyses) == 1
    assert len({a.stored_filename for a in steps + analyses}) == 1   # stored once, shared
    assert (world.upload_dir / steps[0].stored_filename).read_bytes() == b"dose 1e15"


def test_cannot_attach_to_someone_elses_entry(world):
    me, other = world.user("attach-intruder"), world.user("attach-victim")
    mine, theirs = world.sample(me), world.sample(other)
    my_step, _ = _entry(mine, "Annealing", me)
    their_step, _ = _entry(theirs, "Annealing", other)
    response = world.client(me).post("/attach", data={"entry": [f"step:{my_step}", f"step:{their_step}"]},
                                     files=[("files", ("x.txt", b"x", "text/plain"))])
    assert response.status_code == 403
    assert _attachments("step", [my_step, their_step]) == []


def test_nothing_chosen_adds_nothing(world):
    me = world.user("attach-empty")
    step_id, _ = _entry(world.sample(me), "Annealing", me)
    client = world.client(me)
    response = client.post("/attach", data={"entry": [f"step:{step_id}"]})
    assert response.status_code == 303
    assert _attachments("step", [step_id]) == []
    assert "Marque pelo menos uma entrada" in client.get(response.headers["location"]).text


def test_tab_is_in_the_menu(world):
    me = world.user("attach-menu")
    html = world.client(me).get("/samples/").text
    assert 'href="/attach"' in html and "Adicionar ficheiros" in html
