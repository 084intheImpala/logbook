"""Search tab: filter samples, group the results, export them as CSV."""
from datetime import date
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User, SAMPLE_TYPES
from backend.auth import require_login, can_view, is_owner
from backend.export import samples_csv
from backend.lineage import Family, load_samples_full

router = APIRouter(tags=["search"])
templates = Jinja2Templates(directory="frontend/templates")

GROUP_BY = {
    "": "No grouping",
    "investigator": "Researcher",
    "year": "Year",
    "sample_type": "Sample type",
    "film_material": "Film material",
    "substrate_material": "Substrate",
    "technique": "Technique",
    "tag": "Tag",
}
NONE_LABEL = "(none)"


def _techniques(family: Family, sample) -> list[str]:
    """Techniques on the sample's timeline, including those inherited by a piece."""
    return list(dict.fromkeys(i.technique for i in family.timeline(sample)))


def _group_keys(family: Family, sample, group_by: str) -> list[str]:
    """A sample can fall in several groups (e.g. one per technique or tag)."""
    if group_by == "investigator":
        keys = [sample.researcher]
    elif group_by == "year":
        keys = [str(sample.created_at.year)]
    elif group_by == "sample_type":
        keys = [sample.type_label]
    elif group_by == "technique":
        keys = _techniques(family, sample)
    elif group_by == "tag":
        keys = sample.tags or []
    else:
        keys = [getattr(sample, group_by)]
    return [k for k in keys if k] or [NONE_LABEL]


def _matches(family: Family, sample, user, q: str, investigator: str, sample_type: str,
             material: str, technique: str, tag: str) -> bool:
    eq = lambda a, b: (a or "").strip().lower() == b.strip().lower()
    if investigator and not eq(sample.researcher, investigator):
        return False
    if sample_type and sample.sample_type != sample_type:
        return False
    if material and not (eq(sample.film_material, material) or eq(sample.substrate_material, material)):
        return False
    if technique and not any(eq(t, technique) for t in _techniques(family, sample)):
        return False
    if tag and not any(eq(t, tag) for t in sample.tags or []):
        return False
    if q:
        # Don't reveal hidden details through matches. Viewing a piece includes
        # what it inherits, so its inherited entries count as viewable too.
        viewable = can_view(user, sample)
        haystack = [sample.code, sample.label, sample.external_id, sample.supplier, sample.film_material,
                    sample.substrate_material, sample.substrate.name if sample.substrate else None,
                    sample.researcher, sample.type_label, *(sample.tags or [])]
        if viewable:
            haystack.append(sample.description)
        for item in family.timeline(sample):
            e = item.entry
            haystack.append(item.technique)
            if viewable:
                haystack += [e.notes, e.performed_by,
                             *(f"{k} {v}" for k, v in (e.parameters or {}).items())]
        text = " ".join(str(h) for h in haystack if h).lower()
        if not all(word in text for word in q.lower().split()):
            return False
    return True


async def _search(db: AsyncSession, user, q, investigator, sample_type, material, technique, tag):
    samples = await load_samples_full(db)
    family = Family(samples)
    results = [s for s in samples if _matches(family, s, user, q, investigator, sample_type, material, technique, tag)]
    options = {
        "investigators": sorted({s.researcher for s in samples if s.researcher}, key=str.lower),
        "materials": sorted({m for s in samples for m in (s.film_material, s.substrate_material) if m}, key=str.lower),
        "techniques": sorted({t for s in samples for t in _techniques(family, s)}, key=str.lower),
        "tags": sorted({t for s in samples for t in s.tags or []}, key=str.lower),
    }
    return results, options, family


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = "",
    investigator: str = "",
    sample_type: str = "",
    material: str = "",
    technique: str = "",
    tag: str = "",
    group_by: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    results, options, family = await _search(db, current_user, q, investigator, sample_type, material, technique, tag)
    if group_by not in GROUP_BY:
        group_by = ""

    groups: dict[str, list] = {}
    if group_by:
        for s in results:
            for key in _group_keys(family, s, group_by):
                groups.setdefault(key, []).append(s)
        # Alphabetical, with the "(none)" bucket last
        groups = dict(sorted(groups.items(), key=lambda kv: (kv[0] == NONE_LABEL, kv[0].lower())))
    else:
        groups = {"": results}

    filters = {"q": q, "investigator": investigator, "sample_type": sample_type, "material": material,
               "technique": technique, "tag": tag}
    return templates.TemplateResponse("search/index.html", {
        "request": request,
        "current_user": current_user,
        "filters": filters,
        "group_by": group_by,
        "group_by_options": GROUP_BY,
        "sample_types": SAMPLE_TYPES,
        "groups": groups,
        "result_count": len(results),
        "options": options,
        "techniques_of": lambda s: _techniques(family, s),
        "parent_of": lambda s: family.parent_and_cut(s)[0],
        "can_view": lambda s: can_view(current_user, s),
        "is_owner": lambda s: is_owner(current_user, s),
        "any_owned": any(is_owner(current_user, s) for s in results),
        "share_users": (await db.execute(
            select(User).where(User.is_admin.is_(False), User.id != current_user.id).order_by(User.username)
        )).scalars().all(),
        "flash": request.session.pop("flash", None),
        "current_url": str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
        "export_url": "/search/export.csv?" + urlencode({k: v for k, v in filters.items() if v}),
    })


@router.get("/search/export.csv")
async def search_export(
    q: str = "",
    investigator: str = "",
    sample_type: str = "",
    material: str = "",
    technique: str = "",
    tag: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    results, _, family = await _search(db, current_user, q, investigator, sample_type, material, technique, tag)
    return await samples_csv(db, results, family, f"logbook_search_{date.today():%Y%m%d}.csv",
                             show_details=lambda s: can_view(current_user, s))
