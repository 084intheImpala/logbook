from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models import Sample, ProcessStep, Analysis, ProcessStepType, AnalysisType, Attachment
from backend.auth import require_login, can_edit as _can_edit

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


async def _attachments_for(db: AsyncSession, entity_type: str, entity_ids: list[int]) -> dict[int, list]:
    if not entity_ids:
        return {}
    result = await db.execute(
        select(Attachment)
        .where(Attachment.entity_type == entity_type, Attachment.entity_id.in_(entity_ids))
        .order_by(Attachment.uploaded_at)
    )
    grouped: dict[int, list] = {eid: [] for eid in entity_ids}
    for att in result.scalars():
        grouped[att.entity_id].append(att)
    return grouped


async def _load_sample_full(sample_id: int, db: AsyncSession):
    result = await db.execute(
        select(Sample)
        .options(
            selectinload(Sample.process_steps).selectinload(ProcessStep.step_type),
            selectinload(Sample.analyses).selectinload(Analysis.analysis_type),
        )
        .where(Sample.id == sample_id)
    )
    return result.scalar_one_or_none()


@router.get("/", response_class=HTMLResponse)
async def list_samples(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).order_by(Sample.created_at.desc()))
    samples_list = result.scalars().all()
    return templates.TemplateResponse("samples/list.html", {
        "request": request,
        "samples": samples_list,
        "current_user": current_user,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_sample_form(
    request: Request,
    current_user=Depends(require_login),
):
    return templates.TemplateResponse("samples/form.html", {
        "request": request,
        "sample": None,
        "current_user": current_user,
    })


@router.post("/new")
async def create_sample(
    request: Request,
    name: str = Form(...),
    substrate_material: str = Form(""),
    substrate_dimensions: str = Form(""),
    film_material: str = Form(""),
    description: str = Form(""),
    created_by: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = Sample(
        name=name,
        substrate_material=substrate_material or None,
        substrate_dimensions=substrate_dimensions or None,
        film_material=film_material or None,
        description=description or None,
        created_by=created_by or current_user.username,
        owner_id=current_user.id,
    )
    db.add(sample)
    await db.commit()
    await db.refresh(sample)
    return RedirectResponse(f"/samples/{sample.id}", status_code=303)


@router.get("/{sample_id}", response_class=HTMLResponse)
async def sample_detail(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await _load_sample_full(sample_id, db)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")

    step_attachments = await _attachments_for(db, "step", [s.id for s in sample.process_steps])
    analysis_attachments = await _attachments_for(db, "analysis", [a.id for a in sample.analyses])

    # Build unified timeline sorted by date
    timeline = []
    for step in sample.process_steps:
        timeline.append({
            "kind": "process",
            "id": step.id,
            "type_name": step.step_type.name,
            "parameters": step.parameters,
            "notes": step.notes,
            "performed_by": step.performed_by,
            "performed_at": step.performed_at,
            "created_at": step.created_at,
            "sort_key": step.performed_at or step.created_at,
            "attachments": step_attachments.get(step.id, []),
            "edit_url": f"/samples/{sample_id}/steps/{step.id}/edit",
            "delete_url": f"/samples/{sample_id}/steps/{step.id}/delete",
        })
    for analysis in sample.analyses:
        timeline.append({
            "kind": "analysis",
            "id": analysis.id,
            "type_name": analysis.analysis_type.name,
            "parameters": analysis.parameters,
            "notes": analysis.notes,
            "performed_by": analysis.performed_by,
            "performed_at": analysis.performed_at,
            "created_at": analysis.created_at,
            "sort_key": analysis.performed_at or analysis.created_at,
            "attachments": analysis_attachments.get(analysis.id, []),
            "edit_url": f"/samples/{sample_id}/analyses/{analysis.id}/edit",
            "delete_url": f"/samples/{sample_id}/analyses/{analysis.id}/delete",
        })
    timeline.sort(key=lambda x: x["sort_key"])

    return templates.TemplateResponse("samples/detail.html", {
        "request": request,
        "sample": sample,
        "timeline": timeline,
        "current_user": current_user,
        "can_edit": _can_edit(current_user, sample),
    })


@router.get("/{sample_id}/edit", response_class=HTMLResponse)
async def edit_sample_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).where(Sample.id == sample_id))
    sample = result.scalar_one_or_none()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if not _can_edit(current_user, sample):
        raise HTTPException(status_code=403, detail="You don't have permission to edit this sample.")
    return templates.TemplateResponse("samples/form.html", {
        "request": request,
        "sample": sample,
        "current_user": current_user,
    })


@router.post("/{sample_id}/edit")
async def update_sample(
    request: Request,
    sample_id: int,
    name: str = Form(...),
    substrate_material: str = Form(""),
    substrate_dimensions: str = Form(""),
    film_material: str = Form(""),
    description: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).where(Sample.id == sample_id))
    sample = result.scalar_one_or_none()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if not _can_edit(current_user, sample):
        raise HTTPException(status_code=403, detail="You don't have permission to edit this sample.")
    sample.name = name
    sample.substrate_material = substrate_material or None
    sample.substrate_dimensions = substrate_dimensions or None
    sample.film_material = film_material or None
    sample.description = description or None
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/delete")
async def delete_sample(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).where(Sample.id == sample_id))
    sample = result.scalar_one_or_none()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if not _can_edit(current_user, sample):
        raise HTTPException(status_code=403, detail="You don't have permission to delete this sample.")
    await db.delete(sample)
    await db.commit()
    return RedirectResponse("/samples/", status_code=303)
