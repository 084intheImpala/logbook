import uuid
import mimetypes
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import Attachment, ProcessStep, Analysis, User
from backend.config import settings
from backend.auth import require_login, load_sample
from backend.lineage import can_view_entry

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(require_login)])

ENTITY_MODELS = {"step": ProcessStep, "analysis": Analysis}


async def _entity_sample_id(db: AsyncSession, entity_type: str, entity_id: int) -> int:
    """The sample a step/analysis belongs to; 404 if it doesn't exist."""
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


@router.post("/upload/{sample_id}")
async def upload_file_for_sample(
    sample_id: int,
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(require_login),
):
    """Upload a file and redirect back to the sample page."""
    if await _entity_sample_id(db, entity_type, entity_id) != sample_id:
        raise HTTPException(status_code=400, detail="Entry does not belong to this sample")
    await load_sample(db, sample_id, current_user, "edit")

    content = await file.read()
    size = len(content)
    if size > settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024:
        raise HTTPException(status_code=413, detail=f"File exceeds {settings.MAX_UPLOAD_SIZE_MB} MB limit")

    mime = file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream"
    ext = Path(file.filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOAD_DIR / stored_name
    dest.write_bytes(content)

    attachment = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        stored_filename=stored_name,
        original_filename=file.filename,
        file_size=size,
        mime_type=mime,
        uploaded_by=current_user.username,
    )
    db.add(attachment)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.get("/{attachment_id}")
async def download_file(attachment_id: int, db: AsyncSession = Depends(get_db),
                        current_user: User = Depends(require_login)):
    attachment = await _attachment(db, attachment_id)
    sample_id = await _entity_sample_id(db, attachment.entity_type, attachment.entity_id)
    sample = await load_sample(db, sample_id, current_user, "summary")
    entry = await db.get(ENTITY_MODELS[attachment.entity_type], attachment.entity_id)
    if not await can_view_entry(db, current_user, sample, entry):
        raise HTTPException(status_code=403, detail="You don't have access to this file.")

    path = settings.UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing from disk")

    return FileResponse(
        path=path,
        filename=attachment.original_filename,
        media_type=attachment.mime_type or "application/octet-stream",
    )


@router.post("/{attachment_id}/delete")
async def delete_file(attachment_id: int, db: AsyncSession = Depends(get_db),
                      current_user: User = Depends(require_login)):
    attachment = await _attachment(db, attachment_id)
    sample_id = await _entity_sample_id(db, attachment.entity_type, attachment.entity_id)
    await load_sample(db, sample_id, current_user, "edit")

    path = settings.UPLOAD_DIR / attachment.stored_filename
    if path.exists():
        path.unlink()

    await db.delete(attachment)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
