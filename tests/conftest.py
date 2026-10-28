"""Test setup: the real app on a throwaway SQLite database and uploads folder.

Nothing here touches the Postgres database or the uploads/ folder: the
settings are overridden before the app is imported. Run with `pytest`
(install requirements-dev.txt first)."""
import itertools
import os
import tempfile
from pathlib import Path

_TMP = tempfile.TemporaryDirectory(prefix="logbook-tests-")
os.environ["DATABASE_URL"] = f"sqlite+aiosqlite:///{_TMP.name}/test.db"
os.environ["UPLOAD_DIR"] = f"{_TMP.name}/uploads"
os.environ["SMTP_PASSWORD"] = ""   # never send email

import pytest
from fastapi.testclient import TestClient

from backend.auth import hash_password
from backend.database import AsyncSessionLocal
from backend.main import app
from backend.models import (Analysis, AnalysisType, Attachment, ProcessStep, ProcessStepType, Project, Sample,
                            SampleShare, Substrate, Team, TeamMember, User)
from sqlalchemy import select
from tests.loop import run

PASSWORD = "pw"
_n = itertools.count(1)


@pytest.fixture(scope="session")
def server():
    with TestClient(app, follow_redirects=False) as c:
        yield c


class World:
    """Makes users and samples and logs in as them."""

    def __init__(self, server):
        self.server = server
        self.upload_dir = Path(os.environ["UPLOAD_DIR"])

    def user(self, name: str, admin: bool = False, **extra) -> User:
        n = next(_n)

        async def make():
            async with AsyncSessionLocal() as db:
                u = User(username=f"{name}{n}", hashed_password=hash_password(PASSWORD), is_admin=admin,
                         must_change_password=False, name=name.title(), email=f"{name}{n}@example.org",
                         initials=f"T{chr(65 + n // 26 % 26)}{chr(65 + n % 26)}", **extra)
                db.add(u)
                await db.commit()
                return u
        return run(make())

    def sample(self, owner: User | None, shared_view=(), shared_edit=(), **extra) -> Sample:
        n = next(_n)

        async def make():
            async with AsyncSessionLocal() as db:
                s = Sample(code=f"TST-2026-{n:03d}", owner_id=owner.id if owner else None, **extra)
                s.shares = ([SampleShare(user_id=u.id, can_edit=False) for u in shared_view]
                            + [SampleShare(user_id=u.id, can_edit=True) for u in shared_edit])
                db.add(s)
                await db.commit()
                return s
        return run(make())

    def project(self, name: str = "Test project") -> Project:
        n = next(_n)

        async def make():
            async with AsyncSessionLocal() as db:
                p = Project(name=f"{name} {n}", code=f"P{n:03d}")
                db.add(p)
                await db.commit()
                return p
        return run(make())

    def substrate(self) -> Substrate:
        n = next(_n)

        async def make():
            async with AsyncSessionLocal() as db:
                sub = Substrate(name=f"Sub {n}", material="Si")
                db.add(sub)
                await db.commit()
                return sub
        return run(make())

    def step(self, sample: Sample, notes: str, performer: User | None = None, with_file: str | None = None,
             analysis: bool = False):
        """A step (or analysis) with `notes`; `with_file` is the text of a file attached to it."""
        async def make():
            async with AsyncSessionLocal() as db:
                if analysis:
                    kind = (await db.execute(select(AnalysisType).limit(1))).scalar_one()
                    entry = Analysis(sample_id=sample.id, analysis_type_id=kind.id, notes=notes, position=1,
                                     performer_id=performer.id if performer else None)
                else:
                    kind = (await db.execute(select(ProcessStepType).limit(1))).scalar_one()
                    entry = ProcessStep(sample_id=sample.id, step_type_id=kind.id, notes=notes, position=1,
                                        performer_id=performer.id if performer else None)
                db.add(entry)
                await db.flush()
                attachment_id = None
                if with_file is not None:
                    folder = self.upload_dir / sample.code
                    folder.mkdir(parents=True, exist_ok=True)
                    name = f"{entry.id}-{'a' if analysis else 's'}.txt"
                    (folder / name).write_text(with_file)
                    att = Attachment(entity_type="analysis" if analysis else "step", entity_id=entry.id,
                                     stored_filename=f"{sample.code}/{name}", original_filename=name,
                                     mime_type="text/plain", file_size=len(with_file))
                    db.add(att)
                    await db.flush()
                    attachment_id = att.id
                await db.commit()
                return entry.id, attachment_id
        return run(make())

    def team(self, name: str, members=(), coordinators=()) -> Team:
        n = next(_n)

        async def make():
            async with AsyncSessionLocal() as db:
                t = Team(name=f"{name}{n}")
                t.members = ([TeamMember(user_id=u.id) for u in members]
                             + [TeamMember(user_id=u.id, is_coordinator=True) for u in coordinators])
                db.add(t)
                await db.commit()
                return t
        return run(make())

    def client(self, user: User | None) -> TestClient:
        """A separate browser session, logged in as `user` (or anonymous)."""
        c = TestClient(app, follow_redirects=False)
        if user is not None:
            r = c.post("/login", data={"username": user.username, "password": PASSWORD})
            assert r.status_code == 303, r.text
        return c


@pytest.fixture(scope="session")
def world(server):
    return World(server)
