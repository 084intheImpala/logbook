from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import Sample, SampleShare, ProcessStep, ProcessStepType, Analysis, Attachment, User
from backend.auth import require_login, load_sample, can_view, can_edit, is_owner
from backend import timeline as tl
from backend.lineage import load_sample_full, load_family, pieces_of
from backend.params import parse_datetime
from backend.seed import PROCESS_STEP_TYPES

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


@router.get("/", response_class=HTMLResponse)
async def list_samples(
    request: Request,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    result = await db.execute(select(Sample).order_by(Sample.created_at.desc()))
    samples_list = result.scalars().all()
    by_id = {s.id: s for s in samples_list}
    parent_ids = (await db.execute(
        select(Sample.id, ProcessStep.sample_id).join(ProcessStep, Sample.cut_step_id == ProcessStep.id)
    )).all()
    return templates.TemplateResponse("samples/list.html", {
        "request": request,
        "samples": samples_list,
        "parents": {piece_id: by_id[parent_id] for piece_id, parent_id in parent_ids},
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
    sample = await load_sample_full(db, sample_id)
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    viewable = can_view(current_user, sample)
    fam = await load_family(db, sample)
    items = fam["family"].timeline(sample)

    # Viewing a piece includes its inherited history; inherited entries are
    # also visible to whoever can view the sample they're recorded on.
    def visible(item):
        return viewable or (item.source is not sample and can_view(current_user, item.source))

    shown = [i for i in items if visible(i)]
    step_attachments = await _attachments_for(db, "step", [i.entry.id for i in shown if i.kind == "process"])
    analysis_attachments = await _attachments_for(db, "analysis", [i.entry.id for i in shown if i.kind == "analysis"])

    own_count = sum(1 for i in items if i.source is sample)
    timeline, own_index = [], 0
    for item in items:
        e, inherited = item.entry, item.source is not sample
        path = "steps" if item.kind == "process" else "analyses"
        attachments = step_attachments if item.kind == "process" else analysis_attachments
        timeline.append({
            "kind": item.kind,
            "id": e.id,
            "type_name": item.technique,
            "parameters": e.parameters,
            "notes": e.notes,
            "performed_by": e.performed_by,
            "performed_at": e.performed_at,
            "visible": visible(item),
            "inherited": inherited,
            "source": item.source,
            "first_own": not inherited and own_index == 0,
            "last_own": not inherited and own_index == own_count - 1,
            "pieces": fam["pieces_by_cut"].get(e.id, []) if not inherited else [],
            "attachments": attachments.get(e.id, []),
            "edit_url": f"/samples/{sample_id}/{path}/{e.id}/edit",
            "delete_url": f"/samples/{sample_id}/{path}/{e.id}/delete",
        })
        own_index += not inherited

    owner = is_owner(current_user, sample)
    return templates.TemplateResponse("samples/detail.html", {
        "request": request,
        "sample": sample,
        "timeline": timeline,
        "has_inherited": own_count < len(items),
        "parent": fam["parent"],
        "cut": fam["cut"],
        "siblings": fam["siblings"],
        "current_user": current_user,
        "can_view": viewable,
        "can_edit": can_edit(current_user, sample),
        "is_owner": owner,
        "share_candidates": await _share_candidates(db, sample) if owner else [],
        "owner_user": (await db.get(User, sample.owner_id)) if sample.owner_id else None,
        "flash": request.session.pop("flash", None),
        "flash_error": request.session.pop("flash_error", None),
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
    pieces = await pieces_of(db, sample_id)
    if pieces:
        request.session["flash_error"] = (
            f"Can't delete: {len(pieces)} piece{'s' if len(pieces) != 1 else ''} were cut from this sample "
            "and inherit its history. Delete the pieces first.")
        return RedirectResponse(f"/samples/{sample_id}", status_code=303)
    await db.delete(sample)
    await db.commit()
    return RedirectResponse("/samples/", status_code=303)


# ── Cutting into pieces ───────────────────────────────────────────────────────

CUT_TYPE_NAME = "Cut"


@router.get("/{sample_id}/cut", response_class=HTMLResponse)
async def cut_form(
    request: Request,
    sample_id: int,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    return templates.TemplateResponse("samples/cut.html", {
        "request": request,
        "sample": sample,
        "flash_error": request.session.pop("flash_error", None),
        "current_user": current_user,
    })


@router.post("/{sample_id}/cut")
async def cut_sample(
    request: Request,
    sample_id: int,
    piece_names: list[str] = Form([]),
    piece_dimensions: list[str] = Form([]),
    keep_reference: str = Form(""),
    reference_name: str = Form(""),
    reference_dimensions: str = Form(""),
    method: str = Form(""),
    notes: str = Form(""),
    performed_at: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    """Record a Cut step on the sample and create one sample per piece.

    Pieces copy the parent's materials, tags, owner and shares; if the person
    cutting isn't the owner, they get edit access to the pieces."""
    parent = await load_sample(db, sample_id, current_user, "edit")
    pieces = [(n.strip(), d.strip(), False) for n, d in zip(piece_names, piece_dimensions) if n.strip()]
    if keep_reference:
        pieces.append((reference_name.strip() or f"{parent.name}-REF", reference_dimensions.strip(), True))
    if not pieces:
        request.session["flash_error"] = "Give at least one piece a name."
        return RedirectResponse(f"/samples/{sample_id}/cut", status_code=303)

    cut_type = (await db.execute(
        select(ProcessStepType).where(ProcessStepType.name == CUT_TYPE_NAME))).scalar_one_or_none()
    if cut_type is None:  # renamed or deleted by an admin: recreate it
        cut_type = ProcessStepType(**next(t for t in PROCESS_STEP_TYPES if t["name"] == CUT_TYPE_NAME))
        db.add(cut_type)
        await db.flush()

    params = {"method": method.strip(), "pieces": len(pieces)} if method.strip() else {"pieces": len(pieces)}
    cut = ProcessStep(
        sample_id=sample_id,
        step_type_id=cut_type.id,
        step_order=0,  # set by place_new
        parameters=params,
        notes=notes or None,
        performed_by=current_user.username,
        performed_at=parse_datetime(performed_at),
    )
    db.add(cut)
    await db.flush()
    await tl.place_new(db, cut)

    owner_id = parent.owner_id or current_user.id
    for name, dims, is_ref in pieces:
        piece = Sample(
            name=name,
            film_material=parent.film_material,
            substrate_material=parent.substrate_material,
            substrate_dimensions=dims or None,
            tags=list(parent.tags) if parent.tags else None,
            created_by=current_user.username,
            owner_id=owner_id,
            cut_step_id=cut.id,
            is_reference=is_ref,
        )
        piece.shares = [SampleShare(user_id=sh.user_id, can_edit=sh.can_edit) for sh in parent.shares]
        if current_user.id != owner_id and not current_user.is_admin:
            _set_share(piece, current_user.id, True)
        db.add(piece)
    await db.commit()
    request.session["flash"] = f"Cut into {len(pieces)} piece{'s' if len(pieces) != 1 else ''}."
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


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
