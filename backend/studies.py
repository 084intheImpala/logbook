"""Studies: who may see and change them, and the order of their notes.

A study's co-owners (and admins) may change everything in it. Who else can
see it follows its visibility, as for a sample: personal, only the
co-owners; team, also everyone in a co-owner's team; public, everyone logged
in. Anyone who can see a study may add a reference to it (and remove the
ones they added). Its samples are listed only to people who can see them.

Notes are ordered like a sample's timeline (see timeline.py): a `position`
each, a new or re-dated note goes after the others of its day, and they can
then be moved freely.
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import can_view_shared, is_co_owner
from backend.models import Study, StudyNote, StudyOwner, StudySample, User


def is_study_owner(user: User | None, study: Study) -> bool:
    return is_co_owner(user, study)


def can_view_study(user: User | None, study: Study) -> bool:
    return can_view_shared(user, study)


async def load_study(db: AsyncSession, study_id: int, user: User, need: str = "view") -> Study:
    """The study, 404 if missing, 403 if `user` can't view it (need="view") or own it ("owner")."""
    study = await db.get(Study, study_id)
    if study is None:
        raise HTTPException(status_code=404, detail="Study not found")
    allowed = is_study_owner(user, study) if need == "owner" else can_view_study(user, study)
    if not allowed:
        raise HTTPException(status_code=403, detail="You don't have access to this study.")
    return study


async def studies_of_sample(db: AsyncSession, sample_id: int) -> list[Study]:
    rows = await db.execute(select(Study).join(StudySample, StudySample.study_id == Study.id)
                            .where(StudySample.sample_id == sample_id).order_by(Study.title))
    return list(rows.scalars())


async def visible_studies(db: AsyncSession, user: User) -> list[Study]:
    """Studies `user` can see: theirs first, then the others, by title."""
    studies = [s for s in (await db.execute(select(Study).order_by(Study.title))).scalars() if can_view_study(user, s)]
    return sorted(studies, key=lambda s: (not any(o.user_id == user.id for o in s.owners), s.title.lower()))


async def owned_studies(db: AsyncSession, user: User) -> list[Study]:
    """Studies `user` is a co-owner of (admins: all of them)."""
    query = select(Study).order_by(Study.title)
    if not user.is_admin:
        query = query.join(StudyOwner, StudyOwner.study_id == Study.id).where(StudyOwner.user_id == user.id)
    return list((await db.execute(query)).scalars())


# ── Note order ───────────────────────────────────────────────────────────────

async def ordered_notes(db: AsyncSession, study_id: int) -> list[StudyNote]:
    notes = (await db.execute(select(StudyNote).where(StudyNote.study_id == study_id))).scalars().all()
    big = 1 << 30   # a just-added note has no position yet
    return sorted(notes, key=lambda n: (n.position if n.position is not None else big, n.id))


def _apply_positions(notes: list[StudyNote]):
    for i, n in enumerate(notes):
        n.position = i


async def place_note(db: AsyncSession, note: StudyNote):
    """Put a just-added (flushed) note, or one whose date changed, in its slot:
    before the first note dated later, else at the end."""
    others = [n for n in await ordered_notes(db, note.study_id) if n is not note]
    index = len(others)
    if note.noted_on:
        index = next((i for i, n in enumerate(others) if n.noted_on and n.noted_on > note.noted_on), index)
    others.insert(index, note)
    _apply_positions(others)


async def move_note(db: AsyncSession, note: StudyNote, direction: str):
    notes = await ordered_notes(db, note.study_id)
    i = notes.index(note)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(notes):
        notes[i], notes[j] = notes[j], notes[i]
    _apply_positions(notes)
