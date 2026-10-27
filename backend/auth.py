"""Auth helpers: password hashing, session deps, custom exception."""
from datetime import datetime, timedelta
from passlib.context import CryptContext
from fastapi import Depends, HTTPException, Request
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func

from backend.config import settings
from backend.database import get_db
from backend.models import User, Sample, Suggestion, SuggestionReply

pwd_context = CryptContext(schemes=["bcrypt"], deprecated="auto")


def hash_password(plain: str) -> str:
    return pwd_context.hash(plain)


def verify_password(plain: str, hashed: str) -> bool:
    return pwd_context.verify(plain, hashed)


class RequiresLoginException(Exception):
    """Raised by require_login dependency; caught in main.py to redirect."""
    pass


class RequiresProfileException(Exception):
    """Raised by require_login when the user hasn't set their name and
    initials yet (needed for sample IDs); main.py redirects to /profile."""
    pass


# Pages a user without initials can still reach
PROFILE_EXEMPT_PATHS = ("/profile", "/change-password", "/logout")


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
    if not user.initials and not request.url.path.startswith(PROFILE_EXEMPT_PATHS):
        raise RequiresProfileException()
    from backend.approvals import count_to_decide   # imported here: approvals imports this module
    user.approval_badge = await count_to_decide(db, user)
    user.suggestion_badge = await _suggestion_badge(db, user)
    user.pending_badge = (await db.execute(
        select(func.count()).select_from(Sample)
        .where(Sample.owner_id == user.id, Sample.requested_by_id.is_not(None))
    )).scalar() or 0
    return user


async def _suggestion_badge(db: AsyncSession, user: User) -> int:
    """Sidebar badge: open suggestions for admins; for everyone else, their
    suggestions with replies from someone else they haven't seen yet."""
    if user.is_admin:
        q = select(func.count()).select_from(Suggestion).where(Suggestion.solved.is_(False))
    else:
        q = (select(func.count(func.distinct(Suggestion.id)))
             .join(SuggestionReply, SuggestionReply.suggestion_id == Suggestion.id)
             .where(Suggestion.user_id == user.id,
                    SuggestionReply.user_id != user.id,
                    SuggestionReply.created_at > func.coalesce(Suggestion.author_seen_at, Suggestion.created_at)))
    return (await db.execute(q)).scalar() or 0


# ── Sample permissions ───────────────────────────────────────────────────────
# Everyone logged in sees a sample's summary (name, materials, tags, which
# techniques were used). Details — parameters, notes, dates, files — need
# view access: the owner, anyone it is shared with, the coordinators of the
# owner's team, and whoever the sample's visibility lets in (team: the owner's
# team, public: everyone). Samples without an owner (created before logins)
# stay open.

def _share_for(user: User, sample):
    return next((sh for sh in sample.shares if sh.user_id == user.id), None)


def is_owner(user: User | None, sample) -> bool:
    """Owner or admin: may delete the sample and manage its sharing."""
    if user is None:
        return False
    return user.is_admin or sample.owner_id is None or sample.owner_id == user.id


def _teams(user: User | None) -> set[int]:
    return {m.team_id for m in user.memberships} if user else set()


def is_coordinator_of(user: User | None, sample) -> bool:
    """A coordinator of a team the sample's owner is in."""
    owner = sample.owner
    if user is None or owner is None or owner.id == user.id:
        return False
    mine = {m.team_id for m in user.memberships if m.is_coordinator}
    return bool(mine & _teams(owner))


def in_owners_team(user: User | None, sample) -> bool:
    return user is not None and sample.owner is not None and bool(_teams(user) & _teams(sample.owner))


def can_view(user: User | None, sample) -> bool:
    if is_owner(user, sample) or (user is not None and _share_for(user, sample) is not None):
        return True
    if user is None:
        return False
    return (sample.visibility == "public"
            or (sample.visibility == "team" and in_owners_team(user, sample))
            or is_coordinator_of(user, sample))


def can_edit(user: User | None, sample) -> bool:
    """True if this user may change the sample, its steps, analyses and files."""
    if is_owner(user, sample):
        return True
    share = user and _share_for(user, sample)
    return bool(share and share.can_edit)


def can_propose(user: User | None, sample) -> bool:
    """Someone in the owner's team, without edit access, may propose an entry for the owner to approve."""
    return (user is not None and sample.owner_id is not None and not can_edit(user, sample)
            and in_owners_team(user, sample))


def is_proposer(user: User | None, entry) -> bool:
    """The author of an entry still waiting for approval can see and change it."""
    return user is not None and entry.status == "pending" and entry.proposed_by_id == user.id


def waited_long_enough(since: datetime | None) -> bool:
    return since is not None and datetime.utcnow() - since >= timedelta(days=settings.APPROVAL_ESCALATION_DAYS)


def can_decide(user: User | None, sample, since: datetime | None) -> bool:
    """Approve a proposed entry or access request made at `since`: the owner (or
    an admin) at any time; a coordinator of the owner's team once the owner
    hasn't answered for APPROVAL_ESCALATION_DAYS."""
    if user is None or sample.owner_id is None:
        return False
    return (user.is_admin or sample.owner_id == user.id
            or (is_coordinator_of(user, sample) and waited_long_enough(since)))


def is_performer(user: User | None, entry) -> bool:
    """Whoever is recorded as having performed a step or analysis can see and
    edit that entry (and its files), even without access to the sample."""
    return user is not None and entry.performer_id == user.id


def can_edit_entry(user: User | None, sample, entry) -> bool:
    return can_edit(user, sample) or is_performer(user, entry) or is_proposer(user, entry)


_CHECKS = {"summary": lambda u, s: True, "view": can_view, "edit": can_edit, "owner": is_owner,
           "propose": lambda u, s: can_edit(u, s) or can_propose(u, s)}


async def load_sample(db: AsyncSession, sample_id: int, user: User | None, need: str = "view"):
    """Fetch a sample, raising 404 if missing or 403 if `user` lacks `need` access."""
    sample = (await db.execute(select(Sample).where(Sample.id == sample_id))).scalar_one_or_none()
    if not sample:
        raise HTTPException(status_code=404, detail="Sample not found")
    if not _CHECKS[need](user, sample):
        raise HTTPException(status_code=403, detail="You don't have access to this sample.")
    return sample
