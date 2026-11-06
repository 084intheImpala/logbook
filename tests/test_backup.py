"""backup/backup.py: which snapshots are kept, and how one is made (pg_dump faked)."""
import importlib.util
import os
import shutil
from datetime import date, timedelta

import pytest

spec = importlib.util.spec_from_file_location("backup_script", "backup/backup.py")
backup = importlib.util.module_from_spec(spec)
spec.loader.exec_module(backup)

FAKE_DUMP = ["sh", "-c", "echo database"]
needs_rsync = pytest.mark.skipif(shutil.which("rsync") is None, reason="rsync not installed")


def test_keeps_7_days_4_weeks_12_months():
    today = date(2026, 11, 6)
    days = [today - timedelta(days=n) for n in range(400)]   # a snapshot every day for 400 days
    kept = backup.keep(days, daily=7, weekly=4, monthly=12)
    assert {today - timedelta(days=n) for n in range(7)} <= kept
    # Newest of each period: the last 4 ISO weeks' Sundays (or today), the last 12 months' last days
    assert date(2026, 10, 25) in kept and date(2026, 10, 18) in kept and date(2026, 10, 11) not in kept
    assert date(2026, 9, 30) in kept and date(2025, 12, 31) in kept and date(2025, 11, 30) not in kept
    assert len(kept) <= 7 + 4 + 12


def test_gaps_dont_empty_a_tier():
    # The PC was off for months: the old snapshots still count as the latest weeks and months
    days = [date(2026, 1, 5), date(2026, 1, 12), date(2026, 2, 2), date(2026, 11, 6)]
    assert backup.keep(days, daily=1, weekly=4, monthly=12) == set(days)


@needs_rsync
def test_snapshot_shares_unchanged_files(tmp_path):
    uploads, root = tmp_path / "uploads", tmp_path / "backups"
    (uploads / "S-1").mkdir(parents=True)
    (uploads / "S-1" / "scan.raw").write_bytes(b"x" * 1000)
    (uploads / ".trash" / "2026-11-01").mkdir(parents=True)
    (uploads / ".trash" / "2026-11-01" / "old.raw").write_text("deleted")

    first = backup.make_snapshot(date(2026, 11, 5), root, uploads, FAKE_DUMP)
    (uploads / "S-1" / "new.raw").write_text("new")
    second = backup.make_snapshot(date(2026, 11, 6), root, uploads, FAKE_DUMP)

    assert (second / "logbook.dump").read_text() == "database\n"
    assert (second / "uploads" / "S-1" / "new.raw").exists()
    assert not (second / "uploads" / ".trash").exists()
    assert os.path.samefile(first / "uploads" / "S-1" / "scan.raw", second / "uploads" / "S-1" / "scan.raw")
    assert backup.shares_files(first, second)
    assert sorted(backup.snapshots(root)) == [date(2026, 11, 5), date(2026, 11, 6)]


@needs_rsync
def test_failed_dump_leaves_no_snapshot(tmp_path):
    uploads, root = tmp_path / "uploads", tmp_path / "backups"
    uploads.mkdir()
    with pytest.raises(Exception):
        backup.make_snapshot(date(2026, 11, 6), root, uploads, ["sh", "-c", "exit 1"])
    with pytest.raises(RuntimeError):
        backup.make_snapshot(date(2026, 11, 6), root, uploads, ["true"])   # empty dump
    assert backup.snapshots(root) == {}
    backup.prune(root)
    assert not list(root.iterdir())   # the .partial folder is cleaned up


def test_prune_deletes_what_isnt_kept(tmp_path):
    for n in range(10):
        (tmp_path / (date(2026, 11, 6) - timedelta(days=n)).isoformat()).mkdir()
    (tmp_path / "notes").mkdir()
    gone = backup.prune(tmp_path, daily=3, weekly=0, monthly=0)
    assert len(gone) == 7 and len(backup.snapshots(tmp_path)) == 3
    assert (tmp_path / "notes").exists()
