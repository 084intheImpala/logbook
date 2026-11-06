"""Devices on a sample: made by a "Devices made" step, analyses can name a device."""
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Analysis, AnalysisType, Device, ProcessStep
from tests.loop import run


def devices_of(sample):
    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Device).where(Device.sample_id == sample.id).order_by(Device.id))).scalars().all()
    return run(go())


def marker_steps(sample):
    async def go():
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample.id))).scalars().all()
            return [r for r in rows if r.step_type_id and r.status == "approved"]
    return run(go())


def test_add_and_remove_devices(world):
    owner, other = world.user("dev-owner"), world.user("dev-other")
    sample = world.sample(owner)
    c = world.client(owner)
    assert c.post(f"/samples/{sample.id}/devices", data={"labels": "A1, A2, a1"}).status_code == 303
    assert c.post(f"/samples/{sample.id}/devices", data={"count": "2", "performed_at": "2026-05-01"}).status_code == 303
    assert len(marker_steps(sample)) == 2
    assert [d.label for d in devices_of(sample)] == ["A1", "A2", "D1", "D2"]
    assert "A2" in c.get(f"/samples/{sample.id}").text
    assert world.client(other).post(f"/samples/{sample.id}/devices", data={"labels": "X"}).status_code == 403

    first = devices_of(sample)[0]
    entry_id, _ = world.step(sample, "measured", analysis=True)

    async def attach():
        async with AsyncSessionLocal() as db:
            (await db.get(Analysis, entry_id)).device_id = first.id
            await db.commit()
    run(attach())
    assert "A1" in c.get(f"/samples/{sample.id}").text

    assert c.post(f"/samples/{sample.id}/devices/{first.id}/delete").status_code == 303

    async def after():
        async with AsyncSessionLocal() as db:
            return (await db.get(Analysis, entry_id)).device_id
    assert run(after()) is None
    assert "A1" not in [d.label for d in devices_of(sample)]


def test_analysis_form_sets_device(world):
    owner = world.user("dev-form-owner")
    sample = world.sample(owner)
    c = world.client(owner)
    c.post(f"/samples/{sample.id}/devices", data={"labels": "D1"})
    dev = devices_of(sample)[0]
    assert 'name="device_id"' in c.get(f"/samples/{sample.id}/analyses/new").text

    async def type_id():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(AnalysisType).limit(1))).scalar_one().id
    r = c.post(f"/samples/{sample.id}/analyses/new", data={"type_id": str(run(type_id())), "device_id": str(dev.id)})
    assert r.status_code == 303

    async def saved():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Analysis).where(Analysis.sample_id == sample.id))).scalar_one().device_id
    assert run(saved()) == dev.id


def test_deleting_the_devices_made_step_removes_its_devices(world):
    owner = world.user("dev-step-owner")
    sample = world.sample(owner)
    c = world.client(owner)
    c.post(f"/samples/{sample.id}/devices", data={"labels": "X1, X2"})
    step = marker_steps(sample)[0]
    assert c.get(f"/samples/{sample.id}/steps/{step.id}/edit").status_code == 200
    assert c.post(f"/samples/{sample.id}/steps/{step.id}/delete").status_code == 303
    assert devices_of(sample) == []
    assert marker_steps(sample) == []


def test_numbering_continues_after_the_highest(world):
    owner = world.user("dev-num-owner")
    sample = world.sample(owner)
    c = world.client(owner)
    c.post(f"/samples/{sample.id}/devices", data={"labels": "D3, D4, other"})
    c.post(f"/samples/{sample.id}/devices", data={"count": "2"})
    assert [d.label for d in devices_of(sample)] == ["D3", "D4", "other", "D5", "D6"]
