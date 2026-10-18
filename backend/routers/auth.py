from backend.config import settings
from datetime import datetime, timezone
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import User
from backend.auth import hash_password, verify_password, require_login

router = APIRouter()
templates = Jinja2Templates(directory="frontend/templates")


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request):
    if request.session.get("user_id"):
        return RedirectResponse("/samples/", status_code=302)
    return templates.TemplateResponse("auth/login.html", {
        "request": request,
        "error": None,
        "next": request.query_params.get("next", "/samples/"),
    })


@router.post("/login")
async def login(
    request: Request,
    username: str = Form(...),
    password: str = Form(...),
    next: str = Form("/samples/"),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    if not user or not verify_password(password, user.hashed_password):
        return templates.TemplateResponse("auth/login.html", {
            "request": request,
            "error": "Invalid username or password.",
            "next": next,
        }, status_code=401)
    request.session["user_id"] = user.id
    if user.must_change_password:
        return RedirectResponse("/change-password", status_code=303)
    return RedirectResponse(next if next.startswith("/") else "/samples/", status_code=303)


@router.post("/logout")
async def logout(request: Request):
    request.session.pop("user_id", None)
    return RedirectResponse("/login", status_code=303)


@router.get("/change-password", response_class=HTMLResponse)
async def change_password_page(
    request: Request,
    user: User = Depends(require_login),
):
    forced = user.must_change_password
    magic = request.session.get("magic_login", False)
    return templates.TemplateResponse("auth/change_password.html", {
        "request": request,
        "error": None,
        "forced": forced,
        "magic": magic,
    })


@router.post("/change-password")
async def change_password(
    request: Request,
    current_password: str = Form(default=""),
    new_password: str = Form(...),
    confirm_password: str = Form(...),
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    forced = user.must_change_password
    magic = request.session.get("magic_login", False)
    error = None

    if not magic and not verify_password(current_password, user.hashed_password):
        error = "Current password is incorrect."
    elif len(new_password) < 8:
        error = "New password must be at least 8 characters."
    elif new_password != confirm_password:
        error = "Passwords do not match."

    if error:
        return templates.TemplateResponse("auth/change_password.html", {
            "request": request,
            "error": error,
            "forced": forced,
            "magic": magic,
        }, status_code=400)

    result = await db.execute(select(User).where(User.id == user.id))
    db_user = result.scalar_one()
    db_user.hashed_password = hash_password(new_password)
    db_user.must_change_password = False
    await db.commit()
    request.session.pop("magic_login", None)
    return RedirectResponse("/samples/", status_code=303)

@router.get("/magic", response_class=HTMLResponse)
async def magic_login(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
):
    """One-time login link sent in welcome / password-reset emails."""
    result = await db.execute(select(User).where(User.login_token == token))
    user = result.scalar_one_or_none()

    if not user or not user.login_token_expires:
        return templates.TemplateResponse("auth/magic_expired.html", {"request": request}, status_code=400)

    if datetime.utcnow() > user.login_token_expires:
        return templates.TemplateResponse("auth/magic_expired.html", {"request": request}, status_code=400)

    # Valid — log the user in and clear the token
    user.login_token = None
    user.login_token_expires = None
    await db.commit()

    request.session["user_id"] = user.id
    request.session["magic_login"] = True
    return RedirectResponse("/change-password", status_code=303)


# ---------------------------------------------------------------------------
# Forgot-password flow
# ---------------------------------------------------------------------------

@router.get("/forgot-password", response_class=HTMLResponse)
async def forgot_password_page(request: Request):
    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request,
        "sent": False,
        "error": None,
    })


@router.post("/forgot-password", response_class=HTMLResponse)
async def forgot_password(
    request: Request,
    email: str = Form(...),
    db: AsyncSession = Depends(get_db),
):
    from datetime import timedelta
    from backend.email_utils import send_password_reset_email
    from backend.routers.admin import _generate_login_token  # reuse helper

    # Always show the "check your email" page — don't reveal whether the
    # address exists in the system.
    result = await db.execute(
        select(User).where(User.email == email.strip().lower())
    )
    user = result.scalar_one_or_none()

    if user:
        token = _generate_login_token(user)
        await db.commit()
        magic_link = f"{settings.BASE_URL}/magic?token={token}"
        try:
            await send_password_reset_email(to=user.email, username=user.username, magic_link=magic_link)
        except Exception:
            pass  # silently swallow — we don't reveal send failures

    return templates.TemplateResponse("auth/forgot_password.html", {
        "request": request,
        "sent": True,
        "error": None,
    })
