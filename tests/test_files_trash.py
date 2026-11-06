"""Files stored once however often they're uploaded; deleted files wait in the trash."""
import os
from datetime import date, timedelta

from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.dedupe_files import _print, dedupe
from backend.models import Attachment
from backend.trash import empty_old, trash_dir
from tests.loop import run

TODAY = date.today().isoformat()


def attachments(**where):
    async def go():
        async with AsyncSessionLocal() as db:
            query = select(Attachment).order_by(Attachment.id)
            for key, value in where.items():
                query = query.where(getattr(Attachment, key) == value)
            return (await db.execute(query)).scalars().all()
    return run(go())


def upload(client, sample, kind, entry_id, name, content):
    r = client.post(f"/files/upload/{sample.id}", data={"entity_type": kind, "entity_id": str(entry_id)},
                    files={"files": (name, content, "application/octet-stream")})
    assert r.status_code == 303, r.text[:300]


def stored(name):
    return settings.UPLOAD_DIR / name


def test_same_file_on_two_entries_is_stored_once(world):
    owner = world.user("dup-two")
    a, b = world.sample(owner), world.sample(owner)
    step_a, _ = world.step(a, "first")
    step_b, _ = world.step(b, "second")
    client = world.client(owner)
    upload(client, a, "step", step_a, "scan.raw", b"same bytes dup-two")
    upload(client, b, "step", step_b, "renamed.raw", b"same bytes dup-two")
    first, = attachments(entity_type="step", entity_id=step_a)
    second, = attachments(entity_type="step", entity_id=step_b)
    assert first.sha256 and first.sha256 == second.sha256
    assert second.stored_filename == first.stored_filename
    assert second.original_filename == "renamed.raw"
    assert not list(stored(first.stored_filename).parent.parent.glob(f"{b.code}*/**/renamed.raw"))


def test_same_file_twice_on_one_entry_is_attached_once(world):
    owner = world.user("dup-one")
    sample = world.sample(owner)
    step, _ = world.step(sample, "once")
    client = world.client(owner)
    upload(client, sample, "step", step, "x.raw", b"dup-one")
    upload(client, sample, "step", step, "x.raw", b"dup-one")
    assert len(attachments(entity_type="step", entity_id=step)) == 1


def test_different_content_is_stored_separately(world):
    owner = world.user("dup-diff")
    sample = world.sample(owner)
    step, _ = world.step(sample, "diff")
    client = world.client(owner)
    upload(client, sample, "step", step, "x.raw", b"dup-diff 1")
    upload(client, sample, "step", step, "x.raw", b"dup-diff 2")
    one, two = attachments(entity_type="step", entity_id=step)
    assert one.stored_filename != two.stored_filename


def test_deleted_file_goes_to_the_trash(world):
    owner = world.user("trash-del")
    sample = world.sample(owner)
    step, _ = world.step(sample, "del")
    client = world.client(owner)
    upload(client, sample, "step", step, "gone.raw", b"trash-del")
    att, = attachments(entity_type="step", entity_id=step)
    assert client.post(f"/files/{att.id}/delete").status_code == 303
    assert not stored(att.stored_filename).exists()
    assert (trash_dir() / TODAY / att.stored_filename).read_bytes() == b"trash-del"


def test_shared_file_stays_until_its_last_attachment_goes(world):
    owner = world.user("trash-shared")
    a, b = world.sample(owner), world.sample(owner)
    step_a, _ = world.step(a, "a")
    step_b, _ = world.step(b, "b")
    client = world.client(owner)
    upload(client, a, "step", step_a, "s.raw", b"trash-shared")
    upload(client, b, "step", step_b, "s.raw", b"trash-shared")
    first, = attachments(entity_type="step", entity_id=step_a)
    second, = attachments(entity_type="step", entity_id=step_b)
    client.post(f"/files/{first.id}/delete")
    assert stored(first.stored_filename).exists()
    client.post(f"/files/{second.id}/delete")
    assert not stored(first.stored_filename).exists()
    assert (trash_dir() / TODAY / first.stored_filename).exists()


def test_deleting_an_entry_or_sample_trashes_its_files(world):
    owner = world.user("trash-entry")
    sample = world.sample(owner)
    step, _ = world.step(sample, "s")
    analysis, _ = world.step(sample, "a", analysis=True)
    client = world.client(owner)
    upload(client, sample, "step", step, "s.raw", b"trash-entry step")
    upload(client, sample, "analysis", analysis, "a.raw", b"trash-entry analysis")
    upload(client, sample, "sample", sample.id, "spec.pdf", b"trash-entry sample")
    names = [a.stored_filename for a in attachments(entity_type="step", entity_id=step)
             + attachments(entity_type="analysis", entity_id=analysis)
             + attachments(entity_type="sample", entity_id=sample.id)]
    assert len(names) == 3

    assert client.post(f"/samples/{sample.id}/steps/{step}/delete").status_code == 303
    assert not attachments(entity_type="step", entity_id=step)
    assert (trash_dir() / TODAY / names[0]).exists() and not stored(names[0]).exists()

    assert client.post(f"/samples/{sample.id}/delete").status_code == 303
    assert not attachments(entity_type="analysis", entity_id=analysis)
    for name in names[1:]:
        assert (trash_dir() / TODAY / name).exists() and not stored(name).exists()


def test_old_trash_is_emptied():
    today = date.today()
    for day in (today - timedelta(days=31), today - timedelta(days=30)):
        (trash_dir() / day.isoformat()).mkdir(parents=True, exist_ok=True)
    (trash_dir() / "notes").mkdir(exist_ok=True)
    assert empty_old(today) == 1
    assert not (trash_dir() / (today - timedelta(days=31)).isoformat()).exists()
    assert (trash_dir() / (today - timedelta(days=30)).isoformat()).exists()
    assert (trash_dir() / "notes").exists()


def _old_attachment(sample_code, entity_type, entity_id, name, content):
    """An attachment stored the way it was before hashes: its own file, no sha256."""
    async def go():
        folder = settings.UPLOAD_DIR / sample_code / "old"
        folder.mkdir(parents=True, exist_ok=True)
        (folder / name).write_bytes(content)
        async with AsyncSessionLocal() as db:
            att = Attachment(entity_type=entity_type, entity_id=entity_id, stored_filename=f"{sample_code}/old/{name}",
                             original_filename=name, file_size=len(content))
            db.add(att)
            await db.commit()
            return att.id, att.stored_filename
    return run(go())


def test_dedupe_merges_old_duplicates(world, capsys):
    owner = world.user("dedupe")
    a, b = world.sample(owner), world.sample(owner)
    step_a, _ = world.step(a, "a")
    step_b, _ = world.step(b, "b")
    kept_id, kept = _old_attachment(a.code, "step", step_a, "one.raw", b"dedupe same")
    copy_id, copy = _old_attachment(b.code, "step", step_b, "two.raw", b"dedupe same")
    twice_id, twice = _old_attachment(b.code, "step", step_b, "three.raw", b"dedupe same")
    orphan_id, orphan = _old_attachment(b.code, "step", 999999, "left.raw", b"dedupe orphan")

    report = run(dedupe(apply=False))
    _print(report, done=False)   # the command's output works on what the report holds
    assert copy in report.merged[kept] and twice in report.merged[kept]
    assert orphan_id in [x.id for x in report.orphans] and twice_id in [x.id for x in report.repeated]
    assert stored(copy).exists() and attachments(id=copy_id)[0].stored_filename == copy   # dry run: no change

    assert "Would merge 2 duplicate file(s) into 1" in capsys.readouterr().out
    run(dedupe(apply=True))
    assert attachments(id=copy_id)[0].stored_filename == kept
    assert attachments(id=kept_id)[0].sha256 == attachments(id=copy_id)[0].sha256
    assert not attachments(id=twice_id) and not attachments(id=orphan_id)
    assert stored(kept).exists()
    for name in (copy, twice, orphan):
        assert not stored(name).exists() and (trash_dir() / TODAY / name).exists()
    assert os.path.exists(settings.UPLOAD_DIR / b.code / "sample.json")
