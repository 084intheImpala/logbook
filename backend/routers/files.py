import uuid
import mimetypes
from pathlib import Path
from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from fastapi.responses import FileResponse, RedirectResponse
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select

from backend.database import get_db
from backend.models import Attachment
from backend.config import settings
from backend.auth import require_login

router = APIRouter(prefix="/files", tags=["files"], dependencies=[Depends(require_login)])

ALLOWED_MIME_TYPES = {
    # Data files
    "text/plain", "text/csv", "application/json",
    # Documents
    "application/pdf",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.ms-excel",
    # Images
    "image/png", "image/jpeg", "image/gif", "image/tiff", "image/bmp", "image/svg+xml",
    # Common data formats
    "application/zip", "application/x-zip-compressed",
}


@router.post("/upload")
async def upload_file(
    entity_type: str = Form(...),   # 'sample' | 'step' | 'analysis'
    entity_id: int = Form(...),
    uploaded_by: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    if entity_type not in ("sample", "step", "analysis"):
        raise HTTPException(status_code=400, detail="Invalid entity_type")

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
        uploaded_by=uploaded_by or None,
    )
    db.add(attachment)
    await db.commit()

    # Redirect back to the sample page — entity_id is sample_id when entity_type='sample',
    # otherwise we need the sample_id passed separately. Use Referer header as fallback.
    sample_id = entity_id  # caller should pass sample_id when entity_type != 'sample'
    # Workaround: we always redirect to the sample page; the form passes sample_id explicitly
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.post("/upload/{sample_id}")
async def upload_file_for_sample(
    sample_id: int,
    entity_type: str = Form(...),
    entity_id: int = Form(...),
    uploaded_by: str = Form(""),
    file: UploadFile = File(...),
    db: AsyncSession = Depends(get_db),
):
    """Upload a file and redirect back to the sample page."""
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
        uploaded_by=uploaded_by or None,
    )
    db.add(attachment)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)


@router.get("/{attachment_id}")
async def download_file(attachment_id: int, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="File not found")

    path = settings.UPLOAD_DIR / attachment.stored_filename
    if not path.exists():
        raise HTTPException(status_code=404, detail="File missing from disk")

    return FileResponse(
        path=path,
        filename=attachment.original_filename,
        media_type=attachment.mime_type or "application/octet-stream",
    )


@router.post("/{attachment_id}/delete")
async def delete_file(attachment_id: int, sample_id: int = Form(...),
                      db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Attachment).where(Attachment.id == attachment_id))
    attachment = result.scalar_one_or_none()
    if not attachment:
        raise HTTPException(status_code=404, detail="File not found")

    path = settings.UPLOAD_DIR / attachment.stored_filename
    if path.exists():
        path.unlink()

    await db.delete(attachment)
    await db.commit()
    return RedirectResponse(f"/samples/{sample_id}", status_code=303)
