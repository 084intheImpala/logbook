"""Devices on a sample (D1, D2, …): see models.Device.

They are made by declaring the sample's process done: a "Devices made" step
goes on the timeline and the devices are listed under it. Later steps still
apply to all of them.
"""
from fastapi import APIRouter, Depends, Form, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from backend import timeline as tl
from backend.auth import load_sample, require_login
from backend.database import get_db
from backend.lineage import DEVICES_TYPE_NAME
from backend.models import Analysis, Device, ProcessStep, ProcessStepType
from backend.params import parse_date
from backend.seed_data import PROCESS_STEP_TYPES

router = APIRouter()


def _labels(sample, labels: str, count: str) -> list[str]:
    """The new devices' names: those typed (comma separated), or `count` numbered on from the last."""
    typed = [x.strip()[:50] for x in labels.replace("\n", ",").split(",") if x.strip()]
    taken = {d.label.lower() for d in sample.devices}
    out = []
    if not typed and count.isdigit():
        n = 1
        while len(out) < min(int(count), 100):
            if f"D{n}".lower() not in taken:
                out.append(f"D{n}")
                taken.add(f"d{n}")
            n += 1
        return out
    for label in typed:
        if label.lower() not in taken:
            taken.add(label.lower())
            out.append(label)
    return out


@router.post("/{sample_id}/devices")
async def make_devices(sample_id: int, labels: str = Form(""), count: str = Form(""), performed_at: str = Form(""),
                       notes: str = Form(""), db: AsyncSession = Depends(get_db), current_user=Depends(require_login)):
    """Declare the process done and create the devices, with a "Devices made" step marking the moment."""
    sample = await load_sample(db, sample_id, current_user, "edit")
    names = _labels(sample, labels, count)
    if not names:
        return RedirectResponse(f"/samples/{sample_id}#devices", status_code=303)
    step_type = (await db.execute(
        select(ProcessStepType).where(ProcessStepType.name == DEVICES_TYPE_NAME))).scalar_one_or_none()
    if step_type is None:  # renamed or deleted by an admin: recreate it
        step_type = ProcessStepType(**next(t for t in PROCESS_STEP_TYPES if t["name"] == DEVICES_TYPE_NAME))
        db.add(step_type)
        await db.flush()
    step = ProcessStep(sample_id=sample_id, step_type_id=step_type.id, performer_id=current_user.id,
                       performed_at=parse_date(performed_at), notes=notes.strip() or None)
    db.add(step)
    await db.flush()
    await tl.place_new(db, step)
    for label in names:
        sample.devices.append(Device(label=label, made_step_id=step.id))
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}#step-{step.id}", status_code=303)


async def remove_devices(db: AsyncSession, *where):
    """Delete the devices matching `where`; their analyses stay on the sample, no longer tied to a device."""
    ids = (await db.execute(select(Device.id).where(*where))).scalars().all()
    if ids:
        await db.execute(update(Analysis).where(Analysis.device_id.in_(ids)).values(device_id=None))
        for device in (await db.execute(select(Device).where(Device.id.in_(ids)))).scalars():
            await db.delete(device)


@router.post("/{sample_id}/devices/{device_id}/delete")
async def delete_device(sample_id: int, device_id: int, db: AsyncSession = Depends(get_db),
                        current_user=Depends(require_login)):
    """Removes one device; its analyses stay on the sample."""
    await load_sample(db, sample_id, current_user, "edit")
    if not (await db.execute(select(Device.id).where(Device.id == device_id, Device.sample_id == sample_id))).first():
        raise HTTPException(status_code=404, detail="Device not found")
    await remove_devices(db, Device.id == device_id)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}#devices", status_code=303)
