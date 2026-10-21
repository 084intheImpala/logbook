"""'Performed by' on steps and analyses: a user, who then gets access to that
entry, or a typed name for someone without an account."""
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.email_utils import send_performer_email
from backend.i18n import t
from backend.models import User


async def users_for_form(db: AsyncSession) -> list[User]:
    return sorted((await db.execute(select(User))).scalars().all(), key=lambda u: u.display_name.lower())


async def apply_performer(db: AsyncSession, entry, performer: str, performed_by: str) -> User | None:
    """Set who performed `entry` from the form's `performer` choice (a user id,
    "other" with a typed name, or "" for nobody). Returns the user if one was
    newly chosen, so they can be told."""
    previous = entry.performer_id
    user = await db.get(User, int(performer)) if performer.isdigit() else None
    if user:
        entry.performer_id, entry.performed_by = user.id, None
        return user if user.id != previous else None
    entry.performer_id = None
    entry.performed_by = (performed_by.strip() or None) if performer == "other" else None
    return None


async def tell_performer(request: Request, performer: User | None, by: User, samples: list, entry_name: str):
    """Email someone newly recorded as having performed an entry (on one or,
    for a run, several samples). Call after committing."""
    if performer is None or performer.id == by.id or not settings.SMTP_PASSWORD or not performer.email:
        return
    try:
        await send_performer_email(performer.email, by.display_name, samples, entry_name)
    except Exception as exc:
        request.session["flash_error"] = t(request, "Couldn't email {name} ({error}).",
                                           name=performer.display_name, error=exc)
