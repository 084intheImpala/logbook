"""Approving or declining what is waiting for you: entries teammates proposed
on your samples, and requests for access to them (see backend/approvals.py)."""
from datetime import datetime

from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import approvals
from backend.auth import can_decide, can_edit, can_view, load_sample, require_login
from backend.database import get_db
from backend.i18n import t
from backend.models import (AccessRequest, Analysis, AnalysisType, Attachment, ProcessStep, ProcessStepType,
                            Sample, SampleShare, User)
from backend.templating import templates
from backend.timeline import place_new, renumber
from backend.utils import delete_attachment

router = APIRouter(tags=["approvals"])
KINDS = {"step": (ProcessStep, ProcessStepType, "step_type_id"),
         "analysis": (Analysis, AnalysisType, "analysis_type_id")}


async def _type_name(db: AsyncSession, kind: str, entry) -> str:
    _, type_model, fk = KINDS[kind]
    return (await db.get(type_model, getattr(entry, fk))).name


@router.get("/approvals", response_class=HTMLResponse)
async def inbox(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_login)):
    entries, requests = await approvals.to_decide(db, current_user)
    rows = []
    for kind, entry, sample in entries:
        proposer = await db.get(User, entry.proposed_by_id) if entry.proposed_by_id else None
        rows.append(dict(kind=kind, entry=entry, sample=sample, proposer=proposer,
                         type_name=await _type_name(db, kind, entry)))
    mine = []
    for kind, entry, sample in await approvals.pending_entries(db):
        if entry.proposed_by_id == current_user.id:
            mine.append(dict(kind=kind, entry=entry, sample=sample, type_name=await _type_name(db, kind, entry)))
    my_requests = list((await db.execute(select(AccessRequest).where(
        AccessRequest.user_id == current_user.id, AccessRequest.status == "pending")
        .order_by(AccessRequest.created_at))).scalars())
    return templates.TemplateResponse("approvals/index.html", {
        "request": request, "current_user": current_user, "entries": rows, "requests": requests,
        "mine": mine, "my_requests": my_requests,
        "flash": request.session.pop("flash", None), "flash_error": request.session.pop("flash_error", None),
    })


async def _pending_entry(db: AsyncSession, kind: str, entry_id: int):
    if kind not in KINDS:
        raise HTTPException(status_code=404, detail="Unknown entry kind")
    entry = await db.get(KINDS[kind][0], entry_id)
    if entry is None or entry.status != "pending":
        raise HTTPException(status_code=404, detail="Nothing pending here")
    return entry, await db.get(Sample, entry.sample_id)


def _back(request: Request, default: str) -> RedirectResponse:
    back = request.query_params.get("back", default)
    return RedirectResponse(back if back.startswith("/") and not back.startswith("//") else default, status_code=303)


@router.post("/approvals/entries/{kind}/{entry_id}/approve")
async def approve_entry(request: Request, kind: str, entry_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_login)):
    entry, sample = await _pending_entry(db, kind, entry_id)
    if not can_decide(current_user, sample):
        raise HTTPException(status_code=403, detail="You can't decide this.")
    entry.status = "approved"
    await db.flush()
    await place_new(db, entry)
    name, proposer = await _type_name(db, kind, entry), await db.get(User, entry.proposed_by_id or 0)
    await db.commit()
    request.session["flash"] = t(request, "Approved: {name} is now on {sample}.", name=name, sample=sample.title)
    await approvals.tell_decision(request, proposer, current_user, sample, name, True)
    return _back(request, "/approvals")


@router.post("/approvals/entries/{kind}/{entry_id}/reject")
async def reject_entry(request: Request, kind: str, entry_id: int, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    """Declining deletes the proposal (and anything attached to it); the author is told."""
    entry, sample = await _pending_entry(db, kind, entry_id)
    proposer_id = entry.proposed_by_id
    is_author = proposer_id == current_user.id
    if not is_author and not can_decide(current_user, sample):
        raise HTTPException(status_code=403, detail="You can't decide this.")
    name, proposer = await _type_name(db, kind, entry), await db.get(User, proposer_id or 0)
    for att in (await db.execute(select(Attachment).where(
            Attachment.entity_type == kind, Attachment.entity_id == entry_id))).scalars():
        await delete_attachment(att, db)
    await db.delete(entry)
    await db.commit()
    request.session["flash"] = (t(request, "Withdrawn: {name}.", name=name) if is_author
                                else t(request, "Declined: {name}.", name=name))
    if not is_author:
        await approvals.tell_decision(request, proposer, current_user, sample, name, False)
    return _back(request, "/approvals")


# ── Requests for access ──────────────────────────────────────────────────────

@router.post("/samples/{sample_id}/request-access")
async def request_access(request: Request, sample_id: int, level: str = Form("view"), message: str = Form(""),
                         db: AsyncSession = Depends(get_db), current_user: User = Depends(require_login)):
    sample = await load_sample(db, sample_id, current_user, "summary")
    back = RedirectResponse(f"/samples/{sample_id}", status_code=303)
    if level not in ("view", "edit"):
        raise HTTPException(status_code=400, detail="Unknown access level")
    if sample.owner_id is None or sample.owner_id == current_user.id:
        return back
    if (can_edit(current_user, sample) if level == "edit" else can_view(current_user, sample)):
        request.session["flash"] = t(request, "You already have that access.")
        return back
    req = (await db.execute(select(AccessRequest).where(
        AccessRequest.sample_id == sample_id, AccessRequest.user_id == current_user.id,
        AccessRequest.level == level, AccessRequest.status == "pending"))).scalar_one_or_none()
    if req is None:
        req = AccessRequest(sample_id=sample_id, user_id=current_user.id, level=level)
        db.add(req)
    req.message = message.strip() or None
    await db.commit()
    request.session["flash"] = t(request, "Request sent to {name}.", name=sample.owner.display_name)
    await approvals.tell_owner_of_request(request, req)
    return back


@router.post("/approvals/requests/{request_id}/approve")
async def approve_request(request: Request, request_id: int, db: AsyncSession = Depends(get_db),
                          current_user: User = Depends(require_login)):
    req = await _pending_request(db, request_id, current_user)
    sample, wants_edit = req.sample, req.level == "edit"
    share = next((sh for sh in sample.shares if sh.user_id == req.user_id), None)
    if share is None:
        sample.shares.append(SampleShare(user_id=req.user_id, can_edit=wants_edit))
    else:
        share.can_edit = share.can_edit or wants_edit
    req.status, req.decided_by_id, req.decided_at = "approved", current_user.id, datetime.utcnow()
    await db.commit()
    request.session["flash"] = t(request, "{name} now has {level} access to {sample}.", name=req.user.display_name,
                                 level=t(request, "edit") if wants_edit else t(request, "view"), sample=sample.title)
    await approvals.tell_decision(request, req.user, current_user, sample,
                                  "edit access" if wants_edit else "view access", True)
    return _back(request, "/approvals")


@router.post("/approvals/requests/{request_id}/deny")
async def deny_request(request: Request, request_id: int, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    req = await _pending_request(db, request_id, current_user, allow_requester=True)
    withdrawn = req.user_id == current_user.id and not can_decide(current_user, req.sample)
    req.status, req.decided_by_id, req.decided_at = "denied", current_user.id, datetime.utcnow()
    await db.commit()
    request.session["flash"] = t(request, "Request withdrawn.") if withdrawn else t(request, "Request declined.")
    if not withdrawn:
        await approvals.tell_decision(request, req.user, current_user, req.sample,
                                      "edit access" if req.level == "edit" else "view access", False)
    return _back(request, "/approvals")


async def _pending_request(db: AsyncSession, request_id: int, user: User, allow_requester: bool = False) -> AccessRequest:
    req = await db.get(AccessRequest, request_id)
    if req is None or req.status != "pending":
        raise HTTPException(status_code=404, detail="Nothing pending here")
    if not (can_decide(user, req.sample) or (allow_requester and req.user_id == user.id)):
        raise HTTPException(status_code=403, detail="You can't decide this.")
    return req
