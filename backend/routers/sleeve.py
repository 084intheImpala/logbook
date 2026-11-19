"""Sleeve sheet: several samples on one printable page, a compact block each
(ID, label, type, researcher, substrate, film stack, short timeline), to file with samples kept together in a sleeve.
Pieces are grouped under their mother sample (the first ancestor), in ID order;
what a piece inherits from a sample on the sheet is left to that sample's block.

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
MAX_ENTRIES = 3        # timeline lines per sample; with more, a summary instead (techniques and analyses, counted)
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


def _summary(entries: list[dict]) -> dict:
    """A long timeline in a few lines: how many of each step type and analysis type
    (in the order first done), and the dates it spans."""
    counts: dict[str, dict[str, int]] = {"process": {}, "analysis": {}}
    for e in entries:
        kind = counts["analysis" if e["kind"] == "analysis" else "process"]
        kind[e["type"]] = kind.get(e["type"], 0) + 1
    dates = [e["date"] for e in entries if e["date"]]
    return {"count": len(entries),
            "process": list(counts["process"].items()), "analysis": list(counts["analysis"].items()),
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
    (a mother and/or her pieces), or a run of samples on their own sharing rows.
    `head` names the mother when she isn't on the sheet herself."""
    sections = []
    for g in groups:
        if g["pieces"]:
            mother_here = g["blocks"][0]["sample"].id == g["root"].id
            sections.append({"head": None if mother_here else g["root"], "blocks": [
                b | {"wide": b["sample"].id == g["root"].id} for b in g["blocks"]]})
        elif sections and sections[-1].get("singles"):
            sections[-1]["blocks"] += g["blocks"]
        else:
            sections.append({"head": None, "singles": True, "blocks": list(g["blocks"])})
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
    blocks = []
    for sample_id in ids:
        if await db.get(Sample, sample_id) is None:
            continue
        page = await _page(request, db, sample_id, current_user)
        entries = _entries(page) if page["can_view"] or any(e["visible"] for e in page["timeline"]) else []
        blocks.append({
            "sample": page["sample"], "parent": page["parent"], "root": page["root"], "can_view": page["can_view"],
            "layers": _layers(page), "entries": entries,
        })
    # No doubled lines: an entry a piece inherits from a sample that has its own
    # block on the sheet is shown there only, so a piece lists what came after its cut.
    shown = {b["sample"].id for b in blocks}
    for b in blocks:
        entries = [e for e in b["entries"] if not (e["inherited"] and e["source_id"] in shown)]
        if len(entries) > MAX_ENTRIES:     # a long timeline would take a lot of paper: summed up instead
            b["entries"], b["summary"] = [], _summary(entries)
        else:
            b["entries"], b["summary"] = entries, None
    return templates.TemplateResponse("samples/sleeve.html", {
        "request": request, "current_user": current_user, "sections": _sections(_groups(blocks)),
        "count": len(blocks), "title": title.strip(), "left_out": left_out, "max_samples": MAX_SAMPLES,
        "printed_at": datetime.now().replace(microsecond=0),
    })
