"""Asking for the deposition rate once a film's thickness is measured.

After an Ellipsometry or Profilometry analysis with a thickness is saved on a
thin film, the sample page offers to fill in the Deposition rate (nm/min) of the
Deposition step before it on the timeline (inherited ones included, e.g. a
piece's parent's), if that step has no rate yet. The suggested rate is the
thickness over the deposition's duration, offered only when that deposition
is the only one before the measurement (otherwise the thickness is of the
whole stack, and the field is left for the user to fill in).
"""
from sqlalchemy import select

from backend.auth import can_edit_entry
from backend.lineage import _full_options, load_family
from backend.models import Sample

DEPOSITION_TYPE_NAME = "Deposition"
RATE_KEY = "deposition_rate"
# Analyses whose "thickness" is the film's thickness
THICKNESS_ANALYSES = {"Ellipsometry", "Profilometry"}


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


async def rate_prompt(db, sample, analysis, type_name: str, user) -> dict | None:
    """What to ask after `analysis` was saved on `sample`, or None."""
    thickness = _number((analysis.parameters or {}).get("thickness"))
    if (type_name not in THICKNESS_ANALYSES or thickness is None or sample.sample_type != "thin_film"
            or analysis.status != "approved"):
        return None
    # Reloaded: the session may hold the sample's entries from before the save
    full = (await db.execute(select(Sample).options(*_full_options()).where(Sample.id == sample.id)
                             .execution_options(populate_existing=True))).scalar_one()
    items = (await load_family(db, full))["family"].timeline(full)
    index = next((i for i, item in enumerate(items) if item.kind == "analysis" and item.entry.id == analysis.id), None)
    if index is None:
        return None
    depositions = [item for item in items[:index] if item.kind == "process" and item.technique == DEPOSITION_TYPE_NAME]
    if not depositions:
        return None
    last = depositions[-1]
    step = last.entry
    if (step.parameters or {}).get(RATE_KEY) not in (None, "") or not can_edit_entry(user, last.source, step):
        return None
    seconds = duration_seconds((step.parameters or {}).get("duration"))
    suggested = float(f"{thickness / seconds * 60:.3g}") if seconds and len(depositions) == 1 else None
    return {
        "sample_id": last.source.id,
        "step_id": step.id,
        "step_date": step.performed_at.isoformat() if step.performed_at else None,
        "inherited": last.source.id != sample.id,
        "source_title": last.source.title,
        "analysis": type_name,
        "thickness": thickness,
        "duration": (step.parameters or {}).get("duration") if seconds else None,
        "suggested": suggested,
        "stack": len(depositions) > 1,
    }


def set_rate(entries, rate: float) -> int:
    """Fill in `rate` on deposition steps that have none (the step itself and
    copies of it in the same run, deposited together); how many were filled."""
    filled = 0
    for entry in entries:
        params = dict(entry.parameters or {})
        if params.get(RATE_KEY) in (None, ""):
            entry.parameters = params | {RATE_KEY: rate}   # a new dict, so the JSON change is saved
            filled += 1
    return filled
