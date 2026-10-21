"""Shared utilities."""
import uuid
import mimetypes
from pathlib import Path
from fastapi import UploadFile
from sqlalchemy.ext.asyncio import AsyncSession
from backend.models import Attachment
from backend.config import settings


async def save_upload(
    file: UploadFile | None,
    entity_type: str,
    entity_id: int,
    db: AsyncSession,
    uploaded_by: str | None = None,
) -> Attachment | None:
    """Save an uploaded file to disk and create an Attachment record.
    Returns the Attachment (not yet committed) or None if no file provided."""
    if not file or not file.filename:
        return None
    content = await file.read()
    if not content:
        return None
    ext = Path(file.filename).suffix
    stored_name = f"{uuid.uuid4().hex}{ext}"
    dest = settings.UPLOAD_DIR / stored_name
    dest.write_bytes(content)
    attachment = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        stored_filename=stored_name,
        original_filename=file.filename,
        file_size=len(content),
        mime_type=file.content_type or mimetypes.guess_type(file.filename)[0] or "application/octet-stream",
        uploaded_by=uploaded_by,
    )
    db.add(attachment)
    return attachment


async def delete_attachment(attachment: Attachment, db: AsyncSession):
    """Remove an attachment's file from disk and its record from the session."""
    path = settings.UPLOAD_DIR / attachment.stored_filename
    if path.exists():
        path.unlink()
    await db.delete(attachment)
