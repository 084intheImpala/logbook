from datetime import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models import Sample, ProcessStep, ProcessStepType, Attachment
from backend.utils import save_upload
from backend.auth import require_login

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


def _parse_params(text: str) -> dict:
    """Parse 'key: value' lines into a dict."""
    params = {}
    for line in text.strip().splitlines():
        if ":" in line:
            k, _, v = line.partition(":")
            k, v = k.strip(), v.strip()
            if k and v:
                try:
                    params[k] = float(v) if "." in v else int(v)
                except ValueError:
                    params[k] = v
    return params


def _params_to_text(params: dict | None) -> str:
    if not params:
        return ""
    return "\n".join(f"{k}: {v}" for k, v in params.items())


def _type_schemas_json(step_types) -> str:
    """Build a JSON map of step_type_id → list of {key, label} for JS pre-fill."""
    return json.dumps({
        str(st.id): [{"key": f["key"], "label": f.get("label", f["key"])}
                     for f in (st.parameter_schema or [])]
        for st in step_types
    })


@router.get("/{sample_id}/steps/new", response_class=HTMLResponse)
async def new_step_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).where(Sample.id == sample_id))
    sample = result.scalar_one_or_none()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    step_types = (await db.execute(select(ProcessStepType).order_by(ProcessStepType.name))).scalars().all()
    return templates.TemplateResponse("steps/form.html", {
        "request": request,
        "sample": sample,
        "step_types": step_types,
        "step": None,
        "params_text": "",
        "type_schemas_json": _type_schemas_json(step_types),
        "attachments": [],
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
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).where(Sample.id == sample_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sample not found")

    order_result = await db.execute(
        select(func.coalesce(func.max(ProcessStep.step_order), -1))
        .where(ProcessStep.sample_id == sample_id)
    )
    next_order = order_result.scalar() + 1

    step = ProcessStep(
        sample_id=sample_id,
        step_type_id=step_type_id,
        step_order=next_order,
        parameters=_parse_params(params_text) or None,
        notes=notes or None,
        performed_by=performed_by or current_user.username,
        performed_at=datetime.strptime(performed_at, '%Y-%m-%dT%H:%M') if performed_at else None,
    )
    db.add(step)
    await db.flush()  # get step.id without committing

    await save_upload(file, "step", step.id, db)
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

    sample_result = await db.execute(select(Sample).where(Sample.id == sample_id))
    sample = sample_result.scalar_one_or_none()
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
        "params_text": _params_to_text(step.parameters),
        "type_schemas_json": _type_schemas_json(step_types),
        "attachments": attachments,
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
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(
        select(ProcessStep).where(ProcessStep.id == step_id, ProcessStep.sample_id == sample_id)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    step.step_type_id = step_type_id
    step.parameters = _parse_params(params_text) or None
    step.notes = notes or None
    step.performed_by = performed_by or None
    step.performed_at = datetime.strptime(performed_at, '%Y-%m-%dT%H:%M') if performed_at else None

    await save_upload(file, "step", step_id, db)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/steps/{step_id}/delete")
async def delete_step(
    sample_id: int,
    step_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(
        select(ProcessStep).where(ProcessStep.id == step_id, ProcessStep.sample_id == sample_id)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    deleted_order = step.step_order
    await db.delete(step)

    remaining = await db.execute(
        select(ProcessStep)
        .where(ProcessStep.sample_id == sample_id, ProcessStep.step_order > deleted_order)
        .order_by(ProcessStep.step_order)
    )
    for s in remaining.scalars():
        s.step_order -= 1

    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/steps/{step_id}/move")
async def move_step(
    sample_id: int,
    step_id: int,
    direction: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(
        select(ProcessStep).where(ProcessStep.id == step_id, ProcessStep.sample_id == sample_id)
    )
    step = result.scalar_one_or_none()
    if not step:
        raise HTTPException(status_code=404, detail="Step not found")

    target_order = step.step_order + (-1 if direction == "up" else 1)
    swap_result = await db.execute(
        select(ProcessStep).where(
            ProcessStep.sample_id == sample_id,
            ProcessStep.step_order == target_order
        )
    )
    swap = swap_result.scalar_one_or_none()
    if swap:
        swap.step_order, step.step_order = step.step_order, swap.step_order
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
