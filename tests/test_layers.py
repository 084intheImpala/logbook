"""The film stack drawn on a thin-film sample's page (backend/layers.py)."""
from types import SimpleNamespace

from backend import layers
from backend.deposition_rate import RatePoint
from backend.lineage import Item
from tests.test_deposition_rate import _deposit, _measure, _type_id
from tests.loop import run
from backend.models import ProcessStepType

SCHEMA = [{"key": "method", "label": "Method", "type": "text"},
          {"key": "temperature", "label": "Temperature", "type": "number", "unit": "°C"}]
_ids = iter(range(1, 10_000))


def _item(technique, planned=False, **params):
    step = SimpleNamespace(id=next(_ids), parameters=params, planned=planned, performed_at=None,
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
