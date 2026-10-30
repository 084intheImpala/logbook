"""What a team coordinator can do for their team without an admin."""
import pytest
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import TeamMember, User
from tests.loop import run


@pytest.fixture(scope="module")
def lab(world):
    coord, mate, outsider = world.user("coord"), world.user("mate"), world.user("outsider")
    coord2, loner, admin = world.user("coordb"), world.user("loner"), world.user("admin", admin=True)
    team = world.team("page-a", members=[mate], coordinators=[coord])
    team_b = world.team("page-b", coordinators=[coord2])
    users = dict(coord=coord, mate=mate, outsider=outsider, coord2=coord2, loner=loner, admin=admin)
    return dict(team=team, team_b=team_b, users=users, clients={k: world.client(u) for k, u in users.items()})


def memberships(team):
    async def q():
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(TeamMember).where(TeamMember.team_id == team.id))).scalars().all()
            return {m.user_id: m.is_coordinator for m in rows}
    return run(q())


def test_only_coordinators_have_the_page(lab):
    assert lab["clients"]["coord"].get("/team").status_code == 200
    for who in ("mate", "outsider"):
        assert lab["clients"][who].get("/team").status_code == 403


def test_page_lists_own_team_only(lab):
    page = lab["clients"]["coord"].get("/team").text
    assert lab["users"]["mate"].username in page and lab["users"]["coord2"].username not in page.split("Add someone")[0]


def test_coordinator_adds_someone_without_a_team(lab):
    team, c = lab["team"], lab["clients"]["coord"]
    assert c.post(f"/team/{team.id}/members", data={"user_id": lab["users"]["loner"].id}).status_code == 303
    assert lab["users"]["loner"].id in memberships(team)
    # a person in another team is not taken over
    c.post(f"/team/{team.id}/members", data={"user_id": lab["users"]["coord2"].id})
    assert lab["users"]["coord2"].id not in memberships(team)


def test_coordinator_removes_members_but_not_coordinators(lab):
    team, c = lab["team"], lab["clients"]["coord"]
    c.post(f"/team/{team.id}/members/{lab['users']['loner'].id}/remove")
    assert lab["users"]["loner"].id not in memberships(team)
    c.post(f"/team/{team.id}/members/{lab['users']['coord'].id}/remove")
    assert memberships(team)[lab["users"]["coord"].id] is True


def test_coordinator_cannot_touch_other_teams(lab):
    team_b, c = lab["team_b"], lab["clients"]["coord"]
    assert c.post(f"/team/{team_b.id}/members", data={"user_id": lab["users"]["loner"].id}).status_code == 403
    assert c.post(f"/team/{team_b.id}/users/new", data={"username": "x", "email": "x@x.org"}).status_code == 403


def test_members_cannot_use_team_actions(lab):
    team = lab["team"]
    assert lab["clients"]["mate"].post(f"/team/{team.id}/members", data={"user_id": lab["users"]["loner"].id}).status_code == 403


def test_coordinator_creates_an_account_in_their_team(lab):
    team, c = lab["team"], lab["clients"]["coord"]
    assert c.post(f"/team/{team.id}/users/new", data={"username": "newcomer-a", "name": "New", "email": "newcomer-a@example.org"}).status_code == 303

    async def find():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(User).where(User.username == "newcomer-a"))).scalar_one_or_none()
    user = run(find())
    assert user is not None and user.must_change_password and user.id in memberships(team) and not user.is_admin
    # a duplicate username is refused
    c.post(f"/team/{team.id}/users/new", data={"username": "newcomer-a", "email": "other@example.org"})


def test_coordinator_resets_a_members_password_but_not_a_coordinators(lab):
    team, c = lab["team"], lab["clients"]["coord"]

    async def pw(user):
        async with AsyncSessionLocal() as db:
            return (await db.get(User, user.id)).hashed_password
    mate, other = lab["users"]["mate"], lab["users"]["coord"]
    before = run(pw(mate))
    assert c.post(f"/team/{team.id}/members/{mate.id}/reset-password").status_code == 303
    assert run(pw(mate)) != before
    # a user from another team isn't theirs to reset
    assert c.post(f"/team/{team.id}/members/{lab['users']['coord2'].id}/reset-password").status_code == 404


def test_only_admins_appoint_coordinators(lab):
    team, mate = lab["team"], lab["users"]["mate"]
    c = lab["clients"]["coord"]
    c.post(f"/admin/teams/{team.id}/members/{mate.id}/coordinator")
    assert memberships(team)[mate.id] is False
    lab["clients"]["admin"].post(f"/admin/teams/{team.id}/members/{mate.id}/coordinator")
    assert memberships(team)[mate.id] is True
    lab["clients"]["admin"].post(f"/admin/teams/{team.id}/members/{mate.id}/coordinator")


def test_admin_message_can_go_to_a_team(world, monkeypatch):
    from backend.config import settings
    from backend.routers import admin as admin_routes
    sent = []

    async def fake(to, subject, body):
        sent.append(to)
    monkeypatch.setattr(settings, "SMTP_PASSWORD", "x")
    monkeypatch.setattr(admin_routes, "send_admin_message", fake)
    a, b, outsider = world.user("msg-a"), world.user("msg-b"), world.user("msg-out")
    team = world.team("msg-team", members=[a], coordinators=[b])
    admin = world.client(world.user("msg-admin", admin=True))
    assert f'value="team:{team.id}"' in admin.get("/admin/").text
    r = admin.post("/admin/message", data={"to": f"team:{team.id}", "subject": "s", "body": "b"})
    assert r.status_code == 303
    assert sorted(sent) == sorted([a.email, b.email]) and outsider.email not in sent
    assert admin.post("/admin/message", data={"to": "team:99999", "subject": "s", "body": "b"}).status_code == 404
    assert world.client(a).post("/admin/message", data={"to": f"team:{team.id}", "subject": "s", "body": "b"}).status_code == 403
