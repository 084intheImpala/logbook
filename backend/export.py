"""Loading samples with their full timeline, and flattening them to CSV."""
import csv
import io
from datetime import datetime
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.models import Sample, ProcessStep, Analysis, Attachment

SAMPLE_COLUMNS = [
    "sample_id", "sample_name", "tags", "film_material", "substrate_material",
    "substrate_dimensions", "description", "created_by", "created_at",
]
ENTRY_COLUMNS = [
    "entry_order", "entry_kind", "technique", "performed_at", "performed_by", "notes", "attachments",
]


async def load_samples_full(db: AsyncSession) -> list[Sample]:
    result = await db.execute(
        select(Sample)
        .options(
            selectinload(Sample.process_steps).selectinload(ProcessStep.step_type),
            selectinload(Sample.analyses).selectinload(Analysis.analysis_type),
        )
        .order_by(Sample.id)
    )
    return list(result.scalars())


def timeline_of(sample: Sample) -> list[tuple[str, str, ProcessStep | Analysis]]:
    """(kind, technique name, entry) for each step/analysis, in timeline order."""
    entries = [("process", s.step_type.name, s) for s in sample.process_steps]
    entries += [("analysis", a.analysis_type.name, a) for a in sample.analyses]
    return sorted(entries, key=lambda e: (e[2].position is None, e[2].position or 0, e[2].id))


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


async def samples_csv(db: AsyncSession, samples: list[Sample], filename: str,
                      show_details=lambda sample: True) -> Response:
    """One row per timeline entry (a sample with no entries gets one row).
    Each parameter key gets its own `param:<key>` column. For samples where
    `show_details(sample)` is false, only the summary columns are filled."""
    att_rows = (await db.execute(select(Attachment))).scalars().all()
    attachments: dict[tuple[str, int], list[str]] = {}
    for att in att_rows:
        attachments.setdefault((att.entity_type, att.entity_id), []).append(att.original_filename)

    rows, param_keys = [], {}
    for s in samples:
        details = show_details(s)
        base = {
            "sample_id": s.id, "sample_name": s.name, "tags": ", ".join(s.tags or []),
            "film_material": s.film_material, "substrate_material": s.substrate_material,
            "substrate_dimensions": s.substrate_dimensions, "description": s.description if details else None,
            "created_by": s.created_by, "created_at": s.created_at,
        }
        entries = timeline_of(s)
        if not entries:
            rows.append(base)
        for i, (kind, technique, e) in enumerate(entries, 1):
            row = {**base, "entry_order": i, "entry_kind": kind, "technique": technique}
            if not details:
                rows.append(row)
                continue
            row |= {
                "performed_at": e.performed_at, "performed_by": e.performed_by, "notes": e.notes,
                "attachments": "; ".join(attachments.get(("step" if kind == "process" else "analysis", e.id), [])),
            }
            for k, v in (e.parameters or {}).items():
                param_keys.setdefault(k, None)
                row[f"param:{k}"] = v
            rows.append(row)

    columns = SAMPLE_COLUMNS + ENTRY_COLUMNS + [f"param:{k}" for k in param_keys]
    buf = io.StringIO()
    buf.write("﻿")  # BOM so Excel reads UTF-8 (°, µ, θ…) correctly
    writer = csv.writer(buf)
    writer.writerow(columns)
    for row in rows:
        writer.writerow([_fmt(row.get(c)) for c in columns])
    return Response(
        buf.getvalue(),
        media_type="text/csv; charset=utf-8",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )
