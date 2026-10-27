"""Entries teammates propose, and requests for access: who can decide, and when."""
from datetime import datetime, timedelta

import pytest
from sqlalchemy import select, update

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import AccessRequest, Analysis, ProcessStep, ProcessStepType, Sample
from tests.loop import run

NOTE = "PROPOSED-NOTE"


@pytest.fixture(scope="module")
def lab(world):
    owner, mate, coord = world.user("owner"), world.user("mate"), world.user("coord")
    outsider, admin = world.user("outsider"), world.user("admin", admin=True)
    world.team("approvals", members=[owner, mate], coordinators=[coord])
    users = dict(owner=owner, mate=mate, coord=coord, outsider=outsider, admin=admin)
    return dict(users=users, clients={k: world.client(u) for k, u in users.items()})


def step_type_id():
    async def q():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(ProcessStepType.id).where(ProcessStepType.name == "Annealing"))).scalar_one()
    return run(q())


def propose(lab, who, sample, kind="steps", notes=NOTE):
    data = {"type_id": str(step_type_id()), "notes": notes} if kind == "steps" else {"type_id": "1", "notes": notes}
    return lab["clients"][who].post(f"/samples/{sample.id}/{kind}/new", data=data)


def entries(sample, model=ProcessStep):
    async def q():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(model).where(model.sample_id == sample.id))).scalars().all()
    return run(q())


def age(entry_model, entry_id, days):
    async def q():
        async with AsyncSessionLocal() as db:
            await db.execute(update(entry_model).where(entry_model.id == entry_id)
                             .values(proposed_at=datetime.utcnow() - timedelta(days=days)))
            await db.commit()
    run(q())


def timeline_has(lab, who, sample, text):
    return text in lab["clients"][who].get(f"/samples/{sample.id}").text


# ── Proposing ────────────────────────────────────────────────────────────────

def test_teammate_proposal_is_pending_and_off_the_timeline(world, lab):
    sample = world.sample(lab["users"]["owner"])
    r = propose(lab, "mate", sample)
    assert r.status_code == 303 and r.headers["location"].endswith("#pending")
    (entry,) = entries(sample)
    assert entry.status == "pending" and entry.proposed_by_id == lab["users"]["mate"].id and entry.position is None
    owner_page = lab["clients"]["owner"].get(f"/samples/{sample.id}").text
    assert "approvals/entries/step/" in owner_page and "Waiting for approval" in owner_page.replace("Aguarda aprovação", "Waiting for approval")
    # not in the CSV export, which only has approved timeline entries
    assert NOTE not in lab["clients"]["owner"].get("/search/export.csv?q=" + sample.code).text


@pytest.mark.parametrize("who", ["outsider"])
def test_strangers_cannot_propose(world, lab, who):
    sample = world.sample(lab["users"]["owner"])
    assert propose(lab, who, sample).status_code == 403
    assert entries(sample) == []


def test_owner_adds_directly(world, lab):
    sample = world.sample(lab["users"]["owner"])
    propose(lab, "owner", sample)
    (entry,) = entries(sample)
    assert entry.status == "approved" and entry.position is not None


def test_proposer_sees_only_their_own_pending_entry(world, lab):
    sample = world.sample(lab["users"]["owner"])
    propose(lab, "mate", sample)
    page = lab["clients"]["mate"].get(f"/samples/{sample.id}").text
    assert NOTE in page   # their own proposal, with its notes
    other = world.step(sample, "OTHER-SECRET")
    assert "OTHER-SECRET" not in lab["clients"]["mate"].get(f"/samples/{sample.id}").text


def test_proposer_can_edit_and_withdraw_while_pending(world, lab):
    sample = world.sample(lab["users"]["owner"])
    propose(lab, "mate", sample)
    (entry,) = entries(sample)
    assert lab["clients"]["mate"].get(f"/samples/{sample.id}/steps/{entry.id}/edit").status_code == 200
    r = lab["clients"]["mate"].post(f"/approvals/entries/step/{entry.id}/reject")
    assert r.status_code == 303 and entries(sample) == []


# ── Approving ────────────────────────────────────────────────────────────────

def test_owner_approves_and_it_joins_the_timeline(world, lab):
    sample = world.sample(lab["users"]["owner"])
    world.step(sample, "existing")
    propose(lab, "mate", sample)
    entry = next(e for e in entries(sample) if e.status == "pending")
    assert lab["clients"]["owner"].post(f"/approvals/entries/step/{entry.id}/approve").status_code == 303
    after = {e.id: e for e in entries(sample)}[entry.id]
    assert after.status == "approved" and after.position is not None
    assert NOTE in lab["clients"]["owner"].get("/search/export.csv?q=" + sample.code).text


def test_owner_declines_and_it_is_deleted(world, lab):
    sample = world.sample(lab["users"]["owner"])
    propose(lab, "mate", sample)
    (entry,) = entries(sample)
    assert lab["clients"]["owner"].post(f"/approvals/entries/step/{entry.id}/reject").status_code == 303
    assert entries(sample) == []


@pytest.mark.parametrize("who", ["mate", "outsider"])
def test_others_cannot_approve(world, lab, who):
    sample = world.sample(lab["users"]["owner"])
    propose(lab, "mate", sample)
    (entry,) = entries(sample)
    assert lab["clients"][who].post(f"/approvals/entries/step/{entry.id}/approve").status_code == 403
    assert entries(sample)[0].status == "pending"


def test_coordinator_waits_before_approving(world, lab):
    sample = world.sample(lab["users"]["owner"])
    propose(lab, "mate", sample)
    (entry,) = entries(sample)
    coord = lab["clients"]["coord"]
    assert coord.post(f"/approvals/entries/step/{entry.id}/approve").status_code == 403
    age(ProcessStep, entry.id, settings.APPROVAL_ESCALATION_DAYS + 1)
    assert coord.post(f"/approvals/entries/step/{entry.id}/approve").status_code == 303
    assert entries(sample)[0].status == "approved"


def test_admin_can_always_approve(world, lab):
    sample = world.sample(lab["users"]["owner"])
    propose(lab, "mate", sample)
    (entry,) = entries(sample)
    assert lab["clients"]["admin"].post(f"/approvals/entries/step/{entry.id}/approve").status_code == 303


def test_inbox_and_badge(world, lab):
    sample = world.sample(lab["users"]["owner"])
    propose(lab, "mate", sample)
    page = lab["clients"]["owner"].get("/approvals")
    assert page.status_code == 200 and sample.code in page.text
    assert sample.code not in lab["clients"]["outsider"].get("/approvals").text


# ── Access requests ──────────────────────────────────────────────────────────

def ask(lab, who, sample, level="view", message=""):
    return lab["clients"][who].post(f"/samples/{sample.id}/request-access", data={"level": level, "message": message})


def requests_for(sample):
    async def q():
        async with AsyncSessionLocal() as db:
            return (await db.execute(select(AccessRequest).where(AccessRequest.sample_id == sample.id))).scalars().all()
    return run(q())


def test_stranger_asks_for_view_and_owner_approves(world, lab):
    sample = world.sample(lab["users"]["owner"])
    world.step(sample, "REQ-SECRET")
    assert not timeline_has(lab, "outsider", sample, "REQ-SECRET")
    assert ask(lab, "outsider", sample, "view", "please").status_code == 303
    (req,) = requests_for(sample)
    assert req.status == "pending" and req.message == "please"
    assert lab["clients"]["outsider"].post(f"/approvals/requests/{req.id}/approve").status_code == 403
    assert lab["clients"]["owner"].post(f"/approvals/requests/{req.id}/approve").status_code == 303
    assert timeline_has(lab, "outsider", sample, "REQ-SECRET")
    assert lab["clients"]["outsider"].get(f"/samples/{sample.id}/edit").status_code == 403   # view only


def test_asking_again_updates_instead_of_duplicating(world, lab):
    sample = world.sample(lab["users"]["owner"])
    ask(lab, "outsider", sample, "view", "one")
    ask(lab, "outsider", sample, "view", "two")
    (req,) = requests_for(sample)
    assert req.message == "two"


def test_owner_declines(world, lab):
    sample = world.sample(lab["users"]["owner"])
    ask(lab, "outsider", sample, "view")
    (req,) = requests_for(sample)
    lab["clients"]["owner"].post(f"/approvals/requests/{req.id}/deny")
    assert requests_for(sample)[0].status == "denied"
    assert lab["clients"]["outsider"].get(f"/samples/{sample.id}/edit").status_code == 403


def test_coordinator_requests_edit_then_accepts_it_themselves_after_the_wait(world, lab):
    sample = world.sample(lab["users"]["owner"])
    assert lab["clients"]["coord"].get(f"/samples/{sample.id}/edit").status_code == 403     # view only
    ask(lab, "coord", sample, "edit", "need to fix a value")
    (req,) = requests_for(sample)
    coord = lab["clients"]["coord"]
    assert coord.post(f"/approvals/requests/{req.id}/approve").status_code == 403          # too early

    async def backdate():
        async with AsyncSessionLocal() as db:
            await db.execute(update(AccessRequest).where(AccessRequest.id == req.id).values(
                created_at=datetime.utcnow() - timedelta(days=settings.APPROVAL_ESCALATION_DAYS + 1)))
            await db.commit()
    run(backdate())
    assert coord.post(f"/approvals/requests/{req.id}/approve").status_code == 303
    assert coord.get(f"/samples/{sample.id}/edit").status_code == 200


def test_requester_can_withdraw_but_not_approve(world, lab):
    sample = world.sample(lab["users"]["owner"])
    ask(lab, "outsider", sample, "view")
    (req,) = requests_for(sample)
    assert lab["clients"]["outsider"].post(f"/approvals/requests/{req.id}/deny").status_code == 303
    assert requests_for(sample)[0].status == "denied"


def test_no_request_for_what_you_already_have(world, lab):
    sample = world.sample(lab["users"]["owner"], shared_view=[lab["users"]["outsider"]])
    ask(lab, "outsider", sample, "view")
    assert requests_for(sample) == []
    ask(lab, "outsider", sample, "edit")
    assert len(requests_for(sample)) == 1
