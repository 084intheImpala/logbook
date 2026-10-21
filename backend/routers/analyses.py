from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models import Analysis, AnalysisType, Attachment
from backend.params import parse_params, params_to_text, type_schemas_json, parse_datetime
from backend.timeline import place_new, renumber
from backend.config import settings
from backend.utils import save_upload, chosen_files
from backend.auth import require_login, load_sample

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/{sample_id}/analyses/new", response_class=HTMLResponse)
async def new_analysis_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    analysis_types = (await db.execute(select(AnalysisType).order_by(AnalysisType.name))).scalars().all()
    return templates.TemplateResponse("analyses/form.html", {
        "request": request,
        "sample": sample,
        "analysis_types": analysis_types,
        "analysis": None,
        "params_text": "",
        "type_schemas_json": type_schemas_json(analysis_types),
        "attachments": [],
        "photo_max_px": settings.PHOTO_MAX_PX,
        "current_user": current_user,
    })


@router.post("/{sample_id}/analyses/new")
async def create_analysis(
    sample_id: int,
    analysis_type_id: int = Form(...),
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

    analysis = Analysis(
        sample_id=sample_id,
        analysis_type_id=analysis_type_id,
        parameters=parse_params(params_text) or None,
        notes=notes or None,
        performed_by=performed_by or current_user.username,
        performed_at=parse_datetime(performed_at),
    )
    db.add(analysis)
    await db.flush()  # get analysis.id
    await place_new(db, analysis)

    for f in chosen_files(photos):
        await save_upload(f, "analysis", analysis.id, db, uploaded_by=current_user.username, photo=True)
    for f in chosen_files(files):
        await save_upload(f, "analysis", analysis.id, db, uploaded_by=current_user.username)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.get("/{sample_id}/analyses/{analysis_id}/edit", response_class=HTMLResponse)
async def edit_analysis_form(
    request: Request,
    sample_id: int,
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(
        select(Analysis)
        .options(selectinload(Analysis.analysis_type))
        .where(Analysis.id == analysis_id, Analysis.sample_id == sample_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    sample = await load_sample(db, sample_id, current_user, "edit")
    analysis_types = (await db.execute(select(AnalysisType).order_by(AnalysisType.name))).scalars().all()

    att_result = await db.execute(
        select(Attachment)
        .where(Attachment.entity_type == "analysis", Attachment.entity_id == analysis_id)
        .order_by(Attachment.uploaded_at)
    )
    attachments = att_result.scalars().all()

    return templates.TemplateResponse("analyses/form.html", {
        "request": request,
        "sample": sample,
        "analysis": analysis,
        "analysis_types": analysis_types,
        "params_text": params_to_text(analysis.parameters, analysis.analysis_type.parameter_schema),
        "type_schemas_json": type_schemas_json(analysis_types),
        "attachments": attachments,
        "photo_max_px": settings.PHOTO_MAX_PX,
        "current_user": current_user,
    })


@router.post("/{sample_id}/analyses/{analysis_id}/edit")
async def update_analysis(
    sample_id: int,
    analysis_id: int,
    analysis_type_id: int = Form(...),
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
        select(Analysis).where(Analysis.id == analysis_id, Analysis.sample_id == sample_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    analysis.analysis_type_id = analysis_type_id
    analysis.parameters = parse_params(params_text) or None
    analysis.notes = notes or None
    analysis.performed_by = performed_by or None
    analysis.performed_at = parse_datetime(performed_at)

    for f in chosen_files(photos):
        await save_upload(f, "analysis", analysis_id, db, uploaded_by=current_user.username, photo=True)
    for f in chosen_files(files):
        await save_upload(f, "analysis", analysis_id, db, uploaded_by=current_user.username)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/analyses/{analysis_id}/delete")
async def delete_analysis(
    sample_id: int,
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    await load_sample(db, sample_id, current_user, "edit")
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id, Analysis.sample_id == sample_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    await db.delete(analysis)
    await db.flush()
    await renumber(db, sample_id)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
