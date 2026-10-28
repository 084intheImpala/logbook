"""The add/edit form shared by process steps and analyses.

Parameters follow the chosen type's schema (backend/params.py); dropdown
values come from the shared lists (backend/choices.py). An entry can be added
to several samples, when it's created or later: the copies share a `run_id`,
and editing one can update the others. Files from the main fields of a new
entry are stored once and attached to every copy; each sample in the run also
has its own file field, for its own data.
"""
import uuid
from dataclasses import dataclass
from datetime import datetime

from fastapi import HTTPException, Request
from fastapi.responses import JSONResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import UploadFile

from backend import approvals
from backend.auth import can_edit, can_edit_entry, can_view
from backend.choices import DEFAULT_LOCATION, LOCATION_LIST, option_lists, option_locations, option_methods, remember
from backend.config import settings
from backend.i18n import t
from backend.lineage import CUT_TYPE_NAME, SPECIAL_STEP_TYPES
from backend.models import Analysis, AnalysisType, Attachment, ProcessStep, ProcessStepType, Sample, User
from backend.params import (describe, extra_params, located_lists, located_methods, params_to_text, parse_date, parse_form,
                            parse_params, scalar_fields, schema_keys, varied_params)
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


async def _run_candidates(db: AsyncSession, user, sample, run) -> list[tuple[Sample, str]]:
    """Samples the user could add the same entry to (they need edit access),
    leaving out those already in its run, as (sample, group): first the
    siblings (cut from the same step), then the same researcher's, newest
    first, then the rest."""
    taken = {sample.id} | {s.id for _, s in run}
    samples = (await db.execute(
        select(Sample).order_by(Sample.created_at.desc(), Sample.id.desc()))).scalars()

    def group(s):
        if sample.cut_step_id and s.cut_step_id == sample.cut_step_id:
            return "sibling"
        return "owner" if sample.owner_id and s.owner_id == sample.owner_id else "other"

    picked = [(s, group(s)) for s in samples if s.id not in taken and can_edit(user, s)]
    return sorted(picked, key=lambda p: ("sibling", "owner", "other").index(p[1]))   # stable: newest first


async def form_page(request: Request, db: AsyncSession, kind: Kind, sample, entry, user,
                    error: str | None = None, status_code: int = 200):
    types = (await db.execute(select(kind.type_model).order_by(kind.type_model.name))).scalars().all()
    current_type = next((ty for ty in types if entry and ty.id == getattr(entry, kind.type_field)), None)
    if kind is STEP:
        # Cuts are made with "Cut into pieces", which also creates the pieces. A
        # Cut stays a Cut when edited, and nothing else becomes one.
        # The same goes for Devices made.
        special = current_type.name if current_type is not None and current_type.name in SPECIAL_STEP_TYPES else None
        types = [ty for ty in types if (ty.name == special if special else ty.name not in SPECIAL_STEP_TYPES)]
    options = await option_lists(db)
    run = await run_entries(db, kind, entry) if entry else []
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
        # Whoever only performed this entry sees the sample's ID and label, not its description
        "can_view_sample": can_view(user, sample),
        "entry": entry,
        "types": types,
        "params": (entry.parameters or {}) if entry else {},
        "extra_text": params_to_text(extra_params(entry.parameters, current_type.parameter_schema
                                                  if current_type else None)) if entry else "",
        "options": options,
        "places": await option_locations(db),
        "methods": await option_methods(db),
        "location_list": LOCATION_LIST,
        # New entries default to where most work happens
        "location": entry.location if entry else DEFAULT_LOCATION if DEFAULT_LOCATION in options.get(LOCATION_LIST, []) else None,
        "users": await users_for_form(db),
        "attachments": attachments,
        "run": run,
        "devices": sample.devices if kind is ANALYSIS else [],
        # Single-value fields that can differ from sample to sample, per type
        "vary_fields": {ty.id: [{"key": f["key"], "label": t(request, f.get("label") or f["key"]),
                                 "unit": f.get("unit", ""), "options": options.get(f.get("list") or f["key"], [])
                                 if f.get("type") == "choice" else None}
                                for f in scalar_fields(ty.parameter_schema)] for ty in types},
        "run_candidates": await _run_candidates(db, user, sample, run),
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
    if kind is STEP:
        old_type = await db.get(ProcessStepType, entry.step_type_id) if entry else None
        if entry is None and entry_type.name == CUT_TYPE_NAME:
            return RedirectResponse(f"/samples/{sample.id}/cut", status_code=303)
        if entry is None and entry_type.name in SPECIAL_STEP_TYPES:
            return await form_page(request, db, kind, sample, entry, user,
                                   t(request, "Choose a type."), status_code=400)
        if old_type and (old_type.name in SPECIAL_STEP_TYPES or entry_type.name in SPECIAL_STEP_TYPES) \
                and old_type.name != entry_type.name:
            return await form_page(request, db, kind, sample, entry, user,
                                   t(request, "A Cut or a Devices made step can't be changed to another type, or another step to one of them."),
                                   status_code=400)

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
    device_id = form.get("device_id", "")
    device = next((d for d in sample.devices if str(d.id) == device_id), None) if kind is ANALYSIS else None
    performed_at = parse_date(form.get("performed_at", ""))
    performer, performed_by = form.get("performer", ""), form.get("performed_by", "")

    async def apply(target):
        for name, value in fields.items():
            setattr(target, name, value)
        # What this sample has different from the others (new copies only)
        if target.sample_id in new_sample_ids:
            own, own_picked = varied_params(form, entry_type.parameter_schema, target.sample_id)
            if own:
                target.parameters = (params | own)
                picked.extend(own_picked)
        if kind is ANALYSIS and target.sample_id == sample.id:   # copies on other samples have their own devices
            target.device_id = device.id if device else None
        newly = await apply_performer(db, target, performer, performed_by)
        if performed_at != target.performed_at or target.position is None:
            target.performed_at = performed_at
            if target.status == "pending":   # not on the timeline until approved
                return newly
            if performed_at or target.position is None:  # re-dated or new: slot it by date
                await db.flush()
                await place_new(db, target)
        return newly

    newly_told = {}   # performer id → (user, [samples])

    def tell(newly, on_sample):
        if newly:
            newly_told.setdefault(newly.id, (newly, []))[1].append(on_sample)

    # Other samples ticked to get a copy too (for a new entry, or to extend a run)
    others = [int(i) for i in form.getlist("run_samples") if i.isdigit() and int(i) != sample.id]
    extra_samples = [s for s in (await db.execute(select(Sample).where(Sample.id.in_(others)))).scalars()
                     if can_edit(user, s)] if others else []

    is_new = entry is None
    proposing = is_new and not can_edit(user, sample)   # a teammate's entry waits for the owner
    if proposing:
        extra_samples = []
    # Samples getting a new copy now (they may have their own values)
    new_sample_ids = {s.id for s in extra_samples} | ({sample.id} if is_new else set())
    if is_new:
        entry = kind.model(sample_id=sample.id)
        if proposing:
            entry.status, entry.proposed_by_id, entry.proposed_at = "pending", user.id, datetime.utcnow()
        db.add(entry)
        tell(await apply(entry), sample)   # fills it in, then flushes and slots it into the timeline
        members = [(entry, sample)]
    else:
        tell(await apply(entry), sample)
        members = [(entry, sample)] + [(o, s) for o, s in await run_entries(db, kind, entry)
                                       if can_edit_entry(user, s, o)]
        if form.get("apply_to_run"):
            for other, other_sample in members[1:]:
                tell(await apply(other), other_sample)
    if extra_samples:
        entry.run_id = entry.run_id or uuid.uuid4().hex
        for target_sample in extra_samples:
            copy = kind.model(sample_id=target_sample.id, run_id=entry.run_id)
            db.add(copy)
            tell(await apply(copy), target_sample)
            members.append((copy, target_sample))

    # Photos/files from the main fields: on a new entry they go to every copy
    # (stored once); when editing, to this sample's entry only.
    shared_to = [e for e, _ in members] if is_new else [entry]
    for upload_name, photo in (("photos", True), ("files", False)):
        for f in _uploads(form, upload_name):
            att = await save_upload(f, kind.name, shared_to[0].id, db, uploaded_by=user.username, photo=photo)
            for other in shared_to[1:]:
                copy_attachment(att, kind.name, other.id, db)
    # Files for one sample only (the field next to each sample of the run)
    for member, member_sample in members:
        for f in _uploads(form, f"files_for_{member_sample.id}"):
            await save_upload(f, kind.name, member.id, db, uploaded_by=user.username)

    await remember(db, picked, user.id, location, located_lists(entry_type.parameter_schema),
                   located_methods(entry_type.parameter_schema, params))
    await db.commit()
    if proposing:
        await approvals.tell_owner_of_proposal(request, sample, user, entry_type.name)
    else:
        for performer_user, samples in newly_told.values():
            await tell_performer(request, performer_user, user, samples, entry_type.name)
    anchor = "pending" if entry.status == "pending" else f"{kind.name}-{entry.id}"
    return RedirectResponse(f"/samples/{sample.id}#{anchor}", status_code=303)


# ── Warning before overwriting the other samples of a run ────────────────────

def _comparable(request: Request, type_name: str, schema, params, notes, location, performer, performed_at) -> dict:
    """An entry's values as {translated label: text}, for comparing copies."""
    values = {t(request, "Type"): type_name}
    for row in describe(params, schema):
        if "rows" in row:   # a mode, e.g. XRD's rocking curve
            prefix = f"{t(request, row['group'])}: {row['label']}" if row["group"] else row["label"]
            values |= {f"{prefix} / {t(request, sub['label'])}": sub["value"] for sub in row["rows"]}
        else:
            values[t(request, row["label"])] = row["value"]
    values |= {t(request, "Notes"): notes or "", t(request, "Where"): location or "",
               t(request, "Performed by"): performer or "",
               t(request, "Date"): performed_at.isoformat() if performed_at else ""}
    return values


async def overwrite_check(request: Request, db: AsyncSession, kind: Kind, sample, entry, user) -> JSONResponse:
    """What saving this form with "apply to the others" ticked would overwrite:
    values the other copies have that differ from the form's. Filling in
    their empty fields isn't an overwrite. Nothing is saved."""
    form = await request.form()
    type_id = form.get("type_id", "")
    entry_type = await db.get(kind.type_model, int(type_id)) if type_id.isdigit() else None
    if entry_type is None:
        return JSONResponse({"conflicts": []})
    params, _ = parse_form(form, entry_type.parameter_schema)
    params = parse_params(form.get("params_extra", "")) | params
    performer = form.get("performer", "")
    performer_user = await db.get(User, int(performer)) if performer.isdigit() else None
    performer_name = (performer_user.display_name if performer_user
                      else form.get("performed_by", "").strip() if performer == "other" else "")
    new = _comparable(request, entry_type.name, entry_type.parameter_schema, params,
                      form.get("notes", "").strip(), form.get("location", "").strip(), performer_name,
                      parse_date(form.get("performed_at", "")))
    conflicts = []
    for other, other_sample in await run_entries(db, kind, entry):
        if not can_edit_entry(user, other_sample, other):
            continue
        other_type = await db.get(kind.type_model, getattr(other, kind.type_field))
        old = _comparable(request, other_type.name, other_type.parameter_schema, other.parameters, other.notes,
                          other.location, other.performer_name, other.performed_at)
        for label, value in old.items():
            if value and new.get(label, "") != value:
                conflicts.append({"sample": other_sample.title, "field": label, "old": value,
                                  "new": new.get(label) or "—"})
    return JSONResponse({"conflicts": conflicts})
