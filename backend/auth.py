"""Auth helpers: password hashing, session deps, custom exception."""
from passlib.context import CryptContext
from fastapi import Depends, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import User

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


class RequiresLoginException(Exception):
    """Raised by require_login dependency; caught in main.py to redirect."""
    pass


async def get_current_user(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User | None:
    """Return the logged-in User or None if not authenticated."""
    user_id = request.session.get("user_id")
    if not user_id:
        return None
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if not user:
        # stale session — clear it
        request.session.pop("user_id", None)
    return user


async def require_login(
    request: Request,
    db: AsyncSession = Depends(get_db),
) -> User:
    """Return the logged-in User or raise RequiresLoginException."""
    user = await get_current_user(request, db)
    if not user:
        raise RequiresLoginException()
    return user


def can_edit(user: User | None, sample) -> bool:
    """True if this user may edit/delete the given sample."""
    if user is None:
        return False
    if user.is_admin:
        return True
    if sample.owner_id is None:
        return True   # legacy sample (pre-auth): anyone logged in can edit
    return sample.owner_id == user.id
