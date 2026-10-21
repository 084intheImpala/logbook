from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models import Sample, ProcessStep, ProcessStepType, Attachment
from backend.params import parse_params, params_to_text, type_schemas_json, parse_datetime
from backend.timeline import place_new, renumber
from backend.config import settings
from backend.utils import save_upload, chosen_files
from backend.auth import require_login, load_sample

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/{sample_id}/steps/new", response_class=HTMLResponse)
async def new_step_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    step_types = (await db.execute(select(ProcessStepType).order_by(ProcessStepType.name))).scalars().all()
    return templates.TemplateResponse("steps/form.html", {
        "request": request,
        "sample": sample,
        "step_types": step_types,
        "step": None,
        "params_text": "",
        "type_schemas_json": type_schemas_json(step_types),
        "attachments": [],
        "photo_max_px": settings.PHOTO_MAX_PX,
        "current_user": current_user,
    })


@router.post("/{sample_id}/steps/new")
async def create_step(
    sample_id: int,
    step_type_id: int = Form(...),
    params_text: str = Form(""),
    notes: str = Form(""),
    performed_by: str = Form(""),
    performed_at: str = Form(""),
    photos: list[UploadFile | str] = File([]),
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    await load_sample(db, sample_id, current_user, "edit")

    step = ProcessStep(
        sample_id=sample_id,
        step_type_id=step_type_id,
        step_order=0,  # set by place_new
        parameters=parse_params(params_text) or None,
        notes=notes or None,
        performed_by=performed_by or current_user.username,
        performed_at=parse_datetime(performed_at),
    )
    db.add(step)
    await db.flush()  # get step.id without committing
    await place_new(db, step)

    for f in chosen_files(photos):
        await save_upload(f, "step", step.id, db, uploaded_by=current_user.username, photo=True)
    for f in chosen_files(files):
        await save_upload(f, "step", step.id, db, uploaded_by=current_user.username)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.get("/{sample_id}/steps/{step_id}/edit", response_class=HTMLResponse)
async def edit_step_form(
    request: Request,
    sample_id: int,
    step_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(
        select(ProcessStep)
        .options(selectinload(ProcessStep.step_type))
        .where(ProcessStep.id == step_id, ProcessStep.sample_id == sample_id)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    sample = await load_sample(db, sample_id, current_user, "edit")
    step_types = (await db.execute(select(ProcessStepType).order_by(ProcessStepType.name))).scalars().all()

    att_result = await db.execute(
        select(Attachment)
        .where(Attachment.entity_type == "step", Attachment.entity_id == step_id)
        .order_by(Attachment.uploaded_at)
    )
    attachments = att_result.scalars().all()

    return templates.TemplateResponse("steps/form.html", {
        "request": request,
        "sample": sample,
        "step": step,
        "step_types": step_types,
        "params_text": params_to_text(step.parameters, step.step_type.parameter_schema),
        "type_schemas_json": type_schemas_json(step_types),
        "attachments": attachments,
        "photo_max_px": settings.PHOTO_MAX_PX,
        "current_user": current_user,
    })


@router.post("/{sample_id}/steps/{step_id}/edit")
async def update_step(
    sample_id: int,
    step_id: int,
    step_type_id: int = Form(...),
    params_text: str = Form(""),
    notes: str = Form(""),
    performed_by: str = Form(""),
    performed_at: str = Form(""),
    photos: list[UploadFile | str] = File([]),
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    await load_sample(db, sample_id, current_user, "edit")
    result = await db.execute(
        select(ProcessStep).where(ProcessStep.id == step_id, ProcessStep.sample_id == sample_id)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    step.step_type_id = step_type_id
    step.parameters = parse_params(params_text) or None
    step.notes = notes or None
    step.performed_by = performed_by or None
    step.performed_at = parse_datetime(performed_at)

    for f in chosen_files(photos):
        await save_upload(f, "step", step_id, db, uploaded_by=current_user.username, photo=True)
    for f in chosen_files(files):
        await save_upload(f, "step", step_id, db, uploaded_by=current_user.username)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/steps/{step_id}/delete")
async def delete_step(
    request: Request,
    sample_id: int,
    step_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    await load_sample(db, sample_id, current_user, "edit")
    result = await db.execute(
        select(ProcessStep).where(ProcessStep.id == step_id, ProcessStep.sample_id == sample_id)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")
    pieces = (await db.execute(select(Sample).where(Sample.cut_step_id == step_id))).scalars().all()
    if pieces:
        request.session["flash_error"] = (
            f"Can't delete this cut: {len(pieces)} piece{'s' if len(pieces) != 1 else ''} were cut here "
            "and inherit the history before it. Delete the pieces first.")
        return RedirectResponse(f"/samples/{sample_id}", status_code=303)

    await db.delete(step)
    await db.flush()
    await renumber(db, sample_id)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
