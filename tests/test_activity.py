"""The activity log: what gets recorded and who can read it."""
import pytest

from backend.activity import ACTIONS


@pytest.fixture(scope="module")
def lab(world):
    owner, mate, coord = world.user("owner"), world.user("mate"), world.user("coord")
    outsider, other_owner, other_coord = world.user("outsider"), world.user("otherowner"), world.user("othercoord")
    admin = world.user("admin", admin=True)
    world.team("log-a", members=[owner, mate], coordinators=[coord])
    world.team("log-b", members=[other_owner], coordinators=[other_coord])
    users = dict(owner=owner, mate=mate, coord=coord, outsider=outsider, other_owner=other_owner,
                 other_coord=other_coord, admin=admin)
    return dict(users=users, clients={k: world.client(u) for k, u in users.items()})


def page(lab, who, action=""):
    return lab["clients"][who].get(f"/activity?action={action}")


def test_only_admins_and_coordinators_can_read_it(lab):
    for who in ("admin", "coord", "other_coord"):
        assert page(lab, who).status_code == 200
    for who in ("owner", "mate", "outsider"):
        assert page(lab, who).status_code == 403


def test_team_sees_its_own_events_only(world, lab):
    mine = world.sample(lab["users"]["owner"])
    theirs = world.sample(lab["users"]["other_owner"])
    assert lab["clients"]["coord"].post(f"/samples/{mine.id}/visibility", data={"visibility": "team"}).status_code == 303
    assert lab["clients"]["other_coord"].post(f"/samples/{theirs.id}/visibility", data={"visibility": "public"}).status_code == 303
    coord_view = page(lab, "coord", "sample_visibility").text
    assert mine.code in coord_view and theirs.code not in coord_view
    assert "personal → team" in coord_view
    admin_view = page(lab, "admin", "sample_visibility").text
    assert mine.code in admin_view and theirs.code in admin_view


def test_deleting_a_sample_is_logged_with_its_code(world, lab):
    sample = world.sample(lab["users"]["mate"])
    lab["clients"]["coord"].post(f"/samples/{sample.id}/delete")
    row = page(lab, "coord", "sample_deleted").text
    assert sample.code in row and lab["users"]["coord"].name in row


def test_sharing_and_requests_are_logged(world, lab):
    sample = world.sample(lab["users"]["owner"])
    lab["clients"]["owner"].post(f"/samples/{sample.id}/shares", data={"user_id": lab["users"]["outsider"].id, "access": "edit"})
    assert sample.code in page(lab, "coord", "share_set").text
    lab["clients"]["outsider"].post(f"/samples/{sample.id}/request-access", data={"level": "edit"})   # already has it: nothing
    other = world.sample(lab["users"]["owner"])
    lab["clients"]["outsider"].post(f"/samples/{other.id}/request-access", data={"level": "view"})
    from tests.test_approvals import requests_for
    (req,) = requests_for(other)
    lab["clients"]["coord"].post(f"/approvals/requests/{req.id}/approve")
    assert other.code in page(lab, "coord", "request_approved").text


def test_accounts_and_teams_are_logged(world, lab):
    team_page = lab["clients"]["admin"].post("/admin/teams/new", data={"name": "logged-team"})
    assert team_page.status_code == 303
    assert "logged-team" in page(lab, "admin", "team_created").text
    assert "logged-team" not in page(lab, "coord", "team_created").text
    lab["clients"]["coord"].get("/team")   # page renders for coordinators


def test_every_action_has_a_label():
    assert all(label for label in ACTIONS.values())
