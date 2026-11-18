"""Importing samples from JSON files (e.g. old samples, written up after the fact).

An import is one .json file, or a .zip with .json files and the photos/files
they name. A .json file holds one sample (an object), a list of them, or
{"samples": [...]}. The format is described in the README ("Importing
samples"); in short:

    {"label": "ZnO on Si, 2021 batch", "sample_type": "thin_film",
     "owner": "asousa",              # a username; or "team": "WBS" if nobody is known
     "year": 2021,                   # for the ID; else the year of its first dated entry, else this year
     "substrate": "Si (100) 2in",    # by name, from the Substrates library
     "film_material": "ZnO", "substrate_dimensions": "10x10 mm", "tags": ["old"],
     "description": "...", "visibility": "team", "files": ["photos/overview.jpg"],
     "studies": ["Annealing series"],  # added to these studies (by title; ones you co-own)
     "timeline": [
       {"kind": "step", "type": "Deposition", "performed_at": "2021-03-04", "performed_by": "asousa",
        "location": "CTN", "parameters": {"target": "ZnO", "thickness": 100}, "notes": "...",
        "files": ["dep.jpg"], "ref": "zno"},
       {"kind": "analysis", "type": "XRD / HRXRD", "performed_at": "2021-03-10"},
       {"kind": "cut", "performed_at": "2021-04-01", "method": "Diamond saw",
        "pieces": [{"label": "for RBS", "timeline": [...]}, {"is_reference": true}]}
     ]}

Samples get IDs as usual (<initials>-<year>-<n>): the owner's initials, the
project's code for a project sample, or the team's name for a team's sample.
Within one import they are numbered in date order. Someone else's samples are
created on their behalf and wait for them to confirm (as on the New sample
form); a team's belong to the team (its members have owner rights). A sample
or piece can be added to studies the importer co-owns, as from the study's
page (the importer can always see what they import, which adding needs).

Everything is checked first (run_import with dry_run=True, rolled back by the
caller): an import with any error changes nothing.
"""
import io
import json
import mimetypes
import posixpath
import uuid
import zipfile
from dataclasses import dataclass, field
from datetime import date

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from starlette.datastructures import Headers, UploadFile

from backend import timeline as tl
from backend.auth import can_view_shared
from backend.choices import FILM_LIST, LOCATION_LIST, canonical, remember
from backend.deposition_rate import DEPOSITION_TYPE_NAME
from backend.lineage import CUT_TYPE_NAME, SPECIAL_STEP_TYPES
from backend.models import (DEFAULT_VISIBILITY, SAMPLE_TYPES, VISIBILITY, Analysis, AnalysisType, Procedure,
                            ProcessStep, ProcessStepType, Project, Sample, StudySample, Substrate, Team, User)
from backend.params import (_coerce, located_lists, located_methods, normalize_duration, option_list,
                            with_equipment)
from backend.sample_ids import INITIALS_RE, PROJECT_CODE_RE, next_code, piece_codes
from backend.seed import PROCESS_STEP_TYPES
from backend.studies import owned_studies
from backend.utils import save_upload

MAX_BUNDLE = 2 * 1024 ** 3   # what a zip may unpack to

SAMPLE_KEYS = {"label", "sample_type", "owner", "team", "year", "substrate", "project", "substrate_dimensions",
               "film_material", "external_id", "description", "tags", "visibility", "is_reference", "files",
               "studies", "timeline"}
PIECE_KEYS = {"label", "owner", "team", "substrate_dimensions", "description", "tags", "is_reference", "files",
              "studies", "timeline"}
ENTRY_KEYS = {"kind", "type", "performed_at", "performed_by", "location", "parameters", "notes", "files",
              "procedure", "ref", "on", "partial", "run"}
CUT_KEYS = {"kind", "performed_at", "performed_by", "location", "method", "notes", "files", "pieces"}


class Problem(Exception):
    """Something wrong with the upload: an English message with {placeholders}, and their values."""

    def __init__(self, text: str, **values):
        super().__init__(text)
        self.text, self.values = text, values


def _english(text: str, **values) -> str:
    return text.format(**values) if values else text


@dataclass
class Bundle:
    documents: list[tuple[str, object]] = field(default_factory=list)   # (file name, parsed JSON)
    files: dict[str, bytes] = field(default_factory=dict)                 # path in the zip → content


@dataclass
class Report:
    samples: list[dict] = field(default_factory=list)   # what was (or would be) created, top-level samples
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)
    handed_over: dict[int, list[Sample]] = field(default_factory=dict)   # owner id → samples awaiting them

    @property
    def count(self) -> int:
        def n(s): return 1 + sum(n(p) for p in s["pieces"])
        return sum(n(s) for s in self.samples)


# ── Reading the upload ───────────────────────────────────────────────────────

def _parse_json(name: str, content: bytes):
    try:
        return json.loads(content.decode("utf-8-sig"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise Problem("{name}: not valid JSON ({error}).", name=name, error=exc)


def read_bundle(name: str, content: bytes) -> Bundle:
    """The .json documents and other files in an uploaded .json or .zip."""
    bundle = Bundle()
    if name.lower().endswith(".zip") or content[:4] == b"PK\x03\x04":
        try:
            archive = zipfile.ZipFile(io.BytesIO(content))
        except zipfile.BadZipFile:
            raise Problem("{name}: not a valid zip file.", name=name)
        members = [m for m in archive.infolist() if not m.is_dir()
                   and not m.filename.startswith("__MACOSX/") and not posixpath.basename(m.filename).startswith(".")]
        if sum(m.file_size for m in members) > MAX_BUNDLE:
            raise Problem("{name}: the zip unpacks to more than 2 GB; split it.", name=name)
        for m in members:
            path = posixpath.normpath(m.filename.replace("\\", "/")).lstrip("/")
            data = archive.read(m)
            if path.lower().endswith(".json"):
                bundle.documents.append((path, _parse_json(path, data)))
            else:
                bundle.files[path] = data
        if not bundle.documents:
            raise Problem("{name}: the zip has no .json file.", name=name)
    else:
        bundle.documents.append((name, _parse_json(name, content)))
    return bundle


def samples_in(document) -> list:
    if isinstance(document, dict) and "samples" in document and set(document) <= {"samples", "format"}:
        document = document["samples"]
    if isinstance(document, dict):
        return [document]
    if isinstance(document, list):
        return document
    raise Problem("expected a sample (an object), a list of samples, or {example}", example='{"samples": [...]}')


# ── Looking things up ────────────────────────────────────────────────────────

class Lookups:
    """Library entries, users, teams, types and procedures, loaded once."""

    async def load(self, db: AsyncSession, user: User):
        self.users = list((await db.execute(select(User))).scalars())
        self.teams = list((await db.execute(select(Team))).scalars())
        self.substrates = list((await db.execute(select(Substrate))).scalars())
        self.projects = list((await db.execute(select(Project))).scalars())
        self.step_types = {t.name.lower(): t for t in (await db.execute(select(ProcessStepType))).scalars()}
        self.analysis_types = {t.name.lower(): t for t in (await db.execute(select(AnalysisType))).scalars()}
        self.procedures = [p for p in (await db.execute(select(Procedure))).scalars() if can_view_shared(user, p)]
        self.studies = await owned_studies(db, user)   # samples can be added only to these, as on the study page
        return self

    def user(self, text: str) -> User | None:
        """By username, else by initials or full name if only one user has them."""
        text = text.strip()
        exact = [u for u in self.users if u.username.lower() == text.lower()]
        if exact:
            return exact[0]
        for attr in ("initials", "name"):
            found = [u for u in self.users if (getattr(u, attr) or "").lower() == text.lower()]
            if len(found) == 1:
                return found[0]
        return None

    def team(self, text: str) -> Team | None:
        return next((t for t in self.teams if t.name.lower() == text.strip().lower()), None)

    def substrate(self, text: str) -> Substrate | None:
        found = [s for s in self.substrates if s.name.lower() == text.strip().lower()]
        return found[0] if len(found) == 1 else None

    def project(self, text: str) -> Project | None:
        return next((p for p in self.projects
                     if text.strip().lower() in ((p.code or "").lower(), p.name.lower())), None)

    def study(self, title: str) -> list:
        return [s for s in self.studies if s.title.strip().lower() == title.strip().lower()]

    def procedure(self, text: str) -> list[Procedure]:
        return [p for p in self.procedures if p.title.lower() == text.strip().lower()]


def team_prefix(team: Team) -> str | None:
    """The team's name as an ID prefix (WBS-2026-001), if it can be one."""
    code = "".join(c for c in team.name.upper() if c.isalnum())
    return code if PROJECT_CODE_RE.fullmatch(code) else None


# ── Checking values ──────────────────────────────────────────────────────────

class Checker:
    """Collects problems, each prefixed with where it is. Messages are English
    with {placeholders}, put through `tr` (the page's language)."""

    def __init__(self, report: Report, tr=_english):
        self.report, self.tr = report, tr

    def error(self, where: str, text: str, **values):
        self.report.errors.append(f"{where}: {self.tr(text, **values)}")

    def warn(self, where: str, text: str, **values):
        self.report.warnings.append(f"{where}: {self.tr(text, **values)}")

    def keys(self, where: str, obj: dict, allowed: set[str]):
        for k in sorted(set(obj) - allowed):
            self.error(where, 'unknown field "{key}" (allowed: {allowed})', key=k, allowed=", ".join(sorted(allowed)))

    def text(self, where: str, obj: dict, key: str, max_len: int | None = None) -> str | None:
        value = obj.get(key)
        if value is None:
            return None
        if isinstance(value, (int, float)) and not isinstance(value, bool):
            value = str(value)
        if not isinstance(value, str):
            self.error(where, '"{key}" must be text', key=key)
            return None
        value = value.strip()
        if max_len and len(value) > max_len:
            self.error(where, '"{key}" is longer than {n} characters', key=key, n=max_len)
        return value or None

    def date(self, where: str, obj: dict) -> date | None:
        value = obj.get("performed_at")
        if value in (None, ""):
            return None
        try:
            return date.fromisoformat(str(value))
        except ValueError:
            self.error(where, '"performed_at" must be a date as YYYY-MM-DD, not {value} (leave it out if the '
                              "day isn't known, and say what is known in the notes)", value=repr(value))
            return None

    def files(self, where: str, obj: dict, bundle: Bundle, base: str) -> list[tuple[str, bytes]]:
        names = obj.get("files") or []
        if not isinstance(names, list) or not all(isinstance(n, str) for n in names):
            self.error(where, '"files" must be a list of file paths')
            return []
        found = []
        for name in names:
            path = posixpath.normpath(posixpath.join(base, name.replace("\\", "/"))).lstrip("/")
            content = bundle.files.get(path, bundle.files.get(posixpath.normpath(name.replace("\\", "/"))))
            if content is None:
                self.error(where, 'file "{name}" isn\'t in the zip', name=name)
            else:
                found.append((posixpath.basename(name), content))
        return found

    def params(self, where: str, params, schema: list[dict]) -> tuple[dict, list[tuple[str, str]]]:
        """The parameters as they'd be stored from the form, and the dropdown values to remember."""
        if params is None:
            return {}, []
        if not isinstance(params, dict):
            self.error(where, '"parameters" must be an object')
            return {}, []
        fields = _flat_fields(schema)
        out, picked = {}, []
        for key, value in params.items():
            if value is None or value == "":
                continue
            f = fields.get(key)
            if f is None:
                if isinstance(value, (dict, list)):
                    self.error(where, 'parameter "{key}" isn\'t on this type\'s form', key=key)
                else:
                    out[key] = value
                    self.warn(where, 'parameter "{key}" isn\'t on this type\'s form: kept as an extra parameter', key=key)
                continue
            kind = f.get("type", "text")
            if kind == "modes":
                if not isinstance(value, dict) or not all(isinstance(v, dict) for v in value.values()):
                    self.error(where, '"{key}" must be {shape}', key=key, shape="{mode: {sub-field: value}}")
                    continue
                modes = {}
                for mode, sub in value.items():
                    modes[mode], sub_picked = self.params(f"{where} › {key} › {mode}", sub, f.get("fields") or [])
                    picked += [(option_list(f), mode)] + sub_picked
                out[key] = modes
            elif kind == "check":
                if value is True:
                    out[key] = True
                elif value is not False:
                    self.error(where, '"{key}" must be true or false', key=key)
            elif kind == "number":
                coerced = _coerce(str(value).replace(",", ".")) if isinstance(value, str) else value
                if isinstance(coerced, bool) or not isinstance(coerced, (int, float)):
                    self.warn(where, '"{key}" should be a number; kept as typed: {value}', key=key, value=repr(value))
                    coerced = str(value)
                out[key] = coerced
            elif kind == "duration":
                text = str(value)
                out[key] = normalize_duration(text)
                if out[key] == text and ":" not in text:
                    self.warn(where, '"{key}" should be minutes or min:s; kept as typed: {value}', key=key, value=repr(value))
            elif isinstance(value, (dict, list, bool)):
                self.error(where, '"{key}" must be text', key=key)
            else:
                out[key] = str(value).strip()
                if kind == "choice":
                    picked.append((option_list(f), out[key]))
                elif kind == "variant" and out[key] not in {o["value"] for o in f.get("options", [])}:
                    self.warn(where, '"{key}" is usually one of {values}', key=key, values=", ".join(o["value"] for o in f.get("options", [])))
        return out, picked


def _flat_fields(schema: list[dict] | None) -> dict[str, dict]:
    """Fields by key, with variant options' and checks' fields (stored side by side)."""
    fields = {}
    for f in schema or []:
        fields[f["key"]] = f
        if f.get("type") == "variant":
            for o in f.get("options", []):
                fields |= _flat_fields(o.get("fields"))
        if f.get("type") == "check":
            fields |= _flat_fields(f.get("fields"))
    return fields


# ── The import ───────────────────────────────────────────────────────────────

@dataclass
class _Owner:
    user: User | None = None
    team: Team | None = None

    def name(self, tr) -> str:
        return self.user.display_name if self.user else tr("The {team} team", team=self.team.name)


class Importer:
    def __init__(self, db: AsyncSession, user: User, bundle: Bundle, dry_run: bool, tr=_english):
        self.db, self.user, self.bundle, self.dry_run, self.tr = db, user, bundle, dry_run, tr
        self.report = Report()
        self.check = Checker(self.report, tr)
        self.picked: list[tuple[str, str, str | None, set, dict]] = []   # for remember()
        self.my_teams = {m.team_id for m in user.memberships}
        self.runs: dict[str, tuple] = {}   # "run" name → (kind, type name, run id): entries done together

    async def run(self) -> Report:
        self.look = await Lookups().load(self.db, self.user)
        todo = []
        for name, document in self.bundle.documents:
            try:
                items = samples_in(document)
            except Problem as exc:
                self.check.error(name, exc.text, **exc.values)
                continue
            base = posixpath.dirname(name)   # files are named relative to the .json file
            for n, item in enumerate(items, 1):
                where = f"{name} › " + self.tr("sample {n}", n=n) + (
                    f" ({item.get('label')})" if isinstance(item, dict) and item.get("label") else "")
                if not isinstance(item, dict):
                    self.check.error(where, "a sample must be an object")
                    continue
                prepared = self._prepare(where, item, base)
                if prepared:
                    todo.append(prepared)
        if self.report.errors:
            return self.report
        # IDs in date order within each prefix and year (stable: file order otherwise)
        todo.sort(key=lambda p: (p["prefix"], p["year"], p["first_date"] or date.max))
        for prepared in todo:
            self.report.samples.append(await self._create(prepared))
        for list_name, value, location, located, methods in self.picked:
            await remember(self.db, [(list_name, value)], self.user.id, location, located, methods)
        return self.report

    # Checking a sample, before anything is created

    def _owner(self, where: str, item: dict, default: _Owner) -> _Owner | None:
        owner, team = self.check.text(where, item, "owner"), self.check.text(where, item, "team")
        if owner and team:
            self.check.error(where, 'give "owner" or "team", not both')
            return None
        if owner:
            u = self.look.user(owner)
            if u is None:
                self.check.error(where, 'no user "{name}" (use their username)', name=owner)
                return None
            return _Owner(user=u)
        if team:
            t = self.look.team(team)
            if t is None:
                self.check.error(where, 'no team "{name}"', name=team)
                return None
            if not self.user.is_admin and t.id not in self.my_teams:
                self.check.error(where, "only members of the {team} team (or an admin) can import its samples", team=t.name)
                return None
            return _Owner(team=t)
        return default

    def _prepare(self, where: str, item: dict, base: str) -> dict | None:
        c = self.check
        before = len(self.report.errors)
        c.keys(where, item, SAMPLE_KEYS)
        sample_type = item.get("sample_type", "thin_film")
        if sample_type not in SAMPLE_TYPES:
            c.error(where, '"sample_type" must be one of {values}', values=", ".join(SAMPLE_TYPES))
            sample_type = "thin_film"
        owner = self._owner(where, item, _Owner(user=self.user))
        fields = {k: c.text(where, item, k, n) for k, n in (
            ("label", 100), ("substrate_dimensions", 100), ("film_material", 100), ("external_id", 100),
            ("description", None))}
        substrate = project = None
        if sample_type in ("thin_film", "bulk"):
            name = c.text(where, item, "substrate")
            substrate = self.look.substrate(name) if name else None
            if substrate is None:
                if name:
                    c.error(where, "substrate {name} isn't in the Substrates library (add it there first)", name=repr(name))
                else:
                    c.error(where, '"substrate" is needed: a name from the Substrates library')
        else:
            name = c.text(where, item, "project")
            project = self.look.project(name) if name else None
            if project is None:
                if name:
                    c.error(where, "no project {name} (give its code or name; add it on the Partners tab)", name=repr(name))
                else:
                    c.error(where, 'a project sample needs "project": its code or name')
            if not fields["description"]:
                c.error(where, 'a project sample needs a "description"')
        visibility = item.get("visibility", DEFAULT_VISIBILITY)
        if visibility not in VISIBILITY:
            c.error(where, '"visibility" must be one of {values}', values=", ".join(VISIBILITY))
        year = item.get("year")
        if year is not None and not (isinstance(year, int) and 1950 <= year <= date.today().year):
            c.error(where, '"year" must be a year such as 2021')
            year = None
        tags = self._tags(where, item)
        studies = self._studies(where, item)
        files = c.files(where, item, self.bundle, base)
        if not isinstance(item.get("is_reference", False), bool):
            c.error(where, '"is_reference" must be true or false')
        timeline = self._timeline(where, item, base, refs={}, owner=owner)
        if len(self.report.errors) > before or owner is None:
            return None
        if project is not None:
            prefix = project.code
        elif owner.user is not None:
            prefix = owner.user.initials
            if not prefix or not INITIALS_RE.fullmatch(prefix):
                c.error(where, "{name} hasn't set their initials, so their samples can't get an ID", name=owner.user.display_name)
                return None
        else:
            prefix = team_prefix(owner.team)
            if not prefix:
                c.error(where, 'the team name "{team}" can\'t be used for sample IDs (it needs 2 to 6 letters or digits)',
                        team=owner.team.name)
                return None
        dates = [e["date"] for e in timeline if e["date"]]
        first = min(dates) if dates else None
        return {"where": where, "owner": owner, "prefix": prefix, "first_date": first,
                "year": year or (first.year if first else date.today().year),
                "sample_type": sample_type, "fields": fields, "substrate": substrate, "project": project,
                "visibility": visibility, "tags": tags, "studies": studies, "files": files,
                "is_reference": bool(item.get("is_reference")), "timeline": timeline}

    def _studies(self, where: str, item: dict) -> list:
        """The studies named by title in "studies" (ones the importer co-owns)."""
        titles = item.get("studies")
        if titles is None:
            return []
        if not isinstance(titles, list) or not all(isinstance(t, str) and t.strip() for t in titles):
            self.check.error(where, '"studies" must be a list of study titles')
            return []
        found = []
        for title in dict.fromkeys(t.strip() for t in titles):
            matches = self.look.study(title)
            if not matches:
                self.check.error(where, 'no study "{title}" that you co-own (samples can be added only to those)',
                                 title=title)
            elif len(matches) > 1:
                self.check.error(where, 'several of your studies are called "{title}"; rename one first', title=title)
            elif matches[0] not in found:
                found.append(matches[0])
        return found

    def _tags(self, where: str, item: dict) -> list[str] | None:
        tags = item.get("tags")
        if tags is None:
            return None
        if not isinstance(tags, list) or not all(isinstance(t, str) for t in tags):
            self.check.error(where, '"tags" must be a list of words')
            return None
        return list(dict.fromkeys(t.strip() for t in tags if t.strip())) or None

    def _timeline(self, where: str, item: dict, base: str, refs: dict, owner: _Owner | None) -> list[dict]:
        """Checked entries; `refs` maps "ref" names to the entries they name (shared down a family)."""
        entries = item.get("timeline") or []
        if not isinstance(entries, list):
            self.check.error(where, '"timeline" must be a list')
            return []
        out = []
        for n, entry in enumerate(entries, 1):
            here = f"{where} › " + self.tr("entry {n}", n=n)
            if not isinstance(entry, dict):
                self.check.error(here, "an entry must be an object")
                continue
            if entry.get("type"):
                here += f" ({entry['type']})"
            checked = (self._cut(here, entry, base, refs, owner) if entry.get("kind") == "cut"
                       else self._entry(here, entry, base, refs))
            if checked:
                out.append(checked)
        return out

    def _common(self, where: str, entry: dict, base: str) -> dict:
        c = self.check
        by = c.text(where, entry, "performed_by", 100)
        performer = self.look.user(by) if by else None
        location = c.text(where, entry, "location", 120)
        return {"date": c.date(where, entry), "performer": performer, "performed_by": None if performer else by,
                "location": location, "notes": c.text(where, entry, "notes"),
                "files": c.files(where, entry, self.bundle, base)}

    def _entry(self, where: str, entry: dict, base: str, refs: dict) -> dict | None:
        c = self.check
        c.keys(where, entry, ENTRY_KEYS)
        kind = entry.get("kind")
        if kind not in ("step", "analysis"):
            c.error(where, '"kind" must be "step", "analysis" or "cut"')
            return None
        name = c.text(where, entry, "type") or ""
        entry_type = (self.look.step_types if kind == "step" else self.look.analysis_types).get(name.lower())
        if entry_type is None:
            c.error(where, 'no process step type "{name}"' if kind == "step" else 'no analysis type "{name}"', name=name)
            return None
        if entry_type.name in SPECIAL_STEP_TYPES:
            if entry_type.name == CUT_TYPE_NAME:
                c.error(where, "a cut is written as {example}", example='{"kind": "cut", "pieces": [...]}')
            else:
                c.error(where, "\"{type}\" can't be imported; add the devices on the sample page", type=entry_type.name)
            return None
        schema = with_equipment(entry_type.parameter_schema or [], entry_type.name)
        params, picked = c.params(where, entry.get("parameters"), schema)
        checked = self._common(where, entry, base) | {
            "kind": kind, "type": entry_type, "params": params, "picked": picked, "schema": schema,
            "procedure": None, "on": None, "on_substrate": False, "partial": False}
        title = c.text(where, entry, "procedure")
        if title:
            found = self.look.procedure(title)
            if len(found) != 1:
                c.error(where, 'no procedure "{title}" that you can see' if not found
                        else 'more than one procedure is called "{title}"', title=title)
            else:
                checked["procedure"] = found[0]
        on, partial = entry.get("on"), entry.get("partial", False)
        if (on is not None or partial) and entry_type.name != DEPOSITION_TYPE_NAME:
            c.error(where, '"on" and "partial" are only for a Deposition')
        elif on == "substrate":
            checked["on_substrate"] = True
        elif on is not None:
            if on not in refs:
                c.error(where, '"on": no earlier Deposition with "ref": {ref} (or use "substrate")', ref=repr(on))
            elif refs[on]["type"].name != DEPOSITION_TYPE_NAME:
                c.error(where, '"on": {ref} isn\'t a Deposition', ref=repr(on))
            else:
                checked["on"] = refs[on]
        if not isinstance(partial, bool):
            c.error(where, '"partial" must be true or false')
        checked["partial"] = partial is True
        ref = entry.get("ref")
        if ref is not None:
            if not isinstance(ref, str) or not ref:
                c.error(where, '"ref" must be a name')
            elif ref in refs:
                c.error(where, '"ref" {ref} is used twice', ref=repr(ref))
            else:
                refs[ref] = checked
        run = entry.get("run")
        checked["run"] = None
        if run is not None:
            if not isinstance(run, str) or not run.strip():
                c.error(where, '"run" must be a name')
            else:
                kind_type = (kind, entry_type.name)
                first = self.runs.setdefault(run, (*kind_type, uuid.uuid4().hex))
                if first[:2] != kind_type:
                    c.error(where, '"run" {run} joins entries of different types', run=repr(run))
                checked["run"] = first[2]
        return checked

    def _cut(self, where: str, entry: dict, base: str, refs: dict, owner: _Owner | None) -> dict | None:
        c = self.check
        c.keys(where, entry, CUT_KEYS)
        pieces = entry.get("pieces")
        if not isinstance(pieces, list) or not pieces:
            c.error(where, 'a cut needs "pieces": a list with one object per piece')
            return None
        checked = self._common(where, entry, base) | {"kind": "cut", "method": c.text(where, entry, "method", 200),
                                                       "pieces": []}
        if sum(1 for p in pieces if isinstance(p, dict) and p.get("is_reference")) > 1:
            c.error(where, "a cut can keep at most one reference piece")
        for n, piece in enumerate(pieces, 1):
            here = f"{where} › " + self.tr("piece {n}", n=n) + (
                f" ({piece.get('label')})" if isinstance(piece, dict) and piece.get("label") else "")
            if not isinstance(piece, dict):
                c.error(here, "a piece must be an object")
                continue
            c.keys(here, piece, PIECE_KEYS)
            if not isinstance(piece.get("is_reference", False), bool):
                c.error(here, '"is_reference" must be true or false')
            piece_owner = self._owner(here, piece, owner or _Owner(user=self.user))
            checked["pieces"].append({
                "where": here, "owner": piece_owner, "label": c.text(here, piece, "label", 100),
                "substrate_dimensions": c.text(here, piece, "substrate_dimensions", 100),
                "description": c.text(here, piece, "description"), "tags": self._tags(here, piece),
                "studies": self._studies(here, piece),
                "is_reference": piece.get("is_reference") is True, "files": c.files(here, piece, self.bundle, base),
                # pieces can put layers on the parent's depositions before the cut, not on each other's
                "timeline": self._timeline(here, piece, base, dict(refs), piece_owner)})
        return checked

    # Creating, once everything has been checked

    async def _create(self, p: dict) -> dict:
        sample = Sample(sample_type=p["sample_type"], substrate_id=p["substrate"].id if p["substrate"] else None,
                        project_id=p["project"].id if p["project"] else None, visibility=p["visibility"],
                        tags=p["tags"], is_reference=p["is_reference"], **p["fields"])
        if sample.film_material:
            sample.film_material = await canonical(self.db, FILM_LIST, sample.film_material)
            self.picked.append((FILM_LIST, sample.film_material, None, set(), {}))
        if sample.sample_type != "thin_film":
            sample.film_material = None
        if sample.sample_type == "thin_film":
            sample.external_id = None
        self._set_owner(sample, p["owner"])
        sample.code = await next_code(self.db, p["prefix"], p["year"])
        self.db.add(sample)
        await self.db.flush()
        await self._attach(p["files"], "sample", sample.id)
        return await self._fill(sample, p, p["owner"])

    def _set_owner(self, sample: Sample, owner: _Owner):
        from backend.routers.samples import _hand_over   # the same hand-over as the New sample form
        if owner.team is not None:
            sample.owner_id, sample.owner_team_id = None, owner.team.id
            return
        if _hand_over(sample, owner.user.id, self.user.id, self.user.is_admin):
            self.report.handed_over.setdefault(owner.user.id, []).append(sample)

    async def _fill(self, sample: Sample, p: dict, owner: _Owner) -> dict:
        summary = {"code": sample.code, "label": sample.label, "owner": owner.name(self.tr),
                   "pending": sample.requested_by_id is not None, "entries": 0,
                   "files": len(p["files"]), "pieces": [], "id": sample.id,
                   "studies": [s.title for s in p["studies"]]}
        if not self.dry_run:
            # as from the study's page; the sample is new, so it isn't in any study yet
            self.db.add_all(StudySample(study_id=s.id, sample_id=sample.id, added_by_id=self.user.id)
                            for s in p["studies"])
        for position, e in enumerate(p["timeline"], 1):
            summary["entries"] += 1
            summary["files"] += len(e["files"])
            if e["kind"] == "cut":
                summary["pieces"] += await self._cut_now(sample, e, position)
                continue
            model = ProcessStep if e["kind"] == "step" else Analysis
            row = model(sample_id=sample.id, position=position, parameters=e["params"] or None, notes=e["notes"],
                        performer_id=e["performer"].id if e["performer"] else None, performed_by=e["performed_by"],
                        location=e["location"], performed_at=e["date"],
                        procedure_id=e["procedure"].id if e["procedure"] else None, run_id=e["run"])
            if e["kind"] == "step":
                row.step_type_id = e["type"].id
                row.on_substrate, row.partial = e["on_substrate"], e["partial"]
                row.on_step_id = e["on"]["row"].id if e["on"] else None
            else:
                row.analysis_type_id = e["type"].id
            self.db.add(row)
            await self.db.flush()
            e["row"] = row
            await self._attach(e["files"], e["kind"], row.id)
            schema = e["schema"]
            located = located_lists(schema)
            methods = located_methods(schema, e["params"])
            self.picked += [(lst, v, e["location"], located, methods) for lst, v in e["picked"]]
            if e["location"]:
                self.picked.append((LOCATION_LIST, e["location"], None, set(), {}))
        return summary

    async def _cut_now(self, parent: Sample, e: dict, position: int) -> list[dict]:
        cut_type = (await self.db.execute(
            select(ProcessStepType).where(ProcessStepType.name == CUT_TYPE_NAME))).scalar_one_or_none()
        if cut_type is None:   # renamed or deleted by an admin: recreate it, as the cut form does
            cut_type = ProcessStepType(**next(t for t in PROCESS_STEP_TYPES if t["name"] == CUT_TYPE_NAME))
            self.db.add(cut_type)
            await self.db.flush()
        params = {"pieces": len(e["pieces"])} | ({"method": e["method"]} if e["method"] else {})
        cut = ProcessStep(sample_id=parent.id, step_type_id=cut_type.id, position=position, parameters=params,
                          notes=e["notes"], performer_id=e["performer"].id if e["performer"] else None,
                          performed_by=e["performed_by"], location=e["location"], performed_at=e["date"])
        self.db.add(cut)
        await self.db.flush()
        await self._attach(e["files"], "step", cut.id)
        if e["method"]:
            self.picked.append(("cut_method", e["method"], None, set(), {}))
        if e["location"]:
            self.picked.append((LOCATION_LIST, e["location"], None, set(), {}))
        n_plain = sum(1 for p in e["pieces"] if not p["is_reference"])
        codes, ref_code = await piece_codes(self.db, parent, n_plain, any(p["is_reference"] for p in e["pieces"]))
        codes = iter(codes)
        out = []
        for p in e["pieces"]:
            piece = Sample(code=ref_code if p["is_reference"] else next(codes), label=p["label"],
                           sample_type=parent.sample_type, substrate_id=parent.substrate_id,
                           external_id=parent.external_id, project_id=parent.project_id,
                           film_material=parent.film_material,
                           substrate_dimensions=p["substrate_dimensions"] or parent.substrate_dimensions,
                           description=p["description"],
                           tags=p["tags"] if p["tags"] is not None else (list(parent.tags) if parent.tags else None),
                           cut_step_id=cut.id, is_reference=p["is_reference"], visibility=parent.visibility)
            self._set_owner(piece, p["owner"])
            self.db.add(piece)
            await self.db.flush()
            await self._attach(p["files"], "sample", piece.id)
            out.append(await self._fill(piece, p, p["owner"]))
        return out

    async def _attach(self, files: list[tuple[str, bytes]], entity_type: str, entity_id: int):
        if self.dry_run:
            return
        for name, content in files:
            mime = mimetypes.guess_type(name)[0] or "application/octet-stream"
            upload = UploadFile(io.BytesIO(content), filename=name, headers=Headers({"content-type": mime}))
            await save_upload(upload, entity_type, entity_id, self.db, uploaded_by=self.user.username)


async def run_import(db: AsyncSession, user: User, bundle: Bundle, dry_run: bool, tr=_english) -> Report:
    """Check (dry_run) or carry out the import. The caller commits, or rolls
    back after a dry run or when the report has errors. `tr` translates the
    messages (English by default)."""
    return await Importer(db, user, bundle, dry_run, tr).run()
