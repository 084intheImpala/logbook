from backend.config import settings
from datetime import date, datetime, timezone
from fastapi import APIRouter, Depends, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.database import get_db
from backend.models import User, Sample, Project
from backend.auth import hash_password, verify_password, require_login
from backend.sample_ids import INITIALS_RE, normalize_initials
from backend.i18n import t

router = APIRouter()
from backend.templating import templates


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
            "error": t(request, "Invalid username or password."),
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
        error = t(request, "Current password is incorrect.")
    elif len(new_password) < 8:
        error = t(request, "New password must be at least 8 characters.")
    elif new_password != confirm_password:
        error = t(request, "Passwords do not match.")

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
    return RedirectResponse("/samples/" if db_user.initials else "/profile", status_code=303)


# ---------------------------------------------------------------------------
# Profile: display name and the initials used in sample IDs
# ---------------------------------------------------------------------------

async def validate_profile(request: Request, db: AsyncSession, user: User, name: str, initials: str) -> str | None:
    """Return an error message, or None if `name`/`initials` can be saved for `user`."""
    if not name.strip():
        return t(request, "Please enter your name.")
    if not INITIALS_RE.match(initials):
        return t(request, "Initials must be 2 to 4 letters (A–Z).")
    taken = (await db.execute(
        select(User).where(User.initials == initials, User.id != user.id))).scalar_one_or_none()
    if taken:
        return t(request, "The initials {initials} are already used by {name}.", initials=initials, name=taken.display_name)
    centre = (await db.execute(select(Project).where(Project.code == initials))).scalar_one_or_none()
    if centre:
        return t(request, "{initials} is the code of the project {name}; choose other initials.",
                 initials=initials, name=centre.name)
    return None


async def has_samples(db: AsyncSession, user: User) -> bool:
    return (await db.execute(select(func.count()).where(Sample.owner_id == user.id))).scalar() > 0


@router.get("/profile", response_class=HTMLResponse)
async def profile_page(
    request: Request,
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    return templates.TemplateResponse("auth/profile.html", {
        "request": request,
        "current_user": user,
        "error": None,
        "name": user.name or "",
        "initials": user.initials or "",
        "initials_locked": bool(user.initials) and await has_samples(db, user),
        "year": date.today().year,
    })


@router.post("/profile")
async def save_profile(
    request: Request,
    name: str = Form(""),
    initials: str = Form(""),
    user: User = Depends(require_login),
    db: AsyncSession = Depends(get_db),
):
    # Initials are part of existing sample IDs, so only admins change them later.
    locked = bool(user.initials) and await has_samples(db, user)
    initials = user.initials if locked else normalize_initials(initials)
    error = await validate_profile(request, db, user, name, initials)
    if error:
        return templates.TemplateResponse("auth/profile.html", {
            "request": request,
            "current_user": user,
            "error": error,
            "name": name,
            "initials": initials,
            "initials_locked": locked,
            "year": date.today().year,
        }, status_code=400)
    user.name = name.strip()
    user.initials = initials
    await db.commit()
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
