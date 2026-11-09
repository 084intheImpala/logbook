"""Adding, editing and deleting process steps (the form itself is in backend/entry_forms.py)."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import Sample, ProcessStep, ProcessStepType
from backend.timeline import renumber
from backend.auth import require_login, load_sample, can_edit_entry
from backend.entry_forms import STEP, form_page, save, get_entry, overwrite_check
from backend import rate_plot
from backend.deposition_rate import CONDITION_KEYS, DEPOSITION_TYPE_NAME, all_samples, last_rate, set_rate
from backend.params import parse_form
from backend.i18n import t
from backend.models import Device
from backend.routers.devices import remove_devices
from backend.utils import delete_attachments_of

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


@router.get("/{sample_id}/steps/last-rate")
async def last_known_rate(request: Request, sample_id: int, db: AsyncSession = Depends(get_db),
                          current_user=Depends(require_login)):
    """For the Deposition form's duration calculator: the rate of the latest
    deposition with the conditions filled in on the form (sent as p::<key>)."""
    await load_sample(db, sample_id, current_user, "propose")
    step_type = (await db.execute(select(ProcessStepType).where(ProcessStepType.name == DEPOSITION_TYPE_NAME))).scalar_one()
    params, _ = parse_form(request.query_params, step_type.parameter_schema)
    if not any(params.get(k) not in (None, "") for k in CONDITION_KEYS):
        return JSONResponse({"rate": None, "message": t(request, "Choose the machine, target, gas, gas flow or power first.")})
    point = last_rate(current_user, await all_samples(db), params)
    if point is None:
        return JSONResponse({"rate": None, "message": t(request, "No deposition with these conditions has a rate yet.")})
    how = (t(request, "average of {n}", n=point.n) if point.n > 1 else t(request, "measured") if point.n
           else t(request, "typed"))
    return JSONResponse({
        "rate": point.rate,
        "message": t(request, "{rate} nm/min ({how}), from {sample} on {date}: {conditions}",
                     rate=f"{point.rate:g}", how=how, sample=point.sample.title,
                     date=point.step.performed_at.isoformat() if point.step.performed_at else "—",
                     conditions=rate_plot.condition_label(point.step)),
        "url": f"/samples/{point.sample.id}#step-{point.step.id}",
    })


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


@router.post("/{sample_id}/steps/{step_id}/deposition-rate")
async def add_deposition_rate(request: Request, sample_id: int, step_id: int, db: AsyncSession = Depends(get_db),
                              current_user=Depends(require_login)):
    """Fill in the rate offered after a thickness measurement (see backend/deposition_rate.py)
    on this deposition (not its copies in a run: those are films on other samples),
    then go back to `back` (the measured sample)."""
    sample, entry = await _editable(db, sample_id, step_id, current_user)
    form = await request.form()
    back = form.get("back", "")
    back_url = f"/samples/{back}" if back.isdigit() else f"/samples/{sample_id}"
    step_type = await db.get(ProcessStepType, entry.step_type_id)
    if step_type.name != DEPOSITION_TYPE_NAME:
        raise HTTPException(status_code=400, detail="Not a deposition.")
    params, _ = parse_form({"p::rate": form.get("rate", "")}, [{"key": "rate", "type": "number"}])
    rate = params.get("rate")
    if not isinstance(rate, (int, float)) or rate <= 0:
        request.session["flash_error"] = t(request, "The deposition rate must be a number above zero.")
        return RedirectResponse(back_url, status_code=303)
    filled = set_rate([entry], rate)
    await db.commit()
    if filled:
        request.session["flash"] = t(request, "Deposition rate of {rate} nm/min added to the deposition of {sample}.",
                                      rate=f"{rate:g}", sample=sample.title)
    return RedirectResponse(back_url, status_code=303)


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
    await delete_attachments_of(db, step_ids=[step_id])   # to the trash, unless shared
    await db.delete(step)
    await db.flush()
    await renumber(db, sample_id)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
