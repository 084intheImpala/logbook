"""The activity log page: all of it for admins, and for a team's coordinators
the entries that concern their team's members."""
from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.activity import ACTIONS
from backend.auth import require_login
from backend.database import get_db
from backend.models import ActivityLog, Team, User
from backend.templating import templates

router = APIRouter(tags=["activity"])
LIMIT = 300


@router.get("/activity", response_class=HTMLResponse)
async def activity(request: Request, action: str = "", db: AsyncSession = Depends(get_db),
                   current_user: User = Depends(require_login)):
    if not (current_user.is_admin or current_user.is_coordinator):
        raise HTTPException(status_code=403, detail="Only admins and team coordinators can see the activity log.")
    query = select(ActivityLog).order_by(ActivityLog.id.desc()).limit(LIMIT)
    if action in ACTIONS:
        query = query.where(ActivityLog.action == action)
    if not current_user.is_admin:
        ids = {m.team_id for m in current_user.memberships if m.is_coordinator}
        teams = (await db.execute(select(Team).where(Team.id.in_(ids)))).scalars().all()
        people = {m.user_id for team in teams for m in team.members}
        query = query.where(or_(ActivityLog.subject_user_id.in_(people), ActivityLog.actor_id.in_(people)))
    return templates.TemplateResponse("activity/index.html", {
        "request": request, "current_user": current_user, "rows": (await db.execute(query)).scalars().all(),
        "actions": ACTIONS, "action": action, "limit": LIMIT,
    })
