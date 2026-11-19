"""Updating samples that are already in the logbook from an import file.

Import (sample_import.py) compares each sample of the file that is already
here, instead of creating it again: the one whose ID the file gives as
"code", else the one with the same label (top-level samples the importer can
edit; several with that label is an error, and "code" says which). The
sample page's "Update from a file" does the same for that one sample (the
file's only sample, the one with its code, or the one with its label), and
creates nothing else.

The page lists every difference with a tick box: what the file adds or
changes starts ticked, what it would take away (a value it leaves empty, a
parameter, a file, an entry it doesn't have) starts unticked. Only the ticked
changes are made; new samples in the file are created as usual.

Matching:
- entries, in order, by kind and type and date; then what's left by kind and
  type alone (so a changed date shows as a change, not a new entry). Planned
  entries, "Devices made" and entries awaiting approval aren't compared.
- pieces of a cut by label (unlabelled ones in order); pieces not in the file
  are left alone (an update never deletes samples, nor cuts).
- files by content: a file already on the entry under another name is the same file.

The ID, owner, year and type aren't changed by an update (Edit does that).
A "run" links the file's entries, new and already here, across all the
file's samples; an entry already in a run keeps it.

As at import, the file is checked (dry_run, rolled back by the caller), then
read again to make the changes ticked: change ids are stable in between.
"""
import hashlib
import inspect
import json
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import date
from typing import Awaitable, Callable

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.activity import log as log_activity
from backend.auth import can_edit, is_owner
from backend.choices import FILM_LIST, canonical, remember
from backend.lineage import CUT_TYPE_NAME, DEVICES_TYPE_NAME
from backend.models import Analysis, Attachment, ProcessStep, Sample, StudySample
from backend.sample_ids import piece_codes
from backend.sample_import import Bundle, Importer, Report, _english, _flat_fields
from backend.timeline import ordered_entries
from backend.utils import delete_attachment, delete_attachments_of

# Phases: things are created first (so later changes can point at them), entries deleted last
CREATE, CHANGE, LINK, DELETE = 1, 2, 3, 4


@dataclass
class Change:
    id: str                 # stable between the check and the update: the form sends back the ticked ones
    what: str
    old: str = ""
    new: str = ""
    kind: str = "change"    # add | change | remove
    apply: Callable[[], Awaitable[None]] | None = field(default=None, repr=False)
    phase: int = CHANGE

    @property
    def ticked(self) -> bool:
        """Ticked to start with: all but what would take something away."""
        return self.kind != "remove"


@dataclass
class EntryDiff:
    title: str
    date: date | None
    status: str                       # same | changed | new | gone | kept
    changes: list[Change] = field(default_factory=list)


@dataclass
class SampleDiff:
    sample: Sample
    fields: list[Change] = field(default_factory=list)
    entries: list[EntryDiff] = field(default_factory=list)
    pieces: list["SampleDiff"] = field(default_factory=list)
    new_pieces: list[Change] = field(default_factory=list)
    other_pieces: list[Sample] = field(default_factory=list)   # in the logbook, not in the file: left alone
    order: Change | None = None

    def changes(self) -> list[Change]:
        out = list(self.fields)
        for e in self.entries:
            out += e.changes
        out += self.new_pieces
        if self.order:
            out.append(self.order)
        for p in self.pieces:
            out += p.changes()
        return out


def _empty(value) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _kind(old, new) -> str:
    return "remove" if _empty(new) else "add" if _empty(old) else "change"


def _sha(content: bytes) -> str:
    return hashlib.sha256(content).hexdigest()


class Updater:
    """Plugged into Importer.run: takes the file's samples that are already
    here (all of them that are, or only `only`), compares them, and once the
    new ones are created makes the `ticked` changes."""

    def __init__(self, imp: Importer, only: Sample | None = None, ticked: set[str] | None = None):
        self.imp, self.only, self.ticked = imp, only, ticked or set()
        self.db, self.user, self.tr, self.report = imp.db, imp.user, imp.tr, imp.report
        self.finishers: list[Callable[[], Awaitable[None]]] = []
        self.depositions: list[tuple[EntryDiff, dict, ProcessStep, str]] = []
        self.in_runs: list[tuple[EntryDiff | None, dict, str]] = []
        self.rows: dict[tuple[str, int], object] = {}   # every existing entry seen, for naming the layer below

    def show(self, value) -> str:
        if _empty(value):
            return ""
        if isinstance(value, bool):
            return self.tr("yes") if value else self.tr("no")
        if isinstance(value, list):
            return ", ".join(str(v) for v in value)
        if isinstance(value, dict):
            return json.dumps(value, ensure_ascii=False)
        return str(value)

    # ── Which samples are already here ──────────────────────────────────────

    async def _target(self, p: dict) -> Sample | None:
        """The sample `p` updates: the one with its "code", else the one with its label (if one)."""
        if p["code"]:
            found = (await self.db.execute(select(Sample).where(Sample.code == p["code"]))).scalar_one_or_none()
            if found is None or found.cut_step_id:
                self.imp.check.error(p["where"], 'no sample {code} to update (give the ID of a sample, not of a piece)',
                                     code=p["code"])
            elif not can_edit(self.user, found):
                self.imp.check.error(p["where"], "you can't edit {code}, so it can't be updated", code=p["code"])
            else:
                return found
            return None
        label = (p["fields"]["label"] or "").strip().lower()
        if not label:
            return None
        same = [s for s in (await self.db.execute(select(Sample).where(
            Sample.cut_step_id.is_(None), func.lower(func.trim(Sample.label)) == label))).scalars()
            if can_edit(self.user, s)]
        if len(same) > 1:
            self.imp.check.error(p["where"], 'several samples are labelled {label} ({codes}): add "code" with the ID '
                                             "of the one to update", label=repr(p["fields"]["label"]),
                                 codes=", ".join(s.title for s in same))
            return None
        return same[0] if same else None

    def _pick(self, todo: list[dict]) -> dict | None:
        """The file's sample for `only`: the one with its code, the only one, or the one with its label."""
        mine = [p for p in todo if p["code"] == self.only.code]
        if not mine and len(todo) == 1 and not todo[0]["code"]:
            mine = todo
        if not mine:
            label = (self.only.label or "").strip().lower()
            mine = [p for p in todo if not p["code"] and label
                    and (p["fields"]["label"] or "").strip().lower() == label]
        if len(mine) != 1:
            self.report.errors.append(self.tr(
                "The file has {n} samples: it should have one, or one labelled {label}.",
                n=len(todo), label=repr(self.only.label or "")))
            return None
        return mine[0]

    async def take(self, todo: list[dict]) -> list[dict]:
        """Compare the samples already here; give back the ones to create."""
        if self.only is not None:
            p = self._pick(todo)
            pairs, rest = ([(self.only, p)] if p else []), []
        else:
            pairs, rest, seen = [], [], {}
            for p in todo:
                target = await self._target(p)
                if target is None:
                    rest.append(p)
                elif target.id in seen:
                    self.imp.check.error(p["where"], "{code} is in the file twice", code=target.title)
                else:
                    seen[target.id] = p
                    pairs.append((target, p))
        if self.report.errors:
            return rest
        self.step_names = {t.id: t.name for t in self.imp.look.step_types.values()}
        for sample, p in pairs:
            self.report.updates.append(await self._sample(sample, p, top=True))
        for p in rest:   # new samples' entries can be in a run with entries already here
            self._new_in_runs(p["timeline"])
        self._placements()
        self._runs()
        return rest

    def _new_in_runs(self, timeline: list[dict]):
        for e in timeline:
            if e["kind"] == "cut":
                for piece in e["pieces"]:
                    self._new_in_runs(piece["timeline"])
            else:
                self.in_runs.append((None, e, ""))

    @contextmanager
    def _like_parent(self):
        """Pieces cut here belong to the sample's owner, as from the Cut form (not to whoever the file names)."""
        self.imp.pieces_like_parent = True
        try:
            yield
        finally:
            self.imp.pieces_like_parent = False

    async def apply(self):
        """Make the ticked changes (after the new samples are created)."""
        for change in sorted(self.report.changes, key=lambda c: c.phase):
            if change.id in self.ticked and change.apply:
                await change.apply()
                await self.db.flush()
                self.report.changed += 1
        for finish in self.finishers:
            await finish()

    # ── A sample (or piece) ─────────────────────────────────────────────────

    def _field(self, out: list, cid: str, what: str, old, new, setter, show_old=None, show_new=None):
        if (None if _empty(old) else old) == (None if _empty(new) else new):
            return

        async def apply():
            await setter(new) if _is_async(setter) else setter(new)
        out.append(Change(cid, self.tr(what), show_old if show_old is not None else self.show(old),
                          show_new if show_new is not None else self.show(new), _kind(old, new), apply))

    async def _sample(self, sample: Sample, p: dict, top: bool) -> SampleDiff:
        diff = SampleDiff(sample)
        given, out, sid = p["given"], diff.fields, f"s{sample.id}"

        def put(attr):
            return lambda value: setattr(sample, attr, value)

        if top:
            fields = p["fields"]
            if p["sample_type"] != sample.sample_type and "sample_type" in given:
                self.imp.check.warn(sample.title, "the file says {type}; an update doesn't change the type (Edit does)",
                                    type=p["sample_type"])
            names = [("label", "Label"), ("description", "Description")]
            names += [("film_material", "Film material")] if sample.sample_type == "thin_film" else [("external_id", "External ID")]
            names += [("substrate_dimensions", "Substrate dimensions")]
            for key, what in names:
                if key in given:
                    if key == "film_material":
                        async def film(value):
                            sample.film_material = await canonical(self.db, FILM_LIST, value) if value else None
                            if value:
                                self.imp.picked.append((FILM_LIST, sample.film_material, None, set(), {}))
                        self._field(out, f"{sid}.{key}", what, getattr(sample, key), fields[key], film)
                    else:
                        self._field(out, f"{sid}.{key}", what, getattr(sample, key), fields[key], put(key))
            if "substrate" in given and p["substrate"] and sample.sample_type in ("thin_film", "bulk"):
                old = sample.substrate.name if sample.substrate else None
                if sample.substrate_id != p["substrate"].id:
                    self._field(out, f"{sid}.substrate", "Substrate", old, p["substrate"].name,
                                lambda _v, s=p["substrate"]: setattr(sample, "substrate_id", s.id))
            if "project" in given and p["project"] and sample.sample_type not in ("thin_film", "bulk"):
                if sample.project_id != p["project"].id:
                    self._field(out, f"{sid}.project", "Project", sample.project.name if sample.project else None,
                                p["project"].name, lambda _v, pr=p["project"]: setattr(sample, "project_id", pr.id))
            if "visibility" in given and p["visibility"] != sample.visibility:
                if is_owner(self.user, sample):
                    def visibility(value):
                        log_activity(self.db, self.user, "sample_visibility", sample.title, sample.owner_id,
                                     f"{sample.visibility} → {value}")
                        sample.visibility = value
                    self._field(out, f"{sid}.visibility", "Visibility", sample.visibility, p["visibility"], visibility)
                else:
                    self.imp.check.warn(sample.title, "only the owner can change the visibility")
            owner = p["owner"]
            if ("owner" in given or "team" in given) and (
                    (owner.user and owner.user.id != sample.owner_id) or (owner.team and owner.team.id != sample.owner_team_id)):
                self.imp.check.warn(sample.title, "the file names another owner; an update doesn't change it (Edit does)")
        else:
            for key, what in (("label", "Label"), ("description", "Description"),
                              ("substrate_dimensions", "Substrate dimensions")):
                if key in given:
                    self._field(out, f"{sid}.{key}", what, getattr(sample, key), p[key], put(key))
        if "tags" in given:
            self._field(out, f"{sid}.tags", "Tags", sample.tags, p["tags"], put("tags"))
        if "is_reference" in given:
            self._field(out, f"{sid}.is_reference", "Reference sample", bool(sample.is_reference),
                        p["is_reference"], put("is_reference"))
        if p["studies"]:
            have = set((await self.db.execute(select(StudySample.study_id).where(
                StudySample.sample_id == sample.id))).scalars())
            for study in p["studies"]:
                if study.id not in have:
                    async def add(s=study):
                        self.db.add(StudySample(study_id=s.id, sample_id=sample.id, added_by_id=self.user.id))
                    out.append(Change(f"{sid}.study{study.id}", self.tr("Study"), "", study.title, "add", add))
        out += await self._files(f"{sid}.files", "sample", sample.id, p["files"])
        await self._timeline(diff, sample, p["timeline"])
        return diff

    async def _files(self, cid: str, entity_type: str, entity_id: int, files: list[tuple[str, bytes]]) -> list[Change]:
        existing = (await self.db.execute(select(Attachment).where(
            Attachment.entity_type == entity_type, Attachment.entity_id == entity_id))).scalars().all()
        have = {a.sha256 for a in existing}
        wanted, out = set(), []
        for name, content in files:
            digest = _sha(content)
            if digest in have or digest in wanted:
                wanted.add(digest)
                continue
            wanted.add(digest)

            async def add(name=name, content=content):
                await self.imp._attach([(name, content)], entity_type, entity_id)
            out.append(Change(f"{cid}.{digest[:20]}", self.tr("File"), "", name, "add", add))
        for a in existing:
            if a.sha256 not in wanted:
                async def drop(a=a):
                    await delete_attachment(a, self.db)
                out.append(Change(f"{cid}.a{a.id}", self.tr("File"), a.original_filename, "", "remove", drop, DELETE))
        return out

    # ── Its timeline ────────────────────────────────────────────────────────

    def _key(self, row) -> tuple:
        if isinstance(row, Analysis):
            return ("analysis", row.analysis_type_id)
        if self.step_names.get(row.step_type_id) == CUT_TYPE_NAME:
            return ("cut", None)
        return ("step", row.step_type_id)

    @staticmethod
    def _file_key(e: dict) -> tuple:
        return ("cut", None) if e["kind"] == "cut" else (e["kind"], e["type"].id)

    def _title(self, row) -> str:
        if isinstance(row, Analysis):
            name = next((t.name for t in self.imp.look.analysis_types.values() if t.id == row.analysis_type_id), "?")
        else:
            name = self.step_names.get(row.step_type_id, "?")
        return self.tr(name)

    @staticmethod
    def _rid(row) -> str:
        return f"{'a' if isinstance(row, Analysis) else 'p'}{row.id}"

    async def _timeline(self, diff: SampleDiff, sample: Sample, entries: list[dict]):
        all_rows = await ordered_entries(self.db, sample.id)
        rows = [r for r in all_rows if not r.planned
                and not (isinstance(r, ProcessStep) and self.step_names.get(r.step_type_id) == DEVICES_TYPE_NAME)]
        for r in rows:
            self.rows[(type(r).__name__, r.id)] = r
        matched: list = [None] * len(entries)
        free = list(rows)
        for exact in (True, False):
            for i, e in enumerate(entries):
                if matched[i] is not None:
                    continue
                row = next((r for r in free if self._key(r) == self._file_key(e)
                            and (not exact or r.performed_at == e["date"])), None)
                if row is not None:
                    matched[i] = row
                    free.remove(row)
        sid = f"s{sample.id}"
        for i, (e, row) in enumerate(zip(entries, matched)):
            if row is None:
                diff.entries.append(self._new_entry(sample, e, sid, i))
                continue
            e["row"] = row
            cid = f"{sid}.{self._rid(row)}"
            entry = EntryDiff(self._title(row), row.performed_at, "same")
            if e["kind"] == "cut":
                await self._cut(diff, entry, sample, e, row, cid)
            else:
                await self._entry(entry, e, row, cid)
            entry.status = "changed" if entry.changes else "same"
            diff.entries.append(entry)
        for row in free:
            entry = EntryDiff(self._title(row), row.performed_at, "gone")
            if self._key(row)[0] == "cut":
                entry.status = "kept"   # its pieces inherit what's before it
            else:
                async def drop(row=row):
                    kind = "analysis_ids" if isinstance(row, Analysis) else "step_ids"
                    await delete_attachments_of(self.db, **{kind: [row.id]})
                    await self.db.delete(row)
                entry.changes.append(Change(f"{sid}.{self._rid(row)}.delete", self.tr("Not in the file: delete it"),
                                            kind="remove", apply=drop, phase=DELETE))
            diff.entries.append(entry)
        self._order(diff, sample, entries, matched, rows, all_rows)

    def _new_entry(self, sample: Sample, e: dict, sid: str, i: int) -> EntryDiff:
        title = self.tr("Cut") if e["kind"] == "cut" else self.tr(e["type"].name)
        bits = [self.show(e["date"])] if e["date"] else []
        if e["kind"] == "cut":
            bits.append(self.tr("{n} pieces", n=len(e["pieces"])))
        elif e["params"]:
            bits.append(", ".join(f"{k}: {self.show(v)}" for k, v in e["params"].items()))
        if e["files"]:
            bits.append(self.tr("{n} files", n=len(e["files"])))

        async def create():
            if e["kind"] == "cut":
                with self._like_parent():
                    await self.imp._cut_now(sample, e, None)
            else:
                await self.imp._entry_now(sample, e, None)
        entry = EntryDiff(title, e["date"], "new")
        entry.changes.append(Change(f"{sid}.new{i}", self.tr("Add this entry"), "", " · ".join(bits), "add",
                                    create, CREATE))
        self._new_in_runs([e])
        return entry

    def _common(self, out: list, e: dict, row, cid: str):
        self._field(out, f"{cid}.date", "Date", row.performed_at, e["date"],
                    lambda v: setattr(row, "performed_at", v))
        old_by = (row.performer_id, None if row.performer_id else row.performed_by)
        new_by = (e["performer"].id if e["performer"] else None, e["performed_by"])
        if old_by != new_by:
            def by(_v):
                row.performer_id, row.performed_by = new_by
            self._field(out, f"{cid}.by", "Performed by", row.performer_name,
                        e["performer"].display_name if e["performer"] else e["performed_by"], by)
        self._field(out, f"{cid}.location", "Where", row.location, e["location"],
                    lambda v: setattr(row, "location", v))
        self._field(out, f"{cid}.notes", "Notes", row.notes, e["notes"], lambda v: setattr(row, "notes", v))

    async def _entry(self, entry: EntryDiff, e: dict, row, cid: str):
        out = entry.changes
        self._common(out, e, row, cid)
        if (row.procedure_id or None) != (e["procedure"].id if e["procedure"] else None):
            self._field(out, f"{cid}.procedure", "Procedure followed", row.procedure.title if row.procedure else None,
                        e["procedure"].title if e["procedure"] else None,
                        lambda _v: setattr(row, "procedure_id", e["procedure"].id if e["procedure"] else None))
        old, new = row.parameters or {}, e["params"]
        labels = _flat_fields(e["schema"])
        for key in [*new, *(k for k in old if k not in new)]:
            def set_param(value, key=key):
                params = dict(row.parameters or {})
                if _empty(value):
                    params.pop(key, None)
                else:
                    params[key] = value
                row.parameters = params or None
                self.imp.remember_choices(e)
            f = labels.get(key, {})
            label = self.tr(f.get("label") or key) + (f" ({f['unit']})" if f.get("unit") else "")
            self._field(out, f"{cid}.param.{key}", label, old.get(key), new.get(key), set_param)
        out += await self._files(f"{cid}.files", e["kind"], row.id, e["files"])
        if isinstance(row, ProcessStep) and e["type"].name == "Deposition":
            self.depositions.append((entry, e, row, cid))
        self.in_runs.append((entry, e, cid))

    async def _cut(self, diff: SampleDiff, entry: EntryDiff, sample: Sample, e: dict, row: ProcessStep, cid: str):
        out = entry.changes
        self._common(out, e, row, cid)

        def method(value):
            params = dict(row.parameters or {})
            params.pop("method", None)
            row.parameters = params | ({"method": value} if value else {})
        self._field(out, f"{cid}.method", "Method", (row.parameters or {}).get("method"), e["method"], method)
        out += await self._files(f"{cid}.files", "step", row.id, e["files"])
        pieces = list((await self.db.execute(select(Sample).where(Sample.cut_step_id == row.id)
                                             .order_by(Sample.code))).scalars())
        free = list(pieces)
        matches: list = [None] * len(e["pieces"])
        label = lambda s: (s or "").strip().lower()   # noqa: E731
        for i, pp in enumerate(e["pieces"]):
            found = (next((s for s in free if s.is_reference), None) if pp["is_reference"] and not pp["label"]
                     else next((s for s in free if pp["label"] and label(s.label) == label(pp["label"])), None))
            if found:
                matches[i] = found
                free.remove(found)
        for i, pp in enumerate(e["pieces"]):   # unlabelled pieces in order
            if matches[i] is None and not pp["label"]:
                found = next((s for s in free if not s.label and s.is_reference == pp["is_reference"]), None)
                if found:
                    matches[i] = found
                    free.remove(found)
        for i, (pp, piece) in enumerate(zip(e["pieces"], matches)):
            if piece is None:
                async def create(pp=pp):
                    codes, ref = await piece_codes(self.db, sample, 0 if pp["is_reference"] else 1, pp["is_reference"])
                    with self._like_parent():
                        await self.imp.piece_now(sample, row, pp, ref if pp["is_reference"] else codes[0])
                    row.parameters = dict(row.parameters or {}) | {
                        "pieces": int((row.parameters or {}).get("pieces") or 0) + 1}
                what = self.tr("Reference piece") if pp["is_reference"] else self.tr("Piece")
                summary = " · ".join(filter(None, [pp["label"], self.tr("{n} entries", n=len(pp["timeline"]))
                                                   if pp["timeline"] else ""]))
                diff.new_pieces.append(Change(f"{cid}.piece{i}", what, "", summary, "add", create, CREATE))
                self._new_in_runs(pp["timeline"])
            elif can_edit(self.user, piece):
                diff.pieces.append(await self._sample(piece, pp, top=False))
            else:
                self.imp.check.warn(piece.title, "you can't edit this piece, so it isn't compared")
        diff.other_pieces += free

    def _order(self, diff: SampleDiff, sample: Sample, entries, matched, rows, all_rows):
        """New entries go where the file has them; the others can be put in the file's order."""
        in_file = [r for r in matched if r is not None]
        now = sorted(in_file, key=rows.index)
        follow = {"on": False}
        if in_file != now:
            async def reorder():
                follow["on"] = True
            diff.order = Change(f"s{sample.id}.order", self.tr("Order of the timeline"), self.tr("as it is"),
                                self.tr("as in the file"), "change", reorder)
        before = {(type(r).__name__, r.id) for r in all_rows}

        async def finish():
            current = await ordered_entries(self.db, sample.id)
            new = [r for r in current if (type(r).__name__, r.id) not in before]
            file_rows = [e["row"] for e in entries if e.get("row") is not None and e["row"] in current]
            if not new and not follow["on"]:
                return
            if follow["on"]:
                order, base = file_rows, [r for r in current if r not in new]
            else:
                order, base = [r for r in current if r not in new], file_rows
            # the rows of `base` missing from `order` go after the one they follow in `base`
            order, anchor = list(order), -1
            for r in base:
                if r in order:
                    anchor = order.index(r)
                else:
                    anchor += 1
                    order.insert(anchor, r)
            for r in current:   # anything else (not in either): at the end
                if r not in order:
                    order.append(r)
            for position, r in enumerate(order):
                r.position = position
        self.finishers.append(finish)

    # ── Layers and runs, once everything is matched ─────────────────────────

    def _layer(self, on_row, on_substrate: bool, partial: bool) -> str:
        if on_substrate:
            text = self.tr("on the substrate")
        elif on_row is not None:
            text = self.tr("on {entry}", entry=" ".join(filter(None, [self._title(on_row), self.show(on_row.performed_at)])))
        else:
            text = self.tr("on top")
        return text + (", " + self.tr("partial") if partial else "")

    def _placements(self):
        for entry, e, row, cid in self.depositions:
            target = e["on"]
            target_row = target.get("row") if target else None
            if target is not None and target_row is None:
                same = False   # on a new deposition
            else:
                same = ((row.on_step_id, bool(row.on_substrate), bool(row.partial)) ==
                        (target_row.id if target_row else None, e["on_substrate"], e["partial"]))
            if same:
                continue
            old_row = self.rows.get(("ProcessStep", row.on_step_id)) if row.on_step_id else None

            async def place(row=row, e=e):
                below = e["on"] and e["on"].get("row")
                row.on_step_id = below.id if below else None
                row.on_substrate, row.partial = e["on_substrate"], e["partial"]
            new_text = (self._layer(None, e["on_substrate"], e["partial"]) if target is None else
                        self._layer(target_row, False, e["partial"]) if target_row is not None else
                        self.tr("on {entry}", entry=self.tr("the new {type}", type=self.tr(target["type"].name)))
                        + (", " + self.tr("partial") if e["partial"] else ""))
            entry.changes.append(Change(f"{cid}.layer", self.tr("Layer"),
                                        self._layer(old_row, row.on_substrate, row.partial), new_text, "change",
                                        place, LINK))
            entry.status = "changed"

    def _runs(self):
        groups: dict[str, list] = {}
        for entry, e, cid in self.in_runs:
            if e.get("run"):
                groups.setdefault(e["run"], []).append((entry, e, cid))
        for members in groups.values():
            rows = [e["row"] for _, e, _ in members if e.get("row") is not None]
            run_id = next((r.run_id for r in rows if r.run_id), members[0][1]["run"])
            for entry, e, cid in members:
                e["run"] = run_id   # what new entries are created with
                row = e.get("row")
                if row is None or row.run_id or len(members) < 2:
                    continue

                async def link(row=row, run_id=run_id):
                    row.run_id = run_id
                entry.changes.append(Change(f"{cid}.run", self.tr("Done together"), "",
                                            self.tr("one run with 1 other entry in the file") if len(members) == 2 else
                                            self.tr("one run with {n} other entries in the file", n=len(members) - 1),
                                            "add", link, LINK))
                entry.status = "changed"


def _is_async(fn) -> bool:
    return inspect.iscoroutinefunction(fn)


async def run_import(db: AsyncSession, user, bundle: Bundle, dry_run: bool, tr=_english,
                     update: bool = True, ticked: set[str] | None = None) -> Report:
    """Import the file's samples; with `update`, those already here (by "code",
    else label) are compared instead (report.updates) and the `ticked`
    changes made. The caller commits, or rolls back after a check."""
    imp = Importer(db, user, bundle, dry_run, tr)
    return await imp.run(Updater(imp, ticked=ticked) if update else None)


async def run_update(db: AsyncSession, user, bundle: Bundle, sample: Sample, dry_run: bool, tr=_english,
                     ticked: set[str] | None = None) -> Report:
    """The same for one sample (its page's Update from a file): nothing else in the file is created."""
    imp = Importer(db, user, bundle, dry_run, tr)
    return await imp.run(Updater(imp, only=sample, ticked=ticked))
