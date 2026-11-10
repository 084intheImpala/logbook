"""Procedures (/procedures): how someone does a technique, and the entries that followed one."""
import io
import json
import re

from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import AnalysisType, ProcessStep, ProcessStepType
from tests.loop import run
from tests.test_deposition_rate import _type_id


def _procedure(client, title="My 2θ/ω scan", technique="", text="1. Mount the sample\n2. Align on Si 004",
               visibility="team", **extra) -> int:
    data = {"title": title, "technique": technique, "text": text, "visibility": visibility,
            "summary": "For thin films on Si"} | extra
    r = client.post("/procedures/new", data=data)
    assert r.status_code == 303, r.text
    return int(re.search(r"/procedures/(\d+)", r.headers["location"]).group(1))


def _xrd() -> str:
    return f"analysis:{run(_type_id(AnalysisType, 'XRD / HRXRD'))}"


def _annealing_id() -> int:
    return run(_type_id(ProcessStepType, "Annealing"))


def test_a_procedure_is_written_in_markdown_for_a_technique(world):
    me = world.user("proc-maker")
    client = world.client(me)
    text = "1. Mount the sample\n2. Align on **Si 004**\n3. Scan 20–80°\n\n## Notes\n- Check the slits first"
    proc_id = _procedure(client, technique=_xrd(), text=text)
    page = client.get(f"/procedures/{proc_id}").text
    assert "My 2θ/ω scan" in page and "XRD / HRXRD" in page
    assert "<ol>" in page and "<li>Mount the sample</li>" in page and "<strong>Si 004</strong>" in page
    assert "<h2>Notes</h2>" in page and "<li>Check the slits first</li>" in page
    listed = client.get("/procedures/").text
    assert "My 2θ/ω scan" in listed and 'href="/procedures/"' in listed     # and the sidebar tab
    assert "<li>Mount the sample</li>" in client.get(f"/procedures/{proc_id}/print").text

    # Edited and retyped; no title is refused
    client.post(f"/procedures/{proc_id}/edit", data={"title": "My scan", "technique": "", "text": "Just scan.",
                                                      "visibility": "team"})
    page = client.get(f"/procedures/{proc_id}").text
    assert "My scan" in page and "<p>Just scan.</p>" in page and "XRD / HRXRD" not in page
    assert client.post("/procedures/new", data={"title": " "}).status_code == 400


def test_html_and_script_links_in_the_markdown_are_not_run(world):
    client = world.client(world.user("proc-xss"))
    proc_id = _procedure(client, text='<script>alert(1)</script>\n\n[click](javascript:alert(2)) <img src=x onerror=alert(3)>')
    page = client.get(f"/procedures/{proc_id}").text
    assert "<script>alert(1)" not in page and "&lt;script&gt;" in page
    assert 'href="javascript:' not in page and "<img src=x" not in page


def test_visibility_and_co_owners(world):
    owner, mate, stranger = world.user("pv-owner"), world.user("pv-mate"), world.user("pv-stranger")
    world.team("pv-team", members=[owner, mate])
    client = world.client(owner)
    personal = _procedure(client, "Secret recipe", visibility="personal")
    team = _procedure(client, "Team recipe")
    mate_c, stranger_c = world.client(mate), world.client(stranger)
    assert mate_c.get(f"/procedures/{personal}").status_code == 403
    assert mate_c.get(f"/procedures/{team}").status_code == 200
    assert stranger_c.get(f"/procedures/{team}").status_code == 403
    assert mate_c.post(f"/procedures/{team}/edit", data={"title": "mine"}).status_code == 403

    client.post(f"/procedures/{personal}/owners", data={"user_id": mate.id})
    assert mate_c.post(f"/procedures/{personal}/edit", data={"title": "Shared recipe", "visibility": "personal"}).status_code == 303
    assert "Shared recipe" in client.get(f"/procedures/{personal}").text
    assert "Shared recipe" in mate_c.get("/procedures/?mine=1").text and "Team recipe" not in mate_c.get("/procedures/?mine=1").text


def test_an_entry_records_the_procedure_it_followed(world):
    owner, other = world.user("pe-owner"), world.user("pe-other")
    client = world.client(owner)
    annealing = _procedure(client, "N2 anneal at 800 °C", technique=f"step:{_annealing_id()}")
    general = _procedure(client, "Glove box routine")
    xrd = _procedure(client, "Quick XRD", technique=_xrd())
    secret = _procedure(world.client(other), "Someone else's", technique=f"step:{_annealing_id()}", visibility="personal")
    sample = world.sample(owner)

    form = client.get(f"/samples/{sample.id}/steps/new").text
    assert "N2 anneal at 800 °C" in form and "Glove box routine" in form
    assert "Quick XRD" not in form and "Someone else&#39;s" not in form   # an analysis's; not visible

    r = client.post(f"/samples/{sample.id}/steps/new", data={"type_id": _annealing_id(), "procedure_id": annealing})
    assert r.status_code == 303
    page = client.get(f"/samples/{sample.id}").text
    assert f'href="/procedures/{annealing}"' in page and "N2 anneal at 800 °C" in page
    assert sample.code in client.get(f"/procedures/{annealing}").text      # "Followed in"
    assert "N2 anneal at 800 °C" in client.get(f"/samples/{sample.id}/print").text

    # A procedure you can't see isn't recorded
    client.post(f"/samples/{sample.id}/steps/new", data={"type_id": _annealing_id(), "procedure_id": secret})

    async def recorded():
        async with AsyncSessionLocal() as db:
            return [s.procedure_id for s in (await db.execute(select(ProcessStep).where(
                ProcessStep.sample_id == sample.id).order_by(ProcessStep.id))).scalars()]
    assert run(recorded()) == [annealing, None]

    # Someone who can't see it, editing the entry, keeps it
    step_id = re.search(r'id="step-(\d+)"', page).group(1)
    editor = world.user("pe-editor")
    sample_shared = world.sample(other, shared_edit=[editor])
    world.client(other).post(f"/samples/{sample_shared.id}/steps/new",
                             data={"type_id": _annealing_id(), "procedure_id": secret})
    shared_page = world.client(editor).get(f"/samples/{sample_shared.id}").text
    shared_step = re.search(r'id="step-(\d+)"', shared_page).group(1)
    assert "Someone else&#39;s" in world.client(editor).get(f"/samples/{sample_shared.id}/steps/{shared_step}/edit").text
    world.client(editor).post(f"/samples/{sample_shared.id}/steps/{shared_step}/edit",
                              data={"type_id": _annealing_id(), "procedure_id": secret, "notes": "edited"})

    async def kept():
        async with AsyncSessionLocal() as db:
            return (await db.get(ProcessStep, int(shared_step))).procedure_id
    assert run(kept()) == secret

    # Deleting the procedure keeps the entry, without it
    assert client.post(f"/procedures/{annealing}/delete").status_code == 303
    assert run(recorded()) == [None, None]
    assert f'id="step-{step_id}"' in client.get(f"/samples/{sample.id}").text
    assert general and xrd


def test_files_procedure_json_and_sample_json(world):
    owner, stranger = world.user("pj-owner"), world.user("pj-stranger")
    client = world.client(owner)
    proc_id = _procedure(client, "Cleaning", visibility="personal")
    r = client.post(f"/procedures/{proc_id}/edit",
                    data={"title": "Cleaning", "text": "1. Acetone\n2. IPA\n3. DI water", "visibility": "personal"},
                    files={"files": ("checklist.pdf", io.BytesIO(b"%PDF-1.4 x"), "application/pdf")})
    assert r.status_code == 303
    page = client.get(f"/procedures/{proc_id}").text
    file_id = int(re.search(r'href="/files/(\d+)"', page).group(1))
    assert client.get(f"/files/{file_id}").content == b"%PDF-1.4 x"
    assert world.client(stranger).get(f"/files/{file_id}").status_code == 403

    [folder] = list((settings.UPLOAD_DIR / "procedures").glob(f"{proc_id}-*"))
    data = json.loads((folder / "procedure.json").read_text())
    assert data["title"] == "Cleaning" and data["text"] == "1. Acetone\n2. IPA\n3. DI water"
    assert data["files"][0]["original_name"] == "checklist.pdf" and (folder / "checklist.pdf").is_file()

    sample = world.sample(owner)
    client.post(f"/samples/{sample.id}/steps/new", data={"type_id": _annealing_id(), "procedure_id": proc_id})
    entry = json.loads((settings.UPLOAD_DIR / sample.code / "sample.json").read_text())
    assert entry["format"] == 9 and entry["timeline"][0]["procedure"] == {"id": proc_id, "title": "Cleaning"}

    # Renamed: same folder, and the sample's file follows
    client.post(f"/procedures/{proc_id}/edit", data={"title": "Solvent clean", "visibility": "personal"})
    assert json.loads((folder / "procedure.json").read_text())["title"] == "Solvent clean"
    entry = json.loads((settings.UPLOAD_DIR / sample.code / "sample.json").read_text())
    assert entry["timeline"][0]["procedure"]["title"] == "Solvent clean"

    client.post(f"/procedures/{proc_id}/delete")
    assert not (folder / "procedure.json").exists()
    assert client.get(f"/files/{file_id}").status_code == 404


def test_the_printable_procedure_and_portuguese(world):
    me = world.user("pp-printer")
    client = world.client(me)
    proc_id = _procedure(client, "Spin coating", text="1. Clean the chuck\n2. Spin at 3000 rpm")
    html = client.get(f"/procedures/{proc_id}/print").text
    assert "Spin coating" in html and "Clean the chuck" in html and "Spin at 3000 rpm" in html
    assert "window.print()" in html and "<form" not in html
    assert f'href="/procedures/{proc_id}/print"' in client.get(f"/procedures/{proc_id}").text
    client.post("/lang", data={"lang": "pt"})
    assert "Procedimentos" in client.get("/procedures/").text
    assert "Procedimentos" in client.get(f"/procedures/{proc_id}").text
    form = client.get("/procedures/new").text
    assert 'id="markdown-tips"' in form and "Dicas de Markdown" in form and "uma tabela" in form
