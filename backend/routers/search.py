"""Search tab: filter samples, group the results, export them as CSV."""
from datetime import date
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User
from backend.auth import require_login, can_view, is_owner
from backend.export import load_samples_full, timeline_of, samples_csv

router = APIRouter(tags=["search"])
templates = Jinja2Templates(directory="frontend/templates")

GROUP_BY = {
    "": "No grouping",
    "investigator": "Investigator",
    "film_material": "Film material",
    "substrate_material": "Substrate",
    "technique": "Technique",
    "tag": "Tag",
}
NONE_LABEL = "(none)"


def _techniques(sample) -> list[str]:
    return list(dict.fromkeys(t for _, t, _ in timeline_of(sample)))


def _group_keys(sample, group_by: str) -> list[str]:
    """A sample can fall in several groups (e.g. one per technique or tag)."""
    if group_by == "investigator":
        keys = [sample.created_by]
    elif group_by == "technique":
        keys = _techniques(sample)
    elif group_by == "tag":
        keys = sample.tags or []
    else:
        keys = [getattr(sample, group_by)]
    return [k for k in keys if k] or [NONE_LABEL]


def _matches(sample, user, q: str, investigator: str, material: str, technique: str, tag: str) -> bool:
    eq = lambda a, b: (a or "").strip().lower() == b.strip().lower()
    if investigator and not eq(sample.created_by, investigator):
        return False
    if material and not (eq(sample.film_material, material) or eq(sample.substrate_material, material)):
        return False
    if technique and not any(eq(t, technique) for t in _techniques(sample)):
        return False
    if tag and not any(eq(t, tag) for t in sample.tags or []):
        return False
    if q:
        viewable = can_view(user, sample)  # don't reveal hidden details through matches
        haystack = [sample.name, str(sample.id), sample.film_material,
                    sample.substrate_material, sample.created_by, *(sample.tags or [])]
        if viewable:
            haystack.append(sample.description)
        for _, technique_name, e in timeline_of(sample):
            haystack.append(technique_name)
            if viewable:
                haystack += [e.notes, e.performed_by,
                             *(f"{k} {v}" for k, v in (e.parameters or {}).items())]
        text = " ".join(str(h) for h in haystack if h).lower()
        if not all(word in text for word in q.lower().split()):
            return False
    return True


async def _search(db: AsyncSession, user, q, investigator, material, technique, tag):
    samples = await load_samples_full(db)
    results = [s for s in samples if _matches(s, user, q, investigator, material, technique, tag)]
    options = {
        "investigators": sorted({s.created_by for s in samples if s.created_by}, key=str.lower),
        "materials": sorted({m for s in samples for m in (s.film_material, s.substrate_material) if m}, key=str.lower),
        "techniques": sorted({t for s in samples for t in _techniques(s)}, key=str.lower),
        "tags": sorted({t for s in samples for t in s.tags or []}, key=str.lower),
    }
    return results, options


@router.get("/search", response_class=HTMLResponse)
async def search_page(
    request: Request,
    q: str = "",
    investigator: str = "",
    material: str = "",
    technique: str = "",
    tag: str = "",
    group_by: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    results, options = await _search(db, current_user, q, investigator, material, technique, tag)
    if group_by not in GROUP_BY:
        group_by = ""

    groups: dict[str, list] = {}
    if group_by:
        for s in results:
            for key in _group_keys(s, group_by):
                groups.setdefault(key, []).append(s)
        # Alphabetical, with the "(none)" bucket last
        groups = dict(sorted(groups.items(), key=lambda kv: (kv[0] == NONE_LABEL, kv[0].lower())))
    else:
        groups = {"": results}

    filters = {"q": q, "investigator": investigator, "material": material,
               "technique": technique, "tag": tag}
    return templates.TemplateResponse("search/index.html", {
        "request": request,
        "current_user": current_user,
        "filters": filters,
        "group_by": group_by,
        "group_by_options": GROUP_BY,
        "groups": groups,
        "result_count": len(results),
        "options": options,
        "techniques_of": _techniques,
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
    material: str = "",
    technique: str = "",
    tag: str = "",
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    results, _ = await _search(db, current_user, q, investigator, material, technique, tag)
    return await samples_csv(db, results, f"logbook_search_{date.today():%Y%m%d}.csv",
                             show_details=lambda s: can_view(current_user, s))
