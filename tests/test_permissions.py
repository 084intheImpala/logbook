"""Who can see and do what with a sample, as the app behaves today.

These pin down the current rules before teams and visibility tiers change
them: anything that should stay true after that work is asserted here, and
each change to the rules shows up as a deliberate change to a test.

Roles: the owner, an admin, someone the sample is shared with (view / edit),
the person recorded as having performed a step, and a stranger.
"""
import pytest

SECRET = "SECRET-NOTE"


@pytest.fixture(scope="module")
def cast(world):
    owner, admin = world.user("owner"), world.user("admin", admin=True)
    viewer, editor = world.user("viewer"), world.user("editor")
    performer, stranger = world.user("performer"), world.user("stranger")
    sample = world.sample(owner, shared_view=[viewer], shared_edit=[editor])
    step_id, step_file = world.step(sample, f"{SECRET} step", performer=performer, with_file="step data")
    other_step_id, _ = world.step(sample, "plain step")
    _, analysis_file = world.step(sample, "analysis", with_file="analysis data", analysis=True)
    clients = {name: world.client(u) for name, u in dict(
        owner=owner, admin=admin, viewer=viewer, editor=editor, performer=performer, stranger=stranger).items()}
    clients["anonymous"] = world.client(None)
    return dict(sample=sample, step_id=step_id, other_step_id=other_step_id, step_file=step_file,
                analysis_file=analysis_file, clients=clients, users=dict(
                    owner=owner, admin=admin, viewer=viewer, editor=editor, performer=performer, stranger=stranger))


def get(cast, who, url):
    return cast["clients"][who].get(url)


def post(cast, who, url, **data):
    return cast["clients"][who].post(url, data=data)


# ── Seeing a sample ──────────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["owner", "admin", "viewer", "editor", "performer", "stranger"])
def test_everyone_logged_in_can_open_the_summary(cast, who):
    assert get(cast, who, f"/samples/{cast['sample'].id}").status_code == 200


def test_anonymous_is_sent_to_login(cast):
    r = get(cast, "anonymous", f"/samples/{cast['sample'].id}")
    assert r.status_code == 302 and r.headers["location"].startswith("/login")


@pytest.mark.parametrize("who,sees", [
    ("owner", True), ("admin", True), ("viewer", True), ("editor", True),
    ("performer", True),    # sees the entries they performed, nothing else
    ("stranger", False),
])
def test_details_need_view_access(cast, who, sees):
    assert (SECRET in get(cast, who, f"/samples/{cast['sample'].id}").text) is sees


def test_performer_sees_only_their_own_entries(cast):
    page = get(cast, "performer", f"/samples/{cast['sample'].id}").text
    assert SECRET in page and "plain step" not in page


# ── Editing ──────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who,ok", [("owner", True), ("admin", True), ("editor", True),
                                    ("viewer", False), ("performer", False), ("stranger", False)])
@pytest.mark.parametrize("path", ["edit", "steps/new", "analyses/new"])
def test_edit_pages_need_edit_access(cast, who, ok, path):
    assert get(cast, who, f"/samples/{cast['sample'].id}/{path}").status_code == (200 if ok else 403)


@pytest.mark.parametrize("who,ok", [("owner", True), ("admin", True), ("editor", True),
                                    ("performer", True),    # their own entry, even without sample access
                                    ("viewer", False), ("stranger", False)])
def test_editing_an_entry(cast, who, ok):
    url = f"/samples/{cast['sample'].id}/steps/{cast['step_id']}/edit"
    assert get(cast, who, url).status_code == (200 if ok else 403)


def test_performer_cannot_edit_someone_elses_entry(cast):
    assert get(cast, "performer", f"/samples/{cast['sample'].id}/steps/{cast['other_step_id']}/edit").status_code == 403


# ── Owner-only actions ───────────────────────────────────────────────────────

@pytest.mark.parametrize("who", ["viewer", "editor", "performer", "stranger"])
def test_only_owner_or_admin_manage_sharing(cast, who):
    sid = cast["sample"].id
    assert post(cast, who, f"/samples/{sid}/shares", user_id=cast["users"]["stranger"].id, access="view").status_code == 403


def test_owner_can_share_and_unshare(world, cast):
    sample = world.sample(cast["users"]["owner"])
    friend = world.user("friend")
    assert get(cast, "owner", f"/samples/{sample.id}").status_code == 200
    friend_client = world.client(friend)
    world.step(sample, f"{SECRET} shared")
    assert SECRET not in friend_client.get(f"/samples/{sample.id}").text
    assert post(cast, "owner", f"/samples/{sample.id}/shares", user_id=friend.id, access="view").status_code == 303
    assert SECRET in friend_client.get(f"/samples/{sample.id}").text
    assert friend_client.get(f"/samples/{sample.id}/edit").status_code == 403
    post(cast, "owner", f"/samples/{sample.id}/shares", user_id=friend.id, access="edit")
    assert friend_client.get(f"/samples/{sample.id}/edit").status_code == 200


@pytest.mark.parametrize("who", ["viewer", "editor", "performer", "stranger"])
def test_only_owner_or_admin_delete(world, cast, who):
    sample = world.sample(cast["users"]["owner"], shared_view=[cast["users"]["viewer"]],
                          shared_edit=[cast["users"]["editor"]])
    assert post(cast, who, f"/samples/{sample.id}/delete").status_code == 403


@pytest.mark.parametrize("who", ["owner", "admin"])
def test_owner_and_admin_can_delete(world, cast, who):
    sample = world.sample(cast["users"]["owner"])
    assert post(cast, who, f"/samples/{sample.id}/delete").status_code == 303
    assert get(cast, "owner", f"/samples/{sample.id}").status_code == 404


@pytest.mark.parametrize("who", ["owner", "editor", "viewer", "stranger"])
def test_only_admins_change_ids(cast, who):
    assert post(cast, who, f"/samples/{cast['sample'].id}/recode", code="ZZ-2026-001").status_code == 403


# ── Files ────────────────────────────────────────────────────────────────────

@pytest.mark.parametrize("who,ok", [("owner", True), ("admin", True), ("viewer", True), ("editor", True),
                                    ("performer", True), ("stranger", False)])
def test_step_files(cast, who, ok):
    assert get(cast, who, f"/files/{cast['step_file']}").status_code == (200 if ok else 403)


def test_performer_cannot_open_files_of_other_entries(cast):
    assert get(cast, "performer", f"/files/{cast['analysis_file']}").status_code == 403


# ── Search and lists ─────────────────────────────────────────────────────────

def test_search_does_not_reveal_hidden_details(cast):
    q = f"/search?q={SECRET}"
    assert cast["sample"].code in get(cast, "owner", q).text
    assert cast["sample"].code not in get(cast, "stranger", q).text


def test_search_finds_summary_fields_for_everyone(cast):
    assert cast["sample"].code in get(cast, "stranger", f"/search?q={cast['sample'].code}").text


# ── Samples without an owner stay open ───────────────────────────────────────

def test_ownerless_samples_are_open(world, cast):
    sample = world.sample(None)
    world.step(sample, f"{SECRET} open")
    assert SECRET in get(cast, "stranger", f"/samples/{sample.id}").text
    assert get(cast, "stranger", f"/samples/{sample.id}/edit").status_code == 200
