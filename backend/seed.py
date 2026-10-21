"""Seed the database with the default step types, analysis types and dropdown
values from seed_data.py. Types are only added when missing (by name) and
dropdown lists only when empty, so admins' changes survive restarts.
"""
from sqlalchemy import select, func

from backend.models import ProcessStepType, AnalysisType, ChoiceOption
from backend.seed_data import PROCESS_STEP_TYPES, ANALYSIS_TYPES, CHOICE_OPTIONS  # noqa: F401 (re-exported)


async def seed_types(session):
    for model, types in ((ProcessStepType, PROCESS_STEP_TYPES), (AnalysisType, ANALYSIS_TYPES)):
        for data in types:
            result = await session.execute(select(model).where(model.name == data["name"]))
            if not result.scalar_one_or_none():
                session.add(model(**data))

    for list_name, values in CHOICE_OPTIONS.items():
        count = (await session.execute(
            select(func.count()).select_from(ChoiceOption).where(ChoiceOption.list == list_name))).scalar()
        if not count:
            session.add_all(ChoiceOption(list=list_name, value=v, location=None) if isinstance(v, str)
                            else ChoiceOption(list=list_name, value=v[0], location=v[1]) for v in values)

    await session.commit()
