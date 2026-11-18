"""The sleeve sheet: several samples on one printable page (/samples/sleeve, routers/sleeve.py)."""
from backend.routers.sleeve import qr_svg
from tests.test_deposition_rate import _deposit


def test_the_sheet_has_a_block_per_sample_with_its_stack_timeline_and_qr_code(world):
    owner = world.user("sleever")
    client = world.client(owner)
    sub = world.substrate()
    first = world.sample(owner, label="first one", film_material="Ga2O3", substrate_id=sub.id, tags=["batch 7"])
    second = world.sample(owner, label="second one")
    _deposit(client, first, "2026-03-02", target="Ga2O3", thickness="200")
    world.step(first, "annealed")

    listing = client.get("/samples/").text
    assert 'action="/samples/sleeve"' in listing and f'name="ids" value="{first.id}"' in listing

    html = client.get(f"/samples/sleeve?ids={second.id}&ids={first.id}&title=Box+3").text
    assert "Box 3" in html and "2 amostras" in html
    assert html.index(first.code) < html.index(second.code)          # in ID order
    assert "first one" in html and "second one" in html and "batch 7" in html
    assert sub.name in html
    assert "Ga2O3 200 nm" in html                                     # the film stack
    assert "2026-03-02" in html and "Deposition" in html              # the timeline
    assert html.count('<svg class="qr"') == 2
    assert "window.print()" in html and "<form" not in html


def test_without_access_a_block_has_the_summary_only(world):
    owner, other = world.user("sleeve-owner"), world.user("sleeve-other")
    sample = world.sample(owner, label="private one")
    world.step(sample, "secret notes")
    html = world.client(other).get(f"/samples/sleeve?ids={sample.id}").text
    assert sample.code in html and "private one" in html
    assert "secret notes" not in html and "Só o resumo" in html


def test_no_samples_goes_back_to_the_list_and_unknown_ids_are_skipped(world):
    client = world.client(world.user("sleeve-empty"))
    assert client.get("/samples/sleeve").status_code == 303
    assert client.get("/samples/sleeve?ids=999999").status_code == 200


def test_the_qr_code_is_an_svg():
    svg = qr_svg("http://lab.example/samples/1")
    assert svg.startswith('<svg class="qr"') and "<path" in svg
