"""Importing samples from JSON / zip files (backend/sample_import.py, /samples/import)."""
import io
import json
import re
import zipfile
from datetime import date

from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Analysis, Attachment, ProcessStep, Sample, StudySample
from tests.loop import run
from tests.test_studies import _study


def _upload(client, payload, name="old.json"):
    content = payload if isinstance(payload, bytes) else json.dumps(payload).encode()
    return client.post("/samples/import/check", files={"files": (name, content, "application/octet-stream")})


def _confirm(client, page):
    token = re.search(r'action="/samples/import/([0-9a-f]+)"', page.text)
    assert token, page.text
    return client.post(f"/samples/import/{token.group(1)}")


def _samples(**where) -> list[Sample]:
    async def get():
        async with AsyncSessionLocal() as db:
            q = select(Sample)
            for k, v in where.items():
                q = q.where(getattr(Sample, k) == v)
            return list((await db.execute(q.order_by(Sample.id))).scalars())
    return run(get())


def _entries(sample_id: int):
    async def get():
        async with AsyncSessionLocal() as db:
            steps = (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample_id))).scalars().all()
            analyses = (await db.execute(select(Analysis).where(Analysis.sample_id == sample_id))).scalars().all()
            return sorted([*steps, *analyses], key=lambda e: e.position)
    return run(get())


def _attachments(entity_type: str, entity_id: int) -> list[Attachment]:
    async def get():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Attachment).where(
                Attachment.entity_type == entity_type, Attachment.entity_id == entity_id))).scalars().all()
    return run(get())


def _sample(sub, **extra) -> dict:
    return {"label": "old ZnO", "substrate": sub.name, "film_material": "ZnO", "tags": ["old"],
            "timeline": [
                {"kind": "step", "type": "Deposition", "performed_at": "2019-03-04", "performed_by": "Someone Gone",
                 "parameters": {"target": "ZnO", "thickness": "100,5", "duration": 12}, "notes": "first try"},
                {"kind": "analysis", "type": "XRD / HRXRD", "performed_at": "2019-03-10"},
            ]} | extra


def test_check_shows_what_would_be_created_and_saves_nothing_until_confirmed(world):
    user = world.user("importer")
    client = world.client(user)
    sub = world.substrate()
    form = client.get("/samples/import").text
    assert "Importar amostras" in form
    # the upload shows its progress, then that the server is checking (translated for the script)
    assert "data-import-upload" in form and "<progress" in form and "a verificar os ficheiros" in form
    assert 'href="/samples/import"' in client.get("/samples/").text
    page = _upload(client, _sample(sub))
    assert page.status_code == 200 and "Importar 1 amostra" in page.text
    assert "data-import-busy" in page.text      # the Import button says it's working while it saves
    code = f"{user.initials}-2019-001"            # the year of its first entry
    assert code in page.text and "old ZnO" in page.text
    assert not _samples(code=code)

    done = _confirm(client, page)
    [sample] = _samples(code=code)
    assert done.status_code == 200 and f'href="/samples/{sample.id}"' in done.text
    assert sample.owner_id == user.id and sample.substrate_id == sub.id and sample.tags == ["old"]
    deposition, xrd = _entries(sample.id)
    assert deposition.parameters == {"target": "ZnO", "thickness": 100.5, "duration": "12:00"}
    assert deposition.performed_by == "Someone Gone" and deposition.performer_id is None
    assert deposition.performed_at == date(2019, 3, 4) and deposition.notes == "first try"
    assert isinstance(xrd, Analysis) and xrd.position == 2
    assert world.client(user).get(f"/samples/{sample.id}").status_code == 200
    # the upload can't be imported twice
    again = client.post(done.request.url.path)
    assert len(_samples(code=code)) == 1 and ("expired" in again.text or "expirou" in again.text)


def test_any_error_and_nothing_is_imported(world):
    user = world.user("importer-bad")
    client = world.client(user)
    sub = world.substrate()
    good = _sample(sub, label="fine one")
    bad = _sample(sub, label="broken one", substrate="no such substrate", colour="blue")
    bad["timeline"] += [{"kind": "analysis", "type": "Tea leaves"}, {"kind": "step", "type": "Annealing",
                                                                     "performed_at": "March 2019"}]
    page = _upload(client, [good, bad])
    text = page.text
    assert "no such substrate" in text and "colour" in text and "Tea leaves" in text and "March 2019" in text
    assert "action=\"/samples/import/" not in text.replace("/samples/import/check", "")
    assert not _samples(label="fine one")


def test_the_year_is_this_year_when_nothing_is_dated_and_samples_are_numbered_in_date_order(world):
    user = world.user("importer-years")
    client = world.client(user)
    sub = world.substrate()
    later = _sample(sub, label="later")
    earlier = _sample(sub, label="earlier")
    earlier["timeline"][0]["performed_at"] = "2019-01-02"
    undated = {"label": "undated", "substrate": sub.name}
    _confirm(client, _upload(client, [later, earlier, undated]))
    assert _samples(label="earlier")[0].code == f"{user.initials}-2019-001"
    assert _samples(label="later")[0].code == f"{user.initials}-2019-002"
    assert _samples(label="undated")[0].code == f"{user.initials}-{date.today().year}-001"


def test_a_team_sample_belongs_to_the_team_whose_members_can_edit_it(world):
    member, outsider = world.user("wbs-member"), world.user("wbs-outsider")
    team = world.team("wbs", members=[member])
    sub = world.substrate()
    item = _sample(sub, team=team.name, label="nobody knows", year=2018, visibility="personal")

    refused = _upload(world.client(outsider), item)
    assert "only members" in refused.text or "só os membros" in refused.text

    client = world.client(member)
    _confirm(client, _upload(client, item))
    [sample] = _samples(label="nobody knows")
    prefix = team.name.upper()
    assert sample.code == f"{prefix}-2018-001"
    assert sample.owner_id is None and sample.owner_team_id == team.id
    backup = json.loads((world.upload_dir / sample.code / "sample.json").read_text())
    assert backup["owner"] is None and backup["owner_team"] == team.name
    page = client.get(f"/samples/{sample.id}")
    assert "nobody knows" in page.text and team.name in page.text
    assert client.get(f"/samples/{sample.id}/edit").status_code == 200
    assert world.client(outsider).get(f"/samples/{sample.id}/edit").status_code == 403

    # Saving the form as a member keeps it the team's; picking someone hands it over
    form = {"sample_type": "thin_film", "label": "nobody knows", "substrate_id": str(sub.id), "owner_id": ""}
    assert client.post(f"/samples/{sample.id}/edit", data=form).status_code == 303
    assert _samples(id=sample.id)[0].owner_team_id == team.id
    form["owner_id"] = str(member.id)
    client.post(f"/samples/{sample.id}/edit", data=form)
    [given] = _samples(id=sample.id)
    assert given.owner_id == member.id and given.owner_team_id is None


def test_someone_elses_sample_waits_for_them_to_confirm(world):
    uploader, owner = world.user("importer-for"), world.user("importer-owner")
    client = world.client(uploader)
    sub = world.substrate()
    page = _upload(client, _sample(sub, owner=owner.username, label="theirs"))
    assert f"{owner.initials}-2019-001" in page.text
    _confirm(client, page)
    [sample] = _samples(label="theirs")
    assert sample.owner_id == owner.id and sample.requested_by_id == uploader.id
    assert any(sh.user_id == uploader.id and sh.can_edit for sh in sample.shares)


def test_cuts_make_pieces_with_their_own_timelines_and_layers_can_sit_on_the_parents(world):
    user = world.user("importer-cut")
    client = world.client(user)
    sub = world.substrate()
    item = {"label": "to be cut", "substrate": sub.name, "film_material": "Ga2O3", "timeline": [
        {"kind": "step", "type": "Deposition", "performed_at": "2020-05-01", "ref": "film",
         "parameters": {"target": "Ga2O3", "thickness": 200}},
        {"kind": "cut", "performed_at": "2020-05-02", "method": "Scribe", "pieces": [
            {"label": "contacts", "timeline": [
                {"kind": "step", "type": "Deposition", "on": "film", "partial": True, "parameters": {"target": "Au"}},
                {"kind": "analysis", "type": "Hall / 4-probe"}]},
            {"label": "spare"},
            {"is_reference": True}]},
        {"kind": "analysis", "type": "XRD / HRXRD", "performed_at": "2020-06-01"},
    ]}
    _confirm(client, _upload(client, item))
    [parent] = _samples(label="to be cut")
    code = f"{user.initials}-2020-001"
    assert parent.code == code
    deposition, cut, xrd = _entries(parent.id)
    assert cut.parameters == {"pieces": 3, "method": "Scribe"}
    contacts, spare, ref = (_samples(code=f"{code}-{s}")[0] for s in ("A", "B", "REF"))
    assert contacts.label == "contacts" and spare.label == "spare" and ref.is_reference
    assert {contacts.cut_step_id, spare.cut_step_id, ref.cut_step_id} == {cut.id}
    assert contacts.film_material == "Ga2O3" and contacts.substrate_id == sub.id
    gold, hall = _entries(contacts.id)
    assert gold.on_step_id == deposition.id and gold.partial
    page = client.get(f"/samples/{contacts.id}").text
    assert "Ga2O3" in page and "Au" in page        # the parent's film is inherited, the gold is its own
    assert not _entries(spare.id)


def test_a_zip_brings_the_photos_and_files(world):
    user = world.user("importer-zip")
    client = world.client(user)
    sub = world.substrate()
    item = _sample(sub, label="with files", files=["photos/top.txt"])
    item["timeline"][1]["files"] = ["xrd/scan.xy"]
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w") as z:
        z.writestr("batch/sample.json", json.dumps(item))
        z.writestr("batch/photos/top.txt", "a photo, really")
        z.writestr("batch/xrd/scan.xy", "10 20\n11 25\n")
    missing = dict(item, label="missing file", files=["nope.jpg"])
    page = _upload(client, json.dumps(missing).encode(), "x.json")
    assert "nope.jpg" in page.text and not _samples(label="missing file")

    page = _upload(client, buffer.getvalue(), "batch.zip")
    assert "with files" in page.text
    _confirm(client, page)
    [sample] = _samples(label="with files")
    assert [a.original_filename for a in _attachments("sample", sample.id)] == ["top.txt"]
    xrd = _entries(sample.id)[1]
    [scan] = _attachments("analysis", xrd.id)
    assert scan.original_filename == "scan.xy" and sample.code in scan.stored_filename


def _study_links(study_id: int) -> list[int]:
    async def get():
        async with AsyncSessionLocal() as db:
            return sorted((await db.execute(
                select(StudySample.sample_id).where(StudySample.study_id == study_id))).scalars())
    return run(get())


def test_samples_and_pieces_can_be_added_to_studies_the_importer_co_owns(world):
    user = world.user("importer-study")
    client = world.client(user)
    sub = world.substrate()
    series = _study(client, "Annealing series")
    other = _study(client, "Other study")
    item = _sample(sub, label="studied", studies=["annealing SERIES", "Annealing series"])
    item["timeline"].append({"kind": "cut", "pieces": [{"label": "kept", "studies": ["Other study"]},
                                                      {"label": "plain"}]})
    page = _upload(client, item)
    assert "Annealing series" in page.text and "Other study" in page.text   # shown in the preview
    assert not _study_links(series) and not _study_links(other)          # the check adds nothing
    _confirm(client, page)
    [sample] = _samples(label="studied")
    [kept] = _samples(label="kept")
    assert _study_links(series) == [sample.id]                           # once, though named twice
    assert _study_links(other) == [kept.id]                              # the piece only
    assert sample.code in client.get(f"/studies/{series}").text


def test_a_study_the_importer_doesnt_co_own_is_an_error(world):
    owner, mate = world.user("st-imp-owner"), world.user("st-imp-mate")
    world.team("st-imp-team", members=[owner, mate])
    theirs = _study(world.client(owner), "Their team study")   # the mate can see it, but not add to it
    client = world.client(mate)
    sub = world.substrate()
    page = _upload(client, [_sample(sub, label="to their study", studies=["Their team study"]),
                            _sample(sub, label="to no study", studies=["No such study"])])
    assert "Their team study" in page.text and "No such study" in page.text
    assert "action=\"/samples/import/" not in page.text.replace("/samples/import/check", "")
    assert not _samples(label="to their study") and not _study_links(theirs)
    bad = _upload(client, _sample(sub, label="bad studies", studies="Their team study"))
    assert "studies" in bad.text and "action=\"/samples/import/" not in bad.text.replace("/samples/import/check", "")
