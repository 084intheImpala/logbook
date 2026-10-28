"""Adding, editing and deleting process steps (the form itself is in backend/entry_forms.py)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import Sample, ProcessStep
from backend.timeline import renumber
from backend.auth import require_login, load_sample, can_edit_entry
from backend.entry_forms import STEP, form_page, save, get_entry, overwrite_check
from backend.i18n import t
from backend.models import Device
from backend.routers.devices import remove_devices

router = APIRouter()


@router.get("/{sample_id}/steps/new", response_class=HTMLResponse)
async def new_form(request: Request, sample_id: int, db: AsyncSession = Depends(get_db),
                   current_user=Depends(require_login)):
    sample = await load_sample(db, sample_id, current_user, "propose")
    return await form_page(request, db, STEP, sample, None, current_user)


@router.post("/{sample_id}/steps/new")
async def create(request: Request, sample_id: int, db: AsyncSession = Depends(get_db),
                 current_user=Depends(require_login)):
    sample = await load_sample(db, sample_id, current_user, "propose")
    return await save(request, db, STEP, sample, None, current_user)


async def _editable(db, sample_id: int, entry_id: int, user):
    """The sample and entry, if `user` may edit the entry (its performer may, too)."""
    sample = await load_sample(db, sample_id, user, "summary")
    entry = await get_entry(db, STEP, sample_id, entry_id)
    if not can_edit_entry(user, sample, entry):
        raise HTTPException(status_code=403, detail="You don't have access to this sample.")
    return sample, entry


@router.get("/{sample_id}/steps/{step_id}/edit", response_class=HTMLResponse)
async def edit_form(request: Request, sample_id: int, step_id: int, db: AsyncSession = Depends(get_db),
                    current_user=Depends(require_login)):
    sample, entry = await _editable(db, sample_id, step_id, current_user)
    return await form_page(request, db, STEP, sample, entry, current_user)


@router.post("/{sample_id}/steps/{step_id}/edit")
async def update(request: Request, sample_id: int, step_id: int, db: AsyncSession = Depends(get_db),
                 current_user=Depends(require_login)):
    sample, entry = await _editable(db, sample_id, step_id, current_user)
    return await save(request, db, STEP, sample, entry, current_user)


@router.post("/{sample_id}/steps/{step_id}/edit/check")
async def check_overwrite(request: Request, sample_id: int, step_id: int, db: AsyncSession = Depends(get_db),
                          current_user=Depends(require_login)):
    """Asked by the form before saving changes to a whole run (see overwrite_check)."""
    sample, entry = await _editable(db, sample_id, step_id, current_user)
    return await overwrite_check(request, db, STEP, sample, entry, current_user)


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
        request.session["flash_error"] = t(
            request,
            "Can't delete this cut: {n} piece was cut here and inherits the history before it. "
            "Delete the piece first." if len(pieces) == 1 else
            "Can't delete this cut: {n} pieces were cut here and inherit the history before it. "
            "Delete the pieces first.",
            n=len(pieces))
        return RedirectResponse(f"/samples/{sample_id}", status_code=303)

    await remove_devices(db, Device.made_step_id == step_id)   # deleting "Devices made" takes its devices
    await db.delete(step)
    await db.flush()
    await renumber(db, sample_id)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
