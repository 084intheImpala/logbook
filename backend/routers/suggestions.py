"""Suggestions: anyone can send one; admins answer and mark them solved.
Each suggestion is a short thread between its author and the admins."""
from fastapi import APIRouter, Depends, HTTPException, Request, Form
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import Suggestion, SuggestionReply, User, SUGGESTION_KINDS
from backend.auth import require_login
from backend.routers.admin import require_admin

router = APIRouter(tags=["suggestions"])
templates = Jinja2Templates(directory="frontend/templates")

STATUS_FILTERS = {"open": "Open", "solved": "Solved", "all": "All"}


def _safe_page(page: str) -> str | None:
    """Only keep in-app paths (it's displayed as a link)."""
    page = page.strip()
    return page[:300] if page.startswith("/") and not page.startswith("//") else None


async def _get(db: AsyncSession, suggestion_id: int) -> Suggestion:
    suggestion = await db.get(Suggestion, suggestion_id)
    if not suggestion:
        raise HTTPException(status_code=404, detail="Suggestion not found")
    return suggestion


@router.get("/suggestions", response_class=HTMLResponse)
async def my_suggestions(
    request: Request,
    page: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    mine = (await db.execute(
        select(Suggestion).where(Suggestion.user_id == current_user.id).order_by(Suggestion.id.desc())
    )).scalars().all()
    # Flag replies that arrived since the author last looked, then mark all seen
    unread = {
        s.id for s in mine
        if any(r.user_id != current_user.id and r.created_at > (s.author_seen_at or s.created_at)
               for r in s.replies)
    }
    response = templates.TemplateResponse("suggestions/index.html", {
        "request": request,
        "current_user": current_user,
        "suggestions": mine,
        "unread": unread,
        "kinds": SUGGESTION_KINDS,
        "page": _safe_page(page),
        "flash": request.session.pop("flash", None),
    })
    if mine:
        for s in mine:
            s.author_seen_at = func.now()
        await db.commit()
    return response


@router.post("/suggestions")
async def submit_suggestion(
    request: Request,
    text: str = Form(""),
    kind: str = Form("idea"),
    page: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    if not text.strip():
        request.session["flash"] = "Please write something before sending."
        return RedirectResponse("/suggestions", status_code=303)
    db.add(Suggestion(
        user_id=current_user.id,
        kind=kind if kind in SUGGESTION_KINDS else "idea",
        text=text.strip(),
        page=_safe_page(page),
        author_seen_at=func.now(),
    ))
    await db.commit()
    request.session["flash"] = "Thanks! Your suggestion was sent to the admins."
    return RedirectResponse("/suggestions", status_code=303)


@router.post("/suggestions/{suggestion_id}/reply")
async def reply(
    request: Request,
    suggestion_id: int,
    text: str = Form(""),
    back: str = Form("/suggestions"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    """The author and admins can add to the thread."""
    suggestion = await _get(db, suggestion_id)
    if not (current_user.is_admin or suggestion.user_id == current_user.id):
        raise HTTPException(status_code=403, detail="You can only reply to your own suggestions.")
    if text.strip():
        db.add(SuggestionReply(suggestion_id=suggestion_id, user_id=current_user.id, text=text.strip()))
        if suggestion.user_id == current_user.id:
            suggestion.author_seen_at = func.now()
        await db.commit()
    back = _safe_page(back) or "/suggestions"
    return RedirectResponse(f"{back}#suggestion-{suggestion_id}", status_code=303)


# ── Admin inbox ───────────────────────────────────────────────────────────────

@router.get("/admin/suggestions", response_class=HTMLResponse)
async def inbox(
    request: Request,
    status: str = "open",
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    if status not in STATUS_FILTERS:
        status = "open"
    q = select(Suggestion).order_by(Suggestion.id.desc())
    if status != "all":
        q = q.where(Suggestion.solved.is_(status == "solved"))
    counts = dict((await db.execute(select(Suggestion.solved, func.count()).group_by(Suggestion.solved))).all())
    return templates.TemplateResponse("suggestions/inbox.html", {
        "request": request,
        "current_user": admin,
        "suggestions": (await db.execute(q)).scalars().all(),
        "status": status,
        "status_filters": STATUS_FILTERS,
        "counts": {"open": counts.get(False, 0), "solved": counts.get(True, 0),
                   "all": sum(counts.values())},
    })


@router.post("/admin/suggestions/{suggestion_id}/status")
async def set_status(
    suggestion_id: int,
    solved: str = Form(...),
    back: str = Form("/admin/suggestions"),
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(require_admin),
):
    suggestion = await _get(db, suggestion_id)
    suggestion.solved = solved == "1"
    suggestion.solved_at = func.now() if suggestion.solved else None
    await db.commit()
    return RedirectResponse(_safe_page(back) or "/admin/suggestions", status_code=303)
