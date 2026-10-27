"""Generated sample IDs.

A new sample gets <INITIALS>-<YEAR>-<NNN>, e.g. ASS-2026-001: the
researcher's initials, the year it was created and that researcher's
counter for the year. Collaboration samples use their project's code
instead of initials (UMIN-2026-001), with the project's own counter. Pieces cut from it add a suffix: -A, -B, … at the
first level, -1, -2, … at the next, alternating, so ASS-2026-001-A-1 is a
piece of piece A. A reference piece gets -REF (then -REF2, …).

IDs don't change when the sample changes owner. Only an admin can change one,
and only on a sample that isn't itself a piece (see recode.py).
"""
import re
import string
from datetime import date
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import Sample

INITIALS_RE = re.compile(r"^[A-Z]{2,4}$")
PROJECT_CODE_RE = re.compile(r"^[A-Z0-9]{2,6}$")   # used like initials, for a project's samples


def normalize_initials(text: str) -> str:
    return text.strip().upper()


async def next_code(db: AsyncSession, initials: str, year: int | None = None) -> str:
    year = year or date.today().year
    prefix = f"{initials}-{year}-"
    codes = (await db.execute(select(Sample.code).where(Sample.code.like(f"{prefix}%")))).scalars()
    numbers = [int(m.group(1)) for c in codes if (m := re.fullmatch(re.escape(prefix) + r"(\d+)", c or ""))]
    return f"{prefix}{max(numbers, default=0) + 1:03d}"


def _suffixes(level: int):
    """Letters at odd depths (A, B, … Z, AA, AB, …), numbers at even depths."""
    if level % 2:
        n = 1
        while True:
            yield str(n)
            n += 1
    letters = string.ascii_uppercase
    for c in letters:
        yield c
    for a in letters:
        for b in letters:
            yield a + b


async def piece_codes(db: AsyncSession, parent: Sample, count: int, reference: bool) -> tuple[list[str], str | None]:
    """Codes for `count` new pieces of `parent` (plus a reference piece),
    continuing after any pieces it already has."""
    base = parent.code or f"S{parent.id}"
    depth = max(len(base.split("-")) - 3, 0)   # 0 for ASS-2026-001, 1 for …-A, 2 for …-A-1
    level = depth % 2                          # 0 → letters, 1 → numbers
    taken = set((await db.execute(select(Sample.code).where(Sample.code.like(f"{base}-%")))).scalars())
    codes = []
    for suffix in _suffixes(level):
        if len(codes) == count:
            break
        if f"{base}-{suffix}" not in taken:
            codes.append(f"{base}-{suffix}")
    ref = None
    if reference:
        ref, n = f"{base}-REF", 1
        while ref in taken:
            n += 1
            ref = f"{base}-REF{n}"
    return codes, ref
