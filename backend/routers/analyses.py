"""Adding, editing and deleting analyses (the form itself is in backend/entry_forms.py)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import Analysis
from backend.timeline import renumber
from backend.auth import require_login, load_sample, can_edit_entry
from backend.entry_forms import ANALYSIS, form_page, save, get_entry, overwrite_check

router = APIRouter()


@router.get("/{sample_id}/analyses/new", response_class=HTMLResponse)
async def new_form(request: Request, sample_id: int, db: AsyncSession = Depends(get_db),
                   current_user=Depends(require_login)):
    sample = await load_sample(db, sample_id, current_user, "edit")
    return await form_page(request, db, ANALYSIS, sample, None, current_user)


@router.post("/{sample_id}/analyses/new")
async def create(request: Request, sample_id: int, db: AsyncSession = Depends(get_db),
                 current_user=Depends(require_login)):
    sample = await load_sample(db, sample_id, current_user, "edit")
    return await save(request, db, ANALYSIS, sample, None, current_user)


async def _editable(db, sample_id: int, entry_id: int, user):
    """The sample and entry, if `user` may edit the entry (its performer may, too)."""
    sample = await load_sample(db, sample_id, user, "summary")
    entry = await get_entry(db, ANALYSIS, sample_id, entry_id)
    if not can_edit_entry(user, sample, entry):
        raise HTTPException(status_code=403, detail="You don't have access to this sample.")
    return sample, entry


@router.get("/{sample_id}/analyses/{analysis_id}/edit", response_class=HTMLResponse)
async def edit_form(request: Request, sample_id: int, analysis_id: int, db: AsyncSession = Depends(get_db),
                    current_user=Depends(require_login)):
    sample, entry = await _editable(db, sample_id, analysis_id, current_user)
    return await form_page(request, db, ANALYSIS, sample, entry, current_user)


@router.post("/{sample_id}/analyses/{analysis_id}/edit")
async def update(request: Request, sample_id: int, analysis_id: int, db: AsyncSession = Depends(get_db),
                 current_user=Depends(require_login)):
    sample, entry = await _editable(db, sample_id, analysis_id, current_user)
    return await save(request, db, ANALYSIS, sample, entry, current_user)


@router.post("/{sample_id}/analyses/{analysis_id}/edit/check")
async def check_overwrite(request: Request, sample_id: int, analysis_id: int, db: AsyncSession = Depends(get_db),
                          current_user=Depends(require_login)):
    """Asked by the form before saving changes to a whole run (see overwrite_check)."""
    sample, entry = await _editable(db, sample_id, analysis_id, current_user)
    return await overwrite_check(request, db, ANALYSIS, sample, entry, current_user)


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
