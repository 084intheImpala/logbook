"""The sleeve sheet: several samples on one printable page (/samples/sleeve, routers/sleeve.py)."""
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
    assert listing.index('action="/samples/sleeve"') < listing.index("<table")   # a button in the header
    found = client.get("/search?q=one").text
    assert found.index('action="/samples/sleeve"') < found.index("Exportar resultados (CSV)") < found.index("<table")
    assert 'id="sleeve-all"' in found

    html = client.get(f"/samples/sleeve?ids={second.id}&ids={first.id}&title=Box+3").text
    assert "Box 3" in html and "2 amostras" in html
    assert html.index(first.code) < html.index(second.code)          # in ID order
    assert "first one" in html and "second one" in html and "batch 7" in html
    assert sub.name in html
    assert "Ga2O3 200 nm" in html                                     # the film stack
    assert "2026-03-02" in html and "Deposition" in html              # the timeline
    assert "<svg" not in html                                          # no QR codes
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


def test_pieces_are_grouped_under_their_mother_sample(world):
    from tests.test_studies import _cut
    owner = world.user("sleeve-mother")
    client = world.client(owner)
    mother = world.sample(owner, label="the wafer")
    other = world.sample(owner, label="unrelated")
    a, b = _cut(mother, "A"), _cut(mother, "B")
    a1 = _cut(a, "A")                                           # a piece of a piece: same mother
    lonely = world.sample(owner, label="lonely mother")
    lonely_piece = _cut(lonely, "A")                            # its mother isn't on the sheet

    ids = [other.id, a1.id, b.id, lonely_piece.id, mother.id, a.id]
    html = client.get("/samples/sleeve?" + "&".join(f"ids={i}" for i in ids)).text
    assert "6 amostras" in html
    # the mother on the sheet: her block takes both columns, marked; no separate heading
    assert html.count('class="block wide"') == 1 and 'class="badge mother">Amostra-mãe<' in html
    # the mother not on the sheet: a heading names her
    assert html.count('<div class="group-head">') == 1 and "lonely mother" in html

    def at(sample):
        return html.index(f'<span class="code mono">{sample.code}<')
    assert at(mother) < at(a) < at(a1) < at(b)                     # mother first, then its pieces
    assert html.index("block wide") < at(mother) < html.index('<div class="group-head">') < at(lonely_piece)
    assert html.index('<div class="group-head">') > at(b)
    # each family is its own section; samples on their own share one
    assert at(b) < at(other) < at(lonely_piece)                      # families in their mothers' ID order
    assert html.count('<div class="grid">') == 3                      # wafer family, unrelated, lonely family
    assert ("grid-template-columns: repeat(2, minmax(0, 1fr))") in html


def test_a_piece_leaves_out_what_its_mother_shows_on_the_same_sheet(world):
    from tests.test_studies import _cut
    owner = world.user("sleeve-nodup")
    client = world.client(owner)
    mother = world.sample(owner, label="wafer")
    world.step(mother, "before the cut")                      # inherited by the piece
    piece = _cut(mother, "A")
    world.step(piece, "after the cut")

    def lines(html, sample):                                  # timeline lines in the sample's block
        block = html[html.index(f'<span class="code mono">{sample.code}<'):]
        return block[:block.index("</section>")].count("<li")

    both = client.get(f"/samples/sleeve?ids={mother.id}&ids={piece.id}").text
    assert lines(both, mother) == 2                          # its step and the Cut
    assert lines(both, piece) == 1                           # only what came after the cut
    alone = client.get(f"/samples/sleeve?ids={piece.id}").text
    assert lines(alone, piece) == 2                          # mother not on the sheet: inherited step shown


def test_a_timeline_line_shows_the_key_values_in_full(world):
    from backend.models import ProcessStepType
    from tests.loop import run
    from tests.test_deposition_rate import _type_id
    owner = world.user("sleeve-values")
    client = world.client(owner)
    sample = world.sample(owner, label="implanted")
    for kind, params in [("Ion Implantation", {"ion": "Eu", "energy": "150", "fluence": "1e15", "tilt_angle": "7"}),
                         ("Annealing", {"method": "RTA", "atmosphere": "N2", "temperature": "900", "duration": "120"})]:
        data = {"type_id": run(_type_id(ProcessStepType, kind))} | {f"p::{k}": v for k, v in params.items()}
        assert client.post(f"/samples/{sample.id}/steps/new", data=data).status_code == 303
    html = client.get(f"/samples/sleeve?ids={sample.id}").text
    assert "150\u00a0keV" in html and "ions/cm²" in html            # energy and fluence, unit kept with its value
    assert "900\u00a0°C" in html and "120\u00a0s" in html          # anneal temperature and time
    assert "text-overflow: ellipsis" not in html                    # wrapped, never cut short


def test_a_deposition_line_shows_the_gas_flow(world):
    from tests.test_deposition_rate import _deposit
    owner = world.user("sleeve-flow")
    client = world.client(owner)
    sample = world.sample(owner, label="sputtered")
    _deposit(client, sample, "2026-03-02", technique="Sputtering", target="Ga2O3", atmosphere="Ar",
             base_pressure="2", working_pressure="3", power="100", gas_flow="20")
    html = client.get(f"/samples/sleeve?ids={sample.id}").text
    assert "Sputtering" in html and "100\u00a0W" not in html     # past the first five values…
    assert "20\u00a0sccm" in html                                # …but the flow is always shown
