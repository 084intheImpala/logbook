"""Flattening samples and their timelines (inherited entries included) to CSV."""
import csv
import io
from datetime import datetime
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Sample, Attachment
from backend.lineage import Family
from backend.params import flatten

SAMPLE_COLUMNS = [
    "sample_id", "label", "sample_type", "researcher", "created_at", "cut_from", "is_reference", "tags",
    "project", "institution", "film_material", "substrate", "substrate_material", "substrate_dimensions", "external_id",
    "supplier",
    "description",
]
ENTRY_COLUMNS = [
    "entry_order", "entry_kind", "technique", "inherited_from", "performed_at", "performed_by", "location", "notes",
    "attachments",
]


def _fmt(value) -> str:
    if value is None:
        return ""
    if isinstance(value, datetime):
        return value.strftime("%Y-%m-%d %H:%M")
    return str(value)


async def samples_csv(db: AsyncSession, samples: list[Sample], family: Family, filename: str,
                      show_details=lambda sample: True) -> Response:
    """One row per timeline entry (a sample with no entries gets one row).
    A piece's rows start with the entries it inherits from its parent(s),
    marked in `inherited_from`; `family` must cover all their ancestors.
    Each parameter key gets its own `param:<key>` column. For samples where
    `show_details(sample)` is false, only the summary columns are filled."""
    att_rows = (await db.execute(select(Attachment))).scalars().all()
    attachments: dict[tuple[str, int], list[str]] = {}
    for att in att_rows:
        attachments.setdefault((att.entity_type, att.entity_id), []).append(att.original_filename)

    rows, param_keys = [], {}
    for s in samples:
        details = show_details(s)
        parent, _ = family.parent_and_cut(s)
        base = {
            "sample_id": s.title, "label": s.label, "sample_type": s.type_label, "researcher": s.researcher,
            "cut_from": parent.title if parent else None,
            "is_reference": "yes" if s.is_reference else None, "tags": ", ".join(s.tags or []),
            "project": s.project.name if s.project else None,
            "institution": s.project.institution if s.project else None,
            "film_material": s.film_material, "substrate": s.substrate.name if s.substrate else None,
            "substrate_material": s.substrate_material, "substrate_dimensions": s.substrate_dimensions,
            "external_id": s.external_id, "supplier": s.supplier,
            "description": s.description if details else None, "created_at": s.created_at,
        }
        items = family.timeline(s)
        if not items:
            rows.append(base)
        for i, item in enumerate(items, 1):
            kind, e = item.kind, item.entry
            row = {**base, "entry_order": i, "entry_kind": kind, "technique": item.technique,
                   "inherited_from": item.source.title if item.source is not s else None}
            if not details:
                rows.append(row)
                continue
            row |= {
                "performed_at": e.performed_at, "performed_by": e.performer_name, "location": e.location, "notes": e.notes,
                "attachments": "; ".join(attachments.get(("step" if kind == "process" else "analysis", e.id), [])),
            }
            for k, v in flatten(e.parameters).items():
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
