from datetime import datetime
import json
from fastapi import APIRouter, Depends, HTTPException, Request, Form, UploadFile, File
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models import Sample, Analysis, AnalysisType, Attachment
from backend.routers.steps import _parse_params, _params_to_text
from backend.utils import save_upload
from backend.auth import require_login

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


def _type_schemas_json(analysis_types) -> str:
    return json.dumps({
        str(at.id): [{"key": f["key"], "label": f.get("label", f["key"])}
                     for f in (at.parameter_schema or [])]
        for at in analysis_types
    })


@router.get("/{sample_id}/analyses/new", response_class=HTMLResponse)
async def new_analysis_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).where(Sample.id == sample_id))
    sample = result.scalar_one_or_none()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    analysis_types = (await db.execute(select(AnalysisType).order_by(AnalysisType.name))).scalars().all()
    return templates.TemplateResponse("analyses/form.html", {
        "request": request,
        "sample": sample,
        "analysis_types": analysis_types,
        "analysis": None,
        "params_text": "",
        "type_schemas_json": _type_schemas_json(analysis_types),
        "attachments": [],
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
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).where(Sample.id == sample_id))
    if not result.scalar_one_or_none():
        raise HTTPException(status_code=404, detail="Sample not found")

    analysis = Analysis(
        sample_id=sample_id,
        analysis_type_id=analysis_type_id,
        parameters=_parse_params(params_text) or None,
        notes=notes or None,
        performed_by=performed_by or current_user.username,
        performed_at=datetime.strptime(performed_at, '%Y-%m-%dT%H:%M') if performed_at else None,
    )
    db.add(analysis)
    await db.flush()  # get analysis.id

    await save_upload(file, "analysis", analysis.id, db)
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

    sample_result = await db.execute(select(Sample).where(Sample.id == sample_id))
    sample = sample_result.scalar_one_or_none()
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
        "params_text": _params_to_text(analysis.parameters),
        "type_schemas_json": _type_schemas_json(analysis_types),
        "attachments": attachments,
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
    file: UploadFile | None = File(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id, Analysis.sample_id == sample_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")

    analysis.analysis_type_id = analysis_type_id
    analysis.parameters = _parse_params(params_text) or None
    analysis.notes = notes or None
    analysis.performed_by = performed_by or None
    analysis.performed_at = datetime.strptime(performed_at, '%Y-%m-%dT%H:%M') if performed_at else None

    await save_upload(file, "analysis", analysis_id, db)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/analyses/{analysis_id}/delete")
async def delete_analysis(
    sample_id: int,
    analysis_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(
        select(Analysis).where(Analysis.id == analysis_id, Analysis.sample_id == sample_id)
    )
    analysis = result.scalar_one_or_none()
    if not analysis:
        raise HTTPException(status_code=404, detail="Analysis not found")
    await db.delete(analysis)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
