"""Procedures: who may see and change them, and which ones an entry's form offers.

A procedure's co-owners (and admins) may change it; others see it according
to its visibility, as for a study (auth.is_co_owner / auth.can_view_shared).
A step or analysis can record the procedure it followed: the form offers the
procedures the user can see, for the chosen type or for none (general ones).
"""
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.auth import can_view_shared, is_co_owner
from backend.models import AnalysisType, Procedure, ProcessStepType, User

FILES = "procedure"   # Attachment.entity_type of a procedure's files


async def load_procedure(db: AsyncSession, procedure_id: int, user: User, need: str = "view") -> Procedure:
    """The procedure, 404 if missing, 403 if `user` can't view it (need="view") or own it ("owner")."""
    procedure = await db.get(Procedure, procedure_id)
    if procedure is None:
        raise HTTPException(status_code=404, detail="Procedure not found")
    allowed = is_co_owner(user, procedure) if need == "owner" else can_view_shared(user, procedure)
    if not allowed:
        raise HTTPException(status_code=403, detail="You don't have access to this procedure.")
    return procedure


async def visible_procedures(db: AsyncSession, user: User) -> list[Procedure]:
    """Procedures `user` can see, by technique then title."""
    rows = (await db.execute(select(Procedure))).scalars()
    return sorted((p for p in rows if can_view_shared(user, p)),
                  key=lambda p: ((p.technique or "~").lower(), p.title.lower()))


async def techniques(db: AsyncSession) -> dict[str, list[tuple[str, str]]]:
    """The types a procedure can be for, as form values: {"steps": [(key, name)], "analyses": [...]}."""
    steps = (await db.execute(select(ProcessStepType).order_by(ProcessStepType.name))).scalars()
    analyses = (await db.execute(select(AnalysisType).order_by(AnalysisType.name))).scalars()
    return {"steps": [(f"step:{t.id}", t.name) for t in steps],
            "analyses": [(f"analysis:{t.id}", t.name) for t in analyses]}


async def apply_technique(db: AsyncSession, procedure: Procedure, key: str):
    """Set the type the procedure is for from a form value ("step:<id>", "analysis:<id>" or "")."""
    procedure.step_type_id = procedure.analysis_type_id = None
    kind, _, raw = key.partition(":")
    if not raw.isdigit():
        return
    if kind == "step" and await db.get(ProcessStepType, int(raw)):
        procedure.step_type_id = int(raw)
    elif kind == "analysis" and await db.get(AnalysisType, int(raw)):
        procedure.analysis_type_id = int(raw)


async def for_entry_form(db: AsyncSession, user: User, kind_name: str, current_id: int | None) -> list[dict]:
    """What the "Procedure followed" field offers on a step ("step") or
    analysis ("analysis") form: the procedures `user` can see for a type of
    that kind, or general ones, plus the entry's current one. `type_id`
    (None for general ones) lets the page show only the chosen type's."""
    offered = []
    for p in await visible_procedures(db, user):
        type_id = p.step_type_id if kind_name == "step" else p.analysis_type_id
        general = not p.step_type_id and not p.analysis_type_id
        if type_id or general or p.id == current_id:
            offered.append({"id": p.id, "title": p.title, "type_id": type_id, "owners": p.owners})
    if current_id and all(o["id"] != current_id for o in offered):
        current = await db.get(Procedure, current_id)   # recorded by someone else, not visible to this user
        if current is not None:
            offered.append({"id": current.id, "title": current.title, "type_id": None, "owners": current.owners})
    return offered


async def chosen_for_entry(db: AsyncSession, user: User, value: str, current_id: int | None) -> int | None:
    """The procedure id picked on an entry's form: one `user` can see, or the
    one the entry already had; anything else is dropped."""
    if not value.isdigit():
        return None
    procedure_id = int(value)
    if procedure_id == current_id:
        return procedure_id
    procedure = await db.get(Procedure, procedure_id)
    return procedure_id if procedure is not None and can_view_shared(user, procedure) else None
