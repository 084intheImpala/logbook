"""Import samples from JSON files (or a zip of them with their photos and files).

Upload → everything is checked and the page shows what would be created
(IDs, owners, entries, pieces, files) with any errors; nothing is saved until
"Import". The upload waits in uploads/.imports/<token>/ in between. See
backend/sample_import.py for the format.
"""
import secrets
import shutil
import time
from pathlib import Path

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile
from fastapi.responses import HTMLResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession

from backend.activity import log as log_activity
from backend.auth import require_login
from backend.config import settings
from backend.database import get_db
from backend.i18n import t
from backend.models import User
from backend.routers.samples import _ask_to_confirm
from backend.sample_import import Bundle, Problem, read_bundle, run_import
from backend.templating import templates
from backend.utils import chosen_files

router = APIRouter(prefix="/samples/import", tags=["import"])

WAITING = ".imports"   # under UPLOAD_DIR


def _folder(token: str) -> Path:
    if not token.isalnum():
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


@router.post("/check", response_class=HTMLResponse)
async def check_import(
    request: Request,
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    files = chosen_files(files)
    if not files:
        return _page(request, current_user, problem=t(request, "Choose a .json or .zip file."))
    _clear_old_uploads()
    token = secrets.token_hex(16)
    folder = _folder(token)
    folder.mkdir(parents=True)
    for n, f in enumerate(files):
        (folder / f"{n:03d}-{Path(f.filename).name}").write_bytes(await f.read())
    # A check never saves anything: rolled back once the page is rendered (a
    # rollback expires everything loaded, the logged-in user included)
    try:
        report = await run_import(db, current_user, _bundle(folder), dry_run=True, tr=_tr(request))
    except Problem as exc:
        shutil.rmtree(folder, ignore_errors=True)
        response = _page(request, current_user, problem=t(request, exc.text, **exc.values))
        await db.rollback()
        return response
    if report.errors:
        shutil.rmtree(folder, ignore_errors=True)
    else:
        request.session["import_token"] = token
    response = _page(request, current_user, report=report, token=None if report.errors else token)
    await db.rollback()
    return response


@router.post("/{token}", response_class=HTMLResponse)
async def do_import(
    request: Request,
    token: str,
    db: AsyncSession = Depends(get_db),
    current_user=Depends(require_login),
):
    folder = _folder(token)
    if request.session.get("import_token") != token or not folder.is_dir():
        return _page(request, current_user,
                     problem=t(request, "That upload has expired or was already imported; upload the file again."))
    tr = _tr(request)
    try:
        report = await run_import(db, current_user, _bundle(folder), dry_run=False, tr=tr)
    except Problem as exc:
        response = _page(request, current_user, problem=t(request, exc.text, **exc.values))
        await db.rollback()
        return response
    if report.errors:   # something changed since the check (e.g. a substrate was deleted)
        response = _page(request, current_user, report=report)
        await db.rollback()
        return response
    log_activity(db, current_user, "samples_imported", ", ".join(s["code"] for s in report.samples), current_user,
                 tr("{n} samples", n=report.count))
    await db.commit()
    request.session.pop("import_token", None)
    shutil.rmtree(folder, ignore_errors=True)
    for owner_id, samples in report.handed_over.items():
        owner = await db.get(User, owner_id)
        await _ask_to_confirm(request, current_user.display_name, owner.display_name, owner.email, samples)
    return _page(request, current_user, report=report, done=True)
