"""Collaborations: partner universities and centres that send us samples.

Each has a code that numbers its samples the way a researcher's initials do
(UMIN-2026-001), so codes and initials share one namespace."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Collaborator, Sample, User
from backend.auth import require_login
from backend.i18n import t
from backend.sample_ids import COLLABORATOR_CODE_RE, normalize_initials

router = APIRouter(prefix="/collaborations", tags=["collaborations"])
from backend.templating import templates


def can_edit_collaborator(user: User, collaborator: Collaborator) -> bool:
    """Anyone can add a centre; whoever added it, and admins, can change it."""
    return user.is_admin or collaborator.created_by_id == user.id


async def _usage(db: AsyncSession) -> dict[int, int]:
    rows = await db.execute(
        select(Sample.collaborator_id, func.count()).where(Sample.collaborator_id.is_not(None))
        .group_by(Sample.collaborator_id))
    return dict(rows.all())


async def _get(db: AsyncSession, collaborator_id: int) -> Collaborator:
    collaborator = await db.get(Collaborator, collaborator_id)
    if not collaborator:
        raise HTTPException(status_code=404, detail="Collaboration not found")
    return collaborator


async def code_error(request: Request, db: AsyncSession, code: str, collaborator_id: int | None = None) -> str | None:
    """Why `code` can't be used for a centre, or None if it can."""
    if not COLLABORATOR_CODE_RE.match(code):
        return t(request, "The code must be 2 to 6 letters (A–Z).")
    user = (await db.execute(select(User).where(User.initials == code))).scalar_one_or_none()
    if user:
        return t(request, "{code} are {name}'s initials; choose another code.", code=code, name=user.display_name)
    other = (await db.execute(
        select(Collaborator).where(Collaborator.code == code, Collaborator.id != collaborator_id))).scalar_one_or_none()
    if other:
        return t(request, "The code {code} is already used by {name}.", code=code, name=other.name)
    return None


def _apply_form(collaborator: Collaborator, name, country, contact_name, contact_email, notes):
    collaborator.name = name.strip()
    collaborator.country = country.strip() or None
    collaborator.contact_name = contact_name.strip() or None
    collaborator.contact_email = contact_email.strip() or None
    collaborator.notes = notes.strip() or None


def _form(request, current_user, collaborator, error=None, can_edit=True, samples=(), code_locked=False,
          status_code=200):
    return templates.TemplateResponse("collaborations/form.html", {
        "request": request, "current_user": current_user, "collaborator": collaborator, "error": error,
        "can_edit": can_edit, "samples": samples, "code_locked": code_locked,
    }, status_code=status_code)


@router.get("/", response_class=HTMLResponse)
async def list_collaborators(request: Request, db: AsyncSession = Depends(get_db),
                             current_user: User = Depends(require_login)):
    collaborators = (await db.execute(select(Collaborator).order_by(Collaborator.name))).scalars().all()
    return templates.TemplateResponse("collaborations/list.html", {
        "request": request,
        "current_user": current_user,
        "collaborators": collaborators,
        "usage": await _usage(db),
        "flash": request.session.pop("flash", None),
        "flash_error": request.session.pop("flash_error", None),
    })


@router.get("/new", response_class=HTMLResponse)
async def new_collaborator_form(request: Request, current_user: User = Depends(require_login)):
    return _form(request, current_user, None)


@router.post("/new")
async def create_collaborator(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    country: str = Form(""),
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    collaborator = Collaborator(created_by_id=current_user.id, code=normalize_initials(code))
    _apply_form(collaborator, name, country, contact_name, contact_email, notes)
    error = await code_error(request, db, collaborator.code)
    if error:
        return _form(request, current_user, collaborator, error, status_code=400)
    db.add(collaborator)
    await db.commit()
    request.session["flash"] = t(request, "Collaboration '{name}' added.", name=collaborator.name)
    return RedirectResponse("/collaborations/", status_code=303)


@router.get("/{collaborator_id}", response_class=HTMLResponse)
async def collaborator_detail(request: Request, collaborator_id: int, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(require_login)):
    collaborator = await _get(db, collaborator_id)
    samples = (await db.execute(
        select(Sample).where(Sample.collaborator_id == collaborator_id).order_by(Sample.code))).scalars().all()
    return _form(request, current_user, collaborator, can_edit=can_edit_collaborator(current_user, collaborator),
                 samples=samples, code_locked=bool(samples))


@router.post("/{collaborator_id}")
async def update_collaborator(
    request: Request,
    collaborator_id: int,
    name: str = Form(...),
    code: str = Form(""),
    country: str = Form(""),
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    collaborator = await _get(db, collaborator_id)
    if not can_edit_collaborator(current_user, collaborator):
        raise HTTPException(status_code=403, detail="Only the person who added this collaboration, or an admin, can edit it.")
    # The code is in its samples' IDs, which never change: it's fixed once used.
    used = (await _usage(db)).get(collaborator_id, 0)
    _apply_form(collaborator, name, country, contact_name, contact_email, notes)
    if not used:
        collaborator.code = normalize_initials(code)
        error = await code_error(request, db, collaborator.code, collaborator_id)
        if error:
            response = _form(request, current_user, collaborator, error, status_code=400)
            await db.rollback()
            return response
    await db.commit()
    request.session["flash"] = t(request, "Collaboration '{name}' saved.", name=collaborator.name)
    return RedirectResponse("/collaborations/", status_code=303)


@router.post("/{collaborator_id}/delete")
async def delete_collaborator(request: Request, collaborator_id: int, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(require_login)):
    collaborator = await _get(db, collaborator_id)
    if not can_edit_collaborator(current_user, collaborator):
        raise HTTPException(status_code=403, detail="Only the person who added this collaboration, or an admin, can delete it.")
    used = (await _usage(db)).get(collaborator_id, 0)
    if used:
        request.session["flash_error"] = (
            t(request, "Can't delete '{name}': 1 sample comes from it.", name=collaborator.name) if used == 1 else
            t(request, "Can't delete '{name}': {n} samples come from it.", name=collaborator.name, n=used))
        return RedirectResponse("/collaborations/", status_code=303)
    await db.delete(collaborator)
    await db.commit()
    request.session["flash"] = t(request, "Collaboration '{name}' deleted.", name=collaborator.name)
    return RedirectResponse("/collaborations/", status_code=303)
