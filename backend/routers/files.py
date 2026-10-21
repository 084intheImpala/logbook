"""Uploaded files. Attachments hang off a step, an analysis, a sample (e.g. a
commercial sample's spec sheet) or a library substrate, and follow that
owner's access rules."""
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import Attachment, ProcessStep, Analysis, Substrate, User
from backend.config import settings
from backend.auth import require_login, load_sample, can_view, can_edit, can_edit_entry
from backend.lineage import can_view_entry
from backend.routers.substrates import can_edit_substrate
from backend.utils import save_upload, delete_attachment, chosen_files, ensure_thumbnail

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(require_login)])

ENTITY_MODELS = {"step": ProcessStep, "analysis": Analysis}


async def _entity_sample_id(db: AsyncSession, entity_type: str, entity_id: int) -> int:
    """The sample a sample/step/analysis attachment belongs to; 404 if missing."""
    if entity_type == "sample":
        return entity_id
    model = ENTITY_MODELS.get(entity_type)
    if model is None:
        raise HTTPException(status_code=400, detail="Invalid entity_type")
    sample_id = (await db.execute(select(model.sample_id).where(model.id == entity_id))).scalar_one_or_none()
    if sample_id is None:
        raise HTTPException(status_code=404, detail="Entry not found")
    return sample_id


async def _attachment(db: AsyncSession, attachment_id: int) -> Attachment:
    attachment = (await db.execute(select(Attachment).where(Attachment.id == attachment_id))).scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="File not found")
    return attachment


async def _substrate(db: AsyncSession, substrate_id: int) -> Substrate:
    substrate = await db.get(Substrate, substrate_id)
    if not substrate:
        raise HTTPException(status_code=404, detail="Substrate not found")
    return substrate


@router.post("/upload/{sample_id}")
async def upload_file_for_sample(
    sample_id: int,
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    photos: list[UploadFile | str] = File([]),
    files: list[UploadFile | str] = File([]),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    """Attach photos and/or files to a sample or one of its steps/analyses,
    then go back to the sample page. Photos may be downscaled; files aren't."""
    if await _entity_sample_id(db, entity_type, entity_id) != sample_id:
        raise HTTPException(status_code=400, detail="Entry does not belong to this sample")
    sample = await load_sample(db, sample_id, current_user, "summary")
    entry = await db.get(ENTITY_MODELS[entity_type], entity_id) if entity_type != "sample" else None
    if not (can_edit_entry(current_user, sample, entry) if entry else can_edit(current_user, sample)):
        raise HTTPException(status_code=403, detail="You don't have access to this sample.")
    photos, files = chosen_files(photos), chosen_files(files)
    for f in photos + files:
        if f.size is not None and f.size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
            raise HTTPException(status_code=413, detail=f"{f.filename} exceeds the {settings.MAX_UPLOAD_SIZE_MB} MB limit")
    for f in photos:
        await save_upload(f, entity_type, entity_id, db, uploaded_by=current_user.username, photo=True)
    for f in files:
        await save_upload(f, entity_type, entity_id, db, uploaded_by=current_user.username)
    await db.commit()
    anchor = f"#{entity_type}-{entity_id}" if entity_type != "sample" else ""
    return RedirectResponse(f"/samples/{sample_id}{anchor}", status_code=303)


async def _readable_attachment(db: AsyncSession, attachment_id: int, user: User) -> Attachment:
    """The attachment, if `user` may see it (403/404 otherwise)."""
    attachment = await _attachment(db, attachment_id)
    if attachment.entity_type == "substrate":
        await _substrate(db, attachment.entity_id)   # library specs are visible to everyone
        return attachment
    sample_id = await _entity_sample_id(db, attachment.entity_type, attachment.entity_id)
    sample = await load_sample(db, sample_id, user, "summary")
    if attachment.entity_type == "sample":
        allowed = can_view(user, sample)
    else:
        entry = await db.get(ENTITY_MODELS[attachment.entity_type], attachment.entity_id)
        allowed = await can_view_entry(db, user, sample, entry)
    if not allowed:
        raise HTTPException(status_code=403, detail="You don't have access to this file.")
    return attachment


@router.get("/{attachment_id}")
async def download_file(attachment_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_login)):
    attachment = await _readable_attachment(db, attachment_id, current_user)
    path = settings.UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing from disk")

    mime = attachment.mime_type or "application/octet-stream"
    return FileResponse(
        path=path,
        filename=attachment.original_filename,
        media_type=mime,
        # Show images (and PDFs) in the browser instead of downloading them
        content_disposition_type="inline" if mime.startswith("image/") or mime == "application/pdf" else "attachment",
    )


@router.get("/{attachment_id}/thumb")
async def thumbnail(attachment_id: int, db: AsyncSession = Depends(get_db),
                    current_user: User = Depends(require_login)):
    """Small JPEG preview; created on first request if it doesn't exist yet.
    Falls back to the original when no thumbnail can be made."""
    attachment = await _readable_attachment(db, attachment_id, current_user)
    had_thumb = attachment.thumbnail_filename is not None
    name = await ensure_thumbnail(attachment)
    if name and not had_thumb:
        await db.commit()
    if name and (settings.UPLOAD_DIR / name).exists():
        return FileResponse(settings.UPLOAD_DIR / name, media_type="image/jpeg",
                            headers={"Cache-Control": "private, max-age=86400"})
    return await download_file(attachment_id, db, current_user)


@router.post("/{attachment_id}/delete")
async def delete_file(attachment_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(require_login)):
    attachment = await _attachment(db, attachment_id)
    if attachment.entity_type == "substrate":
        substrate = await _substrate(db, attachment.entity_id)
        if not can_edit_substrate(current_user, substrate):
            raise HTTPException(status_code=403, detail="You can't change this substrate's files.")
        back = f"/substrates/{substrate.id}"
    else:
        sample_id = await _entity_sample_id(db, attachment.entity_type, attachment.entity_id)
        sample = await load_sample(db, sample_id, current_user, "summary")
        entry = (await db.get(ENTITY_MODELS[attachment.entity_type], attachment.entity_id)
                 if attachment.entity_type != "sample" else None)
        if not (can_edit_entry(current_user, sample, entry) if entry else can_edit(current_user, sample)):
            raise HTTPException(status_code=403, detail="You don't have access to this sample.")
        back = f"/samples/{sample_id}"

    await delete_attachment(attachment, db)
    await db.commit()
    return RedirectResponse(back, status_code=303)
