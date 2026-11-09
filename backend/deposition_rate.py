"""Deposition rates, measured from the thickness of the film.

An Ellipsometry or Profilometry analysis with a thickness measures the
Deposition before it on the timeline, when that is the only deposition so far
(otherwise the thickness is of the whole stack) and nothing that changes the
thickness (etching, CMP, annealing, …: anything outside THICKNESS_KEEPING_STEPS)
was done in between. Pieces count: a piece inherits its parent's timeline, so a
measurement on a piece measures the parent's deposition. Copies of one
deposition on several samples (a run) are films on different samples, so each
copy has only its own measurements: they are not pooled.

Each such measurement gives a rate, thickness ÷ the deposition's duration, in
nm/min. The deposition's *measured rate* is their average. Where there is none
(a stack, no duration), the rate can still be typed in the Deposition rate
field; after such a measurement the sample page asks for it. The rate used for
search and plots is the measured one if there is one, else the typed one.
"""
from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from sqlalchemy import select

from backend.auth import can_edit_entry, can_view, is_performer
from backend.lineage import Family, Item, _full_options
from backend.models import Sample

DEPOSITION_TYPE_NAME = "Deposition"
RATE_KEY = "deposition_rate"
# Analyses whose "thickness" is the film's thickness
THICKNESS_ANALYSES = {"Ellipsometry", "Profilometry"}
# Steps between a deposition and a measurement that leave the film's thickness as it was
THICKNESS_KEEPING_STEPS = {"Cut", "Cleaning"}
# What the rate depends on: depositions are compared (plots) when these all match
CONDITION_KEYS = ("machine", "target", "atmosphere", "gas_flow", "power")


def duration_seconds(value) -> int | None:
    """A stored duration ("min:ss", see params.normalize_duration) in seconds."""
    parts = str(value or "").split(":")
    try:
        seconds = int(parts[0]) * 60 + int(parts[1]) if len(parts) == 2 else None
    except ValueError:
        return None
    return seconds or None


def _number(value) -> float | None:
    return float(value) if isinstance(value, (int, float)) and not isinstance(value, bool) and value > 0 else None


@dataclass
class Measurement:
    item: Item                 # the analysis, and the sample it is recorded on
    deposition: Item           # the deposition it measures
    thickness: float           # nm
    rate: float | None         # nm/min; None when the deposition has no duration

    @property
    def sample(self) -> Sample:
        return self.item.source


@dataclass
class Context:
    """Where a thickness analysis sits on a timeline."""
    deposition: Item | None    # the last deposition before it
    depositions: int           # how many depositions before it
    changed: bool              # a thickness-changing step since the last deposition


def _walk(family: Family, sample: Sample):
    """(analysis item, Context) for each thickness analysis on the sample's timeline."""
    last, count, changed = None, 0, False
    for item in family.timeline(sample):
        if item.kind == "process":
            if item.technique == DEPOSITION_TYPE_NAME:
                last, count, changed = item, count + 1, False
            elif item.technique not in THICKNESS_KEEPING_STEPS:
                changed = True
        elif item.technique in THICKNESS_ANALYSES:
            yield item, Context(last, count, changed)


def measurements(family: Family, samples) -> dict[int, list[Measurement]]:
    """Deposition step id → the thickness measurements of it, found on the
    timelines of `samples` (they and their ancestors must be in `family`)."""
    found: dict[int, list[Measurement]] = {}
    seen = set()
    for sample in samples:
        for item, ctx in _walk(family, sample):
            thickness = _number((item.entry.parameters or {}).get("thickness"))
            if item.entry.id in seen or thickness is None:
                continue
            seen.add(item.entry.id)   # a piece also lists its parent's analyses
            if ctx.deposition is None or ctx.depositions != 1 or ctx.changed:
                continue
            seconds = duration_seconds((ctx.deposition.entry.parameters or {}).get("duration"))
            rate = float(f"{thickness / seconds * 60:.4g}") if seconds else None
            found.setdefault(ctx.deposition.entry.id, []).append(Measurement(item, ctx.deposition, thickness, rate))
    return found


def of_step(by_step: dict[int, list[Measurement]], step) -> list[Measurement]:
    """The measurements of `step` (on its sample and pieces), oldest first."""
    return sorted(by_step.get(step.id, []), key=lambda m: (m.item.entry.performed_at or date.max, m.item.entry.id))


def visible(user, found: list[Measurement]) -> list[Measurement]:
    return [m for m in found if can_view(user, m.sample) or is_performer(user, m.item.entry)]


def average(found: list[Measurement]) -> float | None:
    rates = [m.rate for m in found if m.rate is not None]
    return float(f"{sum(rates) / len(rates):.4g}") if rates else None


def effective_rate(step, found: list[Measurement]) -> tuple[float | None, int]:
    """The rate to use for `step`: (the average of its measurements, how many),
    or (the typed Deposition rate, 0)."""
    measured = [m for m in found if m.rate is not None]
    if measured:
        return average(measured), len(measured)
    return _number((step.parameters or {}).get(RATE_KEY)), 0


def conditions(step) -> tuple:
    """The deposition's machine, target, gas, gas flow and power, for matching (case and spacing ignored)."""
    params = step.parameters or {}
    return tuple(str(params.get(k)).strip().lower() if params.get(k) not in (None, "") else None
                 for k in CONDITION_KEYS)


async def all_samples(db) -> list[Sample]:
    """Every sample with its entries, freshly loaded (the session may hold
    entries from before a save)."""
    return list((await db.execute(select(Sample).options(*_full_options()).order_by(Sample.id)
                                  .execution_options(populate_existing=True))).scalars())


async def after_measurement(db, sample, analysis, type_name: str, user) -> dict | None:
    """What to tell or ask after `analysis` was saved on `sample`, or None:
    {"counted": True, ...} when it counts towards the deposition's measured
    rate; {"counted": False, ...} to ask for the rate by hand (a stack, or no
    duration), if the deposition has none yet and the user may edit it."""
    thickness = _number((analysis.parameters or {}).get("thickness"))
    if type_name not in THICKNESS_ANALYSES or thickness is None or analysis.status != "approved" or analysis.planned:
        return None
    samples = await all_samples(db)
    family = Family(samples)
    me = next(s for s in samples if s.id == sample.id)
    ctx = next((c for item, c in _walk(family, me) if item.entry.id == analysis.id), None)
    if ctx is None or ctx.deposition is None or ctx.changed:
        return None
    step, source = ctx.deposition.entry, ctx.deposition.source
    info = {"sample_id": source.id, "step_id": step.id, "source_title": source.title,
            "step_date": step.performed_at.isoformat() if step.performed_at else None,
            "inherited": source.id != sample.id, "analysis": type_name, "thickness": thickness}
    if ctx.depositions == 1 and duration_seconds((step.parameters or {}).get("duration")):
        found = visible(user, of_step(measurements(family, samples), step))
        return info | {"counted": True, "rate": average(found), "n": sum(m.rate is not None for m in found)}
    if (step.parameters or {}).get(RATE_KEY) not in (None, "") or not can_edit_entry(user, source, step):
        return None
    return info | {"counted": False, "stack": ctx.depositions > 1}


def set_rate(entries, rate: float) -> int:
    """Fill in `rate` on deposition steps that have none; how many were filled."""
    filled = 0
    for entry in entries:
        params = dict(entry.parameters or {})
        if params.get(RATE_KEY) in (None, ""):
            entry.parameters = params | {RATE_KEY: rate}   # a new dict, so the JSON change is saved
            filled += 1
    return filled


@dataclass
class RatePoint:
    step: object               # the Deposition step
    sample: Sample             # the sample it is recorded on
    rate: float | None         # effective_rate
    n: int                     # measurements averaged (0: the typed rate)
    found: list                # its visible measurements (on its sample and pieces)


def rate_points(user, samples, family: Family | None = None) -> dict[int, RatePoint]:
    """Deposition step id → RatePoint, for every approved deposition (not planned) on
    `samples` that `user` can see (all samples should be given, so that
    measurements on pieces and run copies are found)."""
    family = family or Family(samples)
    by_step = measurements(family, samples)
    points = {}
    for sample in samples:
        for step in sample.process_steps:
            if step.status != "approved" or step.planned or step.step_type.name != DEPOSITION_TYPE_NAME:
                continue
            if not (can_view(user, sample) or is_performer(user, step)):
                continue
            found = visible(user, of_step(by_step, step))
            rate, n = effective_rate(step, found)
            points[step.id] = RatePoint(step, sample, rate, n, found)
    return points


def last_rate(user, samples, params: dict) -> RatePoint | None:
    """The latest deposition with a rate whose conditions match those filled
    in `params` (machine, target, gas, gas flow, power; empty ones match
    anything), among those `user` can see: what a new deposition's duration
    can be worked out from. Undated depositions count as the oldest."""
    wanted = {i: v for i, v in enumerate(conditions(SimpleNamespace(parameters=params))) if v is not None}
    if not wanted:
        return None
    found = [p for p in rate_points(user, samples).values()
             if p.rate is not None and all(conditions(p.step)[i] == v for i, v in wanted.items())]
    return max(found, key=lambda p: (p.step.performed_at or date.min, p.step.id), default=None)
