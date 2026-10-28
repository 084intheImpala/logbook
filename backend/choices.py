"""Shared dropdown lists for the step and analysis forms (see ChoiceOption).

A list is identified by name, e.g. "machine" or "location"; a schema field
of type "choice" or "modes" names the list it uses. Values typed on a form
that aren't in the list yet are added when the entry is saved.
"""
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.models import ChoiceOption

LOCATION_LIST = "location"   # "Where" on every step and analysis
DEFAULT_LOCATION = "CTN"


async def option_locations(db: AsyncSession) -> dict[str, dict[str, str]]:
    """list → {value: place} for values that belong to a place (equipment)."""
    places: dict[str, dict[str, str]] = {}
    for opt in (await db.execute(select(ChoiceOption).where(ChoiceOption.location.is_not(None)))).scalars():
        places.setdefault(opt.list, {})[opt.value] = opt.location
    return places


async def option_methods(db: AsyncSession) -> dict[str, dict[str, str]]:
    """list → {value: method} for equipment that only suits one method (e.g. AnnealSYS → RTA)."""
    methods: dict[str, dict[str, str]] = {}
    for opt in (await db.execute(select(ChoiceOption).where(ChoiceOption.applies_to.is_not(None)))).scalars():
        methods.setdefault(opt.list, {})[opt.value] = opt.applies_to
    return methods


async def option_lists(db: AsyncSession) -> dict[str, list[str]]:
    """Every list's values, alphabetically (case-insensitive)."""
    lists: dict[str, list[str]] = {}
    for opt in (await db.execute(select(ChoiceOption))).scalars():
        lists.setdefault(opt.list, []).append(opt.value)
    return {name: sorted(values, key=str.lower) for name, values in lists.items()}


async def remember(db: AsyncSession, picked: list[tuple[str, str]], user_id: int | None,
                   location: str | None = None, located: set[str] = frozenset(),
                   methods: dict[str, str] = {}):
    """Add values typed on a form to their lists, if they're new (same
    spelling ignoring case counts as existing). New values in `located`
    lists (equipment) are filed under `location`, the form's Where, and under
    the method chosen with them (`methods`: list → method), if any."""
    existing = {(o.list, o.value.lower()) for o in (await db.execute(select(ChoiceOption))).scalars()}
    for list_name, value in picked:
        value = str(value).strip()[:200]
        if value and (list_name, value.lower()) not in existing:
            db.add(ChoiceOption(list=list_name, value=value, created_by_id=user_id,
                                location=location if list_name in located else None,
                                applies_to=methods.get(list_name)))
            existing.add((list_name, value.lower()))
