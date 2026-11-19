"""Sleeve sheet: several samples on one printable page, a compact block each
(ID, label, type, researcher, substrate, film stack, short timeline), to file with samples kept together in a sleeve.
Pieces are grouped under their mother sample (the first ancestor), in ID order;
what a piece inherits from a sample on the sheet is left to that sample's block.
Pieces whose mother wasn't ticked bring her block along (`added`), for the history they share.

Picked with the tick boxes on the Samples list or the search results;
/samples/sleeve?ids=1&ids=2… Printed (or saved as PDF) by the browser.
"""
from datetime import datetime

from fastapi import APIRouter, Depends, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import require_login
from backend.database import get_db
from backend.models import Sample
from backend.routers.samples import _page
from backend.templating import templates

router = APIRouter(prefix="/samples/sleeve", tags=["sleeve"])

MAX_SAMPLES = 300      # only a guard against a runaway request; any left out are reported on the sheet
MAX_ENTRIES = 3        # timeline lines per sample; with more, the analyses are summed up (process steps always listed)
MAX_VALUES = 5         # parameter values per line (an implantation's ion, energy, fluence…)
# Values shown on top of the first MAX_VALUES, per step type: what matters most on a sleeve
ALSO_SHOWN = {"Deposition": ["gas_flow"]}


def _layers(page: dict) -> list[dict]:
    """The film stack, top layer first: material, thickness (nm), partial, planned."""
    drawing = page["layers"]
    if not drawing:
        return []
    return [{"material": l.material, "thickness": l.thickness, "partial": l.partial, "planned": l.planned}
            for l in drawing["layers"]]


def _entries(page: dict) -> list[dict]:
    """Done entries the viewer may see, oldest first, with their first few parameter values
    (and those in ALSO_SHOWN for their type)."""
    out = []
    for e in page["timeline"]:
        if e["planned"] or not e["visible"]:
            continue
        shown = [p for p in e["params"] if "value" in p and not p["long"] and p["value"]]
        also = ALSO_SHOWN.get(e["type_name"], [])
        values = [p["value"] for i, p in enumerate(shown) if i < MAX_VALUES or p["key"] in also]
        out.append({"date": e["performed_at"], "type": e["type_name"], "kind": e["kind"],
                    "summary": " · ".join(v.replace(" ", "\u00a0") for v in values),   # a value never splits from its unit
                    "inherited": e["inherited"],
                    "source": e["source"].title, "source_id": e["source"].id, "device": e["device"]})
    return out


def _analyses(entries: list[dict]) -> dict:
    """Analyses in one line: how many, the dates they span, and each analysis type once
    (in the order first done) with how many times it was done."""
    counts: dict[str, int] = {}
    for e in entries:
        counts[e["type"]] = counts.get(e["type"], 0) + 1
    dates = [e["date"] for e in entries if e["date"]]
    return {"count": len(entries), "types": list(counts.items()),
            "first": min(dates) if dates else None, "last": max(dates) if dates else None}


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


def _sections(groups: list[dict]) -> list[dict]:
    """The sheet's sections, each laid out on its own, evenly spaced: a family
    (her mother, then her pieces), or a run of samples on their own sharing rows."""
    sections = []
    for g in groups:
        if g["pieces"]:
            sections.append({"blocks": [b | {"wide": b["sample"].id == g["root"].id} for b in g["blocks"]]})
        elif sections and sections[-1].get("singles"):
            sections[-1]["blocks"] += g["blocks"]
        else:
            sections.append({"singles": True, "blocks": list(g["blocks"])})
    return sections


@router.get("", response_class=HTMLResponse)
async def sleeve_sheet(
    request: Request,
    ids: list[int] = Query([]),
    title: str = "",
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    ids = list(dict.fromkeys(ids))
    left_out = max(0, len(ids) - MAX_SAMPLES)
    ids = ids[:MAX_SAMPLES]
    if not ids:
        return RedirectResponse("/samples/", status_code=303)
    async def block(sample_id: int, added: bool = False) -> dict:
        page = await _page(request, db, sample_id, current_user)
        entries = _entries(page) if page["can_view"] or any(e["visible"] for e in page["timeline"]) else []
        return {"sample": page["sample"], "parent": page["parent"], "root": page["root"],
                "can_view": page["can_view"], "layers": _layers(page), "entries": entries, "added": added}

    blocks = [await block(i) for i in ids if await db.get(Sample, i) is not None]
    # Pieces without their mother on the sheet: she comes along (not counted as one of the
    # samples), so the history they share is written once, in her block
    count = len(blocks)
    shown = {b["sample"].id for b in blocks}
    for root_id in dict.fromkeys(b["root"].id for b in blocks):
        if root_id not in shown:
            blocks.append(await block(root_id, added=True))
            shown.add(root_id)
    # No doubled lines: an entry a piece inherits from a sample that has its own
    # block on the sheet is shown there only, so a piece lists what came after its cut.
    for b in blocks:
        entries = [e for e in b["entries"] if not (e["inherited"] and e["source_id"] in shown)]
        # A long timeline would take a lot of paper: its analyses are summed up in one line. Process
        # steps stay listed in full, as they're what tells samples apart (pieces annealed or
        # implanted differently).
        analyses = [e for e in entries if e["kind"] == "analysis"]
        if len(entries) > MAX_ENTRIES and analyses:
            b["entries"] = [e for e in entries if e["kind"] != "analysis"]
            b["analyses"] = _analyses(analyses)
        else:
            b["entries"], b["analyses"] = entries, None
    return templates.TemplateResponse("samples/sleeve.html", {
        "request": request, "current_user": current_user, "sections": _sections(_groups(blocks)),
        "count": count, "title": title.strip(), "left_out": left_out, "max_samples": MAX_SAMPLES,
        "printed_at": datetime.now().replace(microsecond=0),
    })
