"""Search tab: filter samples, group the results, export them as CSV."""
from datetime import date
from urllib.parse import urlencode
from fastapi import APIRouter, Depends, Request
from fastapi.responses import HTMLResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_db
from backend.models import User, SAMPLE_TYPES
from backend.auth import require_login, can_view, is_owner, is_performer
from backend.export import samples_csv
from backend.lineage import Family, load_samples_full
from backend.params import describe, flatten, scalar_fields
from backend.i18n import t
from backend import rate_plot
from backend.deposition_rate import DEPOSITION_TYPE_NAME, RATE_KEY, rate_points

router = APIRouter(tags=["search"])
from backend.templating import templates

# Labels are English msgids; the templates translate them with _().
GROUP_BY = {
    "": "No grouping",
    "investigator": "Researcher",
    "year": "Year",
    "sample_type": "Sample type",
    "project": "Project",
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
    elif group_by == "project":
        keys = [f"{sample.project.name} ({sample.project.institution})" if sample.project and sample.project.institution
                else sample.project.name if sample.project else None]
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
        haystack = [sample.code, *(sample.previous_codes or []), sample.label, sample.external_id, sample.supplier, sample.film_material,
                    sample.substrate_material, sample.substrate.name if sample.substrate else None,
                    sample.researcher, sample.type_label, *(sample.tags or []),
                    *((sample.project.name, sample.project.code, sample.project.institution) if sample.project else ())]
        if viewable:
            haystack.append(sample.description)
        for item in family.timeline(sample):
            e = item.entry
            haystack.append(item.technique)
            if viewable:
                haystack += [e.notes, e.performer_name, e.location,
                             *(f"{k} {v}" for k, v in flatten(e.parameters).items())]
        text = " ".join(str(h) for h in haystack if h).lower()
        if not all(word in text for word in q.lower().split()):
            return False
    return True


def technique_entries(family: Family, samples, user, technique: str,
                      tr=lambda text: text) -> tuple[list[dict], list[dict], list[dict] | None]:
    """Every entry of `technique` on the given samples' timelines, newest
    first, with its parameters as columns: (columns [{id, label}], rows,
    the technique's schema). An entry inherited by pieces is listed once,
    under the sample it is recorded on; one shared by a run, once per sample.
    Entries the user can't see are left out. `tr` translates labels."""
    seen, rows, columns, schema = set(), [], {}, None
    wanted = technique.strip().lower()
    for sample in samples:
        for item in family.timeline(sample):
            e, source = item.entry, item.source
            if item.technique.lower() != wanted or (item.kind, e.id) in seen:
                continue
            seen.add((item.kind, e.id))
            if not (can_view(user, source) or is_performer(user, e)):
                continue
            entry_type = e.step_type if item.kind == "process" else e.analysis_type
            schema = entry_type.parameter_schema
            values = {}
            for row in describe(e.parameters, schema):
                if "rows" in row:   # a mode, e.g. XRD's rocking curve
                    prefix = f"{tr(row['group'])}: {row['label']}" if row["group"] else row["label"]
                    for sub in row["rows"]:
                        values[f"{row['key']}/{sub['key']}"] = (f"{prefix} / {tr(sub['label'])}", sub["value"])
                else:
                    values[row["key"]] = (tr(row["label"]), row["value"])
            for key, (label, _) in values.items():
                columns.setdefault(key, label)
            rows.append({"sample": source, "entry": e, "kind": item.kind,
                         "values": {key: value for key, (_, value) in values.items()}})
    rows.sort(key=lambda r: (r["entry"].performed_at is not None, r["entry"].performed_at or date.min,
                             r["entry"].id), reverse=True)
    return [{"id": key, "label": label} for key, label in columns.items()], rows, schema


# ── Filtering a technique's entries by their parameters ──────────────────────
# Query parameters: pf.<key> (a dropdown value, or text the value contains),
# min.<key> / max.<key> (a range, for numbers).

FILTERABLE = ("choice", "number", "text", "duration")


def filter_fields(schema: list[dict] | None) -> list[dict]:
    """The fields a technique's entries can be filtered by: the method
    (variant) choices and the single-value fields, long texts left out."""
    fields = [{"key": f["key"], "label": f.get("label") or f["key"], "type": "choice"}
              for f in schema or [] if f.get("type") == "variant"]
    return fields + [f for f in scalar_fields(schema) if f.get("type", "text") in FILTERABLE]


def _number(raw) -> float | None:
    try:
        return float(str(raw or "").strip().replace(",", "."))
    except ValueError:
        return None


def read_param_filters(query, fields: list[dict]) -> dict:
    """key → ("range", min, max) | ("eq", value) | ("has", text), for the filters filled in."""
    found = {}
    for f in fields:
        key = f["key"]
        if f.get("type") == "number":
            raw_low = (query.get(f"min.{key}") or "").strip()
            low, high = _number(raw_low), _number(query.get(f"max.{key}"))
            if raw_low and low is None:   # not a number, e.g. a gas flow of 20/5: that value exactly
                found[key] = ("eq", raw_low)
            elif low is not None or high is not None:
                found[key] = ("range", low, high)
        elif (value := (query.get(f"pf.{key}") or "").strip()):
            found[key] = ("eq" if f.get("type") == "choice" else "has", value)
    return found


def entry_matches(params: dict | None, filters: dict) -> bool:
    params = params or {}
    for key, (op, *args) in filters.items():
        value = params.get(key)
        if op == "range":
            low, high = args
            if not isinstance(value, (int, float)) or isinstance(value, bool) \
                    or (low is not None and value < low) or (high is not None and value > high):
                return False
        elif op == "eq":
            if str(value if value is not None else "").strip().lower() != args[0].lower():
                return False
        elif args[0].lower() not in str(value if value is not None else "").lower():
            return False
    return True


def technique_view(request: Request, family: Family, results, user, technique: str):
    """The entries table for the technique filtered by, with its parameter
    filters applied: (the samples left, the view for the template). With
    parameter filters, only samples with a matching entry are left."""
    columns, rows, schema = technique_entries(family, results, user, technique, lambda text: t(request, text))
    fields = filter_fields(schema)
    filters = read_param_filters(request.query_params, fields)
    for r in rows:
        r["params"] = r["entry"].parameters or {}
    points = {}
    if technique.strip().lower() == DEPOSITION_TYPE_NAME.lower():
        # The rate shown, filtered by and plotted is the measured one (average) when there is one
        points = rate_points(user, list(family.samples.values()), family)
        if not any(c["id"] == RATE_KEY for c in columns):
            columns.append({"id": RATE_KEY, "label": t(request, "Deposition rate")})
        for r in rows:
            point = points.get(r["entry"].id) if r["kind"] == "process" else None
            if point and point.rate is not None:
                r["params"] = r["params"] | {RATE_KEY: point.rate}
                note = (t(request, "average of {n}", n=point.n) if point.n > 1 else t(request, "measured") if point.n
                        else t(request, "typed"))
                r["values"][RATE_KEY] = f"{point.rate:g} nm/min ({note})"
    choices = {f["key"]: sorted({str(r["entry"].parameters[f["key"]]) for r in rows
                                 if (r["entry"].parameters or {}).get(f["key"]) not in (None, "")}, key=str.lower)
               for f in fields if f.get("type") == "choice"}
    # Only offer filters for parameters some entry has (and those in use), so
    # the form stays short enough to see the plot and the table below it
    used = {k for r in rows for k, v in r["params"].items() if v not in (None, "")} | set(filters)
    fields = [f for f in fields if f["key"] in used]
    if filters:
        rows = [r for r in rows if entry_matches(r["params"], filters)]
        matched = {(r["kind"], r["entry"].id) for r in rows}
        results = [s for s in results if any((i.kind, i.entry.id) in matched for i in family.timeline(s))]
    view = {
        "columns": columns,
        "rows": rows,
        "fields": [{"key": f["key"], "label": t(request, f.get("label") or f["key"]), "type": f.get("type", "text"),
                    "unit": f.get("unit", ""), "choices": choices.get(f["key"], [])} for f in fields],
        "active": len(filters),
        "plot": rate_plot.build([points[r["entry"].id] for r in rows if r["entry"].id in points and r["kind"] == "process"],
                                rate_plot.ranks(points.values())) if points else None,
        "query": request.query_params,
    }
    return results, view


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
    entry_view = None
    if technique:
        results, entry_view = technique_view(request, family, results, current_user, technique)
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
        "none_label": NONE_LABEL,
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
        # Filtering by a technique also lists its entries with their parameters
        "entry_view": entry_view,
        "flash": request.session.pop("flash", None),
        "current_url": str(request.url.path) + (f"?{request.url.query}" if request.url.query else ""),
        # Everything filtered by, parameter filters included
        "export_url": "/search/export.csv?" + urlencode([(k, v) for k, v in request.query_params.multi_items()
                                                         if v and k != "group_by"]),
    })


@router.get("/search/export.csv")
async def search_export(
    request: Request,
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
    if technique:   # parameter filters leave only samples with a matching entry
        results, _ = technique_view(request, family, results, current_user, technique)
    return await samples_csv(db, results, family, f"logbook_search_{date.today():%Y%m%d}.csv",
                             show_details=lambda s: can_view(current_user, s))
