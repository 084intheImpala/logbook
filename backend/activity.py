"""A record of management actions, for admins and team coordinators: who
deleted a sample, changed its owner, visibility, ID or sharing, answered a
request, created an account or changed a team. Ordinary editing isn't logged.

`log` only adds a row to the session; the caller's commit saves it.
"""
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ActivityLog, User

ACTIONS = {
    "sample_deleted": "Sample deleted",
    "sample_owner": "Owner changed",
    "sample_visibility": "Visibility changed",
    "sample_id": "ID changed",
    "share_set": "Shared",
    "share_removed": "Sharing removed",
    "request_approved": "Access request approved",
    "request_denied": "Access request declined",
    "entry_approved": "Proposed entry approved",
    "entry_declined": "Proposed entry declined",
    "user_created": "Account created",
    "password_reset": "Password reset",
    "member_added": "Added to team",
    "member_removed": "Removed from team",
    "coordinator_set": "Coordinator appointed",
    "coordinator_unset": "Coordinator removed",
    "team_created": "Team created",
    "team_renamed": "Team renamed",
    "team_deleted": "Team deleted",
    "user_deleted": "Account deleted",
    "admin_set": "Admin rights changed",
}


def log(db: AsyncSession, actor: User | None, action: str, target: str, subject: User | int | None = None,
        detail: str | None = None) -> None:
    """`target` names what it was done to (a sample ID, a username, a team);
    `subject` is the user whose sample or account it concerns, which decides
    which team's coordinators can see the entry."""
    assert action in ACTIONS, action
    db.add(ActivityLog(
        actor_id=actor.id if actor else None, actor_name=actor.display_name if actor else None,
        action=action, target=target, detail=detail,
        subject_user_id=subject.id if isinstance(subject, User) else subject))
