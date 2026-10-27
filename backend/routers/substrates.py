"""Substrate library: shared specs that thin-film and bulk samples refer to."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Substrate, Sample, Attachment, User, POLISHING
from backend.auth import require_login
from backend.i18n import t
from backend.utils import save_upload, delete_attachment, chosen_files

router = APIRouter(prefix="/substrates", tags=["substrates"])
from backend.templating import templates


def can_edit_substrate(user: User, substrate: Substrate) -> bool:
    """Anyone can add substrates; whoever added one, and admins, can change it."""
    return user.is_admin or substrate.created_by_id == user.id


async def _usage(db: AsyncSession) -> dict[int, int]:
    rows = await db.execute(
        select(Sample.substrate_id, func.count()).where(Sample.substrate_id.is_not(None)).group_by(Sample.substrate_id))
    return dict(rows.all())


async def _attachments(db: AsyncSession, substrate_id: int) -> list[Attachment]:
    return (await db.execute(
        select(Attachment)
        .where(Attachment.entity_type == "substrate", Attachment.entity_id == substrate_id)
        .order_by(Attachment.uploaded_at)
    )).scalars().all()


async def _get(db: AsyncSession, substrate_id: int) -> Substrate:
    substrate = await db.get(Substrate, substrate_id)
    if not substrate:
        raise HTTPException(status_code=404, detail="Substrate not found")
    return substrate


def _parse_float(text: str) -> float | None:
    try:
        return float(text.replace(",", ".")) if text.strip() else None
    except ValueError:
        return None


def _apply_form(substrate: Substrate, name, material, orientation, thickness_um, polishing, size, supplier, batch_no, notes):
    substrate.name = name.strip()
    substrate.material = material.strip()
    substrate.orientation = orientation.strip() or None
    substrate.thickness_um = _parse_float(thickness_um)
    substrate.polishing = polishing if polishing in POLISHING else None
    substrate.size = size.strip() or None
    substrate.supplier = supplier.strip() or None
    substrate.batch_no = batch_no.strip() or None
    substrate.notes = notes.strip() or None


@router.get("/", response_class=HTMLResponse)
async def list_substrates(request: Request, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(require_login)):
    substrates = (await db.execute(select(Substrate).order_by(Substrate.material, Substrate.name))).scalars().all()
    file_counts = dict((await db.execute(
        select(Attachment.entity_id, func.count()).where(Attachment.entity_type == "substrate")
        .group_by(Attachment.entity_id))).all())
    return templates.TemplateResponse("substrates/list.html", {
        "request": request,
        "current_user": current_user,
        "substrates": substrates,
        "usage": await _usage(db),
        "file_counts": file_counts,
        "polishing": POLISHING,
        "can_edit": lambda s: can_edit_substrate(current_user, s),
        "flash": request.session.pop("flash", None),
        "flash_error": request.session.pop("flash_error", None),
    })


@router.get("/new", response_class=HTMLResponse)
async def new_substrate_form(request: Request, current_user: User = Depends(require_login)):
    return templates.TemplateResponse("substrates/form.html", {
        "request": request, "current_user": current_user, "substrate": None,
        "attachments": [], "polishing": POLISHING, "can_edit": True,
    })


@router.post("/new")
async def create_substrate(
    request: Request,
    name: str = Form(...),
    material: str = Form(...),
    orientation: str = Form(""),
    thickness_um: str = Form(""),
    polishing: str = Form(""),
    size: str = Form(""),
    supplier: str = Form(""),
    batch_no: str = Form(""),
    notes: str = Form(""),
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    substrate = Substrate(created_by_id=current_user.id)
    _apply_form(substrate, name, material, orientation, thickness_um, polishing, size, supplier, batch_no, notes)
    db.add(substrate)
    await db.flush()
    files = chosen_files(files)
    for f in files:
        await save_upload(f, "substrate", substrate.id, db, uploaded_by=current_user.username)
    await db.commit()
    request.session["flash"] = t(request, "Substrate '{name}' added.", name=substrate.name)
    return RedirectResponse("/substrates/", status_code=303)


@router.get("/{substrate_id}", response_class=HTMLResponse)
async def substrate_detail(request: Request, substrate_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_login)):
    substrate = await _get(db, substrate_id)
    samples = (await db.execute(
        select(Sample).where(Sample.substrate_id == substrate_id).order_by(Sample.code))).scalars().all()
    return templates.TemplateResponse("substrates/form.html", {
        "request": request, "current_user": current_user, "substrate": substrate,
        "attachments": await _attachments(db, substrate_id), "polishing": POLISHING,
        "can_edit": can_edit_substrate(current_user, substrate), "samples": samples,
    })


@router.post("/{substrate_id}")
async def update_substrate(
    request: Request,
    substrate_id: int,
    name: str = Form(...),
    material: str = Form(...),
    orientation: str = Form(""),
    thickness_um: str = Form(""),
    polishing: str = Form(""),
    size: str = Form(""),
    supplier: str = Form(""),
    batch_no: str = Form(""),
    notes: str = Form(""),
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    substrate = await _get(db, substrate_id)
    if not can_edit_substrate(current_user, substrate):
        raise HTTPException(status_code=403, detail="Only the person who added this substrate, or an admin, can edit it.")
    _apply_form(substrate, name, material, orientation, thickness_um, polishing, size, supplier, batch_no, notes)
    files = chosen_files(files)
    for f in files:
        await save_upload(f, "substrate", substrate.id, db, uploaded_by=current_user.username)
    await db.commit()
    request.session["flash"] = t(request, "Substrate '{name}' saved.", name=substrate.name)
    return RedirectResponse("/substrates/", status_code=303)


@router.post("/{substrate_id}/delete")
async def delete_substrate(request: Request, substrate_id: int, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_login)):
    substrate = await _get(db, substrate_id)
    if not can_edit_substrate(current_user, substrate):
        raise HTTPException(status_code=403, detail="Only the person who added this substrate, or an admin, can delete it.")
    used = (await _usage(db)).get(substrate_id, 0)
    if used:
        request.session["flash_error"] = (
            t(request, "Can't delete '{name}': 1 sample uses it.", name=substrate.name) if used == 1 else
            t(request, "Can't delete '{name}': {n} samples use it.", name=substrate.name, n=used))
        return RedirectResponse("/substrates/", status_code=303)
    for att in await _attachments(db, substrate_id):
        await delete_attachment(att, db)
    await db.delete(substrate)
    await db.commit()
    request.session["flash"] = t(request, "Substrate '{name}' deleted.", name=substrate.name)
    return RedirectResponse("/substrates/", status_code=303)
