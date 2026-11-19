"""Creating accounts and resetting passwords, used by admins (routers/admin.py)
and by team coordinators for their own team (routers/team.py).

An account can be made without an email, for someone who has left but still
has samples: it gets initials (for its samples' IDs) and a password nobody is
told, so nobody logs in as them; admins and their team's coordinators give
them samples from each sample's Edit page. If they come back, resetting the
password gives them one."""
import re
import secrets
import string
from datetime import datetime, timedelta

from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.activity import log as log_activity
from backend.auth import hash_password
from backend.config import settings
from backend.email_utils import send_welcome_email
from backend.i18n import t
from backend.models import Team, TeamMember, User
from backend.sample_ids import normalize_initials


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
                         is_admin: bool = False, team: Team | None = None,
                         actor: User | None = None, initials: str = "") -> User | None:
    """Create a user with a temporary password and email them their credentials
    (or show the password in the flash message if email isn't set up). They join
    `team` if given. With no `email`, an account nobody logs in to (see above):
    it needs a name and initials. Returns the user, or None after flashing why not."""
    from backend.routers.auth import validate_profile   # (routers.auth is imported after this module)
    username = username.strip()
    email = email.strip().lower()
    initials = normalize_initials(initials)

    if not username:
        request.session["flash_error"] = t(request, "Give a username.")
        return None
    if email and not re.match(r"^[^@\s]+@[^@\s]+\.[^@\s]+$", email):
        request.session["flash_error"] = t(request, "Invalid email address: {email}", email=email)
        return None
    if (await db.execute(select(User).where(User.username == username))).scalar_one_or_none():
        request.session["flash_error"] = t(request, "Username '{username}' already exists.", username=username)
        return None
    if email and (await db.execute(select(User).where(User.email == email))).scalar_one_or_none():
        request.session["flash_error"] = t(request, "Email '{email}' is already registered to another user.", email=email)
        return None
    if not email and is_admin:
        request.session["flash_error"] = t(request, "An admin needs an email address.")
        return None
    if initials or not email:   # without an email they never log in to set them, so they are needed now
        error = await validate_profile(request, db, User(), name, initials)
        if error:
            request.session["flash_error"] = (
                t(request, "Without an email, give the person's name and initials: {error}", error=error)
                if not email else error)
            return None

    temp_password = _generate_password()
    new_user = User(
        username=username,
        name=name.strip() or None,
        email=email or None,
        initials=initials or None,
        hashed_password=hash_password(temp_password if email else secrets.token_urlsafe(32)),
        is_admin=is_admin,
        must_change_password=True,
    )
    db.add(new_user)
    await db.flush()  # get new_user.id
    if team is not None:
        db.add(TeamMember(team_id=team.id, user_id=new_user.id))
    details = [f"team: {team.name}"] if team else []
    if not email:
        details.append("no email, no login")
        log_activity(db, actor, "user_created", username, new_user, ", ".join(details))
        await db.commit()
        request.session["flash"] = t(
            request, "User '{username}' created without an email: they can't log in. Give them samples from each "
                     "sample's Edit page.", username=username)
        return new_user
    magic_token = _generate_login_token(new_user)
    log_activity(db, actor, "user_created", username, new_user, ", ".join(details) or None)
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


async def reset_password(request: Request, db: AsyncSession, target: User, actor: User | None = None) -> None:
    """Give `target` a new temporary password, emailed to them (or shown in the flash message)."""
    temp_password = _generate_password()
    target.hashed_password = hash_password(temp_password)
    target.must_change_password = True
    magic_token = _generate_login_token(target)
    log_activity(db, actor, "password_reset", target.username, target)
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
