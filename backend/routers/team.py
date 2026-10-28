"""The "My team" page: what a team's coordinators can do without an admin.

They add people who have no team yet, remove members (not coordinators:
appointing and removing coordinators, and creating or deleting teams, is for
admins), create accounts for new members and reset their passwords. Admins can
use these routes for any team too.
"""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend import accounts
from backend.auth import require_login
from backend.database import get_db
from backend.i18n import t
from backend.models import Sample, Team, TeamMember, User
from backend.templating import templates

router = APIRouter(prefix="/team", tags=["team"])
BACK = "/team"


async def _my_team(db: AsyncSession, user: User, team_id: int) -> Team:
    """The team, if `user` coordinates it (or is an admin)."""
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    if not (user.is_admin or any(m.team_id == team_id and m.is_coordinator for m in user.memberships)):
        raise HTTPException(status_code=403, detail="Only this team's coordinators can do that.")
    return team


async def _member(db: AsyncSession, team_id: int, user_id: int) -> TeamMember:
    member = (await db.execute(select(TeamMember).where(
        TeamMember.team_id == team_id, TeamMember.user_id == user_id))).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Not a member of this team")
    return member


@router.get("", response_class=HTMLResponse)
async def my_team(request: Request, db: AsyncSession = Depends(get_db), current_user: User = Depends(require_login)):
    if not current_user.is_coordinator:
        raise HTTPException(status_code=403, detail="Only team coordinators have a team page.")
    ids = {m.team_id for m in current_user.memberships if m.is_coordinator}
    teams = (await db.execute(select(Team).where(Team.id.in_(ids)).order_by(Team.name))).scalars().all()
    unassigned = [u for u in (await db.execute(select(User).order_by(User.username))).scalars() if not u.memberships]
    counts = {}
    for team in teams:
        owners = [m.user_id for m in team.members]
        counts[team.id] = {uid: n for uid, n in (await db.execute(
            select(Sample.owner_id, func.count()).where(Sample.owner_id.in_(owners)).group_by(Sample.owner_id))).all()}
    return templates.TemplateResponse("team/index.html", {
        "request": request, "current_user": current_user, "teams": teams, "unassigned": unassigned, "counts": counts,
        "flash": request.session.pop("flash", None), "flash_error": request.session.pop("flash_error", None),
    })


@router.post("/{team_id}/members")
async def add_member(request: Request, team_id: int, user_id: int = Form(...), db: AsyncSession = Depends(get_db),
                     current_user: User = Depends(require_login)):
    team = await _my_team(db, current_user, team_id)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    if user.memberships:   # people normally belong to one team: an admin moves them between teams
        request.session["flash_error"] = t(request, "{name} is already in a team; ask an admin to move them.",
                                           name=user.display_name)
    else:
        team.members.append(TeamMember(user_id=user_id))
        await db.commit()
    return RedirectResponse(BACK, status_code=303)


@router.post("/{team_id}/members/{user_id}/remove")
async def remove_member(request: Request, team_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_login)):
    await _my_team(db, current_user, team_id)
    member = await _member(db, team_id, user_id)
    if member.is_coordinator and not current_user.is_admin:
        request.session["flash_error"] = t(request, "Only an admin can remove a coordinator.")
    else:
        await db.delete(member)
        await db.commit()
    return RedirectResponse(BACK, status_code=303)


@router.post("/{team_id}/users/new")
async def create_member(request: Request, team_id: int, username: str = Form(...), name: str = Form(""),
                        email: str = Form(...), db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_login)):
    team = await _my_team(db, current_user, team_id)
    await accounts.create_account(request, db, username, name, email, team=team)
    return RedirectResponse(BACK, status_code=303)


@router.post("/{team_id}/members/{user_id}/reset-password")
async def reset_member_password(request: Request, team_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                                current_user: User = Depends(require_login)):
    await _my_team(db, current_user, team_id)
    member = await _member(db, team_id, user_id)
    if (member.is_coordinator or member.user.is_admin) and member.user_id != current_user.id and not current_user.is_admin:
        raise HTTPException(status_code=403, detail="Only an admin can reset a coordinator's or admin's password.")
    await accounts.reset_password(request, db, member.user)
    return RedirectResponse(BACK, status_code=303)
