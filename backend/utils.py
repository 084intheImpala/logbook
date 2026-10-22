"""Shared utilities."""
import re
import mimetypes
import unicodedata
from datetime import date
from pathlib import Path
from fastapi import UploadFile
from starlette.datastructures import UploadFile as StarletteUploadFile
from starlette.concurrency import run_in_threadpool
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import AsyncSession
from backend import images
from backend.models import Attachment, Analysis, AnalysisType, ProcessStep, ProcessStepType, Sample, Substrate
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
    Files keep their original names, in one folder per sample and one
    subfolder per entry (see upload_folder), e.g.
    ASS-2026-001/2026-10-22_XRD-HRXRD/scan 01.raw.
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

    folder = await upload_folder(db, entity_type, entity_id, date.today())
    stored_name = write_new_file(folder, clean_filename(filename), content)
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


def _safe(text: str) -> str:
    """Letters, digits, '.', '_' and '-' only, for the folder names we make up."""
    text = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode()   # ção → cao
    return re.sub(r"[^A-Za-z0-9._-]+", "-", text).strip("-._") or "file"


async def upload_folder(db: AsyncSession, entity_type: str, entity_id: int, fallback_day: date) -> str:
    """The folder (relative to UPLOAD_DIR) for a file of this sample, step,
    analysis or substrate: the sample's ID, plus <date>_<technique> for a step
    or analysis (the entry's date, or `fallback_day` if it has none), e.g.
    ASS-2026-001/2026-10-22_XRD-HRXRD. Substrates: substrates/<name>."""
    if entity_type == "substrate":
        name = (await db.execute(select(Substrate.name).where(Substrate.id == entity_id))).scalar_one_or_none()
        return f"substrates/{_safe(name or str(entity_id))}"
    if entity_type == "sample":
        sample_id, entry_folder = entity_id, None
    else:
        model, type_model, type_fk = ((ProcessStep, ProcessStepType, ProcessStep.step_type_id) if entity_type == "step"
                                      else (Analysis, AnalysisType, Analysis.analysis_type_id))
        row = (await db.execute(select(model.sample_id, type_model.name, model.performed_at)
                                .join(type_model, type_model.id == type_fk).where(model.id == entity_id))).first()
        if row is None:
            return "unsorted"
        sample_id, type_name, day = row
        entry_folder = f"{(day or fallback_day).isoformat()}_{_safe(type_name)[:40]}"
    code = (await db.execute(select(Sample.code).where(Sample.id == sample_id))).scalar_one_or_none()
    folder = _safe(code or f"sample-{sample_id}")
    return f"{folder}/{entry_folder}" if entry_folder else folder


WINDOWS_RESERVED = {"CON", "PRN", "AUX", "NUL", *(f"COM{i}" for i in range(1, 10)), *(f"LPT{i}" for i in range(1, 10))}


def clean_filename(filename: str) -> str:
    """The uploaded file's own name, unchanged except for what a file system
    can't hold: any folders in it, characters Windows forbids (<>:"|?*),
    control characters, trailing dots/spaces and reserved names like CON."""
    name = filename.replace("\\", "/").rsplit("/", 1)[-1]
    name = re.sub(r'[<>:"|?*\x00-\x1f]', "_", name).rstrip(". ")
    if not name.strip("."):
        return "file"
    if name.split(".")[0].upper() in WINDOWS_RESERVED:
        name = f"_{name}"
    return name


MAX_STORED_NAME = 240   # Attachment.stored_filename is 255, and thumbnails add "thumbs/" and ".jpg"


def write_new_file(folder: str, name: str, content: bytes) -> str:
    """Write `content` to UPLOAD_DIR/folder/name, adding " (2)", " (3)", … to
    the name if it's taken. Returns the path relative to UPLOAD_DIR."""
    directory = settings.UPLOAD_DIR / folder
    directory.mkdir(parents=True, exist_ok=True)
    stem, suffix = Path(name).stem, Path(name).suffix
    n = 1
    while True:
        tag = "" if n == 1 else f" ({n})"
        room = MAX_STORED_NAME - len(folder) - 1 - len(suffix) - len(tag)   # very long names only
        candidate = f"{stem[:room]}{tag}{suffix}"
        try:
            with open(directory / candidate, "xb") as f:   # "x": fails if it exists, so two uploads can't collide
                f.write(content)
            return f"{folder}/{candidate}"
        except FileExistsError:
            n += 1


def thumbnail_name(stored_name: str) -> str:
    """Thumbnails sit in a thumbs/ folder next to the file: …/thumbs/<file name>.jpg"""
    path = Path(stored_name)
    return (path.parent / "thumbs" / f"{path.name}.jpg").as_posix()


async def _write_thumbnail(content: bytes, stored_name: str) -> str | None:
    thumb = await run_in_threadpool(images.make_thumbnail, content)
    if thumb is None:
        return None
    name = thumbnail_name(stored_name)
    (settings.UPLOAD_DIR / name).parent.mkdir(parents=True, exist_ok=True)
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
