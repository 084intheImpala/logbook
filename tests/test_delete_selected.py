"""Deleting several samples ticked on the samples list (/samples/delete-selected)."""
from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import ActivityLog, Attachment, Sample
from tests.loop import run


def _exists(*samples) -> list[bool]:
    async def go():
        async with AsyncSessionLocal() as db:
            found = set((await db.execute(select(Sample.id).where(Sample.id.in_([s.id for s in samples])))).scalars())
            return [s.id in found for s in samples]
    return run(go())


def _pieces(client, parent, n=2):
    r = client.post(f"/samples/{parent.id}/cut", data={"piece_labels": [f"p{i}" for i in range(n)],
                                                       "piece_dimensions": [""] * n})
    assert r.status_code == 303, r.text[:300]

    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Sample).where(Sample.code.like(f"{parent.code}-%"))
                                     .order_by(Sample.code))).scalars().all()
    return run(go())


def _ids(*samples):
    """The ticked boxes: ids=1&ids=2 (as a query, or a form with the test client)."""
    return {"ids": [str(s.id) for s in samples]}


def test_the_list_has_the_button_and_asking_deletes_nothing(world):
    owner = world.user("bulk-ask")
    a, b = world.sample(owner), world.sample(owner)
    client = world.client(owner)
    assert 'id="delete-selected"' in client.get("/samples/").text
    page = client.get("/samples/delete-selected", params=_ids(a, b))
    assert page.status_code == 200
    assert a.code in page.text and b.code in page.text and "Eliminar 2 amostras" in page.text
    assert _exists(a, b) == [True, True]


def test_deletes_the_ticked_samples_with_their_files_and_logs_each(world):
    owner = world.user("bulk-del")
    a, b, kept = world.sample(owner), world.sample(owner), world.sample(owner)
    _, att_a = world.step(a, "a", with_file="only a")
    client = world.client(owner)
    r = client.post("/samples/delete-selected", data=_ids(a, b))
    assert r.status_code == 303 and r.headers["location"] == "/samples/"
    assert "Eliminadas 2 amostras." in client.get("/samples/").text
    assert _exists(a, b, kept) == [False, False, True]

    async def go():
        async with AsyncSessionLocal() as db:
            logged = (await db.execute(select(ActivityLog.target).where(ActivityLog.action == "sample_deleted"))).scalars().all()
            left = (await db.execute(select(Attachment).where(Attachment.id == att_a))).scalar_one_or_none()
            return logged, left
    logged, left = run(go())
    assert a.code in logged and b.code in logged and left is None


def test_samples_the_user_cant_delete_stay_and_the_page_says_why(world):
    owner, other = world.user("bulk-mine"), world.user("bulk-theirs")
    mine = world.sample(owner)
    theirs = world.sample(other, shared_edit=[owner])     # may edit, but not delete
    client = world.client(owner)
    page = client.get("/samples/delete-selected", params=_ids(mine, theirs)).text
    assert "Eliminar 1 amostra" in page and "Estas ficam" in page and theirs.code in page
    client.post("/samples/delete-selected", data=_ids(mine, theirs))
    assert _exists(mine, theirs) == [False, True]


def test_a_sample_goes_with_its_pieces_only_when_they_are_ticked_too(world):
    owner = world.user("bulk-pieces")
    parent = world.sample(owner)
    client = world.client(owner)
    left, right = _pieces(client, parent)
    # the parent alone: its pieces stay, so it stays too (as a single delete would refuse)
    page = client.get("/samples/delete-selected", params=_ids(parent)).text
    assert "Nenhuma das amostras selecionadas pode ser eliminada" in page and "herdam" in page
    client.post("/samples/delete-selected", data=_ids(parent, left))
    assert _exists(parent, left, right) == [True, False, True]
    # with all its pieces: the pieces go first, then the sample
    client.post("/samples/delete-selected", data=_ids(parent, right))
    assert _exists(parent, right) == [False, False]


def test_a_file_another_sample_uses_stays(world):
    owner = world.user("bulk-shared")
    a, b = world.sample(owner), world.sample(owner)
    step_a, _ = world.step(a, "a")
    step_b, _ = world.step(b, "b")
    client = world.client(owner)
    for sample, step in ((a, step_a), (b, step_b)):
        r = client.post(f"/files/upload/{sample.id}", data={"entity_type": "step", "entity_id": str(step)},
                        files={"files": ("same.raw", b"bulk-shared-content", "application/octet-stream")})
        assert r.status_code == 303

    async def stored_name():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Attachment.stored_filename)
                                     .where(Attachment.entity_type == "step", Attachment.entity_id == step_b))).scalar_one()
    name = run(stored_name())
    client.post("/samples/delete-selected", data=_ids(a))
    assert _exists(a, b) == [False, True]
    assert (settings.UPLOAD_DIR / name).read_bytes() == b"bulk-shared-content"
