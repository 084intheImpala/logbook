"""Procedures tab: how someone does a technique (in Markdown, with files),
which steps and analyses can say they followed. Permissions and the entry
form's choices are in backend/procedures.py."""
from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import can_view, can_view_shared, is_co_owner, require_login
from backend.config import settings
from backend.database import get_db
from backend.i18n import t
from backend.models import (VISIBILITY, Analysis, AnalysisType, Attachment, Procedure, ProcedureOwner, ProcessStep,
                            ProcessStepType, Sample, User)
from backend.procedures import FILES, apply_technique, load_procedure, techniques, visible_procedures
from backend.templating import templates
from backend.utils import chosen_files, delete_attachment, save_upload

router = APIRouter(prefix="/procedures", tags=["procedures"])


def _back(procedure: Procedure, anchor: str = "") -> RedirectResponse:
    return RedirectResponse(f"/procedures/{procedure.id}{anchor}", status_code=303)


def _is_image(attachment: Attachment) -> bool:
    return (attachment.mime_type or "").startswith("image/")


async def _attachments(db: AsyncSession, procedure_id: int) -> list[Attachment]:
    return list((await db.execute(select(Attachment).where(
        Attachment.entity_type == FILES, Attachment.entity_id == procedure_id)
        .order_by(Attachment.uploaded_at))).scalars())


async def _uses(db: AsyncSession, user: User, procedure_ids: list[int]) -> dict[int, list[dict]]:
    """The approved steps and analyses that followed each procedure, on
    samples `user` can see: id → [{sample, kind, id, type, date, planned}], newest first."""
    uses: dict[int, list[dict]] = {i: [] for i in procedure_ids}
    if not procedure_ids:
        return uses
    for kind, model, type_model, fk in (("step", ProcessStep, ProcessStepType, ProcessStep.step_type_id),
                                        ("analysis", Analysis, AnalysisType, Analysis.analysis_type_id)):
        rows = await db.execute(
            select(model.procedure_id, model.id, model.performed_at, model.planned, type_model.name, Sample)
            .join(type_model, type_model.id == fk).join(Sample, Sample.id == model.sample_id)
            .where(model.procedure_id.in_(procedure_ids), model.status == "approved"))
        for procedure_id, entry_id, day, planned, name, sample in rows.all():
            if can_view(user, sample):
                uses[procedure_id].append({"sample": sample, "kind": kind, "id": entry_id, "type": name,
                                           "date": day, "planned": planned})
    for found in uses.values():
        found.sort(key=lambda u: (u["date"] is not None, u["date"]), reverse=True)
    return uses


async def _save_files(db: AsyncSession, user: User, procedure: Procedure, form):
    photos, files = chosen_files(form.getlist("photos")), chosen_files(form.getlist("files"))
    for f in photos + files:
        if f.size is not None and f.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{f.filename} exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit")
    for f in photos:
        await save_upload(f, FILES, procedure.id, db, uploaded_by=user.username, photo=True)
    for f in files:
        await save_upload(f, FILES, procedure.id, db, uploaded_by=user.username)


# ── List, new, edit, delete ──────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def list_procedures(request: Request, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(require_login)):
    procedures = await visible_procedures(db, current_user)
    mine = request.query_params.get("mine") == "1"
    if mine:
        procedures = [p for p in procedures if any(o.user_id == current_user.id for o in p.owners)]
    uses = await _uses(db, current_user, [p.id for p in procedures])
    return templates.TemplateResponse("procedures/list.html", {
        "request": request, "current_user": current_user, "procedures": procedures, "mine": mine,
        "use_counts": {i: len(u) for i, u in uses.items()}, "visibilities": VISIBILITY,
        "flash": request.session.pop("flash", None),
    })


async def _form(request, db, current_user, procedure, error=None, status_code=200, technique=""):
    return templates.TemplateResponse("procedures/form.html", {
        "request": request, "current_user": current_user, "procedure": procedure, "error": error,
        "visibilities": VISIBILITY, "techniques": await techniques(db),
        "technique": procedure.technique_key if procedure is not None and procedure.id else technique,
        "attachments": await _attachments(db, procedure.id) if procedure is not None and procedure.id else [],
    }, status_code=status_code)


@router.get("/new", response_class=HTMLResponse)
async def new_procedure_form(request: Request, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(require_login)):
    # ?technique=step:3 starts it for that type (e.g. from the entry form)
    return await _form(request, db, current_user, None, technique=request.query_params.get("technique", ""))


@router.post("/new")
async def create_procedure(request: Request, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_login)):
    form = await request.form()
    visibility = form.get("visibility", "team")
    procedure = Procedure(title=form.get("title", "").strip(), summary=form.get("summary", "").strip() or None,
                          text=form.get("text", "").strip() or None,
                          visibility=visibility if visibility in VISIBILITY else "team", created_by_id=current_user.id)
    await apply_technique(db, procedure, form.get("technique", ""))
    if not procedure.title:
        return await _form(request, db, current_user, procedure, t(request, "The procedure needs a title."),
                           status_code=400, technique=form.get("technique", ""))
    procedure.owners = [ProcedureOwner(user_id=current_user.id)]
    db.add(procedure)
    await db.flush()
    await _save_files(db, current_user, procedure, form)
    await db.commit()
    return _back(procedure)


@router.get("/{procedure_id}/edit", response_class=HTMLResponse)
async def edit_procedure_form(request: Request, procedure_id: int, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(require_login)):
    return await _form(request, db, current_user, await load_procedure(db, procedure_id, current_user, "owner"))


@router.post("/{procedure_id}/edit")
async def update_procedure(request: Request, procedure_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_login)):
    procedure = await load_procedure(db, procedure_id, current_user, "owner")
    form = await request.form()
    title = form.get("title", "").strip()
    if not title:
        return await _form(request, db, current_user, procedure, t(request, "The procedure needs a title."),
                           status_code=400)
    procedure.title = title
    procedure.summary = form.get("summary", "").strip() or None
    procedure.text = form.get("text", "").strip() or None
    if form.get("visibility") in VISIBILITY:
        procedure.visibility = form.get("visibility")
    await apply_technique(db, procedure, form.get("technique", ""))
    await _save_files(db, current_user, procedure, form)
    await db.commit()
    return _back(procedure)


@router.post("/{procedure_id}/delete")
async def delete_procedure(request: Request, procedure_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_login)):
    procedure = await load_procedure(db, procedure_id, current_user, "owner")
    for attachment in await _attachments(db, procedure_id):
        await delete_attachment(attachment, db)
    # The entries that followed it keep everything else (the database does this too: ON DELETE SET NULL)
    for model in (ProcessStep, Analysis):
        await db.execute(update(model).where(model.procedure_id == procedure_id).values(procedure_id=None))
    title = procedure.title
    await db.delete(procedure)
    await db.commit()
    request.session["flash"] = t(request, "Procedure '{title}' deleted.", title=title)
    return RedirectResponse("/procedures/", status_code=303)


# ── The procedure's page ─────────────────────────────────────────────────────

async def _page(request: Request, db: AsyncSession, procedure_id: int, current_user: User) -> dict:
    """What the procedure's page shows (also its printable version)."""
    procedure = await load_procedure(db, procedure_id, current_user)
    attachments = await _attachments(db, procedure_id)
    taken = {o.user_id for o in procedure.owners}
    owner = is_co_owner(current_user, procedure)
    return {
        "request": request, "current_user": current_user, "procedure": procedure, "is_owner": owner,
        "photos": [a for a in attachments if _is_image(a)], "files": [a for a in attachments if not _is_image(a)],
        "uses": (await _uses(db, current_user, [procedure_id]))[procedure_id],
        "owner_candidates": [u for u in (await db.execute(
            select(User).order_by(User.name, User.username))).scalars() if u.id not in taken] if owner else [],
        "visibilities": VISIBILITY,
    }


@router.get("/{procedure_id}", response_class=HTMLResponse)
async def procedure_detail(request: Request, procedure_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_login)):
    return templates.TemplateResponse("procedures/detail.html", await _page(request, db, procedure_id, current_user) | {
        "flash": request.session.pop("flash", None),
        "flash_error": request.session.pop("flash_error", None),
    })


@router.get("/{procedure_id}/print", response_class=HTMLResponse)
async def procedure_print(request: Request, procedure_id: int, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(require_login)):
    """The procedure on a sheet, e.g. to keep next to the machine."""
    return templates.TemplateResponse("procedures/print.html", await _page(request, db, procedure_id, current_user) | {
        "printed_at": datetime.now().replace(microsecond=0),
        "page_url": str(request.url_for("procedure_detail", procedure_id=procedure_id)),
    })


# ── Co-owners ────────────────────────────────────────────────────────────────

@router.post("/{procedure_id}/owners")
async def add_owner(request: Request, procedure_id: int, db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(require_login)):
    procedure = await load_procedure(db, procedure_id, current_user, "owner")
    raw = (await request.form()).get("user_id", "")
    user = await db.get(User, int(raw)) if raw.isdigit() else None
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if all(o.user_id != user.id for o in procedure.owners):
        procedure.owners.append(ProcedureOwner(user_id=user.id))
        await db.commit()
    return _back(procedure, "#owners")


@router.post("/{procedure_id}/owners/{user_id}/delete")
async def remove_owner(request: Request, procedure_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    procedure = await load_procedure(db, procedure_id, current_user, "owner")
    owner = next((o for o in procedure.owners if o.user_id == user_id), None)
    if owner is not None:
        if len(procedure.owners) == 1:
            request.session["flash_error"] = t(request, "A procedure needs at least one co-owner.")
            return _back(procedure, "#owners")
        procedure.owners.remove(owner)
        await db.commit()
    if not can_view_shared(current_user, procedure):   # left it, and can't see it any more
        return RedirectResponse("/procedures/", status_code=303)
    return _back(procedure, "#owners")
