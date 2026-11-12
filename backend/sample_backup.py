"""A copy of each sample's record, kept next to its files as a backup.

`uploads/<sample ID>/sample.json` holds everything the database knows about
one sample: its details, who owns it and who it's shared with, the substrate
and project, the studies it is in, its own timeline (parameters, notes, who did it, when, the
files) and, for a piece, which Cut step it came from. If the database is
lost, `uploads/` still says what every file is and what was done.

A piece's inherited entries aren't repeated: they're in its parent's file,
and `cut_from` says where to look.

Studies get the same: `uploads/studies/<id>-<title>/study.json`, next to
their notes' files, holds the study's details, co-owners, samples (by ID),
references and notes (text, what each is about, files). So do procedures:
`uploads/procedures/<id>-<title>/procedure.json`, next to their files.

Files are rewritten after any request that changed the database (see
`write_pending`) and for every sample and study at start-up (`write_all`),
so the database stays the source of truth and a missed write fixes itself.
"""
import json
import logging
import os
from datetime import date, datetime

from sqlalchemy import event, or_, select
from sqlalchemy.orm import Session, selectinload

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.lineage import _full_options
from backend.models import (Analysis, Attachment, Device, Procedure, ProcedureOwner, ProcessStep, Sample, SampleShare,
                            Study, StudyNote, StudyOwner, StudyReference, StudySample)
from backend.utils import _safe, procedure_folder, study_folder

log = logging.getLogger("uvicorn.error")

FILE_NAME = "sample.json"
FORMAT = 9   # 2: adds visibility, previous_codes, and status / proposed_by on entries; 3: devices; 4: sample_type "project" replaces "commercial" and "collaboration"; 5: planned on entries; 6: on_step_id / on_substrate / partial on steps; 7: a Deposition's base_pressure is in 10⁻⁶ Torr, not mTorr; 8: studies; 9: procedure on entries

STUDY_FILE_NAME = "study.json"
STUDY_FORMAT = 3   # 2: references have an id; a note can be about one; 3: status, and files on references
PROCEDURE_FILE_NAME = "procedure.json"
PROCEDURE_FORMAT = 1

# What changed since the last write: ("sample" | "step" | "analysis" | "study" |
# "study_note", id); ("study_title", id) for a study whose own details changed
# (they are in its samples' files too); ("procedure", id), and ("procedure_title",
# id) for a procedure whose title may be in the files of the samples that
# followed it; ("gone" | "study_gone" | "procedure_gone", folder) for a deleted
# sample / study / procedure. Filled as the database is changed.
_pending: set[tuple[str, int | str]] = set()


def folder_for(code: str | None, sample_id: int) -> str:
    """The sample's folder in uploads/ (the same one its files go in)."""
    return _safe(code or f"sample-{sample_id}")


@event.listens_for(Session, "after_flush")
def _note_changes(session, _context):
    for obj in (*session.new, *session.dirty):
        if isinstance(obj, Sample):
            _pending.add(("sample", obj.id))
        elif isinstance(obj, Study):   # its title is in its samples' files
            _pending.update({("study", obj.id), ("study_title", obj.id)})
        elif isinstance(obj, Procedure):
            _pending.update({("procedure", obj.id), ("procedure_title", obj.id)})
        else:
            _note_other(obj)
    for obj in session.deleted:
        if isinstance(obj, Sample):
            _pending.add(("gone", folder_for(obj.code, obj.id)))
        elif isinstance(obj, Study):
            _pending.add(("study_gone", study_folder(obj.id, obj.title)))
        elif isinstance(obj, Procedure):
            _pending.add(("procedure_gone", procedure_folder(obj.id, obj.title)))
        else:
            _note_other(obj)


def _note_other(obj):
    if isinstance(obj, StudySample):
        _pending.update({("sample", obj.sample_id), ("study", obj.study_id)})
    elif isinstance(obj, (ProcessStep, Analysis, SampleShare, Device)):
        _pending.add(("sample", obj.sample_id))
    elif isinstance(obj, (StudyOwner, StudyReference, StudyNote)):
        _pending.add(("study", obj.study_id))
    elif isinstance(obj, ProcedureOwner):
        _pending.add(("procedure", obj.procedure_id))
    elif isinstance(obj, Attachment) and obj.entity_type in ("sample", "step", "analysis", "study_note", "study_reference",
                                                                  "procedure"):
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
        "planned": entry.planned,   # planned, not done yet
        # The procedure followed (its own file: uploads/procedures/<id>-<title>/procedure.json)
        "procedure": {"id": entry.procedure.id, "title": entry.procedure.title} if entry.procedure else None,
        # A deposition's layer: on another deposition's (step id), on the substrate, covering only part
        **({"on_step_id": entry.on_step_id, "on_substrate": entry.on_substrate, "partial": entry.partial}
           if kind == "step" else {}),
        "created_at": entry.created_at,
        "files": [_attachment(a) for a in attachments.get((kind, entry.id), [])],
    }


def _document(sample: Sample, parent: tuple | None, attachments: dict, studies: list[dict] = ()) -> dict:
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
        "studies": list(studies),   # the studies it is in (their notes and references aren't copied here)
        "timeline": entries,
    }


def _json_default(value):
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    raise TypeError(f"Can't store {type(value).__name__}")


def _write(folder: str, document: dict, name: str = FILE_NAME) -> None:
    directory = settings.UPLOAD_DIR / folder
    directory.mkdir(parents=True, exist_ok=True)
    temp = directory / f".{name}.tmp"
    temp.write_text(json.dumps(document, indent=2, ensure_ascii=False, default=_json_default), encoding="utf-8")
    os.replace(temp, directory / name)   # a crash never leaves half a file


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

    studies: dict[int, list[dict]] = {}
    rows = await db.execute(select(StudySample.sample_id, Study.id, Study.title)
                            .join(Study, Study.id == StudySample.study_id)
                            .where(StudySample.sample_id.in_([sm.id for sm in samples])).order_by(Study.title))
    for sample_id, study_id, title in rows:
        studies.setdefault(sample_id, []).append({"id": study_id, "title": title})

    for sm in samples:
        _write(folder_for(sm.code, sm.id), _document(sm, cuts.get(sm.cut_step_id), attachments, studies.get(sm.id, [])))
    return len(samples)


def _study_document(study: Study, notes_files: dict[int, list[Attachment]], codes: dict[int, str],
                    reference_files: dict[int, list[Attachment]]) -> dict:
    def about(note: StudyNote) -> dict | None:
        if note.reference_id:   # by its id in `references`
            return {"kind": "reference", "id": note.reference_id}
        if not note.sample_id:
            return None
        kind, entry_id = (("step", note.step_id) if note.step_id else ("analysis", note.analysis_id)
                          if note.analysis_id else ("sample", None))
        # A step or analysis by its id in that sample's sample.json `timeline`
        # (the sample is one of the study's, a piece cut from one, or the
        # sample a piece inherited the step from)
        return {"sample": codes.get(note.sample_id), "sample_id": note.sample_id, "kind": kind, "id": entry_id}

    return {
        "format": STUDY_FORMAT,
        "written_at": datetime.now().replace(microsecond=0),
        "id": study.id, "title": study.title, "description": study.description, "visibility": study.visibility,
        "status": study.status,   # todo | ongoing | concluded
        "created_at": study.created_at, "created_by": _person(study.created_by),
        "owners": [_person(o.user) for o in study.owners],
        "samples": [{"id": l.sample.id, "code": l.sample.code, "label": l.sample.label, "added_at": l.created_at}
                    for l in study.sample_links if l.sample is not None],
        "references": [{"id": r.id, "doi": r.doi, "url": r.url, "title": r.title, "authors": r.authors, "journal": r.journal,
                        "year": r.year, "note": r.note, "added_by": _person(r.added_by), "created_at": r.created_at,
                        "files": [_attachment(a) for a in reference_files.get(r.id, [])]}
                       for r in study.references],
        "notes": [{"id": n.id, "position": n.position, "noted_on": n.noted_on, "title": n.title, "text": n.text,
                   "about": about(n), "author": _person(n.author), "created_at": n.created_at,
                   "files": [_attachment(a) for a in notes_files.get(n.id, [])]}
                  for n in sorted(study.notes, key=lambda n: (n.position is None, n.position or 0, n.id))],
    }


async def _write_studies(db, study_ids: list[int] | None) -> int:
    query = select(Study).options(selectinload(Study.references), selectinload(Study.notes))
    if study_ids is not None:
        if not study_ids:
            return 0
        query = query.where(Study.id.in_(study_ids))
    studies = list((await db.execute(query)).scalars())
    note_ids = [n.id for st in studies for n in st.notes]
    ref_ids = [r.id for st in studies for r in st.references]
    files: dict[int, list[Attachment]] = {}
    ref_files: dict[int, list[Attachment]] = {}
    for kind, ids, into in (("study_note", note_ids, files), ("study_reference", ref_ids, ref_files)):
        if ids:
            for att in (await db.execute(select(Attachment).where(
                    Attachment.entity_type == kind, Attachment.entity_id.in_(ids)).order_by(Attachment.id))).scalars():
                into.setdefault(att.entity_id, []).append(att)
    note_sample_ids = {n.sample_id for st in studies for n in st.notes if n.sample_id}
    codes = dict((await db.execute(select(Sample.id, Sample.code).where(Sample.id.in_(note_sample_ids)))).all()) \
        if note_sample_ids else {}
    for st in studies:
        _write(study_folder(st.id, st.title), _study_document(st, files, codes, ref_files), STUDY_FILE_NAME)
    return len(studies)


def _procedure_document(procedure: Procedure, files: list[Attachment]) -> dict:
    return {
        "format": PROCEDURE_FORMAT,
        "written_at": datetime.now().replace(microsecond=0),
        "id": procedure.id, "title": procedure.title,
        # The step or analysis type it is for (none: a general procedure)
        "technique": ({"kind": "step" if procedure.step_type_id else "analysis", "type": procedure.technique}
                      if procedure.technique else None),
        "summary": procedure.summary, "text": procedure.text,   # Markdown
        "visibility": procedure.visibility, "created_at": procedure.created_at, "updated_at": procedure.updated_at,
        "created_by": _person(procedure.created_by), "owners": [_person(o.user) for o in procedure.owners],
        "files": [_attachment(a) for a in files],
    }


async def _write_procedures(db, procedure_ids: list[int] | None) -> int:
    query = select(Procedure)
    if procedure_ids is not None:
        if not procedure_ids:
            return 0
        query = query.where(Procedure.id.in_(procedure_ids))
    procedures = list((await db.execute(query)).scalars())
    files: dict[int, list[Attachment]] = {}
    if procedures:
        for att in (await db.execute(select(Attachment).where(
                Attachment.entity_type == "procedure", Attachment.entity_id.in_([p.id for p in procedures]))
                .order_by(Attachment.id))).scalars():
            files.setdefault(att.entity_id, []).append(att)
    for p in procedures:
        _write(procedure_folder(p.id, p.title), _procedure_document(p, files.get(p.id, [])), PROCEDURE_FILE_NAME)
    return len(procedures)


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
            wanted = [i for k, i in changed if k == "study_title"]
            if wanted:
                ids |= set((await db.execute(select(StudySample.sample_id)
                                             .where(StudySample.study_id.in_(wanted)))).scalars())
            wanted = [i for k, i in changed if k == "procedure_title"]
            if wanted:
                for model in (ProcessStep, Analysis):
                    ids |= set((await db.execute(select(model.sample_id)
                                                 .where(model.procedure_id.in_(wanted)))).scalars())
            await _write_samples(db, sorted(ids))

            study_ids = {i for kind, i in changed if kind == "study"}
            for kind, model in (("study_note", StudyNote), ("study_reference", StudyReference)):
                wanted = [i for k, i in changed if k == kind]
                if wanted:
                    study_ids |= set((await db.execute(select(model.study_id)
                                                       .where(model.id.in_(wanted)))).scalars())
            if ids:   # a sample's ID or label is in its studies' files
                study_ids |= set((await db.execute(select(StudySample.study_id)
                                                   .where(StudySample.sample_id.in_(list(ids))))).scalars())
            await _write_studies(db, sorted(study_ids))
            await _write_procedures(db, sorted({i for kind, i in changed if kind == "procedure"}))

            for kind, folder in changed:
                if kind == "gone":
                    (settings.UPLOAD_DIR / folder / FILE_NAME).unlink(missing_ok=True)
                elif kind == "study_gone":
                    (settings.UPLOAD_DIR / folder / STUDY_FILE_NAME).unlink(missing_ok=True)
                elif kind == "procedure_gone":
                    (settings.UPLOAD_DIR / folder / PROCEDURE_FILE_NAME).unlink(missing_ok=True)
    except Exception:
        log.exception("Could not write sample backup files")
        _pending.update(changed)


async def write_all() -> tuple[int, int, int]:
    """Write the file of every sample, study and procedure. Returns how many of each there were."""
    async with AsyncSessionLocal() as db:
        return await _write_samples(db, None), await _write_studies(db, None), await _write_procedures(db, None)


if __name__ == "__main__":
    import asyncio
    samples, studies, procedures = asyncio.run(write_all())
    print(f"Wrote sample.json for {samples} samples, study.json for {studies} studies and "
          f"procedure.json for {procedures} procedures in {settings.UPLOAD_DIR}")
