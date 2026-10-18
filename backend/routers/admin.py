"""Admin routes for managing users and configurations (step/analysis types)."""
import json
import re
import secrets
import string
from datetime import datetime, timedelta, timezone
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import ProcessStepType, AnalysisType, User
from backend.auth import require_login, hash_password
from backend.email_utils import send_welcome_email
from backend.config import settings

router = APIRouter(prefix="/admin", tags=["admin"])
templates = Jinja2Templates(directory="frontend/templates")


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

    # Pop one-time flash from session
    flash = request.session.pop("flash", None)
    flash_error = request.session.pop("flash_error", None)

    return templates.TemplateResponse("admin/index.html", {
        "request": request,
        "step_types": step_types,
        "analysis_types": analysis_types,
        "users": users,
        "current_user": admin,
        "flash": flash,
        "flash_error": flash_error,
        "email_configured": bool(settings.SMTP_PASSWORD),
    })


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
        request.session["flash_error"] = f"Invalid email address: {email}"
        return RedirectResponse("/admin/", status_code=303)

    # Check username uniqueness
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        request.session["flash_error"] = f"Username '{username}' already exists."
        return RedirectResponse("/admin/", status_code=303)

    # Check email uniqueness
    existing_email = await db.execute(select(User).where(User.email == email))
    if existing_email.scalar_one_or_none():
        request.session["flash_error"] = f"Email '{email}' is already registered to another user."
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
            request.session["flash_error"] = f"User created but email failed: {exc}"

    if email_sent:
        request.session["flash"] = f"User '{username}' created — credentials sent to {email}."
    else:
        request.session["flash"] = f"User '{username}' created. Temporary password: {temp_password}"

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
            request.session["flash_error"] = f"Password reset but email failed: {exc}"

    if email_sent:
        request.session["flash"] = f"Password for '{target.username}' reset — new credentials sent to {target.email}."
    else:
        request.session["flash"] = f"Password for '{target.username}' reset. New temporary password: {temp_password}"

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


# ── Step types ────────────────────────────────────────────────────────────────

@router.post("/step-types/new")
async def create_step_type(
    name: str = Form(...),
    description: str = Form(""),
    parameter_schema_json: str = Form("[]"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    schema = json.loads(parameter_schema_json)
    db.add(ProcessStepType(name=name, description=description or None, parameter_schema=schema))
    await db.commit()
    return RedirectResponse("/admin/", status_code=303)


# ── Analysis types ────────────────────────────────────────────────────────────

@router.post("/analysis-types/new")
async def create_analysis_type(
    name: str = Form(...),
    description: str = Form(""),
    parameter_schema_json: str = Form("[]"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    schema = json.loads(parameter_schema_json)
    db.add(AnalysisType(name=name, description=description or None, parameter_schema=schema))
    await db.commit()
    return RedirectResponse("/admin/", status_code=303)
