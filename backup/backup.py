"""Automatic backups of the database and uploads/, kept daily, weekly and monthly.

Runs in its own container (see docker-compose.yml, service "backup"); only
the Python standard library, pg_dump and rsync. Once a day it makes a
snapshot in BACKUP_DIR (inside the container: /backups):

    /backups/2026-11-06/logbook.dump   pg_dump -Fc of the whole database
    /backups/2026-11-06/uploads/       the uploads folder, minus .trash

The uploads copy is made with rsync --link-dest: files unchanged since the
previous snapshot are hard links to it, so each snapshot looks complete but
only new or changed files take space. (That needs a file system with hard
links: ext4, NTFS, APFS; not FAT32 or exFAT. Each run checks, and logs a
warning if every snapshot is a full copy.)

A snapshot is built in <day>.partial and renamed when complete, so a crash or
a failed dump never leaves something that looks like a backup. Then old
snapshots are pruned: kept are the newest one of each of the last KEEP_DAILY
days, KEEP_WEEKLY weeks and KEEP_MONTHLY months that have one (see keep()).

    python3 backup.py          # run forever: a snapshot a day, checked hourly
    python3 backup.py --now    # one snapshot now (replaces today's), prune, exit
"""
import argparse
import logging
import os
import shutil
import subprocess
import sys
import time
from datetime import date
from pathlib import Path

log = logging.getLogger("backup")

BACKUP_DIR = Path(os.environ.get("BACKUP_DIR", "/backups"))
UPLOADS = Path(os.environ.get("UPLOADS", "/uploads"))
KEEP_DAILY = int(os.environ.get("KEEP_DAILY", 7))
KEEP_WEEKLY = int(os.environ.get("KEEP_WEEKLY", 4))
KEEP_MONTHLY = int(os.environ.get("KEEP_MONTHLY", 12))
# pg_dump reads PGHOST, PGPORT, PGUSER, PGPASSWORD and PGDATABASE from the environment
DUMP = ["pg_dump", "-Fc", "--no-owner"]
CHECK_EVERY = 60 * 60   # seconds


def snapshots(root: Path = BACKUP_DIR) -> dict[date, Path]:
    """The complete snapshots in `root`, by day."""
    found = {}
    if root.is_dir():
        for path in root.iterdir():
            try:
                found[date.fromisoformat(path.name)] = path
            except ValueError:
                pass   # <day>.partial, notes, …
    return found


def keep(days, daily=KEEP_DAILY, weekly=KEEP_WEEKLY, monthly=KEEP_MONTHLY) -> set[date]:
    """Which of `days` to keep: the newest of each of the last `daily` days,
    `weekly` ISO weeks and `monthly` months that have a snapshot. Periods
    without one (the PC was off) don't count, so a gap never empties a tier."""
    kept = set()
    for count, period in ((daily, lambda d: d), (weekly, lambda d: d.isocalendar()[:2]),
                          (monthly, lambda d: (d.year, d.month))):
        seen = []
        for day in sorted(days, reverse=True):
            if period(day) in seen:
                continue
            if len(seen) == count:
                break
            seen.append(period(day))
            kept.add(day)
    return kept


def prune(root: Path = BACKUP_DIR, **counts) -> list[date]:
    """Delete the snapshots keep() doesn't keep, and leftover .partial
    folders. Returns the days deleted."""
    found = snapshots(root)
    gone = sorted(set(found) - keep(found, **counts))
    for day in gone:
        shutil.rmtree(found[day])
    for path in root.glob("*.partial"):
        shutil.rmtree(path, ignore_errors=True)
    return gone


def make_snapshot(today: date | None = None, root: Path = BACKUP_DIR, uploads: Path = UPLOADS,
                  dump=DUMP) -> Path:
    """Dump the database and copy uploads/ into root/<today>. Raises if
    either fails; then nothing replaces the last good snapshot."""
    today = today or date.today()
    root.mkdir(parents=True, exist_ok=True)
    work = root / f"{today.isoformat()}.partial"
    shutil.rmtree(work, ignore_errors=True)
    work.mkdir()

    with open(work / "logbook.dump", "wb") as out:
        subprocess.run(dump, stdout=out, check=True)
    if (work / "logbook.dump").stat().st_size == 0:
        raise RuntimeError("pg_dump wrote nothing")

    previous = [p for d, p in sorted(snapshots(root).items()) if d != today]
    link = ["--link-dest", str((previous[-1] / "uploads").resolve())] if previous else []
    subprocess.run(["rsync", "-a", "--delete", "--exclude", "/.trash/", *link,
                    f"{uploads}/", str(work / "uploads")], check=True)

    final = root / today.isoformat()
    if final.exists():   # --now twice in a day: the newer one wins
        shutil.rmtree(final)
    work.rename(final)
    if previous and not shares_files(previous[-1], final):
        log.warning("Snapshots don't share unchanged files: hard links seem not to work in %s, so every "
                    "snapshot is a full copy. Use a disk formatted ext4 or NTFS (not FAT32/exFAT).", root)
    return final


def shares_files(old: Path, new: Path) -> bool:
    """Whether some file in both snapshots is the same file on disk (a hard
    link). True if there's nothing in common to compare."""
    compared = 0
    for path in (old / "uploads").rglob("*"):
        twin = new / "uploads" / path.relative_to(old / "uploads")
        if path.is_file() and twin.is_file() and path.stat().st_size == twin.stat().st_size:
            if os.path.samefile(path, twin):
                return True
            compared += 1
            if compared >= 20:
                break
    return compared == 0


def size_mb(path: Path) -> float:
    """Disk use, counting each hard-linked file once."""
    seen, total = set(), 0
    for p in path.rglob("*"):
        if p.is_file():
            st = p.stat()
            if (st.st_dev, st.st_ino) not in seen:
                seen.add((st.st_dev, st.st_ino))
                total += st.st_size
    return total / 1e6


def run_once(today: date | None = None) -> None:
    started = time.monotonic()
    path = make_snapshot(today)
    gone = prune()
    log.info("Snapshot %s done in %.0f s; removed %s; %d snapshot(s), %.0f MB in all",
             path.name, time.monotonic() - started, ", ".join(map(str, gone)) or "none",
             len(snapshots()), size_mb(BACKUP_DIR))


def forever() -> None:
    """A snapshot a day: checked every hour, so a PC that was off at night
    still gets its backup soon after it's switched on."""
    while True:
        if date.today() not in snapshots():
            try:
                run_once()
            except Exception:
                log.exception("Backup failed; trying again in an hour")
        time.sleep(CHECK_EVERY)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, stream=sys.stdout, format="%(asctime)s %(levelname)s %(message)s",
                        datefmt="%Y-%m-%d %H:%M")
    parser = argparse.ArgumentParser(description="Daily snapshots of the logbook database and uploads.")
    parser.add_argument("--now", action="store_true", help="make one snapshot now, prune, and exit")
    if parser.parse_args().now:
        run_once()
    else:
        log.info("Backups to %s: daily %d, weekly %d, monthly %d", BACKUP_DIR, KEEP_DAILY, KEEP_WEEKLY, KEEP_MONTHLY)
        forever()
