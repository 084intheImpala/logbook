"""Updating a sample from a file: the differences, ticked or not (backend/sample_update.py, /samples/{id}/update)."""
import io
import json
import re
import zipfile
from datetime import date

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Analysis, ProcessStep, Sample, StudySample
from tests.loop import run
from tests.test_sample_import import _attachments, _confirm, _entries, _samples, _upload
from tests.test_studies import _study


def _zip(item, files: dict[str, bytes]) -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("sample.json", json.dumps(item))
        for name, content in files.items():
            z.writestr(name, content)
    return buffer.getvalue()


def _compare(client, sample_id, payload, name="new.json"):
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return client.post(f"/samples/{sample_id}/update/check",
                       files={"files": (name, content, "application/octet-stream")})


def _ticked(page) -> list[str]:
    return re.findall(r'name="change" value="([^"]+)" checked', page.text)


def _boxes(page) -> list[str]:
    return re.findall(r'name="change" value="([^"]+)"', page.text)


def _apply(client, sample_id, page, change):
    token = re.search(rf'action="/samples/{sample_id}/update/([0-9a-f]+)"', page.text)
    assert token, page.text
    return client.post(f"/samples/{sample_id}/update/{token.group(1)}", data={"change": change},
                       follow_redirects=False)


def _original(sub, label) -> dict:
    return {"label": label, "substrate": sub.name, "film_material": "Ga2O3", "tags": ["old"],
            "timeline": [
                {"kind": "step", "type": "Deposition", "performed_at": "2024-06-22", "ref": "film",
                 "parameters": {"target": "Ga2O3", "thickness": 100}, "notes": "first",
                 "files": ["dep.jpg"]},
                {"kind": "analysis", "type": "XRD / HRXRD", "performed_at": "2024-06-25", "notes": "kept here"},
                {"kind": "step", "type": "Annealing", "performed_at": "2024-06-26"},
                {"kind": "cut", "performed_at": "2024-07-01", "method": "Diamond pen", "pieces": [
                    {"label": "A", "timeline": [{"kind": "analysis", "type": "RBS", "performed_at": "2024-07-04"}]},
                    {"label": "B"}]},
            ]}


def _imported(world, client, sub, label) -> Sample:
    page = _upload(client, _zip(_original(sub, label), {"dep.jpg": b"update test photo one"}), "first.zip")
    _confirm(client, page)
    [sample] = _samples(label=label)
    return sample


def test_the_sample_page_offers_an_update_and_an_unchanged_file_has_nothing_to_change(world):
    user = world.user("upd-same")
    client = world.client(user)
    sub = world.substrate()
    sample = _imported(world, client, sub, "AOP U0")
    html = client.get(f"/samples/{sample.id}").text
    assert f'href="/samples/{sample.id}/update"' in html and "Atualizar a partir de um ficheiro" in html
    assert client.get(f"/samples/{sample.id}/update").status_code == 200
    page = _compare(client, sample.id, _zip(_original(sub, "AOP U0"), {"dep.jpg": b"update test photo one"}), "same.zip")
    assert page.status_code == 200 and 'id="update-same"' in page.text and not _boxes(page)
    # someone who can only see it can't
    other = world.user("upd-viewer")
    assert world.client(other).get(f"/samples/{sample.id}/update").status_code == 403
    # a piece is updated through its parent
    piece = next(p for p in _samples(label="A") if p.code.startswith(sample.code))
    assert f'href="/samples/{piece.id}/update"' not in client.get(f"/samples/{piece.id}").text


def test_differences_are_listed_and_only_the_ticked_ones_are_made(world):
    user = world.user("upd-diff")
    client = world.client(user)
    sub = world.substrate()
    sample = _imported(world, client, sub, "AOP U1")
    dep, xrd, anneal, cut = _entries(sample.id)
    item = _original(sub, "AOP U1")
    item["description"] = "now described"
    tl = item["timeline"]
    tl[0]["parameters"] = {"target": "Ga2O3", "thickness": 120}           # changed
    tl[0]["notes"] = "first, fixed"
    tl[0]["files"] = ["dep.jpg", "more/settings.png"]                      # one more file
    tl[1].pop("notes")                                                     # would remove the notes
    tl[2]["performed_at"] = "2024-06-27"                                   # moved a day: still the same entry
    del tl[2:3]                                                            # … in fact gone from the file
    tl.insert(1, {"kind": "analysis", "type": "Ellipsometry", "performed_at": "2024-06-23",
                  "parameters": {}, "files": ["ellipso.csv"]})            # new, between the first two
    tl[-1]["pieces"][0]["timeline"].append({"kind": "analysis", "type": "XRD / HRXRD", "performed_at": "2024-07-05"})
    tl[-1]["pieces"].append({"label": "C", "description": "a new piece"})
    files = {"dep.jpg": b"update test photo one", "more/settings.png": b"update test settings photo", "ellipso.csv": b"update test ellipsometry 0.1,0.2"}
    page = _compare(client, sample.id, _zip(item, files), "new.zip")
    assert page.status_code == 200, page.text
    s = f"s{sample.id}"
    boxes, ticked = set(_boxes(page)), set(_ticked(page))
    assert {f"{s}.description", f"{s}.p{dep.id}.param.thickness", f"{s}.p{dep.id}.notes",
            f"{s}.new1"} <= ticked
    assert any(b.startswith(f"{s}.p{dep.id}.files.") for b in ticked)
    # what would take something away isn't ticked
    assert f"{s}.a{xrd.id}.notes" in boxes - ticked
    assert f"{s}.p{anneal.id}.delete" in boxes - ticked
    assert f"{s}.label" not in boxes and "120" in page.text and "Pedaços novos" in page.text
    # nothing saved by the check
    assert _entries(sample.id)[0].parameters["thickness"] == 100

    keep = [b for b in _ticked(page) if not b.endswith(".notes")]          # leave the notes alone
    done = _apply(client, sample.id, page, keep)
    assert done.status_code == 303 and done.headers["location"] == f"/samples/{sample.id}"
    entries = _entries(sample.id)
    assert [type(e).__name__ for e in entries] == ["ProcessStep", "Analysis", "Analysis", "ProcessStep", "ProcessStep"]
    dep2, ellipso, xrd2, anneal2, cut2 = entries
    assert dep2.id == dep.id and dep2.parameters == {"target": "Ga2O3", "thickness": 120} and dep2.notes == "first"
    assert ellipso.performed_at == date(2024, 6, 23)
    assert xrd2.notes == "kept here"                                       # not ticked: kept
    assert anneal2.id == anneal.id                                         # not ticked: not deleted
    assert sorted(a.original_filename for a in _attachments("step", dep.id)) == ["dep.jpg", "settings.png"]
    assert [a.original_filename for a in _attachments("analysis", ellipso.id)] == ["ellipso.csv"]
    assert _samples(id=sample.id)[0].description == "now described"
    pieces = {p.label: p for p in _samples(cut_step_id=cut.id)}
    assert set(pieces) == {"A", "B", "C"} and pieces["C"].code == f"{sample.code}-C"
    assert pieces["C"].owner_id == user.id and pieces["C"].description == "a new piece"
    assert [type(e).__name__ for e in _entries(pieces["A"].id)] == ["Analysis", "Analysis"]
    assert cut2.parameters["pieces"] == 3

    # the same file again: only the untouched differences are left
    again = _compare(client, sample.id, _zip(item, files), "new.zip")
    assert set(_boxes(again)) == {f"{s}.p{dep.id}.notes", f"{s}.a{xrd.id}.notes", f"{s}.p{anneal.id}.delete"}
    _apply(client, sample.id, again, [f"{s}.p{anneal.id}.delete"])
    assert anneal.id not in [e.id for e in _entries(sample.id) if isinstance(e, ProcessStep)]


def test_the_sample_of_a_file_with_several_is_the_one_with_its_label(world):
    user = world.user("upd-several")
    client = world.client(user)
    sub = world.substrate()
    sample = _imported(world, client, sub, "AOP U2")
    mine = _original(sub, "AOP U2") | {"description": "this one"}
    other = _original(sub, "AOP U2") | {"label": "other 41", "description": "not this one"}
    page = _compare(client, sample.id, _zip({"samples": [other, mine]}, {"dep.jpg": b"update test photo one"}), "both.zip")
    assert "this one" in page.text and "not this one" not in page.text
    unclear = _compare(client, sample.id, _zip([other, other | {"label": "other 42"}],
                                               {"dep.jpg": b"update test photo one"}), "two.zip")
    assert "AOP U2" in unclear.text and not _boxes(unclear)


def test_a_date_change_is_a_change_and_the_order_can_follow_the_file(world):
    user = world.user("upd-order")
    client = world.client(user)
    sub = world.substrate()
    sample = _imported(world, client, sub, "AOP U3")
    dep, xrd, anneal, cut = _entries(sample.id)
    item = _original(sub, "AOP U3")
    tl = item["timeline"]
    tl[1]["performed_at"] = "2024-06-24"
    tl[1], tl[2] = tl[2], tl[1]                                            # annealing first, then XRD
    page = _compare(client, sample.id, _zip(item, {"dep.jpg": b"update test photo one"}), "order.zip")
    s = f"s{sample.id}"
    assert {f"{s}.a{xrd.id}.date", f"{s}.order"} <= set(_ticked(page))
    _apply(client, sample.id, page, _ticked(page))
    assert [e.id for e in _entries(sample.id)] == [dep.id, anneal.id, xrd.id, cut.id]
    assert _entries(sample.id)[2].performed_at == date(2024, 6, 24)


def test_runs_and_layers_and_studies(world):
    user = world.user("upd-runs")
    client = world.client(user)
    sub = world.substrate()
    sample = _imported(world, client, sub, "AOP U4")
    series = _study(client, "Update series")
    dep, xrd, anneal, cut = _entries(sample.id)
    item = _original(sub, "AOP U4") | {"studies": ["Update series"]}
    tl = item["timeline"]
    tl[2]["run"] = "furnace"
    pieces = tl[3]["pieces"]
    pieces[1]["timeline"] = [
        {"kind": "step", "type": "Annealing", "performed_at": "2024-06-26", "run": "furnace"},
        {"kind": "step", "type": "Deposition", "performed_at": "2024-07-10", "on": "film", "partial": True,
         "parameters": {"target": "Ti"}}]
    page = _compare(client, sample.id, _zip(item, {"dep.jpg": b"update test photo one"}), "runs.zip")
    s = f"s{sample.id}"
    assert {f"{s}.p{anneal.id}.run", f"{s}.study{series}"} <= set(_ticked(page))
    _apply(client, sample.id, page, _ticked(page))
    b = next(p for p in _samples(cut_step_id=cut.id) if p.label == "B")
    b_anneal, contact = _entries(b.id)
    assert b_anneal.run_id and b_anneal.run_id == _entries(sample.id)[2].run_id
    assert contact.on_step_id == dep.id and contact.partial

    async def studies():
        async with AsyncSessionLocal() as db:
            return list((await db.execute(select(StudySample.study_id).where(
                StudySample.sample_id == sample.id))).scalars())
    assert run(studies()) == [series]


def test_an_expired_or_foreign_token_changes_nothing(world):
    user = world.user("upd-token")
    client = world.client(user)
    sub = world.substrate()
    sample = _imported(world, client, sub, "AOP U5")
    item = _original(sub, "AOP U5") | {"description": "changed"}
    page = _compare(client, sample.id, _zip(item, {"dep.jpg": b"update test photo one"}), "x.zip")
    token = re.search(rf'action="/samples/{sample.id}/update/([0-9a-f]+)"', page.text).group(1)
    other = world.client(user)   # another session
    r = other.post(f"/samples/{sample.id}/update/{token}", data={"change": [f"s{sample.id}.description"]})
    assert "expirou" in r.text and not _samples(id=sample.id)[0].description


# ── Through Import: several samples at once ──────────────────────────────────

def _import_check(client, payload, name, update=True):
    data = {"update": "1"} if update else {}
    return client.post("/samples/import/check", data=data,
                       files={"files": (name, payload, "application/octet-stream")})


def _import_apply(client, page, change):
    token = re.search(r'action="/samples/import/([0-9a-f]+)"', page.text)
    assert token, page.text
    update = re.search(r'name="update" value="([^"]*)"', page.text).group(1)
    return client.post(f"/samples/import/{token.group(1)}", data={"change": change, "update": update})


def test_import_updates_the_samples_already_here_creates_the_others_and_links_runs_across_them(world):
    user = world.user("upd-many")
    client = world.client(user)
    sub = world.substrate()
    photo = {"dep.jpg": b"update test photo one"}
    one, two = _original(sub, "MANY 40"), _original(sub, "MANY 41")
    _confirm(client, _import_check(client, _zip([one, two], photo), "first.zip"))
    [s40], [s41] = _samples(label="MANY 40"), _samples(label="MANY 41")
    a40, a41 = _entries(s40.id)[2], _entries(s41.id)[2]
    assert a40.run_id is None and a41.run_id is None

    # the same samples, the annealing now one furnace run for both and a new sample in it; 41 gets a description
    for item in (one, two):
        item["timeline"][2]["run"] = "furnace"
    two["description"] = "second batch"
    three = _original(sub, "MANY 42")
    three["timeline"][2]["run"] = "furnace"
    page = _import_check(client, _zip([one, two, three], photo), "again.zip")
    assert page.status_code == 200 and 'id="import-updates"' in page.text
    assert "Importar 3 amostras e fazer as alterações assinaladas" in page.text
    ticked = _ticked(page)
    assert {f"s{s40.id}.p{a40.id}.run", f"s{s41.id}.p{a41.id}.run", f"s{s41.id}.description"} <= set(ticked)
    assert len(_samples(label="MANY 40")) == 1 and not _samples(label="MANY 42")   # nothing saved yet

    done = _import_apply(client, page, ticked)
    assert "Importação concluída!" in done.text and f'href="/samples/{s41.id}"' in done.text
    assert len(_samples(label="MANY 40")) == 1 and len(_samples(label="MANY 41")) == 1
    [s42] = _samples(label="MANY 42")
    runs = {_entries(s.id)[2].run_id for s in (s40, s41, s42)}
    assert len(runs) == 1 and None not in runs
    assert _samples(id=s41.id)[0].description == "second batch"

    # nothing left to do: said so, no button
    again = _import_check(client, _zip([one, two, three], photo), "third.zip")
    assert 'id="import-nothing"' in again.text and 'action="/samples/import/' not in again.text.replace(
        'action="/samples/import/check"', "")


def test_unticking_update_imports_again_and_code_picks_among_samples_with_one_label(world):
    user = world.user("upd-code")
    client = world.client(user)
    sub = world.substrate()
    photo = {"dep.jpg": b"update test photo one"}
    item = _original(sub, "TWICE")
    _confirm(client, _import_check(client, _zip(item, photo), "a.zip"))
    _confirm(client, _import_check(client, _zip(item, photo), "b.zip", update=False))   # a second one, as before
    first, second = _samples(label="TWICE")
    unclear = _import_check(client, _zip(item | {"description": "which?"}, photo), "c.zip")
    assert "code" in unclear.text and first.code in unclear.text and second.code in unclear.text
    assert 'action="/samples/import/' not in unclear.text.replace('action="/samples/import/check"', "")
    page = _import_check(client, _zip(item | {"description": "this one", "code": second.code}, photo), "d.zip")
    _import_apply(client, page, _ticked(page))
    assert _samples(id=second.id)[0].description == "this one" and not _samples(id=first.id)[0].description
    # a code without updating, or of no sample, is an error
    assert "code" in _import_check(client, _zip(item | {"code": second.code}, photo), "e.zip", update=False).text
    assert "XX-1999-001" in _import_check(client, _zip(item | {"code": "XX-1999-001"}, photo), "f.zip").text


def test_a_sample_matched_only_by_its_label_can_be_imported_as_a_new_one(world):
    user = world.user("upd-apart")
    client = world.client(user)
    sub = world.substrate()
    assert re.search(r'name="update" value="1">', client.get("/samples/import").text)   # not ticked to start with
    _confirm(client, _import_check(client, json.dumps({"label": "1", "substrate": sub.name}).encode(), "a.json"))
    [first] = _samples(label="1")
    other = {"label": "1", "substrate": sub.name, "timeline": [
        {"kind": "step", "type": "Annealing", "parameters": {"method": "Furnace", "temperature": 500}}]}
    item = json.dumps([other, {"label": "APART 2", "substrate": sub.name}]).encode()
    page = _import_check(client, item, "b.json")
    assert 'id="import-updates"' in page.text and "data-matched-by-label" in page.text
    token = re.search(r'formaction="/samples/import/([0-9a-f]+)/check" name="new" value="(f\d+)"', page.text)
    assert token and token.group(2) == "f0"
    # a "code" says which sample it is: no such choice
    coded = _import_check(client, json.dumps({"label": "1", "code": first.code, "substrate": sub.name}).encode(),
                          "c.json")
    assert "data-matched-by-label" not in coded.text

    page = _import_check(client, item, "b.json")
    token = re.search(r'formaction="/samples/import/([0-9a-f]+)/check"', page.text).group(1)
    again = client.post(f"/samples/import/{token}/check", data={"new": ["f0"], "update": "1"})
    assert 'id="import-updates"' not in again.text and "Importar 2 amostras" in again.text
    assert 'name="new" value="f0"' in again.text and len(_samples(label="1")) == 1   # nothing saved yet
    done = _import_apply_new(client, again)
    assert "Importação concluída!" in done.text
    assert len(_samples(label="1")) == 2 and _entries(first.id) == []


def _import_apply_new(client, page):
    token = re.search(r'<form method="post" action="/samples/import/([0-9a-f]+)"', page.text).group(1)
    new = re.findall(r'type="hidden" name="new" value="([^"]+)"', page.text)
    return client.post(f"/samples/import/{token}", data={"update": "1", "new": new})
