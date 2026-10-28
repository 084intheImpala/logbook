"""A copy of each sample's record, kept next to its files as a backup.

`uploads/<sample ID>/sample.json` holds everything the database knows about
one sample: its details, who owns it and who it's shared with, the substrate
and project, its own timeline (parameters, notes, who did it, when, the
files) and, for a piece, which Cut step it came from. If the database is
lost, `uploads/` still says what every file is and what was done.

A piece's inherited entries aren't repeated: they're in its parent's file,
and `cut_from` says where to look.

Files are rewritten after any request that changed the database (see
`write_pending`) and for every sample at start-up (`write_all`), so the
database stays the source of truth and a missed write fixes itself.
"""
import json
import logging
import os
from datetime import date, datetime

from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.lineage import _full_options
from backend.models import Analysis, Attachment, Device, ProcessStep, Sample, SampleShare
from backend.utils import _safe

log = logging.getLogger("uvicorn.error")

FILE_NAME = "sample.json"
FORMAT = 3   # 2: adds visibility, previous_codes, and status / proposed_by on entries; 3: devices

# What changed since the last write: ("sample" | "step" | "analysis", id), or
# ("gone", folder) for a deleted sample. Filled as the database is changed.
_pending: set[tuple[str, int | str]] = set()


def folder_for(code: str | None, sample_id: int) -> str:
    """The sample's folder in uploads/ (the same one its files go in)."""
    return _safe(code or f"sample-{sample_id}")


@event.listens_for(Session, "after_flush")
def _note_changes(session, _context):
    for obj in (*session.new, *session.dirty):
        if isinstance(obj, Sample):
            _pending.add(("sample", obj.id))
        elif isinstance(obj, (ProcessStep, Analysis, SampleShare, Device)):
            _pending.add(("sample", obj.sample_id))
        elif isinstance(obj, Attachment) and obj.entity_type in ("sample", "step", "analysis"):
            _pending.add((obj.entity_type, obj.entity_id))
    for obj in session.deleted:
        if isinstance(obj, Sample):
            _pending.add(("gone", folder_for(obj.code, obj.id)))
        elif isinstance(obj, (ProcessStep, Analysis, SampleShare, Device)):
            _pending.add(("sample", obj.sample_id))
        elif isinstance(obj, Attachment) and obj.entity_type in ("sample", "step", "analysis"):
            _pending.add((obj.entity_type, obj.entity_id))


def _person(user) -> dict | None:
    return {"username": user.username, "name": user.name, "initials": user.initials} if user else None


def _attachment(att: Attachment) -> dict:
    return {
        "file": att.stored_filename, "original_name": att.original_filename, "size": att.file_size,
        "mime_type": att.mime_type, "uploaded_by": att.uploaded_by, "uploaded_at": att.uploaded_at,
    }


def _entry(kind: str, entry, type_name: str, attachments: dict) -> dict:
    return {
        **({"device": entry.device.label if entry.device else None} if kind == "analysis" else {}),
        "id": entry.id, "kind": kind, "type": type_name, "position": entry.position,
        "performed_at": entry.performed_at, "location": entry.location,
        "performed_by": _person(entry.performer) or ({"name": entry.performed_by} if entry.performed_by else None),
        "parameters": entry.parameters, "notes": entry.notes, "run_id": entry.run_id,
        # "pending" entries were proposed by a teammate and aren't approved yet
        "status": entry.status, "proposed_by": _person(entry.proposer),
        "created_at": entry.created_at,
        "files": [_attachment(a) for a in attachments.get((kind, entry.id), [])],
    }


def _document(sample: Sample, parent: tuple | None, attachments: dict) -> dict:
    entries = [_entry("step", s, s.step_type.name, attachments) for s in sample.process_steps]
    entries += [_entry("analysis", a, a.analysis_type.name, attachments) for a in sample.analyses]
    entries.sort(key=lambda e: (e["position"] is None, e["position"] or 0, e["id"]))
    sub, project = sample.substrate, sample.project
    return {
        "format": FORMAT,
        "written_at": datetime.now().replace(microsecond=0),
        "id": sample.id, "code": sample.code, "previous_codes": sample.previous_codes, "label": sample.label, "sample_type": sample.sample_type,
        "is_reference": sample.is_reference, "visibility": sample.visibility, "tags": sample.tags, "description": sample.description,
        "film_material": sample.film_material, "substrate_dimensions": sample.substrate_dimensions,
        "external_id": sample.external_id, "supplier": sample.supplier, "created_at": sample.created_at,
        "owner": _person(sample.owner), "requested_by": _person(sample.requested_by),
        "shared_with": [{**_person(sh.user), "can_edit": sh.can_edit} for sh in sample.shares],
        "substrate": None if sub is None else {
            "name": sub.name, "material": sub.material, "orientation": sub.orientation,
            "thickness_um": sub.thickness_um, "polishing": sub.polishing, "size": sub.size,
            "supplier": sub.supplier, "batch_no": sub.batch_no, "notes": sub.notes},
        "project": None if project is None else {
            "name": project.name, "code": project.code, "institution": project.institution,
            "country": project.country, "contact_name": project.contact_name,
            "contact_email": project.contact_email, "notes": project.notes},
        # Pieces inherit the parent's timeline up to this step (kept in the parent's file)
        "cut_from": None if parent is None else {
            "sample": parent[0], "cut_step_id": sample.cut_step_id, "cut_position": parent[1]},
        "files": [_attachment(a) for a in attachments.get(("sample", sample.id), [])],
        "devices": [{"label": d.label, "notes": d.notes} for d in sample.devices],
        "timeline": entries,
    }


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Can't store {type(value).__name__}")


def _write(folder: str, document: dict) -> None:
    directory = settings.UPLOAD_DIR / folder
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f".{FILE_NAME}.tmp"
    temp.write_text(json.dumps(document, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    os.replace(temp, directory / FILE_NAME)   # a crash never leaves half a file


async def _write_samples(db, sample_ids: list[int] | None) -> int:
    query = select(Sample).options(*_full_options())
    if sample_ids is not None:
        query = query.where(Sample.id.in_(sample_ids))
    samples = list((await db.execute(query)).scalars())
    if not samples:
        return 0

    own_steps = {s.id: s.id for sm in samples for s in sm.process_steps}
    own_analyses = {a.id: a.id for sm in samples for a in sm.analyses}
    conditions = [(Attachment.entity_type == "sample") & Attachment.entity_id.in_([sm.id for sm in samples])]
    if own_steps:
        conditions.append((Attachment.entity_type == "step") & Attachment.entity_id.in_(list(own_steps)))
    if own_analyses:
        conditions.append((Attachment.entity_type == "analysis") & Attachment.entity_id.in_(list(own_analyses)))
    attachments: dict[tuple[str, int], list[Attachment]] = {}
    for att in (await db.execute(select(Attachment).where(or_(*conditions)).order_by(Attachment.id))).scalars():
        attachments.setdefault((att.entity_type, att.entity_id), []).append(att)

    cut_ids = {sm.cut_step_id for sm in samples if sm.cut_step_id}
    cuts = {}
    if cut_ids:
        rows = await db.execute(select(ProcessStep.id, Sample.id, Sample.code, ProcessStep.position)
                                .join(Sample, Sample.id == ProcessStep.sample_id).where(ProcessStep.id.in_(cut_ids)))
        cuts = {step_id: (code or f"sample-{sid}", position)
                for step_id, sid, code, position in rows}

    for sm in samples:
        _write(folder_for(sm.code, sm.id), _document(sm, cuts.get(sm.cut_step_id), attachments))
    return len(samples)


async def write_pending() -> None:
    """Rewrite the files of the samples changed since the last call. Never
    raises: a failed backup mustn't fail the request that was saved."""
    if not _pending:
        return
    changed = set(_pending)
    _pending.difference_update(changed)
    try:
        async with AsyncSessionLocal() as db:
            ids = {i for kind, i in changed if kind == "sample"}
            for kind, model in (("step", ProcessStep), ("analysis", Analysis)):
                wanted = [i for k, i in changed if k == kind]
                if wanted:
                    ids |= set((await db.execute(select(model.sample_id).where(model.id.in_(wanted)))).scalars())
            await _write_samples(db, sorted(ids))
            for kind, folder in changed:
                if kind == "gone":
                    (settings.UPLOAD_DIR / folder / FILE_NAME).unlink(missing_ok=True)
    except Exception:
        log.exception("Could not write sample backup files")
        _pending.update(changed)


async def write_all() -> int:
    """Write the file of every sample. Returns how many there were."""
    async with AsyncSessionLocal() as db:
        return await _write_samples(db, None)


if __name__ == "__main__":
    import asyncio
    print(f"Wrote sample.json for {asyncio.run(write_all())} samples in {settings.UPLOAD_DIR}")
