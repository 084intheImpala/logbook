"""Import samples from JSON files (or a zip of them with their photos and files).

Upload → everything is checked and the page shows what would be created
(IDs, owners, entries, pieces, files) with any errors; nothing is saved until
"Import". The upload waits in uploads/.imports/<token>/ in between. See
backend/sample_import.py for the format.

Samples in the file that are already here ("Update samples already here",
on by default) are compared instead of created, and the page lists the
differences to tick (backend/sample_update.py); a sample's own page does the
same for that one sample (/samples/{id}/update).
"""
import secrets
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse, Response
from sqlalchemy.ext.asyncio import AsyncSession

from backend.activity import log as log_activity
from backend.auth import load_sample, require_login
from backend.config import settings
from backend.database import get_db
from backend.i18n import t
from backend.import_guide import guide
from backend.models import User
from backend.routers.samples import _ask_to_confirm
from backend.sample_import import Bundle, Problem, read_bundle
from backend.sample_update import run_import, run_update
from backend.templating import templates
from backend.utils import chosen_files

router = APIRouter(prefix="/samples/import", tags=["import"])
update_router = APIRouter(prefix="/samples", tags=["import"])

WAITING = ".imports"   # under UPLOAD_DIR


def _folder(token: str) -> Path:
    if not token.isalnum() or not token:
        raise HTTPException(status_code=404)
    return settings.UPLOAD_DIR / WAITING / token


def _clear_old_uploads():
    """Uploads checked but never imported are dropped after a day."""
    waiting = settings.UPLOAD_DIR / WAITING
    for folder in waiting.iterdir() if waiting.is_dir() else ():
        if time.time() - folder.stat().st_mtime > 24 * 3600:
            shutil.rmtree(folder, ignore_errors=True)


def _bundle(folder: Path) -> Bundle:
    """All uploaded files as one bundle (each .json or .zip read in turn)."""
    bundle = Bundle()
    for path in sorted(folder.iterdir()):
        part = read_bundle(path.name, path.read_bytes())
        bundle.documents += part.documents
        bundle.files |= part.files
    return bundle


def _tr(request: Request):
    return lambda text, **values: t(request, text, **values)


def _page(request: Request, user: User, **extra):
    return templates.TemplateResponse("samples/import.html", {"request": request, "current_user": user} | extra)


@router.get("", response_class=HTMLResponse)
async def import_form(request: Request, current_user=Depends(require_login)):
    return _page(request, current_user)


@router.get("/CLAUDE.md")
async def claude_md(db: AsyncSession = Depends(get_db), current_user=Depends(require_login)):
    """Instructions for an AI assistant preparing an import, with this logbook's names (import_guide.py)."""
    return Response(await guide(db, current_user), media_type="text/markdown; charset=utf-8",
                    headers={"Content-Disposition": 'attachment; filename="CLAUDE.md"'})


async def _keep(files: list[UploadFile]) -> tuple[str, Path]:
    """Put an upload aside until it's confirmed: its token and folder."""
    _clear_old_uploads()
    token = secrets.token_hex(16)
    folder = _folder(token)
    folder.mkdir(parents=True)
    for n, f in enumerate(files):
        (folder / f"{n:03d}-{Path(f.filename).name}").write_bytes(await f.read())
    return token, folder


@router.post("/check", response_class=HTMLResponse)
async def check_import(
    request: Request,
    files: list[UploadFile | str] = File([]),
    update: str = Form(""),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    files = chosen_files(files)
    if not files:
        return _page(request, current_user, problem=t(request, "Choose a .json or .zip file."))
    token, folder = await _keep(files)
    return await _check(request, db, current_user, token, folder, bool(update), set())


@router.post("/{token}/check", response_class=HTMLResponse)
async def recheck_import(
    request: Request,
    token: str,
    new: list[str] = Form([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    """Check the kept upload again, the samples in `new` (matched by label, marked
    "not the same sample") created as new instead of compared."""
    folder = _folder(token)
    if request.session.get("import_token") != token or not folder.is_dir():
        return _page(request, current_user,
                     problem=t(request, "That upload has expired or was already imported; upload the file again."))
    return await _check(request, db, current_user, token, folder, True, set(new))


async def _check(request: Request, db: AsyncSession, current_user: User, token: str, folder: Path,
                 update: bool, new: set[str]):
    # A check never saves anything: rolled back once the page is rendered (a
    # rollback expires everything loaded, the logged-in user included)
    try:
        report = await run_import(db, current_user, _bundle(folder), dry_run=True, tr=_tr(request), update=update,
                                  new=new)
    except Problem as exc:
        shutil.rmtree(folder, ignore_errors=True)
        response = _page(request, current_user, problem=t(request, exc.text, **exc.values))
        await db.rollback()
        return response
    ok = not report.errors and (report.samples or report.changes)
    if ok:
        request.session["import_token"] = token
    else:
        request.session.pop("import_token", None)
        shutil.rmtree(folder, ignore_errors=True)
    response = _page(request, current_user, report=report, token=token if ok else None, update=update,
                     new=sorted(new))
    await db.rollback()
    return response


@router.post("/{token}", response_class=HTMLResponse)
async def do_import(
    request: Request,
    token: str,
    update: str = Form(""),
    change: list[str] = Form([]),
    new: list[str] = Form([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    folder = _folder(token)
    if request.session.get("import_token") != token or not folder.is_dir():
        return _page(request, current_user,
                     problem=t(request, "That upload has expired or was already imported; upload the file again."))
    tr = _tr(request)
    try:
        report = await run_import(db, current_user, _bundle(folder), dry_run=False, tr=tr, update=bool(update),
                                  ticked=set(change), new=set(new))
    except Problem as exc:
        response = _page(request, current_user, problem=t(request, exc.text, **exc.values))
        await db.rollback()
        return response
    if report.errors:   # something changed since the check (e.g. a substrate was deleted)
        response = _page(request, current_user, report=report)
        await db.rollback()
        return response
    if report.samples:
        log_activity(db, current_user, "samples_imported", ", ".join(s["code"] for s in report.samples),
                     current_user, tr("{n} samples", n=report.count))
    await db.commit()
    request.session.pop("import_token", None)
    shutil.rmtree(folder, ignore_errors=True)
    for owner_id, samples in report.handed_over.items():
        owner = await db.get(User, owner_id)
        await _ask_to_confirm(request, current_user.display_name, owner.display_name, owner.email, samples)
    return _page(request, current_user, report=report, done=True)


# ── Updating a sample from a file ────────────────────────────────────────────

def _update_page(request: Request, user: User, sample, **extra):
    return templates.TemplateResponse("samples/update.html",
                                      {"request": request, "current_user": user, "sample": sample} | extra)


@update_router.get("/{sample_id}/update", response_class=HTMLResponse)
async def update_form(request: Request, sample_id: int, db: AsyncSession = Depends(get_db),
                      current_user=Depends(require_login)):
    sample = await load_sample(db, sample_id, current_user, "edit")
    return _update_page(request, current_user, sample)


@update_router.post("/{sample_id}/update/check", response_class=HTMLResponse)
async def check_update(
    request: Request,
    sample_id: int,
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    files = chosen_files(files)
    if sample.cut_step_id:
        return _update_page(request, current_user, sample, problem=t(
            request, "A piece is updated with the file of the sample it was cut from."))
    if not files:
        return _update_page(request, current_user, sample, problem=t(request, "Choose a .json or .zip file."))
    token, folder = await _keep(files)
    try:
        report = await run_update(db, current_user, _bundle(folder), sample, dry_run=True, tr=_tr(request))
    except Problem as exc:
        shutil.rmtree(folder, ignore_errors=True)
        response = _update_page(request, current_user, sample, problem=t(request, exc.text, **exc.values))
        await db.rollback()
        return response
    ok = not report.errors and report.changes
    if ok:
        request.session["update_token"] = f"{sample_id}:{token}"
    else:
        shutil.rmtree(folder, ignore_errors=True)
    response = _update_page(request, current_user, sample, report=report, token=token if ok else None)
    await db.rollback()
    return response


@update_router.post("/{sample_id}/update/{token}", response_class=HTMLResponse)
async def do_update(
    request: Request,
    sample_id: int,
    token: str,
    change: list[str] = Form([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    sample = await load_sample(db, sample_id, current_user, "edit")
    folder = _folder(token)
    if request.session.get("update_token") != f"{sample_id}:{token}" or not folder.is_dir():
        return _update_page(request, current_user, sample, problem=t(
            request, "That upload has expired or was already used; upload the file again."))
    if not change:
        return _update_page(request, current_user, sample, problem=t(request, "Nothing was ticked, so nothing changed."))
    try:
        report = await run_update(db, current_user, _bundle(folder), sample, dry_run=False, tr=_tr(request),
                                  ticked=set(change))
    except Problem as exc:
        response = _update_page(request, current_user, sample, problem=t(request, exc.text, **exc.values))
        await db.rollback()
        return response
    if report.errors:   # something changed since the check
        response = _update_page(request, current_user, sample, report=report)
        await db.rollback()
        return response
    done = report.changed
    await db.commit()
    request.session.pop("update_token", None)
    shutil.rmtree(folder, ignore_errors=True)
    request.session["flash"] = (t(request, "Updated from the file: 1 change made.") if done == 1 else
                                t(request, "Updated from the file: {n} changes made.", n=done))
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
