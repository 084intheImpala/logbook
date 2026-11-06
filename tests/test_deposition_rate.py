"""Deposition rates measured from thickness measurements (on the sample, its
pieces and its run), the prompt for a rate by hand, and the rate plots (search page)."""
import re
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from backend import rate_plot
from backend.database import AsyncSessionLocal
from backend.deposition_rate import RatePoint, duration_seconds
from backend.models import AnalysisType, ProcessStep, ProcessStepType, Sample, User
from backend.seed_data import PROCESS_STEP_TYPES
from tests.loop import run


async def _type_id(model, name):
    async with AsyncSessionLocal() as db:
        return (await db.execute(select(model.id).where(model.name == name))).scalar_one()


def _deposit(client, sample, date=None, run_samples=(), **params):
    data = {"type_id": run(_type_id(ProcessStepType, "Deposition"))} | {f"p::{k}": v for k, v in params.items()}
    if date:
        data["performed_at"] = date
    if run_samples:
        data["run_samples"] = [s.id for s in run_samples]
    assert client.post(f"/samples/{sample.id}/steps/new", data=data).status_code == 303


def _step(client, sample, type_name):
    data = {"type_id": run(_type_id(ProcessStepType, type_name))}
    assert client.post(f"/samples/{sample.id}/steps/new", data=data).status_code == 303


def _measure(client, sample, technique="Profilometry", **params):
    data = {"type_id": run(_type_id(AnalysisType, technique))} | {f"p::{k}": v for k, v in params.items()}
    r = client.post(f"/samples/{sample.id}/analyses/new", data=data)
    assert r.status_code == 303
    return client.get(f"/samples/{sample.id}").text   # the page right after saving


def _steps(sample):
    async def go():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample.id)
                                     .order_by(ProcessStep.position))).scalars().all()
    return run(go())


def _setup(world, name, **sample_extra):
    owner = world.user(name)
    return world.sample(owner, **sample_extra), world.client(owner)


def _owner(sample):
    async def go():
        async with AsyncSessionLocal() as db:
            return await db.get(User, sample.owner_id)
    return run(go())


def _cut(parent, piece_owner=None):
    """A Cut step at the end of the parent's timeline, and one piece."""
    async def go():
        async with AsyncSessionLocal() as db:
            step = ProcessStep(sample_id=parent.id, step_type_id=await _type_id(ProcessStepType, "Cut"), position=50)
            db.add(step)
            await db.flush()
            piece = Sample(code=f"{parent.code}-A", owner_id=(piece_owner or parent).id if piece_owner
                           else parent.owner_id, cut_step_id=step.id)
            db.add(piece)
            await db.commit()
            return piece
    return run(go())


def _measured_block(html):
    return html[html.index("Taxa de deposição medida"):] if "Taxa de deposição medida" in html else ""


def test_duration_seconds():
    assert duration_seconds("12:30") == 750
    assert duration_seconds("0:00") is None
    assert duration_seconds("about an hour") is None
    assert duration_seconds(None) is None


def test_the_field_is_in_nm_per_min():
    deposition = next(t for t in PROCESS_STEP_TYPES if t["name"] == "Deposition")
    rate = next(f for f in deposition["parameter_schema"] if f["key"] == "deposition_rate")
    assert rate["unit"] == "nm/min"


def test_a_measurement_counts_towards_the_rate(world):
    sample, client = _setup(world, "rate-owner")
    _deposit(client, sample, duration="12:30")
    html = _measure(client, sample, thickness="150")
    assert "Contada para a taxa de deposição de" in html and "12 nm/min, a média de 1 medida" in html
    assert 'id="rate-prompt"' not in html
    block = _measured_block(html)
    assert "12 nm/min" in block and "150 nm → 12 nm/min" in block

    html = _measure(client, sample, "Ellipsometry", thickness="160")   # 12.8
    assert "12.4 nm/min, a média de 2 medidas" in html
    assert "média de 2" in _measured_block(html)


def test_measurements_on_pieces_count_for_the_parents_deposition(world):
    parent, client = _setup(world, "rate-parent")
    _deposit(client, parent, duration="10")
    deposition = _steps(parent)[0]
    piece = _cut(parent)
    _measure(client, parent, thickness="100")    # 10 nm/min
    html = _measure(client, piece, thickness="120")   # 12 nm/min, on the piece
    assert "11 nm/min, a média de 2 medidas" in html
    block = _measured_block(client.get(f"/samples/{parent.id}").text)
    assert piece.code in block and "120 nm → 12 nm/min" in block and "100 nm → 10 nm/min" in block
    assert f"#analysis-" in block and f"/samples/{piece.id}" in block
    assert "deposition_rate" not in (_steps(parent)[0].parameters or {})   # nothing stored: worked out
    assert deposition.id


def test_a_piece_someone_else_cant_see_doesnt_count_for_them(world):
    parent, client = _setup(world, "rate-private-parent")
    _deposit(client, parent, duration="10")
    stranger = world.user("rate-private-piece")
    piece = _cut(parent, piece_owner=stranger)
    _measure(client, parent, thickness="100")
    _measure(world.client(stranger), piece, thickness="300")
    block = _measured_block(client.get(f"/samples/{parent.id}").text)
    assert "300 nm" not in block and "10 nm/min" in block


def test_run_copies_pool_their_measurements(world):
    first, client = _setup(world, "rate-run-pool")
    second = world.sample(_owner(first))
    _deposit(client, first, duration="10", run_samples=[second])
    _measure(client, first, thickness="100")
    html = _measure(client, second, thickness="80")
    assert "9 nm/min, a média de 2 medidas" in html
    assert "média de 2" in _measured_block(client.get(f"/samples/{first.id}").text)


def test_steps_that_change_the_thickness_stop_it_counting(world):
    sample, client = _setup(world, "rate-etched")
    _deposit(client, sample, duration="10")
    _step(client, sample, "Etching")
    html = _measure(client, sample, thickness="50")
    assert "Contada" not in html and 'id="rate-prompt"' not in html and not _measured_block(html)
    # a cleaning doesn't
    sample, client = _setup(world, "rate-cleaned")
    _deposit(client, sample, duration="10")
    _step(client, sample, "Cleaning")
    assert "Contada" in _measure(client, sample, thickness="50")


def test_nothing_to_tell_when_it_doesnt_apply(world):
    for name, technique, params in (("rate-nothick", "Profilometry", {"roughness": "2"}),
                                    ("rate-afm", "AFM", {"thickness": "60"})):
        sample, client = _setup(world, name)
        _deposit(client, sample, duration="10")
        html = _measure(client, sample, technique, **params)
        assert "Contada" not in html and 'id="rate-prompt"' not in html
    sample, client = _setup(world, "rate-nodep")
    html = _measure(client, sample, thickness="60")
    assert "Contada" not in html and 'id="rate-prompt"' not in html


def test_a_stack_asks_for_the_last_layers_rate(world):
    sample, client = _setup(world, "rate-stack")
    _deposit(client, sample, duration="10")
    _deposit(client, sample, duration="5")
    html = _measure(client, sample, thickness="90")
    last = _steps(sample)[-1]
    assert 'id="rate-prompt"' in html and f"/steps/{last.id}/deposition-rate" in html
    assert "todo o empilhamento" in html and not _measured_block(html)
    assert 'id="rate-prompt"' not in client.get(f"/samples/{sample.id}").text   # asked once

    r = client.post(f"/samples/{sample.id}/steps/{last.id}/deposition-rate", data={"rate": "12,5", "back": sample.id})
    assert r.status_code == 303 and r.headers["location"] == f"/samples/{sample.id}"
    assert _steps(sample)[-1].parameters["deposition_rate"] == 12.5
    assert "12.5 nm/min" in client.get(f"/samples/{sample.id}").text
    # once it has a rate, it isn't asked again
    assert 'id="rate-prompt"' not in _measure(client, sample, thickness="95")


def test_no_duration_asks_for_the_rate_and_lists_the_thickness(world):
    sample, client = _setup(world, "rate-nodur")
    _deposit(client, sample, power="100")
    html = _measure(client, sample, thickness="90")
    assert 'id="rate-prompt"' in html and "não tem duração" in html
    block = _measured_block(client.get(f"/samples/{sample.id}").text)
    assert "90 nm" in block and "sem duração registada" in block


def test_a_rate_typed_by_hand_goes_on_the_whole_run(world):
    sample, client = _setup(world, "rate-run")
    other = world.sample(world.user("rate-run-unused"))
    mine = world.sample(_owner(sample))
    _deposit(client, sample, duration="10", run_samples=[mine])
    step = _steps(sample)[0]
    client.post(f"/samples/{sample.id}/steps/{step.id}/deposition-rate", data={"rate": "0.1", "back": sample.id})
    assert _steps(mine)[0].parameters["deposition_rate"] == 0.1
    assert _steps(other) == []


def test_bad_rates_and_strangers_are_refused(world):
    sample, client = _setup(world, "rate-bad")
    _deposit(client, sample, duration="10")
    step = _steps(sample)[0]
    client.post(f"/samples/{sample.id}/steps/{step.id}/deposition-rate", data={"rate": "fast"})
    assert "deposition_rate" not in _steps(sample)[0].parameters
    stranger = world.client(world.user("rate-stranger"))
    assert stranger.post(f"/samples/{sample.id}/steps/{step.id}/deposition-rate",
                         data={"rate": "1"}).status_code == 403


def test_the_sample_page_shows_the_measured_rate_but_no_rate_plot(world):
    """The rate history plot is on the search page only (Search by technique: Deposition)."""
    owner = world.user("rate-history")
    client = world.client(owner)
    target = f"T-{owner.username}"   # conditions no other test uses
    a, b = world.sample(owner), world.sample(owner)
    _deposit(client, a, "2026-01-05", machine="UHV1", target=target, deposition_rate="10")
    _deposit(client, b, "2026-02-05", machine="UHV1", target=target, duration="10")
    _measure(client, b, thickness="120")

    html = client.get(f"/samples/{b.id}").text
    assert "12 nm/min" in html and "data-rate-plot" not in html
    assert "Histórico da taxa nas mesmas condições" not in html


def test_search_uses_the_measured_rate_and_plots_it(world):
    owner = world.user("rate-search")
    client = world.client(owner)
    target = f"S-{owner.username}"
    a, b = world.sample(owner), world.sample(owner)
    _deposit(client, a, "2026-04-01", target=target, gas_flow="20/5", duration="10", deposition_rate="99")
    _measure(client, a, thickness="100")      # measured 10 beats the typed 99
    _deposit(client, b, "2026-05-01", target=target, gas_flow="20", deposition_rate="7")

    html = client.get("/search", params={"technique": "Deposition", "pf.target": target}).text
    section = html[html.index('id="technique-entries"'):]
    assert "10 nm/min (medida)" in section and "7 nm/min (introduzida)" in section
    assert "data-rate-plot" in section and section.count('class="viz-hit"') == 2

    html = client.get("/search", params={"technique": "Deposition", "pf.target": target,
                                         "min.deposition_rate": "9"}).text
    section = html[html.index('id="technique-entries"'):]
    assert "10 nm/min (medida)" in section and "7 nm/min" not in section
    # a gas flow that isn't a number is matched as typed
    html = client.get("/search", params={"technique": "Deposition", "pf.target": target, "min.gas_flow": "20/5"}).text
    section = html[html.index('id="technique-entries"'):]
    assert "10 nm/min (medida)" in section and "7 nm/min" not in section


def _point(step_id, day, rate, power):
    step = SimpleNamespace(id=step_id, performed_at=date(2026, 1, day), parameters={"power": power},
                           step_type=SimpleNamespace(parameter_schema=[{"key": "power", "unit": "W"}]))
    return RatePoint(step, SimpleNamespace(id=1, title="X"), rate, 1, [])


def test_plot_colours_follow_the_conditions_not_the_filter():
    points = [_point(1, 1, 10, 100), _point(2, 2, 11, 100), _point(3, 3, 20, 150)]
    ranks = rate_plot.ranks(points)
    full = rate_plot.build(points, ranks)
    only_150 = rate_plot.build(points[2:], ranks)
    slot = {s["label"]: s["slot"] for s in full["series"]}
    assert only_150["series"][0]["slot"] == slot["— · — · — · — · 150 W"]
    assert full["y_ticks"][0]["label"] == "0" and full["hidden"] == 0
    assert rate_plot.build([_point(1, 1, None, 100)], ranks) is None
