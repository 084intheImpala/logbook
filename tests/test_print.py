"""The printable record of a sample (/samples/{id}/print, samples/print.html)."""
import io

from PIL import Image

from tests.test_deposition_rate import _deposit


def _png() -> bytes:
    out = io.BytesIO()
    Image.new("RGB", (40, 30), "red").save(out, "PNG")
    return out.getvalue()


def test_the_printable_record_has_the_timeline_photo_previews_and_file_names(world):
    owner = world.user("printer")
    client = world.client(owner)
    sample = world.sample(owner, film_material="Ga2O3", label="Ga2O3 on sapphire", tags=["contacts"])
    _deposit(client, sample, "2026-03-02", target="Ga2O3", thickness="100")
    step_id, _ = world.step(sample, "Annealed in N2, looked fine", with_file="raw data")
    r = client.post(f"/files/upload/{sample.id}", data={"entity_type": "step", "entity_id": step_id},
                    files={"photos": ("after.png", _png(), "image/png")})
    assert r.status_code == 303

    page = client.get(f"/samples/{sample.id}")
    assert f'href="/samples/{sample.id}/print"' in page.text

    html = client.get(f"/samples/{sample.id}/print").text
    assert sample.code in html and "Ga2O3 on sapphire" in html and "contacts" in html
    assert "Annealed in N2, looked fine" in html                 # notes
    assert "2026-03-02" in html and "100" in html                # the deposition's date and parameters
    assert 'id="layers"' in html and "<svg" in html              # the film stack
    assert '/thumb"' in html and "after.png" in html             # a small preview of the photo
    assert f"{step_id}-s.txt" in html                            # files by name only, not links
    assert "<form" not in html and "Imprimir / guardar em PDF" in html   # nothing to edit; Portuguese
    assert "window.print()" in html


def test_without_access_the_record_has_the_summary_only(world):
    owner, other = world.user("print-owner"), world.user("print-other")
    sample = world.sample(owner)
    world.step(sample, "secret notes")
    html = world.client(other).get(f"/samples/{sample.id}/print").text
    assert sample.code in html and "secret notes" not in html
    assert world.client(None).get(f"/samples/{sample.id}/print").status_code in (302, 303, 401)
