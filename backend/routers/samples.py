from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from sqlalchemy.orm import selectinload

from backend.database import get_db
from backend.models import Sample, SampleShare, ProcessStep, Analysis, Attachment, User
from backend.auth import require_login, load_sample, can_view, can_edit, is_owner
from backend import timeline as tl

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


def parse_tags(text: str) -> list[str] | None:
    """Split a comma-separated tag string, dropping blanks and duplicates (case-insensitive)."""
    tags, seen = [], set()
    for t in text.split(","):
        t = t.strip()
        if t and t.lower() not in seen:
            seen.add(t.lower())
            tags.append(t)
    return tags or None


async def all_tags(db: AsyncSession) -> list[str]:
    rows = (await db.execute(select(Sample.tags))).scalars()
    return sorted({t for tags in rows for t in tags or []}, key=str.lower)


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
        "can_view": can_view,
        "current_user": current_user,
    })


@router.get("/new", response_class=HTMLResponse)
async def new_sample_form(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    return templates.TemplateResponse("samples/form.html", {
        "request": request,
        "sample": None,
        "known_tags": await all_tags(db),
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
    tags: str = Form(""),
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
        tags=parse_tags(tags),
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
    viewable = can_view(current_user, sample)

    step_attachments, analysis_attachments = {}, {}
    if viewable:
        step_attachments = await _attachments_for(db, "step", [s.id for s in sample.process_steps])
        analysis_attachments = await _attachments_for(db, "analysis", [a.id for a in sample.analyses])

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
            "position": step.position,
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
            "position": analysis.position,
            "attachments": analysis_attachments.get(analysis.id, []),
            "edit_url": f"/samples/{sample_id}/analyses/{analysis.id}/edit",
            "delete_url": f"/samples/{sample_id}/analyses/{analysis.id}/delete",
        })
    timeline.sort(key=lambda x: (x["position"] is None, x["position"] or 0, x["created_at"]))

    owner = is_owner(current_user, sample)
    return templates.TemplateResponse("samples/detail.html", {
        "request": request,
        "sample": sample,
        "timeline": timeline,
        "current_user": current_user,
        "can_view": viewable,
        "can_edit": can_edit(current_user, sample),
        "is_owner": owner,
        "share_candidates": await _share_candidates(db, sample) if owner else [],
        "owner_user": (await db.get(User, sample.owner_id)) if sample.owner_id else None,
    })


async def _share_candidates(db: AsyncSession, sample: Sample) -> list[User]:
    """Users who could be given access: not the owner, not admins, not already shared."""
    taken = {sh.user_id for sh in sample.shares} | {sample.owner_id}
    users = (await db.execute(select(User).where(User.is_admin.is_(False)).order_by(User.username))).scalars()
    return [u for u in users if u.id not in taken]


@router.get("/{sample_id}/edit", response_class=HTMLResponse)
async def edit_sample_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    users = (await db.execute(select(User).order_by(User.username))).scalars().all() if current_user.is_admin else []
    return templates.TemplateResponse("samples/form.html", {
        "request": request,
        "sample": sample,
        "known_tags": await all_tags(db),
        "users": users,
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
    tags: str = Form(""),
    owner_id: str = Form(None),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    sample.name = name
    sample.substrate_material = substrate_material or None
    sample.substrate_dimensions = substrate_dimensions or None
    sample.film_material = film_material or None
    sample.description = description or None
    sample.tags = parse_tags(tags)
    # Only admins can reassign ownership (e.g. claim samples created before logins).
    if current_user.is_admin and owner_id is not None:
        sample.owner_id = int(owner_id) if owner_id else None
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/delete")
async def delete_sample(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "owner")
    await db.delete(sample)
    await db.commit()
    return RedirectResponse("/samples/", status_code=303)


# ── Sharing ───────────────────────────────────────────────────────────────────

def _set_share(sample: Sample, user_id: int, can_edit_: bool):
    share = next((sh for sh in sample.shares if sh.user_id == user_id), None)
    if share:
        share.can_edit = can_edit_
    elif user_id != sample.owner_id:
        sample.shares.append(SampleShare(user_id=user_id, can_edit=can_edit_))


@router.post("/{sample_id}/shares")
async def add_share(
    sample_id: int,
    user_id: int = Form(...),
    access: str = Form("view"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "owner")
    if not await db.get(User, user_id):
        raise HTTPException(status_code=404, detail="User not found")
    _set_share(sample, user_id, access == "edit")
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}#sharing", status_code=303)


@router.post("/{sample_id}/shares/{share_id}/delete")
async def remove_share(
    sample_id: int,
    share_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "owner")
    share = next((sh for sh in sample.shares if sh.id == share_id), None)
    if share:
        sample.shares.remove(share)
        await db.commit()
    return RedirectResponse(f"/samples/{sample_id}#sharing", status_code=303)


@router.post("/share")
async def share_many(
    request: Request,
    sample_ids: list[int] = Form([]),
    user_id: int = Form(...),
    access: str = Form("view"),
    back: str = Form("/search"),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    """Share several samples at once (from the search page). Samples the
    current user doesn't own are skipped."""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    samples = (await db.execute(select(Sample).where(Sample.id.in_(sample_ids)))).scalars().all() if sample_ids else []
    shared = [s for s in samples if is_owner(current_user, s)]
    for s in shared:
        _set_share(s, user_id, access == "edit")
    await db.commit()
    skipped = len(samples) - len(shared)
    msg = f"Shared {len(shared)} sample{'s' if len(shared) != 1 else ''} with {target.username} ({access})."
    if skipped:
        msg += f" Skipped {skipped} you don't own."
    request.session["flash"] = msg
    # Only redirect within the app
    return RedirectResponse(back if back.startswith("/") and not back.startswith("//") else "/search", status_code=303)


@router.post("/{sample_id}/timeline/move")
async def move_timeline_entry(
    sample_id: int,
    kind: str = Form(...),
    entry_id: int = Form(...),
    direction: str = Form(...),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    await load_sample(db, sample_id, current_user, "edit")
    model = ProcessStep if kind == "process" else Analysis
    entry = (await db.execute(
        select(model).where(model.id == entry_id, model.sample_id == sample_id)
    )).scalar_one_or_none()
    if not entry:
        raise HTTPException(status_code=404, detail="Entry not found")
    await tl.move(db, sample_id, entry, direction)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/{sample_id}/timeline/sort-by-date")
async def sort_timeline_by_date(
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    await load_sample(db, sample_id, current_user, "edit")
    await tl.sort_by_date(db, sample_id)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
