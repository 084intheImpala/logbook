"""Ordering of a sample's timeline (process steps and analyses together).

Every ProcessStep and Analysis has a `position`; positions are shared across
both tables so a sample's timeline is one ordered list. Dates (the day only)
are optional and only used to place a new or re-dated entry; the order
within a day, or against the dates, is up to the user.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ProcessStep, Analysis


async def ordered_entries(db: AsyncSession, sample_id: int) -> list:
    steps = (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample_id))).scalars().all()
    analyses = (await db.execute(select(Analysis).where(Analysis.sample_id == sample_id))).scalars().all()
    # A just-added entry has no position until place_new gives it one; it goes last.
    big = 1 << 30
    return sorted(
        [*steps, *analyses],
        key=lambda e: (e.position if e.position is not None else big, e.id),
    )


def _apply_positions(entries: list):
    for i, e in enumerate(entries):
        e.position = i


async def renumber(db: AsyncSession, sample_id: int):
    _apply_positions(await ordered_entries(db, sample_id))


async def place_new(db: AsyncSession, entry):
    """Put a just-added (flushed) entry, or one whose date changed, in its slot.

    With a date, it goes before the first dated entry later than it, so after
    any on the same day; otherwise it is appended. Users can then reorder
    freely, also against the dates (e.g. two entries on the same day).
    """
    others = [e for e in await ordered_entries(db, entry.sample_id) if e is not entry]
    index = len(others)
    if entry.performed_at:
        for i, e in enumerate(others):
            if e.performed_at and e.performed_at > entry.performed_at:
                index = i
                break
    others.insert(index, entry)
    _apply_positions(others)


async def move(db: AsyncSession, sample_id: int, entry, direction: str):
    entries = await ordered_entries(db, sample_id)
    i = entries.index(entry)
    j = i - 1 if direction == "up" else i + 1
    if 0 <= j < len(entries):
        entries[i], entries[j] = entries[j], entries[i]
    _apply_positions(entries)


async def sort_by_date(db: AsyncSession, sample_id: int):
    """Reorder dated entries chronologically; undated entries keep their slots."""
    entries = await ordered_entries(db, sample_id)
    dated = sorted((e for e in entries if e.performed_at), key=lambda e: e.performed_at)
    it = iter(dated)
    _apply_positions([next(it) if e.performed_at else e for e in entries])
