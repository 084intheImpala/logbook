"""Teams, coordinators and the visibility of a sample (personal / team / public)."""
import pytest
from sqlalchemy import select

from backend.database import AsyncSessionLocal
from backend.models import Sample, Team, TeamMember
from tests.loop import run

SECRET = "SECRET-TEAM-NOTE"


@pytest.fixture(scope="module")
def lab(world):
    owner, mate, coord = world.user("owner"), world.user("mate"), world.user("coord")
    outsider, other_coord, admin = world.user("outsider"), world.user("othercoord"), world.user("admin", admin=True)
    team = world.team("alpha", members=[owner, mate], coordinators=[coord])
    world.team("beta", coordinators=[other_coord])
    users = dict(owner=owner, mate=mate, coord=coord, outsider=outsider, other_coord=other_coord, admin=admin)
    return dict(team=team, users=users, clients={k: world.client(u) for k, u in users.items()})


def make(world, lab, visibility):
    sample = world.sample(lab["users"]["owner"], visibility=visibility)
    entry_id, file_id = world.step(sample, f"{SECRET} {visibility}", with_file="data")
    return sample, file_id


def sees(lab, who, sample):
    return SECRET in lab["clients"][who].get(f"/samples/{sample.id}").text


@pytest.mark.parametrize("visibility,expected", [
    ("personal", dict(owner=True, admin=True, coord=True, mate=False, outsider=False, other_coord=False)),
    ("team",     dict(owner=True, admin=True, coord=True, mate=True,  outsider=False, other_coord=False)),
    ("public",   dict(owner=True, admin=True, coord=True, mate=True,  outsider=True,  other_coord=True)),
])
def test_who_sees_details(world, lab, visibility, expected):
    sample, file_id = make(world, lab, visibility)
    for who, can in expected.items():
        assert sees(lab, who, sample) is can, (visibility, who)
        assert lab["clients"][who].get(f"/files/{file_id}").status_code == (200 if can else 403), (visibility, who)


def test_everyone_still_sees_the_summary(world, lab):
    sample, _ = make(world, lab, "personal")
    assert lab["clients"]["outsider"].get(f"/samples/{sample.id}").status_code == 200


def test_search_follows_visibility(world, lab):
    sample, _ = make(world, lab, "team")
    q = f"/search?q={SECRET}"
    assert sample.code in lab["clients"]["mate"].get(q).text
    assert sample.code not in lab["clients"]["outsider"].get(q).text


@pytest.mark.parametrize("who", ["mate", "outsider"])
@pytest.mark.parametrize("visibility", ["personal", "team", "public"])
def test_seeing_is_not_editing(world, lab, who, visibility):
    sample, _ = make(world, lab, visibility)
    c = lab["clients"][who]
    assert c.get(f"/samples/{sample.id}/edit").status_code == 403
    # teammates can propose an entry (see test_approvals.py); strangers can't
    assert c.get(f"/samples/{sample.id}/steps/new").status_code == (403 if who == "outsider" else 200)
    assert c.post(f"/samples/{sample.id}/delete").status_code == 403
    assert c.post(f"/samples/{sample.id}/shares", data={"user_id": lab["users"]["mate"].id}).status_code == 403


def test_a_coordinator_only_sees_their_own_teams_members(world, lab):
    stray = world.sample(lab["users"]["outsider"], visibility="personal")
    world.step(stray, SECRET)
    assert not sees(lab, "coord", stray)


# ── Coordinators run their team ──────────────────────────────────────────────

def test_coordinator_has_owner_rights_on_team_samples(world, lab):
    sample, _ = make(world, lab, "personal")
    coord, sid = lab["clients"]["coord"], sample.id
    assert coord.get(f"/samples/{sid}/edit").status_code == 200
    assert coord.get(f"/samples/{sid}/steps/new").status_code == 200
    assert coord.post(f"/samples/{sid}/visibility", data={"visibility": "team"}).status_code == 303
    assert coord.post(f"/samples/{sid}/shares", data={"user_id": lab["users"]["outsider"].id, "access": "view"}).status_code == 303
    assert sees(lab, "outsider", sample)
    assert coord.post(f"/samples/{sid}/delete").status_code == 303
    assert lab["clients"]["owner"].get(f"/samples/{sid}").status_code == 404


def test_coordinator_has_no_rights_outside_their_team(world, lab):
    stray = world.sample(lab["users"]["outsider"])
    coord = lab["clients"]["coord"]
    assert coord.get(f"/samples/{stray.id}/edit").status_code == 403
    assert coord.post(f"/samples/{stray.id}/delete").status_code == 403
    assert lab["clients"]["other_coord"].get(f"/samples/{lab_sample_edit(world, lab)}/edit").status_code == 403


def lab_sample_edit(world, lab):
    return make(world, lab, "personal")[0].id


def test_coordinator_cannot_change_ids(world, lab):
    sample, _ = make(world, lab, "personal")
    assert lab["clients"]["coord"].post(f"/samples/{sample.id}/recode", data={"code": "ZZ-2026-001"}).status_code == 403


def test_coordinator_reassigns_only_within_the_team(world, lab):
    sample, _ = make(world, lab, "personal")
    coord, sid = lab["clients"]["coord"], sample.id
    data = {"sample_type": "commercial", "description": "bought"}

    async def owner_of():
        async with AsyncSessionLocal() as db:
            return (await db.get(Sample, sid)).owner_id
    coord.post(f"/samples/{sid}/edit", data=data | {"owner_id": str(lab["users"]["outsider"].id)},
               files={"files": ("spec.txt", b"spec", "text/plain")})
    assert run(owner_of()) == lab["users"]["owner"].id        # outsider isn't in the team: ignored
    coord.post(f"/samples/{sid}/edit", data=data | {"owner_id": str(lab["users"]["mate"].id)},
               files={"files": ("spec.txt", b"spec", "text/plain")})
    assert run(owner_of()) == lab["users"]["mate"].id         # in the team: goes straight, no confirmation


def test_owner_changes_visibility(world, lab):
    sample, _ = make(world, lab, "personal")
    assert not sees(lab, "mate", sample)
    assert lab["clients"]["owner"].post(f"/samples/{sample.id}/visibility", data={"visibility": "team"}).status_code == 303
    assert sees(lab, "mate", sample)
    assert lab["clients"]["owner"].post(f"/samples/{sample.id}/visibility", data={"visibility": "nonsense"}).status_code == 400


@pytest.mark.parametrize("who", ["mate", "outsider", "other_coord"])
def test_only_owner_admin_or_team_coordinator_change_visibility(world, lab, who):
    sample, _ = make(world, lab, "personal")
    assert lab["clients"][who].post(f"/samples/{sample.id}/visibility", data={"visibility": "public"}).status_code == 403


def test_new_sample_gets_the_chosen_visibility(world, lab):
    owner = lab["users"]["owner"]
    r = lab["clients"]["owner"].post("/samples/new", data={
        "sample_type": "commercial", "description": "bought", "visibility": "team"},
        files={"files": ("spec.txt", b"spec", "text/plain")})
    assert r.status_code == 303, r.text[:300]

    async def latest():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Sample).where(Sample.owner_id == owner.id)
                                     .order_by(Sample.id.desc()).limit(1))).scalar_one()
    assert run(latest()).visibility == "team"


# ── Managing teams (admin) ───────────────────────────────────────────────────

def test_only_admins_manage_teams(lab):
    for who in ("owner", "coord"):
        assert lab["clients"][who].post("/admin/teams/new", data={"name": "nope"}).status_code in (302, 303, 403)
    names = run(_team_names())
    assert "nope" not in names


async def _team_names():
    async with AsyncSessionLocal() as db:
        return set((await db.execute(select(Team.name))).scalars())


def test_admin_builds_a_team(world, lab):
    admin, newbie = lab["clients"]["admin"], world.user("newbie")
    assert admin.post("/admin/teams/new", data={"name": "gamma-team"}).status_code == 303
    assert "gamma-team" in run(_team_names())

    async def team_id():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(Team.id).where(Team.name == "gamma-team"))).scalar_one()
    tid = run(team_id())

    async def members():
        async with AsyncSessionLocal() as db:
            rows = (await db.execute(select(TeamMember).where(TeamMember.team_id == tid))).scalars().all()
            return {m.user_id: m.is_coordinator for m in rows}
    assert admin.post(f"/admin/teams/{tid}/members", data={"user_id": newbie.id}).status_code == 303
    assert run(members()) == {newbie.id: False}
    admin.post(f"/admin/teams/{tid}/members/{newbie.id}/coordinator")
    assert run(members()) == {newbie.id: True}
    admin.post(f"/admin/teams/{tid}/members/{newbie.id}/remove")
    assert run(members()) == {}
    admin.post(f"/admin/teams/{tid}/rename", data={"name": "gamma-renamed"})
    assert "gamma-renamed" in run(_team_names())
    assert admin.post("/admin/teams/new", data={"name": "gamma-renamed"}).status_code == 303   # duplicate: flashed, not created
    admin.post(f"/admin/teams/{tid}/delete")
    assert "gamma-renamed" not in run(_team_names())
    assert admin.get("/admin/").status_code == 200
