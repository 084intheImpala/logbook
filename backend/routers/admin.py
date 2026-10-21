"""Admin routes for managing users and configurations (step/analysis types)."""
import json
import re
import secrets
import string
from datetime import date, datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.database import get_db
from backend.models import ProcessStepType, AnalysisType, ProcessStep, Analysis, User, ChoiceOption
from backend.params import validate_schema, lists_used, located_lists, with_equipment
from backend.choices import LOCATION_LIST
from backend.auth import require_login, hash_password
from backend.email_utils import send_welcome_email
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


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _generate_login_token(user, expires_hours: int = 72) -> str:
    """Generate a one-time login token, set on the user object."""
    token = secrets.token_urlsafe(32)
    user.login_token = token
    user.login_token_expires = datetime.utcnow() + timedelta(hours=expires_hours)
    return token


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
    step_usage = dict((await db.execute(
        select(ProcessStep.step_type_id, func.count()).group_by(ProcessStep.step_type_id))).all())
    analysis_usage = dict((await db.execute(
        select(Analysis.analysis_type_id, func.count()).group_by(Analysis.analysis_type_id))).all())

    # Dropdown lists: every list with values, plus empty ones a schema uses
    choice_lists: dict[str, list[ChoiceOption]] = {
        name: [] for name in lists_used(ty.parameter_schema for ty in [*step_types, *analysis_types])}
    for opt in (await db.execute(select(ChoiceOption))).scalars():
        choice_lists.setdefault(opt.list, []).append(opt)
    choice_lists = {name: sorted(opts, key=lambda o: o.value.lower())
                    for name, opts in sorted(choice_lists.items())}
    located = set().union(*(located_lists(ty.parameter_schema) for ty in [*step_types, *analysis_types]))

    # Pop one-time flash from session
    flash = request.session.pop("flash", None)
    flash_error = request.session.pop("flash_error", None)

    return templates.TemplateResponse("admin/index.html", {
        "request": request,
        "step_types": step_types,
        "analysis_types": analysis_types,
        "users": users,
        "step_usage": step_usage,
        "choice_lists": choice_lists,
        "located_lists": located,
        "places": [o.value for o in choice_lists.get(LOCATION_LIST, [])],
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
    username = username.strip()
    email = email.strip().lower()

    # Validate email format
    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        request.session["flash_error"] = t(request, "Invalid email address: {email}", email=email)
        return RedirectResponse("/admin/", status_code=303)

    # Check username uniqueness
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        request.session["flash_error"] = t(request, "Username '{username}' already exists.", username=username)
        return RedirectResponse("/admin/", status_code=303)

    # Check email uniqueness
    existing_email = await db.execute(select(User).where(User.email == email))
    if existing_email.scalar_one_or_none():
        request.session["flash_error"] = t(request, "Email '{email}' is already registered to another user.", email=email)
        return RedirectResponse("/admin/", status_code=303)

    temp_password = _generate_password()
    new_user = User(
        username=username,
        name=name.strip() or None,
        email=email,
        hashed_password=hash_password(temp_password),
        is_admin=(is_admin == "on"),
        must_change_password=True,
    )
    db.add(new_user)
    await db.flush()  # get new_user.id
    magic_token = _generate_login_token(new_user)
    await db.commit()

    # Send welcome email
    email_sent = False
    if settings.SMTP_PASSWORD:
        magic_link = f"{settings.BASE_URL}/magic?token={magic_token}"
        try:
            await send_welcome_email(email, username, temp_password, magic_link)
            email_sent = True
        except Exception as exc:
            request.session["flash_error"] = t(request, "User created but email failed: {error}", error=exc)

    if email_sent:
        request.session["flash"] = t(request, "User '{username}' created — credentials sent to {email}.", username=username, email=email)
    else:
        request.session["flash"] = t(request, "User '{username}' created. Temporary password: {password}", username=username, password=temp_password)

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
    result = await db.execute(select(User).where(User.id == user_id))
    target = result.scalar_one_or_none()
    if not target:
        raise HTTPException(status_code=404, detail="User not found")

    temp_password = _generate_password()
    target.hashed_password = hash_password(temp_password)
    target.must_change_password = True
    magic_token = _generate_login_token(target)
    await db.commit()

    email_sent = False
    if settings.SMTP_PASSWORD and target.email:
        magic_link = f"{settings.BASE_URL}/magic?token={magic_token}"
        try:
            await send_welcome_email(target.email, target.username, temp_password, magic_link)
            email_sent = True
        except Exception as exc:
            request.session["flash_error"] = t(request, "Password reset but email failed: {error}", error=exc)

    if email_sent:
        request.session["flash"] = t(request, "Password for '{username}' reset — new credentials sent to {email}.", username=target.username, email=target.email)
    else:
        request.session["flash"] = t(request, "Password for '{username}' reset. New temporary password: {password}", username=target.username, password=temp_password)

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


# ── Dropdown lists ────────────────────────────────────────────────────────────
# Values are added from the step/analysis forms as people type them; admins
# can also add values here, and remove typos or values no longer used.
# Entries that already use a removed value keep it. (Registered before the
# type routes: /admin/{kind}/new would otherwise match /admin/choices/new.)

@router.post("/choices/new")
async def add_choice(
    request: Request,
    list_name: str = Form(...),
    value: str = Form(...),
    location: str = Form(""),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    list_name, value = list_name.strip(), value.strip()[:200]
    exists = (await db.execute(select(ChoiceOption).where(
        ChoiceOption.list == list_name, func.lower(ChoiceOption.value) == value.lower()))).scalar_one_or_none()
    if list_name and value and not exists:
        db.add(ChoiceOption(list=list_name, value=value, created_by_id=admin.id, location=location.strip() or None))
        await db.commit()
    return RedirectResponse("/admin/#choices", status_code=303)


@router.post("/choices/{option_id}/location")
async def set_choice_location(
    option_id: int,
    location: str = Form(""),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    """Move a piece of equipment to another place."""
    option = await db.get(ChoiceOption, option_id)
    if option:
        option.location = location.strip() or None
        await db.commit()
    return RedirectResponse("/admin/#choices", status_code=303)


@router.post("/choices/{option_id}/delete")
async def delete_choice(
    option_id: int,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    option = await db.get(ChoiceOption, option_id)
    if option:
        await db.delete(option)
        await db.commit()
    return RedirectResponse("/admin/#choices", status_code=303)


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
