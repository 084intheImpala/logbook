"""Pieces cut from a sample, and the timelines they inherit.

Cutting a sample adds a "Cut" step to its timeline and creates one new sample
per piece, each pointing at that step (Sample.cut_step_id). A piece inherits
everything on its parent's timeline before the Cut step, including what the
parent itself inherited. Entries are never copied: fixing a parent entry
fixes it for every piece.
"""
from dataclasses import dataclass
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Sample, ProcessStep, Analysis
from backend.auth import can_view, is_performer, is_proposer

# The step type that cutting records; only the cut form adds it.
CUT_TYPE_NAME = "Cut"

_LAST = 1 << 30


@dataclass
class Item:
    kind: str                       # "process" | "analysis"
    technique: str
    entry: ProcessStep | Analysis
    source: Sample                  # the sample the entry is recorded on


def _pos(entry) -> int:
    return entry.position if entry.position is not None else _LAST


def own_items(sample: Sample) -> list[Item]:
    """The sample's own steps and analyses (types must be loaded), in timeline order."""
    # Proposed entries waiting for approval aren't part of the timeline yet
    items = [Item("process", s.step_type.name, s, sample) for s in sample.process_steps if s.status == "approved"]
    items += [Item("analysis", a.analysis_type.name, a, sample) for a in sample.analyses if a.status == "approved"]
    return sorted(items, key=lambda i: (_pos(i.entry), i.entry.id))


class Family:
    """In-memory index over loaded samples, for resolving cuts without queries."""

    def __init__(self, samples):
        self.samples = {s.id: s for s in samples}
        self.steps = {st.id: st for s in samples for st in s.process_steps}

    def parent_and_cut(self, sample: Sample) -> tuple[Sample | None, ProcessStep | None]:
        cut = self.steps.get(sample.cut_step_id) if sample.cut_step_id else None
        return (self.samples.get(cut.sample_id), cut) if cut else (None, None)

    def inherited(self, sample: Sample, _seen=None) -> list[Item]:
        """Entries the sample inherits from its ancestors, oldest first."""
        seen = _seen or set()
        parent, cut = self.parent_and_cut(sample)
        if parent is None or parent.id in seen:
            return []
        seen.add(parent.id)
        before_cut = [i for i in own_items(parent) if _pos(i.entry) < _pos(cut)]
        return self.inherited(parent, seen) + before_cut

    def timeline(self, sample: Sample) -> list[Item]:
        return self.inherited(sample) + own_items(sample)


def _full_options():
    return (
        selectinload(Sample.process_steps).selectinload(ProcessStep.step_type),
        selectinload(Sample.analyses).selectinload(Analysis.analysis_type),
    )


async def load_samples_full(db: AsyncSession) -> list[Sample]:
    result = await db.execute(select(Sample).options(*_full_options()).order_by(Sample.id))
    return list(result.scalars())


async def load_sample_full(db: AsyncSession, sample_id: int) -> Sample | None:
    result = await db.execute(select(Sample).options(*_full_options()).where(Sample.id == sample_id))
    return result.scalar_one_or_none()


async def load_family(db: AsyncSession, sample: Sample) -> dict:
    """Ancestors (for the inherited timeline), siblings and pieces of a sample."""
    loaded = [sample]
    current = sample
    while current.cut_step_id:
        cut = await db.get(ProcessStep, current.cut_step_id)
        parent = await load_sample_full(db, cut.sample_id) if cut else None
        if parent is None or any(s.id == parent.id for s in loaded):
            break
        loaded.append(parent)
        current = parent
    family = Family(loaded)
    parent, cut = family.parent_and_cut(sample)

    siblings = []
    if sample.cut_step_id:
        siblings = (await db.execute(
            select(Sample).where(Sample.cut_step_id == sample.cut_step_id).order_by(Sample.code)
        )).scalars().all()

    own_step_ids = [s.id for s in sample.process_steps]
    pieces_by_cut: dict[int, list[Sample]] = {}
    if own_step_ids:
        rows = (await db.execute(
            select(Sample).where(Sample.cut_step_id.in_(own_step_ids)).order_by(Sample.code)
        )).scalars()
        for piece in rows:
            pieces_by_cut.setdefault(piece.cut_step_id, []).append(piece)

    return {
        "family": family,
        "parent": parent,
        "cut": cut,
        "siblings": siblings,
        "pieces_by_cut": pieces_by_cut,
    }


async def pieces_of(db: AsyncSession, sample_id: int, before_position: int | None = None) -> list[Sample]:
    """All samples descended from `sample_id` (pieces, their pieces, …).

    With `before_position`, only pieces cut after that timeline position,
    i.e. the ones that inherit the entry at that position."""
    q = select(Sample).join(ProcessStep, Sample.cut_step_id == ProcessStep.id).where(ProcessStep.sample_id == sample_id)
    if before_position is not None:
        q = q.where(ProcessStep.position > before_position)
    result = []
    for piece in (await db.execute(q)).scalars().all():
        result.append(piece)
        result += await pieces_of(db, piece.id)
    return result


async def can_view_entry(db: AsyncSession, user, sample: Sample, entry) -> bool:
    """Viewing a piece includes its inherited history, so an entry is visible to
    anyone who can view its own sample or a piece that inherits it, and to
    whoever performed it."""
    if can_view(user, sample) or is_performer(user, entry) or is_proposer(user, entry):
        return True
    return any(can_view(user, p) for p in await pieces_of(db, sample.id, _pos(entry)))
