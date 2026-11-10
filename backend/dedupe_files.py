"""Find and merge files stored more than once, and tidy up after old deletes.

    python -m backend.dedupe_files            # only says what it would do
    python -m backend.dedupe_files --apply    # does it

(In Docker: `docker compose exec app python -m backend.dedupe_files`.)

1. Gives every attachment the hash of its file (attachments stored before
   migration 0015 don't have one), so new uploads can be matched against them.
2. Files with the same content stored more than once: every attachment is
   pointed at the oldest copy, as if it had been shared from the start (see
   utils.copy_attachment), and the other copies go to the trash.
3. The same file attached twice to the same entry: the extra attachment goes.
4. Attachments of entries or samples deleted before deleting them took their
   files along: they go, and so do their files unless something else uses them.

Nothing is deleted outright: files go to uploads/.trash (see trash.py) and
stay there TRASH_DAYS days. Files missing from disk are listed, not touched.
"""
import argparse
import asyncio
from dataclasses import dataclass, field
from typing import NamedTuple

from sqlalchemy import select

from backend.config import settings
from backend.database import AsyncSessionLocal
from backend.models import Analysis, Attachment, ProcessStep, Sample, StudyNote, Substrate
from backend.sample_backup import write_all
from backend.trash import move_to_trash
from backend.utils import file_sha256

OWNERS = {"sample": Sample, "step": ProcessStep, "analysis": Analysis, "substrate": Substrate, "study_note": StudyNote}


class Found(NamedTuple):
    """An attachment, as plain values (the report outlives the session)."""
    id: int
    entity_type: str
    entity_id: int
    original_filename: str
    stored_filename: str

    @classmethod
    def of(cls, a: Attachment) -> "Found":
        return cls(a.id, a.entity_type, a.entity_id, a.original_filename, a.stored_filename)


@dataclass
class Report:
    hashed: int = 0
    merged: dict[str, list[str]] = field(default_factory=dict)   # kept file → copies dropped
    repeated: list[Found] = field(default_factory=list)   # same file twice on one entry
    orphans: list[Found] = field(default_factory=list)    # their entry or sample is gone
    missing: list[Found] = field(default_factory=list)
    trashed: list[str] = field(default_factory=list)
    freed: int = 0   # bytes


async def dedupe(apply: bool) -> Report:
    report = Report()
    async with AsyncSessionLocal() as db:
        attachments = list((await db.execute(select(Attachment).order_by(Attachment.id))).scalars())
        existing = {kind: set((await db.execute(select(model.id))).scalars()) for kind, model in OWNERS.items()}
        orphans = [a for a in attachments if a.entity_id not in existing.get(a.entity_type, set())]
        report.orphans = [Found.of(a) for a in orphans]
        gone = {a.id for a in orphans}

        digests: dict[str, str | None] = {}
        for a in attachments:
            if a.stored_filename not in digests:
                path = settings.UPLOAD_DIR / a.stored_filename
                digests[a.stored_filename] = await asyncio.to_thread(file_sha256, path) if path.is_file() else None
            digest = digests[a.stored_filename]
            if digest is None:
                if a.id not in gone:
                    report.missing.append(Found.of(a))
            elif a.sha256 != digest:
                a.sha256 = digest
                report.hashed += 1

        before = {a.id: (a.stored_filename, a.thumbnail_filename) for a in attachments}
        first: dict[str, Attachment] = {}   # content → its oldest attachment
        seen: set[tuple[str, int, str]] = set()
        repeated = []
        for a in attachments:
            if a.id in gone or digests[a.stored_filename] is None:
                continue
            keep = first.setdefault(a.sha256, a)
            if a.stored_filename != keep.stored_filename:
                dropped = report.merged.setdefault(keep.stored_filename, [])
                if a.stored_filename not in dropped:
                    dropped.append(a.stored_filename)
                a.stored_filename = keep.stored_filename
                a.thumbnail_filename = keep.thumbnail_filename or a.thumbnail_filename
                if keep.thumbnail_filename is None and a.thumbnail_filename:
                    keep.thumbnail_filename = a.thumbnail_filename
            if (a.entity_type, a.entity_id, a.sha256) in seen:
                repeated.append(a)
                report.repeated.append(Found.of(a))
            seen.add((a.entity_type, a.entity_id, a.sha256))

        removed = gone | {a.id for a in repeated}
        used = {name for a in attachments if a.id not in removed
                for name in (a.stored_filename, a.thumbnail_filename) if name}
        unused = {name for names in before.values() for name in names if name} - used
        unused = sorted(name for name in unused if (settings.UPLOAD_DIR / name).is_file())
        report.trashed = unused
        report.freed = sum((settings.UPLOAD_DIR / name).stat().st_size for name in unused)

        if not apply:
            await db.rollback()
            return report
        for a in orphans + repeated:
            await db.delete(a)
        await db.commit()
    for name in unused:   # only once the database no longer points at them
        move_to_trash(name)
    await write_all()
    return report


def _print(report: Report, done: bool) -> None:
    print(f"{'Hashed' if done else 'Would hash'} {report.hashed} attachment(s).")
    for kept, copies in sorted(report.merged.items()):
        print(f"Same content as {kept}:")
        for copy in copies:
            print(f"    {copy}")
    if report.merged:
        print(f"{'Merged' if done else 'Would merge'} {sum(map(len, report.merged.values()))} duplicate file(s) "
              f"into {len(report.merged)}.")
    for a in report.repeated:
        print(f"Attached twice to the same {a.entity_type} ({a.entity_id}): {a.original_filename}")
    for a in report.orphans:
        print(f"Left over from a deleted {a.entity_type} ({a.entity_id}): {a.original_filename}")
    if report.trashed:
        print(f"{'Moved' if done else 'Would move'} {len(report.trashed)} file(s) to uploads/.trash, "
              f"{report.freed / 1e6:.1f} MB, kept there {settings.TRASH_DAYS} days.")
    for a in report.missing:
        print(f"Missing from disk (left as is): {a.stored_filename}")
    if not done:
        print("Nothing was changed. Run again with --apply to do it.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Merge files stored more than once (see the module docstring).")
    parser.add_argument("--apply", action="store_true", help="make the changes (without it, only report them)")
    args = parser.parse_args()
    _print(asyncio.run(dedupe(args.apply)), args.apply)
