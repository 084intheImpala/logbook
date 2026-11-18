"""Sleeve sheet: several samples on one printable page, a compact block each
(ID, label, type, researcher, substrate, film stack, short timeline and a QR
code to the sample's page), to file with samples kept together in a sleeve.
Pieces are grouped under their mother sample (the first ancestor), in ID order;
what a piece inherits from a sample on the sheet is left to that sample's block.

Picked with the tick boxes on the Samples list or the search results;
/samples/sleeve?ids=1&ids=2… Printed (or saved as PDF) by the browser.
"""
from datetime import datetime

import segno
from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_login
from backend.database import get_db
from backend.models import Sample
from backend.routers.samples import _page
from backend.templating import templates

router = APIRouter(prefix="/samples/sleeve", tags=["sleeve"])

MAX_SAMPLES = 60       # more than any sleeve holds
MAX_ENTRIES = 8        # timeline lines per sample; the rest are counted
MAX_VALUES = 5         # parameter values per line (an implantation's ion, energy, fluence…)


def qr_svg(url: str) -> str:
    """An inline SVG QR code for `url` (scales with its box: no width/height)."""
    svg = segno.make(url, error="m").svg_inline(scale=1, border=0, omitsize=True)
    return svg.replace("<svg ", '<svg class="qr" ', 1)


def _layers(page: dict) -> list[dict]:
    """The film stack, top layer first: material, thickness (nm), partial, planned."""
    drawing = page["layers"]
    if not drawing:
        return []
    return [{"material": l.material, "thickness": l.thickness, "partial": l.partial, "planned": l.planned}
            for l in drawing["layers"]]


def _entries(page: dict) -> list[dict]:
    """Done entries the viewer may see, oldest first, with their first few parameter values."""
    out = []
    for e in page["timeline"]:
        if e["planned"] or not e["visible"]:
            continue
        values = [p["value"] for p in e["params"] if "value" in p and not p["long"] and p["value"]]
        out.append({"date": e["performed_at"], "type": e["type_name"], "kind": e["kind"],
                    "summary": " · ".join(v.replace(" ", "\u00a0") for v in values[:MAX_VALUES]), "inherited": e["inherited"],
                    "source": e["source"].title, "source_id": e["source"].id, "device": e["device"]})
    return out


def _groups(blocks: list[dict]) -> list[dict]:
    """Blocks grouped by mother sample (the first ancestor of a piece), in ID order:
    the mother first, then its pieces. `pieces` says whether to head the group."""
    by_root: dict[int, list[dict]] = {}
    for b in blocks:
        by_root.setdefault(b["root"].id, []).append(b)
    groups = []
    for members in by_root.values():
        root = members[0]["root"]
        members.sort(key=lambda b: (b["sample"].id != root.id, b["sample"].code or ""))
        groups.append({"root": root, "blocks": members,
                       "pieces": any(b["sample"].id != root.id for b in members)})
    groups.sort(key=lambda g: g["root"].code or "")
    return groups


@router.get("", response_class=HTMLResponse)
async def sleeve_sheet(
    request: Request,
    ids: list[int] = Query([]),
    title: str = "",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    ids = list(dict.fromkeys(ids))[:MAX_SAMPLES]
    if not ids:
        return RedirectResponse("/samples/", status_code=303)
    blocks = []
    for sample_id in ids:
        if await db.get(Sample, sample_id) is None:
            continue
        page = await _page(request, db, sample_id, current_user)
        entries = _entries(page) if page["can_view"] or any(e["visible"] for e in page["timeline"]) else []
        url = str(request.url_for("sample_detail", sample_id=sample_id))
        blocks.append({
            "sample": page["sample"], "parent": page["parent"], "root": page["root"], "can_view": page["can_view"],
            "layers": _layers(page), "entries": entries, "url": url, "qr": qr_svg(url),
        })
    # No doubled lines: an entry a piece inherits from a sample that has its own
    # block on the sheet is shown there only, so a piece lists what came after its cut.
    shown = {b["sample"].id for b in blocks}
    for b in blocks:
        entries = [e for e in b["entries"] if not (e["inherited"] and e["source_id"] in shown)]
        b["entries"], b["more"] = entries[:MAX_ENTRIES], max(0, len(entries) - MAX_ENTRIES)
    return templates.TemplateResponse("samples/sleeve.html", {
        "request": request, "current_user": current_user, "groups": _groups(blocks),
        "count": len(blocks), "title": title.strip(),
        "printed_at": datetime.now().replace(microsecond=0),
    })
