"""The film stack drawn on a thin-film sample's page (backend/layers.py)."""
from types import SimpleNamespace

from backend import layers
from backend.deposition_rate import RatePoint
from backend.lineage import Item
from tests.test_deposition_rate import _deposit, _measure, _type_id
from tests.loop import run
from backend.models import ProcessStep, ProcessStepType
from backend.database import AsyncSessionLocal
from sqlalchemy import select

SCHEMA = [{"key": "method", "label": "Method", "type": "text"},
          {"key": "temperature", "label": "Temperature", "type": "number", "unit": "°C"}]
_ids = iter(range(1, 10_000))


def _item(technique, planned=False, on=None, on_substrate=False, partial=False, **params):
    step = SimpleNamespace(id=next(_ids), parameters=params, planned=planned, performed_at=None,
                           on_step_id=on.entry.id if on else None, on_substrate=on_substrate, partial=partial,
                           step_type=SimpleNamespace(parameter_schema=SCHEMA))
    return Item("process", technique, step, SAMPLE)


SAMPLE = SimpleNamespace(id=1, film_material="Ga2O3", title="S")


def test_thickness_comes_from_the_best_source():
    measured = _item("Deposition", target="ZnO", thickness=999)
    entered = _item("Deposition", thickness=50)
    from_rate = _item("Deposition", deposition_rate=10, duration="3:00")
    target = _item("Deposition", target_thickness=80)
    unknown = _item("Deposition")
    point = RatePoint(measured.entry, SAMPLE, None, 1,
                      [SimpleNamespace(thickness=100.0), SimpleNamespace(thickness=110.0)])
    stack = layers.stack(SAMPLE, [measured, entered, from_rate, target, unknown], {measured.entry.id: point})
    assert [(l.thickness, l.source) for l in stack] == [
        (105.0, "measured"), (50, "entered"), (30.0, "rate"), (80, "target"), (None, None)]
    assert stack[0].n == 2
    # the Target names the material; without one, the sample's film material
    assert [l.material for l in stack[:2]] == ["ZnO", "Ga2O3"]


def test_each_layer_lists_the_processes_since_it_was_deposited():
    first = _item("Deposition", thickness=100)
    hot = _item("Annealing", method="Furnace", temperature=1000)
    second = _item("Deposition", thickness=200)
    warm = _item("Annealing", method="RTA", temperature=400)
    cut = _item("Cut")
    stack = layers.stack(SAMPLE, [first, hot, second, warm, cut])
    assert [p["summary"] for p in stack[0].processes] == ["Furnace · 1000 °C", "RTA · 400 °C"]
    assert [p["summary"] for p in stack[1].processes] == ["RTA · 400 °C"]


def test_cmp_takes_thickness_off_the_top():
    bottom, top = _item("Deposition", thickness=100), _item("Deposition", thickness=30)
    stack = layers.stack(SAMPLE, [bottom, top, _item("CMP", thickness_removed=50)])
    assert [(l.thickness, l.removed) for l in stack] == [(80.0, 20)]   # the top layer went entirely
    # a planned CMP hasn't happened; a planned deposition is drawn but not polished
    stack = layers.stack(SAMPLE, [bottom, _item("Deposition", planned=True, thickness=10),
                                  _item("CMP", planned=True, thickness_removed=50)])
    assert [(l.thickness, l.planned) for l in stack] == [(100, False), (10, True)]


def test_diagram_scales_films_and_keeps_labels_apart():
    stack = layers.stack(SAMPLE, [_item("Deposition", thickness=1000), _item("Deposition", thickness=1),
                                  _item("Annealing", method="Furnace", temperature=900)])
    d = layers.diagram(stack)
    top, bottom = d["layers"]
    assert top.geometry["h"] == layers.MIN_H and d["clamped"] and d["total"] == 1001
    assert bottom.geometry["h"] > 150
    # labels don't overlap: the top one (3 lines) ends before the bottom one starts
    assert top.geometry["label_y"] + layers.LINE_H * 3 <= bottom.geometry["label_y"]
    assert d["substrate_label_y"] >= bottom.geometry["label_y"] + layers.LINE_H * 3
    assert layers.diagram([]) is None


def test_the_sample_page_draws_the_layers(world):
    owner = world.user("layers-page")
    client = world.client(owner)
    sample = world.sample(owner, film_material="Ga2O3")
    _deposit(client, sample, "2026-01-05", duration="10")
    _measure(client, sample, thickness="100")
    anneal = {"type_id": run(_type_id(ProcessStepType, "Annealing")),
              "p::method": "Furnace", "p::temperature": "1000", "performed_at": "2026-01-06"}
    assert client.post(f"/samples/{sample.id}/steps/new", data=anneal).status_code == 303
    _deposit(client, sample, "2026-01-07", target="ZnO", thickness="200")

    html = client.get(f"/samples/{sample.id}").text
    section = html[html.index('id="layers"'):html.index("</section>", html.index('id="layers"'))]
    assert "Ga2O3 · 100 nm" in section and "ZnO · 200 nm" in section
    assert "medida" in section and section.count("Annealing") == 1    # only the bottom layer was annealed
    assert section.index("ZnO") < section.index("Ga2O3")              # top layer first

    # only thin films
    bulk = world.sample(owner, sample_type="bulk")
    _deposit(client, bulk, thickness="5")
    assert 'id="layers"' not in client.get(f"/samples/{bulk.id}").text


def _contacts():
    """Ni on part of the film, Au on the Ni; Ti on part of the substrate, Au on the Ti."""
    film = _item("Deposition", thickness=100)
    ni = _item("Deposition", target="Ni", thickness=50, partial=True)
    au1 = _item("Deposition", target="Au", thickness=100, on=ni)
    ti = _item("Deposition", target="Ti", thickness=20, on_substrate=True, partial=True)
    au2 = _item("Deposition", target="Au", thickness=100, on=ti)
    return [film, ni, au1, ti, au2]


def test_partial_layers_sit_side_by_side_on_what_they_were_put_on():
    stack = layers.stack(SAMPLE, _contacts())
    film, ni, au1, ti, au2 = stack
    assert au1.on is ni and au2.on is ti and ti.on_substrate and ni.partial and not au1.partial
    d = layers.diagram(stack)
    assert film.span == (0.0, 1.0)
    # Ni and Ti each take a slice of the surface, apart, with clear surface around them;
    # the Au covers all of what it's on
    assert 0 < ni.span[0] < ni.span[1] < ti.span[0] < ti.span[1] < 1
    assert au1.span == ni.span and au2.span == ti.span
    # the tallest column (film + Ni + Au) sets the scale and the total
    assert d["total"] == 250 and d["partial"]
    # each film follows the surface it landed on: the Au on the Ni ends at the Ni's right end, above it
    assert au1.geometry["end_x"] == ni.geometry["end_x"] < layers.STACK_X + layers.STACK_W
    assert au1.geometry["mid"] < ni.geometry["mid"] < film.geometry["mid"]
    assert au1.geometry["inside"] and not film.geometry["inside"]
    # the same material, the same colour
    assert au1.slot == au2.slot != ni.slot


def test_a_full_layer_over_pads_follows_them():
    items = _contacts()
    cap = _item("Deposition", target="SiO2", thickness=10)
    stack = layers.stack(SAMPLE, items + [cap])
    d = layers.diagram(stack)
    assert stack[-1].span == (0.0, 1.0)
    # an outline with steps: more than the four corners of a rectangle
    assert stack[-1].geometry["path"].count(" L") > 3
    assert d["layers"][0] is stack[-1]          # the top label first
    # a layer on one that's not on the timeline (or polished away) goes on everything
    stray = _item("Deposition", thickness=5, on=SimpleNamespace(entry=SimpleNamespace(id=-1)))
    assert layers.stack(SAMPLE, [stray])[0].on is None


def _put(client, sample, date, run_samples=(), layer_on="", layer_partial="", **params):
    """A deposition, with what it goes on (layer_on) and whether it covers only part of it."""
    data = {"type_id": run(_type_id(ProcessStepType, "Deposition")), "performed_at": date, "layer_on": layer_on,
            "run_samples": [s.id for s in run_samples]} | {f"p::{k}": v for k, v in params.items()}
    if layer_partial:
        data["layer_partial"] = layer_partial
    assert client.post(f"/samples/{sample.id}/steps/new", data=data).status_code == 303


def _steps(sample_id):
    async def get():
        async with AsyncSessionLocal() as db:
            return list((await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample_id)
                                          .order_by(ProcessStep.id))).scalars())
    return run(get())


def test_the_form_puts_a_deposition_on_part_of_a_layer(world):
    owner = world.user("layers-contacts")
    client = world.client(owner)
    sample, twin = world.sample(owner, film_material="Ga2O3"), world.sample(owner, film_material="Ga2O3")
    _deposit(client, sample, "2026-02-01", thickness="100")
    form = client.get(f"/samples/{sample.id}/steps/new").text
    assert 'name="layer_on"' in form and 'name="layer_partial"' in form and "Ga2O3 · 100 nm" in form
    # Ni on part of it, on both samples (a run)
    _put(client, sample, "2026-02-02", run_samples=[twin], target="Ni", thickness="50", layer_partial="1")
    ni = _steps(sample.id)[-1]
    assert ni.partial and ni.on_step_id is None and not ni.on_substrate
    # Au on the Ni: on the twin, its own Ni
    _put(client, sample, "2026-02-03", run_samples=[twin], target="Au", thickness="100", layer_on=str(ni.id))
    au, twin_ni, twin_au = _steps(sample.id)[-1], *_steps(twin.id)
    assert au.on_step_id == ni.id and not au.partial
    assert twin_au.on_step_id == twin_ni.id
    # Ti on part of the substrate
    _put(client, sample, "2026-02-04", target="Ti", thickness="20", layer_on="substrate", layer_partial="1")
    ti = _steps(sample.id)[-1]
    assert ti.on_substrate and ti.partial and ti.on_step_id is None

    html = client.get(f"/samples/{sample.id}").text
    section = html[html.index('id="layers"'):html.index("</section>", html.index('id="layers"'))]
    assert "sobre parte da superfície" in section and "sobre o Ni" in section and "sobre parte do substrato" in section
    assert "<path" in section

    # Editing keeps it; only a layer below the deposition can be picked
    edit = client.get(f"/samples/{sample.id}/steps/{au.id}/edit").text
    assert f'value="{ni.id}" selected' in edit and f'value="{ti.id}"' not in edit
    other = _steps(twin.id)[0]
    _put(client, sample, "2026-02-05", target="Cr", thickness="5", layer_on=str(other.id))
    assert _steps(sample.id)[-1].on_step_id is None
    # other steps never have it
    data = {"type_id": run(_type_id(ProcessStepType, "Annealing")), "layer_on": str(ni.id), "layer_partial": "1"}
    assert client.post(f"/samples/{sample.id}/steps/new", data=data).status_code == 303
    anneal = _steps(sample.id)[-1]
    assert anneal.on_step_id is None and not anneal.partial


def test_a_run_copy_shows_only_its_own_thickness(world):
    """A deposition added to two samples at once: each film has its own
    measured thickness, not the average of both."""
    owner = world.user("layers-run")
    client = world.client(owner)
    first, second = world.sample(owner, film_material="Ga2O3"), world.sample(owner, film_material="Ga2O3")
    _deposit(client, first, "2026-01-05", duration="10", run_samples=[second])
    _measure(client, first, thickness="100")
    _measure(client, second, thickness="30")
    for sample, mine, other in ((first, "100 nm", "30 nm"), (second, "30 nm", "100 nm")):
        html = client.get(f"/samples/{sample.id}").text
        section = html[html.index('id="layers"'):html.index("</section>", html.index('id="layers"'))]
        assert f"Ga2O3 · {mine}" in section and other not in section and "média" not in section


def test_a_piece_can_put_a_deposition_on_an_inherited_layer(world):
    """Ga2O3 deposited on the parent, then cut: on the piece, Ti can go on that
    inherited Ga2O3 (the step belongs to the parent, not the piece)."""
    from tests.test_deposition_rate import _cut
    owner = world.user("layers-inherited")
    client = world.client(owner)
    parent, twin = world.sample(owner, film_material="Ga2O3"), world.sample(owner, film_material="Ga2O3")
    _deposit(client, parent, "2026-01-05", thickness="170", run_samples=[twin])   # a run: the step has a run_id
    ga2o3 = _steps(parent.id)[0]
    piece = _cut(parent)
    assert f'value="{ga2o3.id}"' in client.get(f"/samples/{piece.id}/steps/new").text
    _put(client, piece, "2026-03-01", target="Ti", thickness="10", layer_on=str(ga2o3.id), layer_partial="1")
    ti = _steps(piece.id)[-1]
    assert ti.on_step_id == ga2o3.id and ti.partial
    html = client.get(f"/samples/{piece.id}").text
    section = html[html.index('id="layers"'):html.index("</section>", html.index('id="layers"'))]
    assert "sobre parte do Material desconhecido" in section   # the test piece has no film material of its own
    # and editing it keeps the choice
    edit = client.get(f"/samples/{piece.id}/steps/{ti.id}/edit").text
    assert f'value="{ga2o3.id}" selected' in edit


def test_where_a_layer_is_gets_its_own_label_line():
    """How the thickness is known on one line, what it's on / date / sample on
    the next: together they ran off the right of the drawing."""
    from datetime import date
    other = SimpleNamespace(id=2, film_material="Ga2O3", title="P")
    film = Item("process", "Deposition", _item("Deposition", thickness=170, partial=True).entry, other)
    film.entry.performed_at = date(2025, 11, 19)
    bare = _item("Deposition", thickness=10)
    film_layer, bare_layer = layers.stack(SAMPLE, [film, bare])
    assert film_layer.inherited and film_layer.where_line and not bare_layer.where_line
    assert layers._label_h(film_layer) == layers.LINE_H * 3   # name, source, where; no processes since
    assert layers._label_h(bare_layer) == layers.LINE_H * 2
