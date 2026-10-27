"""Changing a sample's ID (admins only), for when it was created under the
wrong owner or type, e.g. ASS-2026-005 that turns out to be a collaboration
sample and becomes UMIN-2026-001.

A sample's ID names its folder in uploads/ and is the start of its pieces' IDs
(ASS-2026-005-A), so changing it renames those pieces and moves their folders
too, and repoints the stored file names of every attachment that lives in them
(a file shared by a run of samples is stored once, in the first one's folder).
The old ID stays on the sample (previous_codes) and is never reused.
"""
import logging
import os
import re
from dataclasses import dataclass

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.config import settings
from backend.models import Attachment, Sample
from backend.sample_ids import retired_codes
from backend.utils import _safe

log = logging.getLogger("uvicorn.error")

CODE_RE = re.compile(r"^[A-Z0-9]{2,6}-\d{4}-\d{3,}$")   # <initials or project code>-<year>-<number>


class RecodeError(Exception):
    """Why an ID can't be changed; the message is for the admin (English, see the router)."""


@dataclass
class Plan:
    codes: dict[str, str]      # old → new, for the sample and each of its pieces
    folders: dict[str, str]    # old → new folder name in uploads/


async def plan(db: AsyncSession, sample: Sample, new_code: str) -> Plan:
    old = sample.code
    if not old:
        raise RecodeError("This sample has no ID to change.")
    if sample.cut_step_id:
        raise RecodeError("This sample is a piece; change the ID of the sample it was cut from instead.")
    if not CODE_RE.fullmatch(new_code):
        raise RecodeError("An ID looks like ABC-2026-001: 2–6 capital letters or digits, the year and a number.")
    if new_code == old:
        raise RecodeError("That is already this sample's ID.")

    pieces = [c for c in (await db.execute(select(Sample.code).where(Sample.code.like(f"{old}-%")))).scalars()
              if c.startswith(old + "-")]
    codes = {old: new_code, **{c: new_code + c[len(old):] for c in pieces}}

    taken = set((await db.execute(select(Sample.code).where(Sample.code.in_(codes.values())))).scalars())
    taken |= set(codes.values()) & await retired_codes(db)
    if taken:
        raise RecodeError(f"{', '.join(sorted(taken))} {'is' if len(taken) == 1 else 'are'} already in use "
                          "or was used by a sample before, and IDs are never reused.")

    folders = {_safe(o): _safe(n) for o, n in codes.items()}
    for new in folders.values():
        path = settings.UPLOAD_DIR / new
        if path.exists() and any(path.iterdir()):
            raise RecodeError(f"The folder uploads/{new} already exists and isn't empty.")
    return Plan(codes, folders)


async def apply(db: AsyncSession, plan: Plan) -> None:
    """Rename the samples and their folders. The caller commits; if anything
    fails here the folders are put back and the caller should roll back."""
    samples = (await db.execute(select(Sample).where(Sample.code.in_(plan.codes)))).scalars().all()
    for s in samples:
        s.previous_codes = [*(s.previous_codes or []), s.code]   # a new list, so the change is noticed
        s.code = plan.codes[s.code]

    for old, new in plan.folders.items():
        attachments = (await db.execute(select(Attachment).where(or_(
            Attachment.stored_filename.like(f"{old}/%"), Attachment.thumbnail_filename.like(f"{old}/%"))))).scalars()
        for a in attachments:
            if a.stored_filename.startswith(old + "/"):
                a.stored_filename = new + a.stored_filename[len(old):]
            if a.thumbnail_filename and a.thumbnail_filename.startswith(old + "/"):
                a.thumbnail_filename = new + a.thumbnail_filename[len(old):]
    await db.flush()
    move_folders(plan.folders)


def move_folders(folders: dict[str, str]) -> None:
    """Rename each folder that exists; undo them all if one fails."""
    done = []
    try:
        for old, new in folders.items():
            src, dst = settings.UPLOAD_DIR / old, settings.UPLOAD_DIR / new
            if not src.exists():
                continue
            if dst.exists():   # empty (checked in plan); os.rename needs it gone on Windows
                dst.rmdir()
            os.rename(src, dst)
            done.append((src, dst))
    except OSError:
        for src, dst in reversed(done):
            os.rename(dst, src)
        raise


def undo_move(folders: dict[str, str]) -> None:
    """Put folders back after the database commit failed."""
    for old, new in folders.items():
        src, dst = settings.UPLOAD_DIR / old, settings.UPLOAD_DIR / new
        if dst.exists() and not src.exists():
            os.rename(dst, src)
