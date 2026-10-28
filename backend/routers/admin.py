"""Admin routes for managing users and configurations (step/analysis types)."""
import json
import re
from datetime import date
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.database import get_db
from backend.models import ProcessStepType, AnalysisType, ProcessStep, Analysis, User, Team
from backend.params import validate_schema, with_equipment
from backend import accounts
from backend.auth import require_login
from backend.email_utils import send_admin_message
from backend.config import settings
from backend.i18n import t
from backend.export import samples_csv
from backend.routers.auth import validate_profile
from backend.sample_ids import normalize_initials
from backend.lineage import Family, load_samples_full

router = APIRouter(prefix="/admin", tags=["admin"])
from backend.templating import templates
# One field per line, unicode units (°C, µm) kept readable
templates.env.filters["schema_json"] = lambda schema: "[\n" + ",\n".join(
    "  " + json.dumps(f, ensure_ascii=False) for f in schema or []) + "\n]"


async def require_admin(user: User = Depends(require_login)) -> User:
    if not user.is_admin:
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


# ── Main admin page ──────────────────────────────────────────────────────────

@router.get("/", response_class=HTMLResponse)
async def admin_index(request: Request, db: AsyncSession = Depends(get_db),
                      admin: User = Depends(require_admin)):
    step_types = (await db.execute(select(ProcessStepType).order_by(ProcessStepType.name))).scalars().all()
    analysis_types = (await db.execute(select(AnalysisType).order_by(AnalysisType.name))).scalars().all()
    users = (await db.execute(select(User).order_by(User.username))).scalars().all()
    teams = (await db.execute(select(Team).order_by(Team.name))).scalars().all()
    step_usage = dict((await db.execute(
        select(ProcessStep.step_type_id, func.count()).group_by(ProcessStep.step_type_id))).all())
    analysis_usage = dict((await db.execute(
        select(Analysis.analysis_type_id, func.count()).group_by(Analysis.analysis_type_id))).all())

    # Pop one-time flash from session
    flash = request.session.pop("flash", None)
    flash_error = request.session.pop("flash_error", None)

    return templates.TemplateResponse("admin/index.html", {
        "request": request,
        "step_types": step_types,
        "analysis_types": analysis_types,
        "users": users,
        "teams": teams,
        "step_usage": step_usage,
        "analysis_usage": analysis_usage,
        "current_user": admin,
        "flash": flash,
        "flash_error": flash_error,
        "email_configured": bool(settings.SMTP_PASSWORD),
    })


@router.get("/export.csv")
async def export_database(db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    samples = await load_samples_full(db)
    return await samples_csv(db, samples, Family(samples), f"logbook_full_{date.today():%Y%m%d}.csv")


# ── User management ──────────────────────────────────────────────────────────

@router.post("/users/new")
async def create_user(
    request: Request,
    username: str = Form(...),
    name: str = Form(""),
    email: str = Form(...),
    is_admin: str = Form(""),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    await accounts.create_account(request, db, username, name, email, is_admin=(is_admin == "on"))
    return RedirectResponse("/admin/", status_code=303)


@router.post("/message")
async def send_message(
    request: Request,
    to: str = Form(...),
    subject: str = Form(...),
    body: str = Form(...),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Email everyone ("all") or one user (their id). Each person gets their
    own copy, so recipients don't see each other's addresses."""
    subject, body = subject.strip(), body.strip()
    if not subject or not body:
        request.session["flash_error"] = t(request, "A message needs a subject and some text.")
        return RedirectResponse("/admin/", status_code=303)
    if not settings.SMTP_PASSWORD:
        request.session["flash_error"] = t(request, "Email is not configured, so the message was not sent.")
        return RedirectResponse("/admin/", status_code=303)

    if to == "all":
        recipients = (await db.execute(select(User).where(User.email.is_not(None)).order_by(User.username))).scalars().all()
    elif to.isdigit():
        target = await db.get(User, int(to))
        if not target:
            raise HTTPException(status_code=404, detail="User not found")
        recipients = [target]
    else:
        raise HTTPException(status_code=400, detail="Unknown recipient")
    recipients = [u for u in recipients if u.email]
    if not recipients:
        request.session["flash_error"] = t(request, "No recipient has an email address.")
        return RedirectResponse("/admin/", status_code=303)

    failed = []
    for user in recipients:
        try:
            await send_admin_message(user.email, subject, body)
        except Exception as exc:
            failed.append(f"{user.username} ({exc})")
    sent = len(recipients) - len(failed)
    if sent:
        request.session["flash"] = t(request, "Message sent to {count} user(s).", count=sent)
    if failed:
        request.session["flash_error"] = t(request, "Could not send to: {users}", users=", ".join(failed))
    return RedirectResponse("/admin/", status_code=303)


@router.post("/users/{user_id}/profile")
async def update_user_profile(
    request: Request,
    user_id: int,
    name: str = Form(""),
    initials: str = Form(""),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Admins can fix anyone's name or initials. Changing initials doesn't
    rename existing sample IDs; only new samples use the new initials."""
    target = await db.get(User, user_id)
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    initials = normalize_initials(initials)
    error = await validate_profile(request, db, target, name, initials)
    if error:
        request.session["flash_error"] = f"{target.username}: {error}"
        return RedirectResponse("/admin/", status_code=303)
    target.name = name.strip()
    target.initials = initials
    await db.commit()
    request.session["flash"] = t(request, "Updated {username}: {name} ({initials}).", username=target.username, name=target.name, initials=initials)
    return RedirectResponse("/admin/", status_code=303)


@router.post("/users/{user_id}/toggle-admin")
async def toggle_admin(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot change your own admin status.")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    target.is_admin = not target.is_admin
    await db.commit()
    return RedirectResponse("/admin/", status_code=303)


@router.post("/users/{user_id}/reset-password")
async def reset_user_password(
    request: Request,
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    target = (await db.execute(select(User).where(User.id == user_id))).scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await accounts.reset_password(request, db, target)
    return RedirectResponse("/admin/", status_code=303)


@router.post("/users/{user_id}/delete")
async def delete_user(
    user_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if user_id == admin.id:
        raise HTTPException(status_code=400, detail="Cannot delete your own account.")
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")
    await db.delete(target)
    await db.commit()
    return RedirectResponse("/admin/", status_code=303)


# ── Step & analysis types ─────────────────────────────────────────────────────
# Editing a type's schema only changes the form hints for future edits; the
# parameters already stored on steps/analyses are never touched.

TYPE_MODELS = {"step-types": ProcessStepType, "analysis-types": AnalysisType}
TYPE_USAGE = {"step-types": ProcessStep.step_type_id, "analysis-types": Analysis.analysis_type_id}


def _parse_schema(request: Request, text: str) -> list[dict]:
    """Validate a parameter schema: a JSON list of objects with unique, non-empty keys."""
    try:
        schema = json.loads(text or "[]")
    except json.JSONDecodeError as exc:
        raise ValueError(t(request, "Parameter schema is not valid JSON: {error}", error=exc))
    error = validate_schema(schema)   # field types: see backend/params.py
    if error:
        raise ValueError(error)
    return schema


def _type_model(kind: str):
    if kind not in TYPE_MODELS:
        raise HTTPException(status_code=404, detail="Unknown type kind")
    return TYPE_MODELS[kind]


async def _name_taken(db: AsyncSession, model, name: str, exclude_id: int | None = None) -> bool:
    q = select(model).where(func.lower(model.name) == name.lower())
    if exclude_id is not None:
        q = q.where(model.id != exclude_id)
    return (await db.execute(q)).scalar_one_or_none() is not None


@router.post("/{kind}/new")
async def create_type(
    request: Request,
    kind: str,
    name: str = Form(...),
    description: str = Form(""),
    parameter_schema_json: str = Form("[]"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    model = _type_model(kind)
    name = name.strip()
    try:
        schema = _parse_schema(request, parameter_schema_json)
    except ValueError as exc:
        request.session["flash_error"] = str(exc)
        return RedirectResponse("/admin/", status_code=303)
    if await _name_taken(db, model, name):
        request.session["flash_error"] = t(request, "A type named '{name}' already exists.", name=name)
        return RedirectResponse("/admin/", status_code=303)
    # New techniques get the standard Equipment dropdown (it can be removed by editing the schema)
    db.add(model(name=name, description=description.strip() or None, parameter_schema=with_equipment(schema, name)))
    await db.commit()
    request.session["flash"] = t(request, "Type '{name}' added.", name=name)
    return RedirectResponse("/admin/", status_code=303)


@router.post("/{kind}/{type_id}/edit")
async def update_type(
    request: Request,
    kind: str,
    type_id: int,
    name: str = Form(...),
    description: str = Form(""),
    parameter_schema_json: str = Form("[]"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    model = _type_model(kind)
    obj = (await db.execute(select(model).where(model.id == type_id))).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Type not found")
    name = name.strip()
    try:
        schema = _parse_schema(request, parameter_schema_json)
    except ValueError as exc:
        request.session["flash_error"] = f"{obj.name}: {exc}"
        return RedirectResponse("/admin/", status_code=303)
    if await _name_taken(db, model, name, exclude_id=type_id):
        request.session["flash_error"] = t(request, "A type named '{name}' already exists.", name=name)
        return RedirectResponse("/admin/", status_code=303)
    obj.name = name
    obj.description = description.strip() or None
    obj.parameter_schema = schema
    await db.commit()
    request.session["flash"] = t(request, "Type '{name}' updated. Existing entries keep their stored values.", name=name)
    return RedirectResponse("/admin/", status_code=303)


@router.post("/{kind}/{type_id}/delete")
async def delete_type(
    request: Request,
    kind: str,
    type_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    model = _type_model(kind)
    obj = (await db.execute(select(model).where(model.id == type_id))).scalar_one_or_none()
    if not obj:
        raise HTTPException(status_code=404, detail="Type not found")
    used = (await db.execute(select(func.count()).where(TYPE_USAGE[kind] == type_id))).scalar()
    if used:
        request.session["flash_error"] = (t(request, "Cannot delete '{name}': it is used by 1 entry.", name=obj.name) if used == 1 else
                                         t(request, "Cannot delete '{name}': it is used by {count} entries.", name=obj.name, count=used))
        return RedirectResponse("/admin/", status_code=303)
    await db.delete(obj)
    await db.commit()
    request.session["flash"] = t(request, "Type '{name}' deleted.", name=obj.name)
    return RedirectResponse("/admin/", status_code=303)
