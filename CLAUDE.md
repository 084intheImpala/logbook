# Logbook: notes for Claude

## Always

- **Update the documentation with every change.** README.md (English, the reference), the Portuguese user
  manual `docs/manual/manual-pt.tex` (rebuild `manual-pt.pdf` with `latexmk -pdf` in `docs/manual`; both are
  tracked) and, where the feature is a headline one, `docs/slides/slides-pt.tex`. Schema or `sample.json`
  changes also go in the README's data model / `sample.json` table (bump `FORMAT` in `backend/sample_backup.py`).
- Every user-visible string is translated: English in the code/templates, Portuguese in `backend/translations/`.
  In templates, don't put `"` inside a `_("...")` string.
- Schema changes are Alembic migrations in `backend/migrations/versions` (next number, `0010`, …).
- Add tests in `tests/` for new behaviour. They run on a throwaway SQLite DB; never touch the real DB or `uploads/`.
  This machine isn't the DB host: say what needs running there (e.g. migrations).
- Commit directly (no feature branches); currently on `restructure`. Only commit when asked.
- `todo` is a personal, git-ignored file: edit it, don't commit it.

## Running things

No system Python packages: make a venv (e.g. in the scratchpad), `pip install -r requirements.txt -r requirements-dev.txt`,
then `python -m pytest -q`. The app runs in Docker (see README); migrations run on startup.

## What it is

A lab logbook (FastAPI + async SQLAlchemy + Jinja2/Tailwind/HTMX, Postgres) for thin-film samples, in Portuguese
and English. Pages are server-rendered from `frontend/templates`; routes in `backend/routers`.

## Features so far

- **Samples** (`models.Sample`): generated ID `<initials>-<year>-<n>` (`sample_ids.py`; admins can recode, old IDs
  stay reserved, `recode.py`), types thin film / bulk / commercial / collaboration, tags, substrate library,
  collaboration projects, reference samples.
- **Timeline**: process steps and analyses share one ordered list (`timeline.py`, `position`, optional date).
  Entries have typed parameters (`params.py`, schemas in `seed_data.py`, admin-editable), shared dropdown lists
  (`choices.py`), performer, location, photos/files. One entry can be added to several samples (a "run").
- **Cut into pieces** (`lineage.py`, `samples.py`): a `Cut` step creates piece samples (`-A`, `-B`, `-REF`) that
  inherit the parent's timeline up to the cut; entries are never copied.
- **Devices** (`routers/devices.py`, `models.Device`): "Process done: make devices" adds a `Devices made` step and
  devices D1, D2… (numbered on from the highest). Later steps apply to all devices; an analysis can name a device.
  `Cut` and `Devices made` are special step types (`lineage.SPECIAL_STEP_TYPES`) with their own forms.
- **Access**: visibility personal/team/public, shares (view/edit), teams with coordinators who have owner rights
  over members' samples (`auth.py`, `routers/team*.py`), proposed entries awaiting owner approval, access requests,
  hand-over of a sample to another owner with confirmation (`approvals.py`).
- **Activity log** of management actions for admins/coordinators (`activity.py`).
- **Search and CSV export** (`routers/search.py`, `export.py`), suggestions inbox, e-mail notifications.
- **Backup**: each sample's `sample.json` is rewritten next to its files in `uploads/` (`sample_backup.py`).
