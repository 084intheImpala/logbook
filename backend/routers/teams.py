"""Admin routes for teams: the groups inside the lab. A team's coordinators can
see all of its members' samples (see backend/auth.py)."""
from fastapi import APIRouter, Depends, Form, HTTPException, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.activity import log as log_activity
from backend.database import get_db
from backend.i18n import t
from backend.models import Team, TeamMember, User
from backend.routers.admin import require_admin

router = APIRouter(prefix="/admin/teams", tags=["teams"])
BACK = "/admin/#teams"


async def _team(db: AsyncSession, team_id: int) -> Team:
    team = await db.get(Team, team_id)
    if team is None:
        raise HTTPException(status_code=404, detail="Team not found")
    return team


async def _name_taken(db: AsyncSession, name: str, exclude_id: int | None = None) -> bool:
    q = select(Team.id).where(Team.name == name)
    if exclude_id:
        q = q.where(Team.id != exclude_id)
    return (await db.execute(q)).first() is not None


@router.post("/new")
async def create_team(request: Request, name: str = Form(...), db: AsyncSession = Depends(get_db),
                      admin: User = Depends(require_admin)):
    name = name.strip()
    if not name:
        request.session["flash_error"] = t(request, "A team needs a name.")
    elif await _name_taken(db, name):
        request.session["flash_error"] = t(request, "There is already a team called {name}.", name=name)
    else:
        db.add(Team(name=name))
        log_activity(db, admin, "team_created", name)
        await db.commit()
    return RedirectResponse(BACK, status_code=303)


@router.post("/{team_id}/rename")
async def rename_team(request: Request, team_id: int, name: str = Form(...), db: AsyncSession = Depends(get_db),
                      admin: User = Depends(require_admin)):
    team, name = await _team(db, team_id), name.strip()
    if not name:
        request.session["flash_error"] = t(request, "A team needs a name.")
    elif await _name_taken(db, name, team_id):
        request.session["flash_error"] = t(request, "There is already a team called {name}.", name=name)
    else:
        log_activity(db, admin, "team_renamed", name, detail=f"{team.name} → {name}")
        team.name = name
        await db.commit()
    return RedirectResponse(BACK, status_code=303)


@router.post("/{team_id}/delete")
async def delete_team(team_id: int, db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    """Members stay users; samples shown to "team" are then seen by their owners' other teams, if any."""
    team = await _team(db, team_id)
    log_activity(db, admin, "team_deleted", team.name)
    await db.delete(team)
    await db.commit()
    return RedirectResponse(BACK, status_code=303)


@router.post("/{team_id}/members")
async def add_member(request: Request, team_id: int, user_id: int = Form(...), coordinator: str = Form(""),
                     db: AsyncSession = Depends(get_db), admin: User = Depends(require_admin)):
    team = await _team(db, team_id)
    user = await db.get(User, user_id)
    if user is None:
        raise HTTPException(status_code=404, detail="User not found")
    member = next((m for m in team.members if m.user_id == user_id), None)
    if member is None:
        team.members.append(TeamMember(user_id=user_id, is_coordinator=bool(coordinator)))
        log_activity(db, admin, "member_added", user.username, user, f"{team.name}{' (coordinator)' if coordinator else ''}")
    else:
        if member.is_coordinator != bool(coordinator):
            log_activity(db, admin, "coordinator_set" if coordinator else "coordinator_unset", user.username, user, team.name)
        member.is_coordinator = bool(coordinator)
    await db.commit()
    return RedirectResponse(BACK, status_code=303)


async def _member(db: AsyncSession, team_id: int, user_id: int) -> TeamMember:
    member = (await db.execute(select(TeamMember).where(
        TeamMember.team_id == team_id, TeamMember.user_id == user_id))).scalar_one_or_none()
    if member is None:
        raise HTTPException(status_code=404, detail="Not a member of this team")
    return member


@router.post("/{team_id}/members/{user_id}/coordinator")
async def toggle_coordinator(team_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                             admin: User = Depends(require_admin)):
    member = await _member(db, team_id, user_id)
    member.is_coordinator = not member.is_coordinator
    log_activity(db, admin, "coordinator_set" if member.is_coordinator else "coordinator_unset",
                 member.user.username, member.user, (await _team(db, team_id)).name)
    await db.commit()
    return RedirectResponse(BACK, status_code=303)


@router.post("/{team_id}/members/{user_id}/remove")
async def remove_member(team_id: int, user_id: int, db: AsyncSession = Depends(get_db),
                        admin: User = Depends(require_admin)):
    member = await _member(db, team_id, user_id)
    log_activity(db, admin, "member_removed", member.user.username, member.user, (await _team(db, team_id)).name)
    await db.delete(member)
    await db.commit()
    return RedirectResponse(BACK, status_code=303)
