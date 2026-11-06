"""Deleted files wait in the trash for a while before they're really gone.

A file nothing uses any more (its last attachment was deleted, or its entry
or sample was) is moved to uploads/.trash/<day deleted>/, keeping its path,
e.g. uploads/.trash/2026-11-06/ASS-2026-001/2026-10-22_XRD-HRXRD/scan.raw.
To get one back, move it to where it was and attach it again. Day folders
older than TRASH_DAYS are deleted when the app starts and once a day after.
"""
import asyncio
import logging
import os
import shutil
from datetime import date, timedelta
from pathlib import Path

from backend.config import settings

log = logging.getLogger("uvicorn.error")

TRASH = ".trash"   # inside UPLOAD_DIR


def trash_dir() -> Path:
    return settings.UPLOAD_DIR / TRASH


def move_to_trash(name: str, today: date | None = None) -> Path | None:
    """Move UPLOAD_DIR/name into today's trash folder; where it went, or None
    if there was no such file. A file of the same name already trashed today
    is kept: this one gets " (2)", " (3)", … added."""
    source = settings.UPLOAD_DIR / name
    if not source.is_file():
        return None
    target = trash_dir() / (today or date.today()).isoformat() / name
    target.parent.mkdir(parents=True, exist_ok=True)
    n = 1
    while target.exists():
        n += 1
        target = target.with_name(f"{Path(name).stem} ({n}){Path(name).suffix}")
    os.replace(source, target)
    return target


def empty_old(today: date | None = None) -> int:
    """Delete the trash's day folders older than TRASH_DAYS. Returns how many."""
    if not trash_dir().is_dir():
        return 0
    oldest = (today or date.today()) - timedelta(days=settings.TRASH_DAYS)
    removed = 0
    for folder in trash_dir().iterdir():
        try:
            day = date.fromisoformat(folder.name)
        except ValueError:
            continue   # not one of ours
        if folder.is_dir() and day < oldest:
            shutil.rmtree(folder, ignore_errors=True)
            removed += 1
    return removed


async def empty_daily() -> None:
    """Empty old trash now and then every day, for as long as the app runs."""
    while True:
        try:
            if n := await asyncio.to_thread(empty_old):
                log.info("Emptied %d day(s) of trash older than %d days", n, settings.TRASH_DAYS)
        except Exception:
            log.exception("Could not empty the trash")
        await asyncio.sleep(24 * 60 * 60)
