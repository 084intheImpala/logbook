"""Shared utilities."""
import uuid
import mimetypes
from pathlib import Path
from fastapi import UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend import images
from backend.models import Attachment
from backend.config import settings


def chosen_files(files: list) -> list[UploadFile]:
    """Browsers send an empty string for a file input left empty; keep real files only.
    (Parsed uploads are Starlette's UploadFile, the base class of FastAPI's.)"""
    return [f for f in files if isinstance(f, StarletteUploadFile) and f.filename]


async def save_upload(
    file: UploadFile | None,
    entity_type: str,
    entity_id: int,
    db: AsyncSession,
    uploaded_by: str | None = None,
    photo: bool = False,
) -> Attachment | None:
    """Save an uploaded file to disk and create an Attachment record.

    With `photo=True` the image may be downscaled/converted (see images.py);
    other files are stored exactly as uploaded. Images get a thumbnail.
    Returns the Attachment (not yet committed) or None if no file provided."""
    if not file or not file.filename:
        return None
    content = await file.read()
    if not content:
        return None
    filename = file.filename
    mime = file.content_type or mimetypes.guess_type(filename)[0] or "application/octet-stream"
    if photo:
        processed = await run_in_threadpool(images.process_photo, content, filename)
        if processed:
            content, filename, mime = processed

    stored_name = f"{uuid.uuid4().hex}{Path(filename).suffix}"
    (settings.UPLOAD_DIR / stored_name).write_bytes(content)
    attachment = Attachment(
        entity_type=entity_type,
        entity_id=entity_id,
        stored_filename=stored_name,
        original_filename=filename,
        file_size=len(content),
        mime_type=mime,
        uploaded_by=uploaded_by,
        thumbnail_filename=await _write_thumbnail(content, stored_name),
    )
    db.add(attachment)
    return attachment


async def _write_thumbnail(content: bytes, stored_name: str) -> str | None:
    thumb = await run_in_threadpool(images.make_thumbnail, content)
    if thumb is None:
        return None
    name = f"thumb_{Path(stored_name).stem}.jpg"
    (settings.UPLOAD_DIR / name).write_bytes(thumb)
    return name


async def ensure_thumbnail(attachment: Attachment) -> str | None:
    """Create a missing thumbnail (e.g. for files uploaded before thumbnails
    existed, or before Pillow was installed). Caller commits."""
    if attachment.thumbnail_filename is None:
        path = settings.UPLOAD_DIR / attachment.stored_filename
        if path.exists():
            attachment.thumbnail_filename = await _write_thumbnail(path.read_bytes(), attachment.stored_filename)
    return attachment.thumbnail_filename


def copy_attachment(attachment: Attachment, entity_type: str, entity_id: int, db: AsyncSession) -> Attachment:
    """Attach an already stored file to another entry too (e.g. every sample in
    a run). The file on disk is shared, not duplicated."""
    copy = Attachment(
        entity_type=entity_type, entity_id=entity_id,
        stored_filename=attachment.stored_filename, original_filename=attachment.original_filename,
        file_size=attachment.file_size, mime_type=attachment.mime_type,
        uploaded_by=attachment.uploaded_by, thumbnail_filename=attachment.thumbnail_filename,
    )
    db.add(copy)
    return copy


async def delete_attachment(attachment: Attachment, db: AsyncSession):
    """Remove an attachment's record from the session, and its files from disk
    unless another attachment shares them (see copy_attachment)."""
    shared = (await db.execute(select(func.count()).select_from(Attachment).where(
        Attachment.stored_filename == attachment.stored_filename, Attachment.id != attachment.id))).scalar()
    if not shared:
        for name in (attachment.stored_filename, attachment.thumbnail_filename):
            if name and (settings.UPLOAD_DIR / name).exists():
                (settings.UPLOAD_DIR / name).unlink()
    await db.delete(attachment)
