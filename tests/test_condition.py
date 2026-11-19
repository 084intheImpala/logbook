"""A sample marked missing or destroyed (Sample.condition, POST /samples/{id}/condition)."""
import json
from datetime import date

from backend.config import settings
from tests.test_sample_import import _confirm, _samples, _upload
from tests.test_sample_update import _apply, _compare, _boxes


def _mark(client, sample, condition, on="", note=""):
    return client.post(f"/samples/{sample.id}/condition",
                       data={"condition": condition, "condition_on": on, "condition_note": note})


def test_marking_a_sample_missing_destroyed_and_there_again(world):
    owner, editor, viewer = world.user("cond-owner"), world.user("cond-editor"), world.user("cond-viewer")
    sample = world.sample(owner, shared_edit=[editor], shared_view=[viewer])
    client = world.client(owner)
    page = client.get(f"/samples/{sample.id}").text
    assert "Desaparecida ou destruída?" in page and f'action="/samples/{sample.id}/condition"' in page
    # Someone who can only see it can't mark it
    assert "Desaparecida ou destruída?" not in world.client(viewer).get(f"/samples/{sample.id}").text
    assert _mark(world.client(viewer), sample, "missing").status_code == 403
    assert _mark(client, sample, "lost").status_code == 400

    # Whoever can edit it can: since when and why
    assert _mark(world.client(editor), sample, "missing", "2026-03-04", "not in box 3").status_code == 303
    [s] = _samples(id=sample.id)
    assert (s.condition, s.condition_on, s.condition_note) == ("missing", date(2026, 3, 4), "not in box 3")
    page = client.get(f"/samples/{sample.id}").text
    assert "Desaparecida" in page and "desde 2026-03-04" in page and "not in box 3" in page and "Voltou a aparecer" in page
    assert "desaparecida" in client.get("/samples/").text
    printed = client.get(f"/samples/{sample.id}/print").text
    assert "Desaparecida" in printed and "not in box 3" in printed
    assert "Desaparecida 2026-03-04" in client.get(f"/samples/sleeve?ids={sample.id}").text
    data = json.loads((settings.UPLOAD_DIR / sample.code / "sample.json").read_text())
    assert data["condition"] == "missing" and data["condition_on"] == "2026-03-04"
    assert data["condition_note"] == "not in box 3"

    # Destroyed without a date: today
    _mark(client, sample, "destroyed", note="used up in RBS")
    [s] = _samples(id=sample.id)
    assert (s.condition, s.condition_on) == ("destroyed", date.today())

    # Found again: all cleared, the record as it was
    _mark(client, sample, "")
    [s] = _samples(id=sample.id)
    assert (s.condition, s.condition_on, s.condition_note) == (None, None, None)
    assert "Voltou a aparecer" not in client.get(f"/samples/{sample.id}").text

    # Logged for admins
    log = world.client(world.user("cond-admin", admin=True)).get("/activity?action=sample_condition").text
    assert sample.code in log and "missing → destroyed" in log and "destroyed → there" in log


def test_importing_and_updating_the_condition(world):
    user = world.user("cond-imp")
    client = world.client(user)
    sub = world.substrate()
    item = {"label": "COND I1", "substrate": sub.name, "condition": "destroyed", "condition_on": "2025-02-01",
            "condition_note": "broke", "timeline": [
                {"kind": "cut", "performed_at": "2024-07-01", "pieces": [{"label": "A", "condition": "missing"}, {"label": "B"}]}]}
    _confirm(client, _upload(client, item))
    [s] = _samples(label="COND I1")
    assert (s.condition, s.condition_on, s.condition_note) == ("destroyed", date(2025, 2, 1), "broke")
    [a] = _samples(label="A", cut_step_id=_samples(label="B")[0].cut_step_id)
    assert a.condition == "missing" and a.condition_on == date.today()
    assert _samples(label="B")[-1].condition is None

    bad = _upload(client, {"label": "COND I2", "substrate": sub.name, "condition": "gone", "condition_on": "March"})
    assert "condition&#34; tem de ser um de" in bad.text and "condition_on&#34; tem de ser uma data" in bad.text

    # Update: the file says it's there again
    item.pop("condition"), item.pop("condition_on"), item.pop("condition_note")
    item["condition"] = None
    page = _compare(client, s.id, item)
    assert page.status_code == 200, page.text
    assert f"s{s.id}.condition" in _boxes(page)
    _apply(client, s.id, page, f"s{s.id}.condition")
    [s] = _samples(id=s.id)
    assert (s.condition, s.condition_on, s.condition_note) == (None, None, None)
