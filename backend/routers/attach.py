"""Add files tab: find steps and analyses across samples (e.g. the annealings
you did yesterday), tick them and attach the same photos and files to all of
them at once. Each file is stored once and shared, as for a run."""
from datetime import date, datetime, timedelta
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from backend.auth import can_edit_entry, require_login
from backend.config import settings
from backend.database import get_db
from backend.i18n import t
from backend.models import Analysis, AnalysisType, Attachment, ProcessStep, ProcessStepType, User
from backend.params import parse_date
from backend.templating import templates
from backend.utils import chosen_files, copy_attachment, save_upload

router = APIRouter(prefix="/attach", tags=["attach"], dependencies=[Depends(require_login)])

KINDS = {"step": (ProcessStep, ProcessStepType, "step_type_id", "step_type"),
         "analysis": (Analysis, AnalysisType, "analysis_type_id", "analysis_type")}
LIMIT = 300   # entries shown at most; narrow the filters to see others
FILTERS = ("type", "date_from", "date_to", "mine", "q")


def _day(raw: str) -> date | None:
    try:
        return parse_date(raw)
    except ValueError:
        return None


async def _type_options(db: AsyncSession) -> list[tuple[str, str, str]]:
    """(value, group, name) for the type filter, e.g. ("step:3", "step", "Annealing")."""
    options = []
    for kind, (_, type_model, _, _) in KINDS.items():
        rows = (await db.execute(select(type_model.id, type_model.name).order_by(type_model.name))).all()
        options += [(f"{kind}:{i}", kind, name) for i, name in rows]
    return options


async def _entries(db: AsyncSession, user: User, filters: dict) -> tuple[list[dict], bool]:
    """The entries matching `filters` that `user` may add files to, newest
    first, and whether there were more than LIMIT."""
    kind_filter, _, type_id = filters["type"].partition(":")
    date_from, date_to = _day(filters["date_from"]), _day(filters["date_to"])
    words = filters["q"].lower().split()
    found = []
    for kind, (model, _, type_column, type_attr) in KINDS.items():
        if kind_filter and kind_filter != kind:
            continue
        query = select(model).options(selectinload(model.sample), selectinload(getattr(model, type_attr)))
        if type_id.isdigit():
            query = query.where(getattr(model, type_column) == int(type_id))
        if date_from:
            query = query.where(model.performed_at >= date_from)
        if date_to:
            query = query.where(model.performed_at <= date_to)
        if filters["mine"]:
            query = query.where(model.performer_id == user.id)
        for entry in (await db.execute(query)).scalars():
            sample = entry.sample
            if not can_edit_entry(user, sample, entry):
                continue
            if words:
                text = " ".join(str(v) for v in (sample.title, sample.code, sample.label, entry.notes, entry.location) if v).lower()
                if not all(w in text for w in words):
                    continue
            found.append({"kind": kind, "entry": entry, "sample": sample,
                          "type_name": getattr(entry, type_attr).name if getattr(entry, type_attr) else "",
                          "device": entry.device.label if kind == "analysis" and entry.device else None})
    found.sort(key=lambda r: (r["entry"].performed_at or date.min, r["entry"].created_at or datetime.min), reverse=True)
    shown = found[:LIMIT]
    for kind in KINDS:
        ids = [r["entry"].id for r in shown if r["kind"] == kind]
        counts = dict((await db.execute(
            select(Attachment.entity_id, func.count()).where(Attachment.entity_type == kind,
                                                             Attachment.entity_id.in_(ids))
            .group_by(Attachment.entity_id))).all()) if ids else {}
        for r in shown:
            if r["kind"] == kind:
                r["files"] = counts.get(r["entry"].id, 0)
    return shown, len(found) > LIMIT


def _filters(params) -> dict:
    filters = {k: (params.get(k) or "").strip() for k in FILTERS}
    # "Done by me" is on unless the form was sent with it unticked
    filters["mine"] = "1" if filters["mine"] or "searched" not in params else ""
    return filters


@router.get("", response_class=HTMLResponse)
async def attach_page(request: Request, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(require_login)):
    filters = _filters(request.query_params)
    rows, more = await _entries(db, current_user, filters)
    today = date.today()
    return templates.TemplateResponse("attach/index.html", {
        "request": request,
        "current_user": current_user,
        "filters": filters,
        "type_options": await _type_options(db),
        "rows": rows,
        "more": more,
        "limit": LIMIT,
        "today": today.isoformat(),
        "yesterday": (today - timedelta(days=1)).isoformat(),
        "back": urlencode({**filters, "searched": "1"}),
        "flash": request.session.pop("flash", None),
    })


@router.post("")
async def attach_files(request: Request, db: AsyncSession = Depends(get_db),
                       current_user: User = Depends(require_login)):
    form = await request.form()
    back = "/attach?" + urlencode({**_filters({k: form.get(k, "") for k in FILTERS}), "searched": "1"}
                                  if form.get("searched") else {})
    targets = []
    for value in dict.fromkeys(form.getlist("entry")):
        kind, _, raw_id = str(value).partition(":")
        if kind not in KINDS or not raw_id.isdigit():
            raise HTTPException(status_code=400, detail="Invalid entry")
        model = KINDS[kind][0]
        entry = (await db.execute(select(model).options(selectinload(model.sample))
                                  .where(model.id == int(raw_id)))).scalar_one_or_none()
        if entry is None:
            raise HTTPException(status_code=404, detail="Entry not found")
        if not can_edit_entry(current_user, entry.sample, entry):
            raise HTTPException(status_code=403, detail="You don't have access to this sample.")
        targets.append((kind, entry))

    uploads = [(f, True) for f in chosen_files(form.getlist("photos"))] + \
              [(f, False) for f in chosen_files(form.getlist("files"))]
    for f, _ in uploads:
        if f.size is not None and f.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{f.filename} exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit")
    if not targets or not uploads:
        request.session["flash"] = t(request, "Tick at least one entry and choose at least one file.")
        return RedirectResponse(back, status_code=303)

    (first_kind, first), rest = targets[0], targets[1:]
    added = 0
    for f, photo in uploads:
        stored = await save_upload(f, first_kind, first.id, db, uploaded_by=current_user.username, photo=photo)
        if stored is None:
            continue
        added += 1
        for kind, entry in rest:
            copy_attachment(stored, kind, entry.id, db)
    await db.commit()
    request.session["flash"] = t(request, "Added {files} file(s) to {entries} entries.",
                                 files=added, entries=len(targets))
    return RedirectResponse(back, status_code=303)
