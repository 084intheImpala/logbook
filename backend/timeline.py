"""Ordering of a sample's timeline (process steps and analyses together).

Every ProcessStep and Analysis has a `position`; positions are shared across
both tables so a sample's timeline is one ordered list. Dates are optional and
only used as a hint when placing a new entry.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ProcessStep, Analysis


async def ordered_entries(db: AsyncSession, sample_id: int, legacy: bool = False) -> list:
    steps = (await db.execute(select(ProcessStep).where(ProcessStep.sample_id == sample_id))).scalars().all()
    analyses = (await db.execute(select(Analysis).where(Analysis.sample_id == sample_id))).scalars().all()
    if legacy:
        return _legacy_order(steps, analyses)
    # Entries without a position (shouldn't happen after migration) go last.
    big = 1 << 30
    return sorted(
        [*steps, *analyses],
        key=lambda e: (e.position if e.position is not None else big, e.id),
    )


def _legacy_order(steps, analyses) -> list:
    """Pre-`position` ordering: steps by step_order, analyses merged in by date."""
    steps = sorted(steps, key=lambda s: s.step_order)
    analyses = sorted(analyses, key=lambda a: a.performed_at or a.created_at)
    result = []
    for a in analyses:
        a_date = a.performed_at or a.created_at
        while steps and (steps[0].performed_at or steps[0].created_at) <= a_date:
            result.append(steps.pop(0))
        result.append(a)
    return result + steps


def _apply_positions(entries: list):
    for i, e in enumerate(entries):
        e.position = i
        if isinstance(e, ProcessStep):
            e.step_order = i


async def renumber(db: AsyncSession, sample_id: int, legacy: bool = False):
    _apply_positions(await ordered_entries(db, sample_id, legacy=legacy))


async def place_new(db: AsyncSession, entry):
    """Insert a just-added (flushed) entry into its sample's timeline.

    With a date, it goes before the first dated entry that is later than it;
    otherwise it is appended. Users can reorder manually afterwards.
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
