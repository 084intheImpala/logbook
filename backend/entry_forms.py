"""The add/edit form shared by process steps and analyses.

Parameters follow the chosen type's schema (backend/params.py); dropdown
values come from the shared lists (backend/choices.py). An entry can be added
to several samples at once: the copies share a `run_id`, and editing one can
update the others. Files uploaded with a run are stored once and attached to
every copy.
"""
import uuid
from dataclasses import dataclass

from fastapi import HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from backend.auth import can_edit, can_edit_entry
from backend.choices import DEFAULT_LOCATION, LOCATION_LIST, option_lists, option_locations, remember
from backend.config import settings
from backend.i18n import t
from backend.models import Analysis, AnalysisType, Attachment, ProcessStep, ProcessStepType, Sample
from backend.params import (extra_params, located_lists, params_to_text, parse_date, parse_form, parse_params,
                            schema_keys)
from backend.performers import apply_performer, tell_performer, users_for_form
from backend.templating import templates
from backend.timeline import place_new
from backend.utils import copy_attachment, save_upload


@dataclass(frozen=True)
class Kind:
    name: str             # "step" | "analysis" (also the attachments' entity_type)
    model: type
    type_model: type
    type_field: str       # e.g. "step_type_id"
    type_rel: str         # e.g. "step_type"
    path: str             # URL segment: "steps" | "analyses"


STEP = Kind("step", ProcessStep, ProcessStepType, "step_type_id", "step_type", "steps")
ANALYSIS = Kind("analysis", Analysis, AnalysisType, "analysis_type_id", "analysis_type", "analyses")


async def get_entry(db: AsyncSession, kind: Kind, sample_id: int, entry_id: int):
    entry = (await db.execute(
        select(kind.model).where(kind.model.id == entry_id, kind.model.sample_id == sample_id)
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    return entry


async def run_entries(db: AsyncSession, kind: Kind, entry) -> list[tuple]:
    """The other entries of the same run, with their samples: [(entry, sample)]."""
    if not entry.run_id:
        return []
    rows = await db.execute(
        select(kind.model, Sample).join(Sample, Sample.id == kind.model.sample_id)
        .where(kind.model.run_id == entry.run_id, kind.model.id != entry.id).order_by(Sample.code))
    return list(rows.all())


async def _run_candidates(db: AsyncSession, user, sample) -> list[Sample]:
    """Samples the user could add the same entry to (they need edit access)."""
    samples = (await db.execute(select(Sample).where(Sample.id != sample.id).order_by(Sample.code.desc()))).scalars()
    return [s for s in samples if can_edit(user, s)]


async def form_page(request: Request, db: AsyncSession, kind: Kind, sample, entry, user,
                    error: str | None = None, status_code: int = 200):
    types = (await db.execute(select(kind.type_model).order_by(kind.type_model.name))).scalars().all()
    current_type = next((ty for ty in types if entry and ty.id == getattr(entry, kind.type_field)), None)
    options = await option_lists(db)
    attachments = []
    if entry:
        attachments = (await db.execute(
            select(Attachment).where(Attachment.entity_type == kind.name, Attachment.entity_id == entry.id)
            .order_by(Attachment.uploaded_at))).scalars().all()
    return templates.TemplateResponse("entries/form.html", {
        "request": request,
        "current_user": user,
        "kind": kind.name,
        "path": kind.path,
        "sample": sample,
        "entry": entry,
        "types": types,
        "params": (entry.parameters or {}) if entry else {},
        "extra_text": params_to_text(extra_params(entry.parameters, current_type.parameter_schema
                                                  if current_type else None)) if entry else "",
        "options": options,
        "places": await option_locations(db),
        "location_list": LOCATION_LIST,
        # New entries default to where most work happens
        "location": entry.location if entry else DEFAULT_LOCATION if DEFAULT_LOCATION in options.get(LOCATION_LIST, []) else None,
        "users": await users_for_form(db),
        "attachments": attachments,
        "run": await run_entries(db, kind, entry) if entry else [],
        "run_candidates": await _run_candidates(db, user, sample) if not entry else [],
        "photo_max_px": settings.PHOTO_MAX_PX,
        "error": error,
    }, status_code=status_code)


def _uploads(form, name: str) -> list[UploadFile]:
    return [f for f in form.getlist(name) if isinstance(f, UploadFile) and f.filename]


async def save(request: Request, db: AsyncSession, kind: Kind, sample, entry, user):
    """Create (entry=None) or update an entry from the submitted form."""
    form = await request.form()
    type_id = form.get("type_id", "")
    entry_type = await db.get(kind.type_model, int(type_id)) if type_id.isdigit() else None
    if entry_type is None:
        return await form_page(request, db, kind, sample, entry, user,
                               t(request, "Choose a type."), status_code=400)

    params, picked = parse_form(form, entry_type.parameter_schema)
    params = parse_params(form.get("params_extra", "")) | params
    if entry:  # keep nested values the form doesn't show (e.g. from an older schema)
        known = schema_keys(entry_type.parameter_schema)
        params |= {k: v for k, v in (entry.parameters or {}).items() if isinstance(v, dict) and k not in known}
    location = form.get("location", "").strip() or None
    if location:
        picked.append((LOCATION_LIST, location))
    fields = {
        kind.type_field: entry_type.id,
        "parameters": params or None,
        "notes": form.get("notes", "").strip() or None,
        "location": location,
    }
    performed_at = parse_date(form.get("performed_at", ""))
    performer, performed_by = form.get("performer", ""), form.get("performed_by", "")

    async def apply(target):
        for name, value in fields.items():
            setattr(target, name, value)
        newly = await apply_performer(db, target, performer, performed_by)
        if performed_at != target.performed_at or target.position is None:
            target.performed_at = performed_at
            if performed_at or target.position is None:  # re-dated or new: slot it by date
                await db.flush()
                await place_new(db, target)
        return newly

    newly_told = {}   # performer id → (user, [samples])
    if entry is None:
        # Add to this sample and any others picked for the same run
        others = [int(i) for i in form.getlist("run_samples") if i.isdigit() and int(i) != sample.id]
        targets = [sample] + [s for s in (await db.execute(select(Sample).where(Sample.id.in_(others)))).scalars()
                              if can_edit(user, s)] if others else [sample]
        run_id = uuid.uuid4().hex if len(targets) > 1 else None
        created = []
        for target_sample in targets:
            new = kind.model(sample_id=target_sample.id, run_id=run_id)
            db.add(new)
            newly = await apply(new)   # fills it in, then flushes and slots it into the timeline
            if newly:
                newly_told.setdefault(newly.id, (newly, []))[1].append(target_sample)
            created.append(new)
        attach_to = created
        entry = created[0]
    else:
        newly = await apply(entry)
        if newly:
            newly_told.setdefault(newly.id, (newly, []))[1].append(sample)
        if form.get("apply_to_run"):
            for other, other_sample in await run_entries(db, kind, entry):
                if can_edit_entry(user, other_sample, other):
                    newly = await apply(other)
                    if newly:
                        newly_told.setdefault(newly.id, (newly, []))[1].append(other_sample)
        attach_to = [entry]

    for upload_name, photo in (("photos", True), ("files", False)):
        for f in _uploads(form, upload_name):
            att = await save_upload(f, kind.name, attach_to[0].id, db, uploaded_by=user.username, photo=photo)
            for other in attach_to[1:]:
                copy_attachment(att, kind.name, other.id, db)

    await remember(db, picked, user.id, location, located_lists(entry_type.parameter_schema))
    await db.commit()
    for performer_user, samples in newly_told.values():
        await tell_performer(request, performer_user, user, samples, entry_type.name)
    return RedirectResponse(f"/samples/{sample.id}#{kind.name}-{entry.id}", status_code=303)
