"""After a thickness measurement on a thin film, the deposition rate is asked for."""
import re

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.deposition_rate import duration_seconds
from backend.models import AnalysisType, ProcessStep, ProcessStepType, Sample
from backend.seed_data import PROCESS_STEP_TYPES
from tests.loop import run


async def _type_id(model, name):
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(model.id).where(model.name == name))).scalar_one()


def _deposit(client, sample, **params):
    data = {"type_id": run(_type_id(ProcessStepType, "Deposition"))} | {f"p::{k}": v for k, v in params.items()}
    assert client.post(f"/samples/{sample.id}/steps/new", data=data).status_code == 303


def _measure(client, sample, technique="Profilometry", **params):
    data = {"type_id": run(_type_id(AnalysisType, technique))} | {f"p::{k}": v for k, v in params.items()}
    assert client.post(f"/samples/{sample.id}/analyses/new", data=data).status_code == 303


def _steps(sample):
    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample.id)
                                     .order_by(ProcessStep.position))).scalars().all()
    return run(go())


def _setup(world, name, **sample_extra):
    owner = world.user(name)
    return world.sample(owner, **sample_extra), world.client(owner)


def test_duration_seconds():
    assert duration_seconds("12:30") == 750
    assert duration_seconds("0:00") is None
    assert duration_seconds("about an hour") is None
    assert duration_seconds(None) is None


def test_the_field_is_in_nm_per_min():
    deposition = next(t for t in PROCESS_STEP_TYPES if t["name"] == "Deposition")
    rate = next(f for f in deposition["parameter_schema"] if f["key"] == "deposition_rate")
    assert rate["unit"] == "nm/min"


def test_profilometry_suggests_the_rate_and_adding_it_fills_the_deposition(world):
    sample, client = _setup(world, "rate-owner")
    _deposit(client, sample, duration="12:30")
    _measure(client, sample, thickness="150")
    html = client.get(f"/samples/{sample.id}").text
    assert 'id="rate-prompt"' in html
    assert re.search(r'name="rate"[^>]*value="12"', html)
    assert client.get(f"/samples/{sample.id}").text.count('id="rate-prompt"') == 0   # asked once

    step = _steps(sample)[0]
    r = client.post(f"/samples/{sample.id}/steps/{step.id}/deposition-rate", data={"rate": "12,5", "back": sample.id})
    assert r.status_code == 303 and r.headers["location"] == f"/samples/{sample.id}"
    assert _steps(sample)[0].parameters["deposition_rate"] == 12.5
    assert "12.5 nm/min" in client.get(f"/samples/{sample.id}").text


def test_ellipsometry_asks_too(world):
    sample, client = _setup(world, "rate-ellips")
    _deposit(client, sample, duration="10")
    _measure(client, sample, "Ellipsometry", thickness="60")
    assert re.search(r'name="rate"[^>]*value="6"', client.get(f"/samples/{sample.id}").text)


def test_no_prompt_when_it_doesnt_apply(world):
    # not a thin film
    sample, client = _setup(world, "rate-bulk", sample_type="bulk")
    _deposit(client, sample, duration="10")
    _measure(client, sample, thickness="60")
    assert 'id="rate-prompt"' not in client.get(f"/samples/{sample.id}").text
    # no thickness measured
    sample, client = _setup(world, "rate-nothick")
    _deposit(client, sample, duration="10")
    _measure(client, sample, roughness="2")
    assert 'id="rate-prompt"' not in client.get(f"/samples/{sample.id}").text
    # the rate is already there
    sample, client = _setup(world, "rate-known")
    _deposit(client, sample, duration="10", deposition_rate="0.3")
    _measure(client, sample, thickness="60")
    assert 'id="rate-prompt"' not in client.get(f"/samples/{sample.id}").text
    # another technique
    sample, client = _setup(world, "rate-xrd")
    _deposit(client, sample, duration="10")
    _measure(client, sample, "AFM", thickness="60")
    assert 'id="rate-prompt"' not in client.get(f"/samples/{sample.id}").text
    # no deposition before it
    sample, client = _setup(world, "rate-nodep")
    _measure(client, sample, thickness="60")
    assert 'id="rate-prompt"' not in client.get(f"/samples/{sample.id}").text


def test_a_stack_asks_for_the_last_layer_without_a_suggestion(world):
    sample, client = _setup(world, "rate-stack")
    _deposit(client, sample, duration="10")
    _deposit(client, sample, duration="5")
    _measure(client, sample, thickness="90")
    html = client.get(f"/samples/{sample.id}").text
    last = _steps(sample)[-1]
    assert f"/steps/{last.id}/deposition-rate" in html
    assert re.search(r'name="rate"[^>]*value=""', html)


def test_no_duration_asks_without_a_suggestion(world):
    sample, client = _setup(world, "rate-nodur")
    _deposit(client, sample, power="100")
    _measure(client, sample, thickness="90")
    assert re.search(r'name="rate"[^>]*value=""', client.get(f"/samples/{sample.id}").text)


def test_a_piece_is_asked_about_its_parents_deposition(world):
    parent, client = _setup(world, "rate-parent")
    _deposit(client, parent, duration="10")
    deposition = _steps(parent)[0]

    async def cut():
        async with AsyncSessionLocal() as db:
            step = ProcessStep(sample_id=parent.id, step_type_id=await _type_id(ProcessStepType, "Cut"), position=5)
            db.add(step)
            await db.flush()
            piece = Sample(code=f"{parent.code}-A", owner_id=parent.owner_id, cut_step_id=step.id)
            db.add(piece)
            await db.commit()
            return piece
    piece = run(cut())
    _measure(client, piece, thickness="120")
    html = client.get(f"/samples/{piece.id}").text
    assert f"/samples/{parent.id}/steps/{deposition.id}/deposition-rate" in html
    r = client.post(f"/samples/{parent.id}/steps/{deposition.id}/deposition-rate", data={"rate": "0.2", "back": piece.id})
    assert r.headers["location"] == f"/samples/{piece.id}"
    assert _steps(parent)[0].parameters["deposition_rate"] == 0.2


def test_the_rate_goes_on_the_whole_run(world):
    sample, client = _setup(world, "rate-run")
    other = world.sample(world.user("rate-run-unused"))
    mine = world.sample(run(_owner(sample)))
    data = {"type_id": run(_type_id(ProcessStepType, "Deposition")), "p::duration": "10", "run_samples": [mine.id]}
    assert client.post(f"/samples/{sample.id}/steps/new", data=data).status_code == 303
    step = _steps(sample)[0]
    client.post(f"/samples/{sample.id}/steps/{step.id}/deposition-rate", data={"rate": "0.1", "back": sample.id})
    assert _steps(mine)[0].parameters["deposition_rate"] == 0.1
    assert _steps(other) == []


async def _owner(sample):
    from backend.models import User
    async with AsyncSessionLocal() as db:
        return await db.get(User, sample.owner_id)


def test_bad_rates_and_other_steps_are_refused(world):
    sample, client = _setup(world, "rate-bad")
    _deposit(client, sample, duration="10")
    step = _steps(sample)[0]
    client.post(f"/samples/{sample.id}/steps/{step.id}/deposition-rate", data={"rate": "fast"})
    assert "deposition_rate" not in _steps(sample)[0].parameters
    stranger = world.client(world.user("rate-stranger"))
    assert stranger.post(f"/samples/{sample.id}/steps/{step.id}/deposition-rate",
                         data={"rate": "1"}).status_code == 403
