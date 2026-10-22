"""Projects: collaborations with partner universities and centres that send
us samples. One institution can have several projects.

Each project has a code that numbers its samples the way a researcher's
initials do (UMIN-2026-001), so codes and initials share one namespace."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Project, Sample, User
from backend.auth import require_login
from backend.i18n import t
from backend.sample_ids import PROJECT_CODE_RE, normalize_initials

router = APIRouter(prefix="/projects", tags=["projects"])
from backend.templating import templates


def can_edit_project(user: User, project: Project) -> bool:
    """Anyone can add a project; whoever added it, and admins, can change it."""
    return user.is_admin or project.created_by_id == user.id


async def _usage(db: AsyncSession) -> dict[int, int]:
    rows = await db.execute(
        select(Sample.project_id, func.count()).where(Sample.project_id.is_not(None))
        .group_by(Sample.project_id))
    return dict(rows.all())


async def _get(db: AsyncSession, project_id: int) -> Project:
    project = await db.get(Project, project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


async def code_error(request: Request, db: AsyncSession, code: str, project_id: int | None = None) -> str | None:
    """Why `code` can't be used for a project, or None if it can."""
    if not PROJECT_CODE_RE.match(code):
        return t(request, "The code must be 2 to 6 letters or digits (A–Z, 0–9).")
    user = (await db.execute(select(User).where(User.initials == code))).scalar_one_or_none()
    if user:
        return t(request, "{code} are {name}'s initials; choose another code.", code=code, name=user.display_name)
    other = (await db.execute(
        select(Project).where(Project.code == code, Project.id != project_id))).scalar_one_or_none()
    if other:
        return t(request, "The code {code} is already used by {name}.", code=code, name=other.name)
    return None


async def _institutions(db: AsyncSession) -> list[str]:
    """Institutions already entered, suggested on the form so one is spelled the same in all its projects."""
    rows = await db.execute(select(Project.institution).where(Project.institution.is_not(None)).distinct())
    return sorted(rows.scalars(), key=str.lower)


def _apply_form(project: Project, name, institution, country, contact_name, contact_email, notes):
    project.name = name.strip()
    project.institution = institution.strip() or None
    project.country = country.strip() or None
    project.contact_name = contact_name.strip() or None
    project.contact_email = contact_email.strip() or None
    project.notes = notes.strip() or None


def _form(request, current_user, project, institutions, error=None, can_edit=True, samples=(), code_locked=False,
          status_code=200):
    return templates.TemplateResponse("projects/form.html", {
        "request": request, "current_user": current_user, "project": project, "error": error,
        "can_edit": can_edit, "samples": samples, "code_locked": code_locked, "institutions": institutions,
    }, status_code=status_code)


@router.get("/", response_class=HTMLResponse)
async def list_projects(request: Request, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_login)):
    projects = (await db.execute(select(Project).order_by(Project.institution, Project.name))).scalars().all()
    return templates.TemplateResponse("projects/list.html", {
        "request": request,
        "current_user": current_user,
        "projects": projects,
        "usage": await _usage(db),
        "flash": request.session.pop("flash", None),
        "flash_error": request.session.pop("flash_error", None),
    })


@router.get("/new", response_class=HTMLResponse)
async def new_project_form(request: Request, db: AsyncSession = Depends(get_db),
                           current_user: User = Depends(require_login)):
    return _form(request, current_user, None, await _institutions(db))


@router.post("/new")
async def create_project(
    request: Request,
    name: str = Form(...),
    code: str = Form(...),
    institution: str = Form(""),
    country: str = Form(""),
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    project = Project(created_by_id=current_user.id, code=normalize_initials(code))
    _apply_form(project, name, institution, country, contact_name, contact_email, notes)
    error = await code_error(request, db, project.code)
    if error:
        return _form(request, current_user, project, await _institutions(db), error, status_code=400)
    db.add(project)
    await db.commit()
    request.session["flash"] = t(request, "Project '{name}' added.", name=project.name)
    return RedirectResponse("/projects/", status_code=303)


@router.get("/{project_id}", response_class=HTMLResponse)
async def project_detail(request: Request, project_id: int, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(require_login)):
    project = await _get(db, project_id)
    samples = (await db.execute(
        select(Sample).where(Sample.project_id == project_id).order_by(Sample.code))).scalars().all()
    return _form(request, current_user, project, await _institutions(db), can_edit=can_edit_project(current_user, project),
                 samples=samples, code_locked=bool(samples))


@router.post("/{project_id}")
async def update_project(
    request: Request,
    project_id: int,
    name: str = Form(...),
    code: str = Form(""),
    institution: str = Form(""),
    country: str = Form(""),
    contact_name: str = Form(""),
    contact_email: str = Form(""),
    notes: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    project = await _get(db, project_id)
    if not can_edit_project(current_user, project):
        raise HTTPException(status_code=403, detail="Only the person who added this project, or an admin, can edit it.")
    # The code is in its samples' IDs, which never change: it's fixed once used.
    used = (await _usage(db)).get(project_id, 0)
    _apply_form(project, name, institution, country, contact_name, contact_email, notes)
    if not used:
        project.code = normalize_initials(code)
        error = await code_error(request, db, project.code, project_id)
        if error:
            response = _form(request, current_user, project, await _institutions(db), error, status_code=400)
            await db.rollback()
            return response
    await db.commit()
    request.session["flash"] = t(request, "Project '{name}' saved.", name=project.name)
    return RedirectResponse("/projects/", status_code=303)


@router.post("/{project_id}/delete")
async def delete_project(request: Request, project_id: int, db: AsyncSession = Depends(get_db),
                              current_user: User = Depends(require_login)):
    project = await _get(db, project_id)
    if not can_edit_project(current_user, project):
        raise HTTPException(status_code=403, detail="Only the person who added this project, or an admin, can delete it.")
    used = (await _usage(db)).get(project_id, 0)
    if used:
        request.session["flash_error"] = (
            t(request, "Can't delete '{name}': 1 sample comes from it.", name=project.name) if used == 1 else
            t(request, "Can't delete '{name}': {n} samples come from it.", name=project.name, n=used))
        return RedirectResponse("/projects/", status_code=303)
    await db.delete(project)
    await db.commit()
    request.session["flash"] = t(request, "Project '{name}' deleted.", name=project.name)
    return RedirectResponse("/projects/", status_code=303)
