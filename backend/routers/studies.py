"""Studies tab: a study spanning several samples, with references (papers by
DOI, or links) and dated notes. Permissions are in backend/studies.py."""
from datetime import date, datetime

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import doi as doi_lookup
from backend.auth import can_view, require_login
from backend.config import settings
from backend.database import get_db
from backend.i18n import t
from backend.models import (VISIBILITY, Attachment, ProcessStep, Sample, Study, StudyNote, StudyOwner, StudyReference, StudySample, User)
from backend.lineage import Family, load_samples_full_by_id, own_items
from backend.params import parse_date
from backend.studies import (can_view_study, is_study_owner, load_study, move_note, ordered_notes, place_note,
                             visible_studies)
from backend.templating import templates
from backend.utils import chosen_files, delete_attachment, save_upload

router = APIRouter(prefix="/studies", tags=["studies"])

NOTE_FILES = "study_note"   # Attachment.entity_type of a note's files


def _back(study: Study, anchor: str = "") -> RedirectResponse:
    return RedirectResponse(f"/studies/{study.id}{anchor}", status_code=303)


def _is_image(attachment: Attachment) -> bool:
    return (attachment.mime_type or "").startswith("image/")


async def _note(db: AsyncSession, study: Study, note_id: int) -> StudyNote:
    note = await db.get(StudyNote, note_id)
    if note is None or note.study_id != study.id:
        raise HTTPException(status_code=404, detail="Note not found")
    return note


async def _family(db: AsyncSession, samples: list[Sample]) -> tuple[Family, dict[int, list[Sample]]]:
    """The samples with their timelines loaded, the samples they were cut from
    (whose earlier entries they inherit), and every piece cut from them (and
    pieces of pieces): an index over them all, and each sample's pieces."""
    loaded = {s.id: s for s in await load_samples_full_by_id(db, [s.id for s in samples])}
    frontier = list(loaded.values())
    while frontier:     # up: the samples they were cut from
        cut_ids = [s.cut_step_id for s in frontier if s.cut_step_id]
        parent_ids = set((await db.execute(select(ProcessStep.sample_id).where(ProcessStep.id.in_(cut_ids))))
                         .scalars()) - loaded.keys() if cut_ids else set()
        frontier = await load_samples_full_by_id(db, parent_ids)
        loaded |= {s.id: s for s in frontier}
    pieces: dict[int, list[Sample]] = {}
    frontier = [loaded[s.id] for s in samples]
    while frontier:     # down: the pieces cut from them
        cut_owner = {st.id: s.id for s in frontier for st in s.process_steps}
        piece_ids = (await db.execute(select(Sample.id).where(Sample.cut_step_id.in_(list(cut_owner)))))\
            .scalars().all() if cut_owner else []
        found = await load_samples_full_by_id(db, piece_ids)
        frontier = []
        for piece in found:
            pieces.setdefault(cut_owner[piece.cut_step_id], []).append(piece)
            if piece.id not in loaded:
                loaded[piece.id] = piece
                frontier.append(piece)
    return Family(loaded.values()), pieces


async def _entries(request: Request, db: AsyncSession, user: User, samples: list[Sample]) -> dict[str, dict]:
    """What a note can be about: each of the study's samples (as
    "sample:<id>") with its whole timeline (what it inherited from the sample
    it was cut from, then its own steps and analyses, as "step:<id>" /
    "analysis:<id>"), and under it every piece cut from it that `user` can
    see (pieces of pieces too) with the pieces' own entries.
    Each key → {"label", "sample_id" (where the entry is recorded), "depth",
    "url" (the sample's page, at the entry)}."""
    choices: dict[str, dict] = {}
    if not samples:
        return choices
    family, pieces = await _family(db, samples)

    def add(key: str, label: str, sample_id: int, depth: int):
        kind, _, entry_id = key.partition(":")
        url = f"/samples/{sample_id}" + (f"#{kind}-{entry_id}" if kind != "sample" else "")
        choices.setdefault(key, {"label": label, "sample_id": sample_id, "depth": depth, "url": url})

    def walk(sample: Sample, depth: int, parent: Sample | None = None):
        if can_view(user, sample):
            add(f"sample:{sample.id}", f"{sample.title} ({t(request, 'piece of')} {parent.title})" if parent
                else sample.title, sample.id, depth)
            # A piece listed under its parent only adds its own entries: the
            # ones it inherited are its parent's, listed just above
            items = own_items(sample, planned=True) if parent else family.timeline(sample, planned=True)
            for item in items:
                e = item.entry
                add(f"{'step' if item.kind == 'process' else 'analysis'}:{e.id}", " · ".join(p for p in (
                    item.source.title, item.technique, e.performed_at.isoformat() if e.performed_at else "",
                    t(request, "(planned)") if e.planned else "") if p), item.source.id, depth + 1)
        for piece in sorted(pieces.get(sample.id, []), key=lambda s: s.title):
            walk(piece, depth + 1, sample)

    for s in sorted(samples, key=lambda s: s.title):
        walk(family.samples[s.id], 0)
    return choices


async def _references(db: AsyncSession, study_id: int) -> list[StudyReference]:
    return list((await db.execute(select(StudyReference).where(StudyReference.study_id == study_id)
                                  .order_by(StudyReference.id))).scalars())


def _about_key(note: StudyNote) -> str | None:
    if note.step_id:
        return f"step:{note.step_id}"
    if note.analysis_id:
        return f"analysis:{note.analysis_id}"
    return f"sample:{note.sample_id}" if note.sample_id else None


def _visible_samples(user: User, study: Study) -> list[Sample]:
    return [l.sample for l in study.sample_links if can_view(user, l.sample)]


async def _set_about(request: Request, db: AsyncSession, user: User, study: Study, note: StudyNote, about: str):
    """Point the note at one of the choices _entries offers `user` (a sample
    of the study or a piece cut from one, or a step or analysis of them); an
    empty `about` points it at nothing."""
    note.sample_id = note.step_id = note.analysis_id = None
    if not about:
        return
    kind, _, raw = about.partition(":")
    if kind not in ("sample", "step", "analysis") or not raw.isdigit():
        raise HTTPException(status_code=400, detail="Invalid entry")
    choice = (await _entries(request, db, user, _visible_samples(user, study))).get(about)
    if choice is None:
        raise HTTPException(status_code=400, detail="That isn't in one of this study's samples you can see.")
    note.sample_id = choice["sample_id"]
    if kind == "step":
        note.step_id = int(raw)
    elif kind == "analysis":
        note.analysis_id = int(raw)


async def _sample_by_code(db: AsyncSession, code: str) -> Sample | None:
    code = code.strip()
    if not code:
        return None
    return (await db.execute(select(Sample).where(func.upper(Sample.code) == code.upper()))).scalar_one_or_none()


async def _addable_samples(db: AsyncSession, user: User, study: Study) -> list[Sample]:
    """Samples `user` can see that aren't in the study yet (suggested when adding one)."""
    taken = {l.sample_id for l in study.sample_links}
    samples = (await db.execute(select(Sample).where(Sample.code.is_not(None)).order_by(Sample.code))).scalars()
    return [s for s in samples if s.id not in taken and can_view(user, s)]


# ── List, new, edit, delete ──────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def list_studies(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    studies = await visible_studies(db, current_user)
    return templates.TemplateResponse("studies/list.html", {
        "request": request, "current_user": current_user, "studies": studies,
        "sample_counts": {s.id: sum(can_view(current_user, l.sample) for l in s.sample_links) for s in studies},
        "note_counts": dict((await db.execute(
            select(StudyNote.study_id, func.count()).group_by(StudyNote.study_id))).all()),
        "visibilities": VISIBILITY,
        "flash": request.session.pop("flash", None),
    })


def _form(request, current_user, study, error=None, status_code=200):
    return templates.TemplateResponse("studies/form.html", {
        "request": request, "current_user": current_user, "study": study, "error": error,
        "visibilities": VISIBILITY,
    }, status_code=status_code)


@router.get("/new", response_class=HTMLResponse)
async def new_study_form(request: Request, current_user: User = Depends(require_login)):
    return _form(request, current_user, None)


@router.post("/new")
async def create_study(request: Request, title: str = Form(...), description: str = Form(""),
                       visibility: str = Form("team"), db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    study = Study(title=title.strip(), description=description.strip() or None, created_by_id=current_user.id,
                  visibility=visibility if visibility in VISIBILITY else "team")
    if not study.title:
        return _form(request, current_user, study, t(request, "The study needs a title."), status_code=400)
    study.owners = [StudyOwner(user_id=current_user.id)]
    db.add(study)
    await db.commit()
    return _back(study)


@router.get("/{study_id}/edit", response_class=HTMLResponse)
async def edit_study_form(request: Request, study_id: int, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(require_login)):
    return _form(request, current_user, await load_study(db, study_id, current_user, "owner"))


@router.post("/{study_id}/edit")
async def update_study(request: Request, study_id: int, title: str = Form(...), description: str = Form(""),
                       visibility: str = Form("team"), db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    if not title.strip():
        return _form(request, current_user, study, t(request, "The study needs a title."), status_code=400)
    study.title, study.description = title.strip(), description.strip() or None
    if visibility in VISIBILITY:
        study.visibility = visibility
    await db.commit()
    return _back(study)


@router.post("/{study_id}/delete")
async def delete_study(request: Request, study_id: int, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    note_ids = (await db.execute(select(StudyNote.id).where(StudyNote.study_id == study_id))).scalars().all()
    if note_ids:
        for attachment in (await db.execute(select(Attachment).where(
                Attachment.entity_type == NOTE_FILES, Attachment.entity_id.in_(note_ids)))).scalars().all():
            await delete_attachment(attachment, db)
    title = study.title
    await db.delete(study)
    await db.commit()
    request.session["flash"] = t(request, "Study '{title}' deleted.", title=title)
    return RedirectResponse("/studies/", status_code=303)


# ── The study's page ─────────────────────────────────────────────────────────

async def _page(request: Request, db: AsyncSession, study_id: int, current_user: User) -> dict:
    """What the study's page shows (also its printable version)."""
    study = await load_study(db, study_id, current_user)
    owner = is_study_owner(current_user, study)
    samples = _visible_samples(current_user, study)
    entries = await _entries(request, db, current_user, samples)
    notes = await ordered_notes(db, study_id)
    attachments: dict[int, list[Attachment]] = {n.id: [] for n in notes}
    if notes:
        for a in (await db.execute(select(Attachment).where(
                Attachment.entity_type == NOTE_FILES, Attachment.entity_id.in_(list(attachments)))
                .order_by(Attachment.uploaded_at))).scalars():
            attachments[a.entity_id].append(a)
    note_rows = []
    for i, n in enumerate(notes):
        key = _about_key(n)
        note_rows.append({
            "note": n, "first": i == 0, "last": i == len(notes) - 1,
            "about": entries[key]["label"] if key in entries else None,
            "about_url": entries[key]["url"] if key in entries else None,
            "photos": [a for a in attachments[n.id] if _is_image(a)],
            "files": [a for a in attachments[n.id] if not _is_image(a)],
        })
    taken = {o.user_id for o in study.owners}
    return {
        "request": request, "current_user": current_user, "study": study, "is_owner": owner,
        "samples": samples, "hidden_samples": len(study.sample_links) - len(samples),
        "addable": await _addable_samples(db, current_user, study) if owner else [],
        "references": await _references(db, study_id),
        "notes": note_rows, "entries": entries, "today": date.today(),
        "owner_candidates": [u for u in (await db.execute(
            select(User).order_by(User.name, User.username))).scalars() if u.id not in taken] if owner else [],
        "visibilities": VISIBILITY,
    }


@router.get("/{study_id}", response_class=HTMLResponse)
async def study_detail(request: Request, study_id: int, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    return templates.TemplateResponse("studies/detail.html", await _page(request, db, study_id, current_user) | {
        "flash": request.session.pop("flash", None),
        "flash_error": request.session.pop("flash_error", None),
    })


@router.get("/{study_id}/print", response_class=HTMLResponse)
async def study_print(request: Request, study_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(require_login)):
    """The study laid out for printing (or saving as a PDF from the browser):
    its samples, references and notes, photos as small previews, files by name."""
    page = await _page(request, db, study_id, current_user)
    return templates.TemplateResponse("studies/print.html", page | {
        "printed_at": datetime.now().replace(microsecond=0),
        "page_url": str(request.url_for("study_detail", study_id=study_id)),
    })


# ── Co-owners ────────────────────────────────────────────────────────────────

@router.post("/{study_id}/owners")
async def add_owner(study_id: int, user_id: int = Form(...), db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    if await db.get(User, user_id) is None:
        raise HTTPException(status_code=404, detail="User not found")
    if all(o.user_id != user_id for o in study.owners):
        study.owners.append(StudyOwner(user_id=user_id))
        await db.commit()
    return _back(study, "#owners")


@router.post("/{study_id}/owners/{user_id}/delete")
async def remove_owner(request: Request, study_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    owner = next((o for o in study.owners if o.user_id == user_id), None)
    if owner is not None:
        if len(study.owners) == 1:
            request.session["flash_error"] = t(request, "A study needs at least one co-owner.")
            return _back(study, "#owners")
        study.owners.remove(owner)
        await db.commit()
    if user_id == current_user.id and not current_user.is_admin:
        return RedirectResponse("/studies/" if not can_view_study(current_user, study) else f"/studies/{study.id}",
                                status_code=303)
    return _back(study, "#owners")


# ── Samples ──────────────────────────────────────────────────────────────────

async def _add(request: Request, db: AsyncSession, user: User, study: Study, sample: Sample | None, code: str = ""):
    if sample is None or not can_view(user, sample):
        request.session["flash_error"] = t(request, "No sample {code} that you can see.", code=code.strip() or "?")
    elif any(l.sample_id == sample.id for l in study.sample_links):
        request.session["flash_error"] = t(request, "{code} is already in this study.", code=sample.title)
    else:
        study.sample_links.append(StudySample(sample_id=sample.id, added_by_id=user.id))
        await db.commit()
        request.session["flash"] = t(request, "{code} added to the study '{title}'.", code=sample.title, title=study.title)


@router.post("/{study_id}/samples")
async def add_samples(request: Request, study_id: int, sample_ids: list[int] = Form([]), code: str = Form(""),
                      db: AsyncSession = Depends(get_db), current_user: User = Depends(require_login)):
    """Add the samples ticked in the study page's list (or one typed by its
    ID), skipping any the user can't see or that are already in."""
    study = await load_study(db, study_id, current_user, "owner")
    if code.strip() and not sample_ids:
        await _add(request, db, current_user, study, await _sample_by_code(db, code), code)
        return _back(study, "#samples")
    taken = {l.sample_id for l in study.sample_links}
    added = []
    for sample_id in dict.fromkeys(sample_ids):
        sample = await db.get(Sample, sample_id)
        if sample is not None and sample.id not in taken and can_view(current_user, sample):
            study.sample_links.append(StudySample(sample_id=sample.id, added_by_id=current_user.id))
            taken.add(sample.id)
            added.append(sample.title)
    if added:
        await db.commit()
        request.session["flash"] = t(request, "Added to the study: {codes}.", codes=", ".join(added))
    else:
        request.session["flash_error"] = t(request, "Tick the samples to add first.")
    return _back(study, "#samples")


@router.post("/add-sample")
async def add_from_sample_page(request: Request, study_id: int = Form(...), sample_id: int = Form(...),
                               db: AsyncSession = Depends(get_db), current_user: User = Depends(require_login)):
    """"Add to a study…" on a sample's page."""
    study = await load_study(db, study_id, current_user, "owner")
    await _add(request, db, current_user, study, await db.get(Sample, sample_id))
    return RedirectResponse(f"/samples/{sample_id}#studies", status_code=303)


@router.post("/{study_id}/samples/{sample_id}/delete")
async def remove_sample(study_id: int, sample_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    link = next((l for l in study.sample_links if l.sample_id == sample_id), None)
    if link is not None:
        study.sample_links.remove(link)
        await db.commit()
    return _back(study, "#samples")


# ── References ───────────────────────────────────────────────────────────────

@router.post("/{study_id}/references")
async def add_reference(request: Request, study_id: int, link: str = Form(...), title: str = Form(""),
                        note: str = Form(""), db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_login)):
    """Anyone who can see the study may add a paper (DOI) or link to it."""
    study = await load_study(db, study_id, current_user)
    doi, url = doi_lookup.parse(link)
    if not doi and not url:
        request.session["flash_error"] = t(request, "Give a DOI or a link.")
        return _back(study, "#references")
    ref = StudyReference(study_id=study.id, doi=doi, url=url, title=title.strip() or None,
                         note=note.strip() or None, added_by_id=current_user.id)
    if doi:
        paper = await doi_lookup.lookup(doi)
        if paper is not None:
            ref.title = ref.title or paper.title
            ref.authors, ref.journal, ref.year = paper.authors, paper.journal, paper.year
        elif not ref.title:
            request.session["flash_error"] = t(
                request, "Couldn't look up {doi}; the reference was added without its title.", doi=doi)
    db.add(ref)
    await db.commit()
    return _back(study, f"#reference-{ref.id}")


@router.post("/{study_id}/references/{reference_id}/delete")
async def delete_reference(study_id: int, reference_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user)
    ref = await db.get(StudyReference, reference_id)
    if ref is None or ref.study_id != study.id:
        raise HTTPException(status_code=404, detail="Reference not found")
    if not (is_study_owner(current_user, study) or ref.added_by_id == current_user.id):
        raise HTTPException(status_code=403, detail="Only the co-owners, or whoever added it, can remove it.")
    await db.delete(ref)
    await db.commit()
    return _back(study, "#references")


# ── Notes ────────────────────────────────────────────────────────────────────

async def _save_files(db, current_user, note: StudyNote, photos, files):
    photos, files = chosen_files(photos), chosen_files(files)
    for f in photos + files:
        if f.size is not None and f.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{f.filename} exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit")
    for f in photos:
        await save_upload(f, NOTE_FILES, note.id, db, uploaded_by=current_user.username, photo=True)
    for f in files:
        await save_upload(f, NOTE_FILES, note.id, db, uploaded_by=current_user.username)


@router.post("/{study_id}/notes")
async def add_note(request: Request, study_id: int, noted_on: str = Form(""), title: str = Form(""),
                   text: str = Form(""), about: str = Form(""),
                   photos: list[UploadFile | str] = File([]), files: list[UploadFile | str] = File([]),
                   db: AsyncSession = Depends(get_db), current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    note = StudyNote(study_id=study.id, noted_on=parse_date(noted_on), title=title.strip() or None,
                     text=text.strip() or None, author_id=current_user.id)
    if not (note.title or note.text or chosen_files(photos) or chosen_files(files)):
        request.session["flash_error"] = t(request, "The note is empty.")
        return _back(study, "#notes")
    await _set_about(request, db, current_user, study, note, about)
    db.add(note)
    await db.flush()
    await place_note(db, note)
    await _save_files(db, current_user, note, photos, files)
    await db.commit()
    return _back(study, f"#note-{note.id}")


@router.get("/{study_id}/notes/{note_id}/edit", response_class=HTMLResponse)
async def edit_note_form(request: Request, study_id: int, note_id: int, db: AsyncSession = Depends(get_db),
                         current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    note = await _note(db, study, note_id)
    attachments = (await db.execute(select(Attachment).where(
        Attachment.entity_type == NOTE_FILES, Attachment.entity_id == note.id))).scalars().all()
    return templates.TemplateResponse("studies/note_form.html", {
        "request": request, "current_user": current_user, "study": study, "note": note,
        "entries": await _entries(request, db, current_user, _visible_samples(current_user, study)),
        "about": _about_key(note), "attachments": attachments, "references": await _references(db, study_id),
    })


@router.post("/{study_id}/notes/{note_id}/edit")
async def update_note(request: Request, study_id: int, note_id: int, noted_on: str = Form(""), title: str = Form(""),
                      text: str = Form(""), about: str = Form(""),
                      photos: list[UploadFile | str] = File([]), files: list[UploadFile | str] = File([]),
                      db: AsyncSession = Depends(get_db), current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    note = await _note(db, study, note_id)
    day = parse_date(noted_on)
    redate = day != note.noted_on
    note.noted_on, note.title, note.text = day, title.strip() or None, text.strip() or None
    await _set_about(request, db, current_user, study, note, about)
    if redate:
        await place_note(db, note)
    await _save_files(db, current_user, note, photos, files)
    await db.commit()
    return _back(study, f"#note-{note.id}")


@router.post("/{study_id}/notes/{note_id}/move")
async def move(study_id: int, note_id: int, direction: str = Form(...), db: AsyncSession = Depends(get_db),
               current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    await move_note(db, await _note(db, study, note_id), direction)
    await db.commit()
    return _back(study, f"#note-{note_id}")


@router.post("/{study_id}/notes/{note_id}/delete")
async def delete_note(study_id: int, note_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(require_login)):
    study = await load_study(db, study_id, current_user, "owner")
    note = await _note(db, study, note_id)
    for attachment in (await db.execute(select(Attachment).where(
            Attachment.entity_type == NOTE_FILES, Attachment.entity_id == note.id))).scalars().all():
        await delete_attachment(attachment, db)
    await db.delete(note)
    await db.commit()
    return _back(study, "#notes")
