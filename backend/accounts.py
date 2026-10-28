"""Creating accounts and resetting passwords, used by admins (routers/admin.py)
and by team coordinators for their own team (routers/team.py)."""
import re
import secrets
import string
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import hash_password
from backend.config import settings
from backend.email_utils import send_welcome_email
from backend.i18n import t
from backend.models import Team, TeamMember, User


def _generate_password(length: int = 12) -> str:
    alphabet = string.ascii_letters + string.digits + "!@#$%"
    return "".join(secrets.choice(alphabet) for _ in range(length))


def _generate_login_token(user, expires_hours: int = 72) -> str:
    """Generate a one-time login token, set on the user object."""
    token = secrets.token_urlsafe(32)
    user.login_token = token
    user.login_token_expires = datetime.utcnow() + timedelta(hours=expires_hours)
    return token


async def create_account(request: Request, db: AsyncSession, username: str, name: str, email: str,
                         is_admin: bool = False, team: Team | None = None) -> User | None:
    """Create a user with a temporary password and email them their credentials
    (or show the password in the flash message if email isn't set up). They join
    `team` if given. Returns the user, or None after flashing why not."""
    username = username.strip()
    email = email.strip().lower()

    if not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        request.session["flash_error"] = t(request, "Invalid email address: {email}", email=email)
        return None
    if (await db.execute(select(User).where(User.username == username))).scalar_one_or_none():
        request.session["flash_error"] = t(request, "Username '{username}' already exists.", username=username)
        return None
    if (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        request.session["flash_error"] = t(request, "Email '{email}' is already registered to another user.", email=email)
        return None

    temp_password = _generate_password()
    new_user = User(
        username=username,
        name=name.strip() or None,
        email=email,
        hashed_password=hash_password(temp_password),
        is_admin=is_admin,
        must_change_password=True,
    )
    db.add(new_user)
    await db.flush()  # get new_user.id
    if team is not None:
        db.add(TeamMember(team_id=team.id, user_id=new_user.id))
    magic_token = _generate_login_token(new_user)
    await db.commit()

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
    return new_user


async def reset_password(request: Request, db: AsyncSession, target: User) -> None:
    """Give `target` a new temporary password, emailed to them (or shown in the flash message)."""
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
