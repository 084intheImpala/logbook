"""Things waiting for someone's yes or no: entries a teammate proposed on a
sample, and requests for view or edit access.

The owner decides, and so can a coordinator of the owner's team (auth.can_decide),
so a sample whose owner is away isn't stuck. Everyone concerned is told by email.
"""
from fastapi import Request
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import can_decide
from backend.config import settings
from backend.email_utils import send_access_request_email, send_decision_email, send_proposal_email
from backend.i18n import t
from backend.models import AccessRequest, Analysis, ProcessStep, Sample, User


async def pending_entries(db: AsyncSession) -> list[tuple[str, object, Sample]]:
    """Every proposed entry still waiting, as (kind, entry, sample), oldest first."""
    rows = []
    for kind, model in (("step", ProcessStep), ("analysis", Analysis)):
        found = await db.execute(select(model, Sample).join(Sample, Sample.id == model.sample_id)
                                 .where(model.status == "pending"))
        rows += [(kind, e, s) for e, s in found.all()]
    return sorted(rows, key=lambda r: (r[1].proposed_at or r[1].created_at, r[1].id))


async def pending_requests(db: AsyncSession) -> list[AccessRequest]:
    return list((await db.execute(select(AccessRequest).where(AccessRequest.status == "pending")
                                  .order_by(AccessRequest.created_at))).scalars())


async def to_decide(db: AsyncSession, user: User) -> tuple[list, list]:
    """What `user` can approve or decline right now: (entries, requests)."""
    entries = [r for r in await pending_entries(db) if can_decide(user, r[2])]
    requests = [r for r in await pending_requests(db) if can_decide(user, r.sample)]
    return entries, requests


async def count_to_decide(db: AsyncSession, user: User) -> int:
    entries, requests = await to_decide(db, user)
    return len(entries) + len(requests)


# ── Emails (called after committing; a failure is shown, not raised) ─────────

async def _send(request: Request, to: User | None, send, *args):
    if to is None or not settings.SMTP_PASSWORD:
        return
    if not to.email:
        request.session["flash_error"] = t(request, "{name} has no email address, so tell them yourself.",
                                           name=to.display_name)
        return
    try:
        await send(to.email, *args)
    except Exception as exc:
        request.session["flash_error"] = t(request, "Couldn't email {name} ({error}).",
                                           name=to.display_name, error=exc)


async def tell_owner_of_proposal(request: Request, sample: Sample, proposer: User, entry_name: str):
    await _send(request, sample.owner, send_proposal_email, proposer.display_name, sample, entry_name)


async def tell_owner_of_request(request: Request, req: AccessRequest):
    await _send(request, req.sample.owner, send_access_request_email, req.user.display_name, req.sample,
                req.level, req.message)


async def tell_decision(request: Request, to: User | None, decider: User, sample: Sample, what: str, approved: bool):
    if to is not None and to.id != decider.id:
        await _send(request, to, send_decision_email, decider.display_name, sample, what, approved)
