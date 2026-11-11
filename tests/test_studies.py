"""Studies (/studies): several samples, references and dated notes, with co-owners."""
import io
import json
import re

from backend import doi
from backend.config import settings


def _study(client, title="Contacts on Ga2O3", visibility="team") -> int:
    r = client.post("/studies/new", data={"title": title, "description": "Which metal works", "visibility": visibility})
    assert r.status_code == 303, r.text
    return int(re.search(r"/studies/(\d+)", r.headers["location"]).group(1))


def test_a_new_study_is_owned_by_its_creator_and_listed(world):
    me = world.user("study-maker")
    client = world.client(me)
    study_id = _study(client, "Annealing series")
    assert "Annealing series" in client.get("/studies/").text
    page = client.get(f"/studies/{study_id}").text
    assert "Annealing series" in page and "Which metal works" in page and me.display_name in page
    assert 'href="/studies/"' in client.get("/samples/").text     # the sidebar tab


def test_visibility_personal_team_public(world):
    owner, mate, stranger = world.user("st-owner"), world.user("st-mate"), world.user("st-stranger")
    world.team("st-team", members=[owner, mate])
    client = world.client(owner)
    personal, team, public = (_study(client, v, v) for v in ("personal", "team", "public"))
    mate_c, stranger_c = world.client(mate), world.client(stranger)
    assert mate_c.get(f"/studies/{personal}").status_code == 403
    assert mate_c.get(f"/studies/{team}").status_code == 200
    assert stranger_c.get(f"/studies/{team}").status_code == 403
    assert stranger_c.get(f"/studies/{public}").status_code == 200
    listed = stranger_c.get("/studies/").text
    assert "public" in listed and ">team<" not in listed
    # Viewers can't change it
    assert mate_c.post(f"/studies/{team}/edit", data={"title": "mine now"}).status_code == 403
    assert mate_c.post(f"/studies/{team}/notes", data={"text": "hi"}).status_code == 403


def test_co_owners_have_full_rights_and_the_last_one_stays(world):
    a, b = world.user("co-a"), world.user("co-b")
    ca, cb = world.client(a), world.client(b)
    study_id = _study(ca, visibility="personal")
    assert cb.get(f"/studies/{study_id}").status_code == 403
    assert ca.post(f"/studies/{study_id}/owners", data={"user_id": b.id}).status_code == 303
    assert cb.post(f"/studies/{study_id}/edit", data={"title": "Renamed by B", "visibility": "personal"}).status_code == 303
    assert "Renamed by B" in ca.get(f"/studies/{study_id}").text
    assert cb.post(f"/studies/{study_id}/owners/{a.id}/delete").status_code == 303
    assert ca.get(f"/studies/{study_id}").status_code == 403
    cb.post(f"/studies/{study_id}/owners/{b.id}/delete")     # the last co-owner can't leave
    assert cb.get(f"/studies/{study_id}").status_code == 200


def test_only_samples_you_can_see_are_added_and_listed(world):
    owner, other, viewer = world.user("ss-owner"), world.user("ss-other"), world.user("ss-viewer")
    client = world.client(owner)
    study_id = _study(client, visibility="public")
    mine = world.sample(owner, label="my film")
    theirs = world.sample(other)                     # personal, not shared with owner
    shared = world.sample(other, shared_view=[owner])

    client.post(f"/studies/{study_id}/samples", data={"code": mine.code})
    client.post(f"/studies/{study_id}/samples", data={"code": theirs.code})
    assert "que possa ver" in client.get(f"/studies/{study_id}").text   # refused (the message names it)
    client.post(f"/studies/{study_id}/samples", data={"code": shared.code.lower()})
    page = client.get(f"/studies/{study_id}").text
    assert mine.code in page and shared.code in page and theirs.code not in page

    # Someone who can see the study but not the samples doesn't see them listed
    seen = world.client(viewer).get(f"/studies/{study_id}").text
    assert mine.code not in seen and "2 amostras que não pode ver" in seen

    # Taking one out
    client.post(f"/studies/{study_id}/samples/{shared.id}/delete")
    assert f'href="/samples/{shared.id}"' not in client.get(f"/studies/{study_id}").text


def test_the_sample_page_shows_its_studies_and_adds_it_to_one(world):
    owner = world.user("sp-owner")
    client = world.client(owner)
    first, second = _study(client, "First study"), _study(client, "Second study")
    sample = world.sample(owner)
    page = client.get(f"/samples/{sample.id}").text
    assert 'action="/studies/add-sample"' in page and "Second study" in page

    r = client.post("/studies/add-sample", data={"study_id": second, "sample_id": sample.id})
    assert r.status_code == 303 and r.headers["location"].startswith(f"/samples/{sample.id}")
    page = client.get(f"/samples/{sample.id}").text
    assert f'href="/studies/{second}"' in page and f'href="/studies/{first}"' not in page

    # Its backup file says which studies it's in
    data = json.loads((settings.UPLOAD_DIR / sample.code / "sample.json").read_text())
    assert data["format"] >= 8 and data["studies"] == [{"id": second, "title": "Second study"}]
    client.post(f"/studies/{second}/edit", data={"title": "Second study, renamed", "visibility": "team"})
    data = json.loads((settings.UPLOAD_DIR / sample.code / "sample.json").read_text())
    assert data["studies"] == [{"id": second, "title": "Second study, renamed"}]

    # Not someone else's study, and not a sample you can't see
    stranger = world.user("sp-stranger")
    assert world.client(stranger).post("/studies/add-sample", data={"study_id": second, "sample_id": sample.id}).status_code == 403
    own = _study(world.client(stranger), "Stranger's")
    world.client(stranger).post("/studies/add-sample", data={"study_id": own, "sample_id": sample.id})
    assert sample.code not in world.client(stranger).get(f"/studies/{own}").text


def test_deleting_a_sample_takes_it_out_of_its_studies(world):
    owner = world.user("del-owner")
    client = world.client(owner)
    study_id = _study(client)
    sample = world.sample(owner)
    client.post(f"/studies/{study_id}/samples", data={"code": sample.code})
    assert sample.code in client.get(f"/studies/{study_id}").text
    assert client.post(f"/samples/{sample.id}/delete").status_code == 303
    page = client.get(f"/studies/{study_id}")
    assert page.status_code == 200 and sample.code not in page.text


def test_doi_parsing():
    assert doi.parse("10.1063/5.0012345") == ("10.1063/5.0012345", None)
    assert doi.parse("https://doi.org/10.1063/5.0012345") == ("10.1063/5.0012345", None)
    assert doi.parse("doi: 10.1002/adma.202000001.") == ("10.1002/adma.202000001", None)
    assert doi.parse("arxiv.org/abs/2401.00001") == (None, "https://arxiv.org/abs/2401.00001")
    assert doi.parse("  ") == (None, None)


def test_references_are_looked_up_from_the_doi_and_anyone_who_sees_the_study_can_add_one(world, monkeypatch):
    owner, mate = world.user("ref-owner"), world.user("ref-mate")
    world.team("ref-team", members=[owner, mate])
    study_id = _study(world.client(owner))
    monkeypatch.setattr(doi, "_fetch_csl", lambda d: {
        "title": "Schottky contacts on β-Ga2O3", "container-title": "Appl. Phys. Lett.",
        "author": [{"given": "Ana", "family": "Silva"}, {"given": "João", "family": "Costa"}],
        "issued": {"date-parts": [[2021, 3]]}})
    mate_c = world.client(mate)
    r = mate_c.post(f"/studies/{study_id}/references",
                    data={"link": "https://doi.org/10.1063/5.0012345", "note": "Ni works best"})
    assert r.status_code == 303
    page = world.client(owner).get(f"/studies/{study_id}").text
    assert "Schottky contacts on β-Ga2O3" in page and "Ana Silva, João Costa" in page and "2021" in page
    assert 'href="https://doi.org/10.1063/5.0012345"' in page and "Ni works best" in page
    ref_id = int(re.search(r'id="reference-(\d+)"', page).group(1))

    # Lookup fails: kept with the DOI, and a link without one
    monkeypatch.setattr(doi, "_fetch_csl", lambda d: None)
    world.client(owner).post(f"/studies/{study_id}/references", data={"link": "10.9999/unknown"})
    world.client(owner).post(f"/studies/{study_id}/references", data={"link": "example.org/paper", "title": "A web page"})
    page = world.client(owner).get(f"/studies/{study_id}").text
    assert "doi:10.9999/unknown" in page and 'href="https://example.org/paper"' in page and "A web page" in page

    # Only its co-owners or whoever added it can remove a reference
    stranger_ref = world.user("ref-other")
    world.team("ref-team2", members=[owner, stranger_ref])
    assert world.client(stranger_ref).post(f"/studies/{study_id}/references/{ref_id}/delete").status_code == 403
    assert mate_c.post(f"/studies/{study_id}/references/{ref_id}/delete").status_code == 303
    assert "Ni works best" not in world.client(owner).get(f"/studies/{study_id}").text


def test_notes_are_ordered_by_date_can_be_moved_and_point_at_a_step(world):
    owner = world.user("note-owner")
    client = world.client(owner)
    study_id = _study(client)
    sample = world.sample(owner)
    client.post(f"/studies/{study_id}/samples", data={"code": sample.code})
    step_id, _ = world.step(sample, "annealed")

    page = client.get(f"/studies/{study_id}").text
    assert f'value="step:{step_id}"' in page and f'value="sample:{sample.id}"' in page

    client.post(f"/studies/{study_id}/notes", data={"noted_on": "2026-03-10", "title": "Plan", "text": "Try Ni next"})
    client.post(f"/studies/{study_id}/notes", data={"noted_on": "2026-03-01", "title": "Literature",
                                                    "text": "Read about Pt", "about": f"step:{step_id}"})
    client.post(f"/studies/{study_id}/notes", data={"noted_on": "2026-03-05", "text": "A thought"})
    page = client.get(f"/studies/{study_id}").text
    assert page.index("Read about Pt") < page.index("A thought") < page.index("Try Ni next")
    assert f'href="/samples/{sample.id}#step-{step_id}"' in page

    ids = [int(i) for i in re.findall(r'id="note-(\d+)"', page)]
    client.post(f"/studies/{study_id}/notes/{ids[2]}/move", data={"direction": "up"})
    page = client.get(f"/studies/{study_id}").text
    assert page.index("Try Ni next") < page.index("A thought")

    # Editing; an empty note isn't added; one about a sample outside the study is refused
    r = client.post(f"/studies/{study_id}/notes/{ids[1]}/edit", data={"noted_on": "2026-03-05", "text": "A better thought"})
    assert r.status_code == 303 and "A better thought" in client.get(f"/studies/{study_id}").text
    assert "A better thought" in client.get(f"/studies/{study_id}/notes/{ids[1]}/edit").text
    client.post(f"/studies/{study_id}/notes", data={"noted_on": "2026-03-06"})
    assert len(re.findall(r'id="note-', client.get(f"/studies/{study_id}").text)) == 3
    elsewhere = world.sample(owner)
    assert client.post(f"/studies/{study_id}/notes",
                       data={"text": "x", "about": f"sample:{elsewhere.id}"}).status_code == 400

    client.post(f"/studies/{study_id}/notes/{ids[0]}/delete")
    assert "Read about Pt" not in client.get(f"/studies/{study_id}").text


def test_note_files_follow_the_study(world):
    owner, stranger = world.user("nf-owner"), world.user("nf-stranger")
    client = world.client(owner)
    study_id = _study(client, "Files study", visibility="personal")
    r = client.post(f"/studies/{study_id}/notes", data={"text": "the paper"},
                    files={"files": ("paper.pdf", io.BytesIO(b"%PDF-1.4 fake"), "application/pdf")})
    assert r.status_code == 303
    page = client.get(f"/studies/{study_id}").text
    file_id = int(re.search(r'href="/files/(\d+)"', page).group(1))
    assert "paper.pdf" in page
    assert client.get(f"/files/{file_id}").content == b"%PDF-1.4 fake"
    assert world.client(stranger).get(f"/files/{file_id}").status_code == 403
    assert (settings.UPLOAD_DIR / f"studies/{study_id}-Files-study/paper.pdf").is_file()

    # Deleting the study deletes its notes' files
    r = client.post(f"/studies/{study_id}/delete")
    assert r.status_code == 303 and "Files study" in client.get("/studies/").text   # "… deleted."
    assert "Files study" not in client.get("/studies/").text
    assert client.get(f"/files/{file_id}").status_code == 404


def test_the_studies_pages_are_in_portuguese(world):
    me = world.user("pt-study")
    client = world.client(me)
    client.post("/lang", data={"lang": "pt"})
    study_id = _study(client)
    assert "Estudos" in client.get("/studies/").text
    page = client.get(f"/studies/{study_id}").text
    assert "Adicionar uma nota" in page and "Referências" in page


def _study_json(study_id: int) -> dict:
    [path] = list((settings.UPLOAD_DIR / "studies").glob(f"{study_id}-*/study.json"))
    return json.loads(path.read_text())


def test_study_json_is_kept_next_to_the_notes_files(world):
    owner = world.user("sj-owner")
    client = world.client(owner)
    study_id = _study(client, "Backup study")
    data = _study_json(study_id)
    assert data["format"] == 1 and data["title"] == "Backup study" and data["owners"][0]["username"] == owner.username

    sample = world.sample(owner, label="film A")
    step_id, _ = world.step(sample, "annealed")
    client.post(f"/studies/{study_id}/samples", data={"code": sample.code})
    client.post(f"/studies/{study_id}/references", data={"link": "10.1063/5.0012345", "note": "relevant"})
    client.post(f"/studies/{study_id}/notes", data={"noted_on": "2026-04-01", "text": "look at this", "about": f"step:{step_id}"},
                files={"files": ("plot.csv", io.BytesIO(b"1,2"), "text/csv")})
    data = _study_json(study_id)
    assert data["samples"] == [{"id": sample.id, "code": sample.code, "label": "film A",
                                "added_at": data["samples"][0]["added_at"]}]
    assert data["references"][0]["doi"] == "10.1063/5.0012345" and data["references"][0]["note"] == "relevant"
    [note] = data["notes"]
    assert note["text"] == "look at this" and note["noted_on"] == "2026-04-01"
    assert note["about"] == {"sample": sample.code, "sample_id": sample.id, "kind": "step", "id": step_id}
    assert note["files"][0]["original_name"] == "plot.csv"
    folder = settings.UPLOAD_DIR / note["files"][0]["file"]
    assert folder.parent == next((settings.UPLOAD_DIR / "studies").glob(f"{study_id}-*"))   # same folder

    # Renamed: same folder, new title; deleted: the file goes
    client.post(f"/studies/{study_id}/edit", data={"title": "Renamed", "visibility": "team"})
    assert _study_json(study_id)["title"] == "Renamed"
    client.post(f"/studies/{study_id}/delete")
    assert not list((settings.UPLOAD_DIR / "studies").glob(f"{study_id}-*/study.json"))


def test_the_printable_study(world):
    owner, viewer = world.user("pr-owner"), world.user("pr-viewer")
    client = world.client(owner)
    study_id = _study(client, "Printed study", visibility="public")
    sample = world.sample(owner, label="printed film")
    hidden = world.sample(owner)
    client.post(f"/studies/{study_id}/samples", data={"code": sample.code})
    client.post(f"/studies/{study_id}/samples", data={"code": hidden.code})
    client.post(f"/studies/{study_id}/references", data={"link": "example.org/x", "title": "A useful page", "note": "see fig 3"})
    client.post(f"/studies/{study_id}/notes", data={"noted_on": "2026-05-02", "title": "Idea", "text": "try thinner"},
                files={"files": ("data.txt", io.BytesIO(b"x"), "text/plain")})

    assert f'href="/studies/{study_id}/print"' in client.get(f"/studies/{study_id}").text
    html = client.get(f"/studies/{study_id}/print").text
    assert "Printed study" in html and sample.code in html and "printed film" in html
    assert "A useful page" in html and "see fig 3" in html
    assert "try thinner" in html and "2026-05-02" in html and "data.txt" in html
    assert "<form" not in html and "window.print()" in html

    # A viewer who can't see one of the samples doesn't get it on paper either
    seen = world.client(viewer).get(f"/studies/{study_id}/print").text
    assert hidden.code not in seen and sample.code not in seen and "try thinner" in seen
    assert world.client(world.user("pr-out")).get(f"/studies/{study_id + 1000}/print").status_code == 404

    # The sample's own printout names its studies
    assert "Printed study" in client.get(f"/samples/{sample.id}/print").text


def _cut(parent, suffix="A", owner=None, **extra):
    """A Cut step at the end of the parent's timeline, and one piece."""
    from sqlalchemy import select
    from backend.database import AsyncSessionLocal
    from backend.models import ProcessStep, ProcessStepType, Sample
    from tests.loop import run

    async def go():
        async with AsyncSessionLocal() as db:
            cut_type = (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == "Cut"))).scalar_one()
            step = ProcessStep(sample_id=parent.id, step_type_id=cut_type, position=50)
            db.add(step)
            await db.flush()
            piece = Sample(code=f"{parent.code}-{suffix}", owner_id=owner.id if owner else parent.owner_id,
                           cut_step_id=step.id, **{"visibility": "personal"} | extra)
            db.add(piece)
            await db.commit()
            return piece
    return run(go())


def test_several_samples_are_ticked_and_added_at_once(world):
    owner, other = world.user("multi-owner"), world.user("multi-other")
    client = world.client(owner)
    study_id = _study(client)
    first, second = world.sample(owner, label="Ni contact"), world.sample(owner, label="Pt contact", tags=["schottky"])
    already, hidden = world.sample(owner), world.sample(other)
    client.post(f"/studies/{study_id}/samples", data={"code": already.code})

    # The list offers what can be added, searchable by name, tag and owner; not what's in or can't be seen
    page = client.get(f"/studies/{study_id}").text
    picker = page[page.index('id="sample-picker"'):page.index("</ul>", page.index('id="sample-picker"'))]
    assert f'value="{first.id}"' in picker and f'value="{second.id}"' in picker
    assert f'value="{already.id}"' not in picker and f'value="{hidden.id}"' not in picker
    assert "pt contact" in picker and "schottky" in picker and owner.display_name.lower() in picker

    r = client.post(f"/studies/{study_id}/samples",
                    data={"sample_ids": [first.id, second.id, already.id, hidden.id, first.id]})
    assert r.status_code == 303
    page = client.get(f"/studies/{study_id}").text
    assert f"{first.code}, {second.code}" in page                      # the message names them
    for s in (first, second, already):
        assert f'href="/samples/{s.id}"' in page
    assert f'href="/samples/{hidden.id}"' not in page
    picker = page[page.index('id="add-samples"'):page.index("</details>", page.index('id="add-samples"'))]
    assert f'value="{first.id}"' not in picker and f'value="{second.id}"' not in picker   # no longer offered

    client.post(f"/studies/{study_id}/samples", data={})
    assert "Selecione primeiro as amostras" in client.get(f"/studies/{study_id}").text


def test_a_note_can_be_about_a_piece_cut_from_a_sample_of_the_study(world):
    owner, other = world.user("piece-owner"), world.user("piece-other")
    client = world.client(owner)
    study_id = _study(client)
    parent = world.sample(owner)
    before_cut, _ = world.step(parent, "polished")                 # inherited by the pieces
    piece = _cut(parent, "A")
    on_piece, _ = world.step(piece, "annealed piece")
    piece_of_piece = _cut(piece, "1")
    on_piece_of_piece, _ = world.step(piece_of_piece, "contacts")
    hidden_piece = _cut(parent, "B", owner=other)                  # someone else's, personal
    on_hidden, _ = world.step(hidden_piece, "secret")
    client.post(f"/studies/{study_id}/samples", data={"sample_ids": [parent.id]})

    page = client.get(f"/studies/{study_id}").text
    for key in (f"step:{before_cut}", f"sample:{piece.id}", f"step:{on_piece}", f"sample:{piece_of_piece.id}",
                f"step:{on_piece_of_piece}"):
        assert f'value="{key}"' in page, key
    assert f'value="sample:{hidden_piece.id}"' not in page and f'value="step:{on_hidden}"' not in page
    # Pieces come under their parent, each piece's steps under it
    assert (page.index(f'value="step:{before_cut}"') < page.index(f'value="sample:{piece.id}"')
            < page.index(f'value="step:{on_piece}"') < page.index(f'value="sample:{piece_of_piece.id}"'))

    r = client.post(f"/studies/{study_id}/notes", data={"text": "Annealing the piece helped",
                                                        "about": f"step:{on_piece_of_piece}"})
    assert r.status_code == 303
    page = client.get(f"/studies/{study_id}").text
    assert f'href="/samples/{piece_of_piece.id}#step-{on_piece_of_piece}"' in page
    data = _study_json(study_id)
    assert data["notes"][0]["about"] == {"sample": piece_of_piece.code, "sample_id": piece_of_piece.id,
                                         "kind": "step", "id": on_piece_of_piece}
    # Not a piece you can't see
    assert client.post(f"/studies/{study_id}/notes",
                       data={"text": "x", "about": f"step:{on_hidden}"}).status_code == 400


def test_a_piece_in_a_study_offers_the_steps_it_inherited(world):
    owner = world.user("inherit-owner")
    client = world.client(owner)
    study_id = _study(client)
    parent = world.sample(owner)
    deposited, _ = world.step(parent, "deposited")
    piece = _cut(parent, "A")
    client.post(f"/studies/{study_id}/samples", data={"sample_ids": [piece.id]})
    page = client.get(f"/studies/{study_id}").text
    assert f'value="step:{deposited}"' in page
    client.post(f"/studies/{study_id}/notes", data={"text": "The film came from here", "about": f"step:{deposited}"})
    assert f'href="/samples/{parent.id}#step-{deposited}"' in client.get(f"/studies/{study_id}").text


def test_pieces_cut_with_the_cut_form_and_their_steps_are_offered(world):
    """The same as above, through the real Cut and Add step forms."""
    from sqlalchemy import select
    from backend.database import AsyncSessionLocal
    from backend.models import ProcessStep, ProcessStepType, Sample
    from tests.loop import run

    owner = world.user("realcut-owner")
    client = world.client(owner)
    study_id = _study(client)
    parent = world.sample(owner)
    client.post(f"/studies/{study_id}/samples", data={"sample_ids": [parent.id]})
    r = client.post(f"/samples/{parent.id}/cut", data={"piece_labels": ["left", "right"], "piece_dimensions": ["", ""]})
    assert r.status_code == 303, r.text

    async def pieces():
        async with AsyncSessionLocal() as db:
            cut = (await db.execute(select(ProcessStep.id).where(ProcessStep.sample_id == parent.id))).scalar_one()
            return (await db.execute(select(Sample).where(Sample.cut_step_id == cut).order_by(Sample.code))).scalars().all()

    async def annealing_id():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == "Annealing"))).scalar_one()

    left, right = run(pieces())
    assert client.post(f"/samples/{left.id}/steps/new", data={"type_id": run(annealing_id())}).status_code == 303

    async def step_on_left():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStep.id).where(ProcessStep.sample_id == left.id))).scalar_one()

    page = client.get(f"/studies/{study_id}").text
    assert f'value="sample:{left.id}"' in page and f'value="sample:{right.id}"' in page
    assert f'value="step:{run(step_on_left())}"' in page


def test_references_can_be_put_in_a_note_s_text(world, monkeypatch):
    owner = world.user("inline-owner")
    client = world.client(owner)
    study_id = _study(client)
    parent = world.sample(owner)
    piece = _cut(parent, "A")
    on_piece, _ = world.step(piece, "etched piece")
    client.post(f"/studies/{study_id}/samples", data={"sample_ids": [parent.id]})
    client.post(f"/studies/{study_id}/references", data={"link": "https://example.org/paper", "title": "A good paper"})

    # The picker offers the papers, the samples, their pieces and the pieces' steps, each with its link
    page = client.get(f"/studies/{study_id}").text
    picker = page[page.index("reference-picker"):page.index("note-text")]
    assert 'data-url="https://example.org/paper"' in picker and "A good paper" in picker
    assert f'data-url="/samples/{piece.id}"' in picker
    assert f'data-url="/samples/{piece.id}#step-{on_piece}"' in picker

    text = f"Etching [the piece](/samples/{piece.id}#step-{on_piece}) like [A good paper](https://example.org/paper) says **works**"
    client.post(f"/studies/{study_id}/notes", data={"text": text})
    page = client.get(f"/studies/{study_id}").text
    assert f'<a href="/samples/{piece.id}#step-{on_piece}">the piece</a>' in page
    assert "<strong>works</strong>" in page
    assert f'<a href="/samples/{piece.id}#step-{on_piece}">the piece</a>' in client.get(f"/studies/{study_id}/print").text
    note_id = re.search(r'id="note-(\d+)"', page).group(1)
    assert 'reference-picker' in client.get(f"/studies/{study_id}/notes/{note_id}/edit").text   # also when editing
