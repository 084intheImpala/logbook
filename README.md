# Thin Film Logbook

A web-based sample logbook for tracking thin film deposition and processing.

## Stack

- **Backend**: FastAPI + SQLAlchemy (async) + PostgreSQL
- **Frontend**: Jinja2 templates + Tailwind CSS + HTMX
- **Files**: Stored locally in `uploads/`, metadata in the DB

---

## Quick start (Docker — recommended)

```bash
# 1. Clone / copy this folder onto the host machine
# 2. Create .env and fill in SECRET_KEY, BASE_URL and SMTP_PASSWORD
cp .env.example .env
# 3. Start everything
docker compose up -d
# 4. Create the first admin user
docker compose exec app python -m backend.create_admin

# The app is now at http://localhost:8000
# On the LAN: http://<host-ip>:8000
```

That's it. Tables and seed data are created automatically on first run.

> **Note:** `docker-compose.yml` is set up for **Docker running inside WSL2 with
> mirrored networking** (see below). On any other setup, make the changes in
> [Running on other environments](#running-on-other-environments) first.

---

## Docker networking

### WSL2 (default configuration)

The `app` service uses `network_mode: host`, and its `DATABASE_URL` points at
`localhost:5432`. With WSL2 mirrored networking, Docker's normal port
publishing (`ports: "8000:8000"`) can't be reached from Windows, so uvicorn
binds directly on the WSL host network instead.

You also need these settings in `C:\Users\<you>\.wslconfig`:

```ini
[wsl2]
networkingMode=mirrored

[experimental]
hostAddressLoopback=true
```

`hostAddressLoopback` lets the Windows machine itself open the app through its
own LAN IP (e.g. `http://10.10.13.172:8000`), not just `localhost`. After
editing the file, run `wsl --shutdown` in PowerShell and start the containers
again.

### Running on other environments

On plain Linux, Docker Desktop (Windows/macOS) or WSL2 with the default NAT
networking, use regular port publishing. In `docker-compose.yml`, change the
`app` service:

```diff
     environment:
-      # Host networking: reach Postgres through its published port on localhost
-      DATABASE_URL: postgresql+asyncpg://logbook:logbook@localhost:5432/logbook
+      DATABASE_URL: postgresql+asyncpg://logbook:logbook@db:5432/logbook
     ...
-    # Docker's port publishing isn't reachable from Windows under WSL mirrored
-    # networking, so bind uvicorn directly on the WSL host network instead.
-    network_mode: host
+    ports:
+      - "8000:8000"
```

- `DATABASE_URL` must use `db` (the Postgres service name), because the app
  is no longer on the host network.
- The `ports:` line in the `db` service (`5432:5432`) is then optional. It's
  only needed if you want to reach Postgres from outside Docker (e.g. for
  `pg_dump` from the host).
- Set `BASE_URL` in `.env` to the address users will open, so emailed login
  links point to the right place.

---

## Windows 10 (WSL2 in NAT mode)

Windows 10 has no mirrored networking, so other PCs can't reach the app
directly. `scripts/start-logbook.ps1` fixes that: it starts WSL, Docker and the
containers, keeps WSL alive, and forwards port 8000 to WSL's current IP
(which changes at every restart). To run it automatically at every login, open
an **administrator** PowerShell in the project folder, once:

```powershell
powershell -ExecutionPolicy Bypass -File .\scripts\install-autostart.ps1
```

This registers the "Logbook autostart" task, adds the firewall rule for TCP
8000 and starts the logbook. Progress is logged to `scripts/start-logbook.log`.
The task runs when the user logs in, so after a reboot someone must log in
(or the PC must be set to sign in automatically).

---

## Quick start (without Docker)

```bash
# Prerequisites: Python 3.12+, PostgreSQL running locally

# 1. Install dependencies
pip install -r requirements.txt

# 2. Create the database
createdb logbook
psql logbook -c "CREATE USER logbook WITH PASSWORD 'logbook';"
psql logbook -c "GRANT ALL PRIVILEGES ON DATABASE logbook TO logbook;"

# 3. Copy env and edit if needed
cp .env.example .env

# 4. Run
uvicorn backend.main:app --host 0.0.0.0 --port 8000 --reload
```

---

## Data model

```
Substrate         (shared library: material, orientation, thickness, polishing, spec files)
Project           (collaboration or commercial supplier: name, institution or company, code used in its samples' IDs, contact)
Sample            (generated ID, type, optional label and tags)
 ├── ProcessStep  (can repeat types, e.g. two annealings; planned or done)
 │    └── Attachment (uploaded files)
 ├── Device       (D1, D2, …; made by a "Devices made" step)
 └── Analysis     (XRD, RBS, SEM, …; optionally on one Device; planned or done)
      └── Attachment (data files, images)
Study             (several samples; co-owners; personal / team / public)
 ├── StudySample     (a sample in it; a sample can be in several studies)
 ├── StudyReference  (a paper by DOI, or a link, with a note)
 └── StudyNote       (dated, ordered note; may point at a sample, step or analysis)
      └── Attachment (photos, files)
```

### Sample IDs

Every sample gets an ID when it's created: the researcher's initials, the
year, and that researcher's counter for the year, e.g. `ASS-2026-001`. Pieces
cut from it add `-A`, `-B`, … (pieces of pieces `-1`, `-2`, …), and a
reference piece adds `-REF`. IDs don't change when the sample changes
owner or the researcher's initials change later. Only an admin can change one,
for a sample created under the wrong type (see below). The optional
**Label** is for your own description and doesn't need to be unique.

**Changing an ID (admins).** There is no ID field on the Edit page. When an
edit changes the type or project (see below), the sample page offers an admin
the next free number under the owner's initials or the project's code. Its pieces are renamed with it (`ASS-2026-005-A`
becomes `UMIN-2026-001-A`), the folders in `uploads/` are renamed and the
stored file names updated, and the owner gets an email listing the old and new
IDs. The old ID is kept on the sample (shown as *Previously*, searchable, and
in the exports) and is never given to another sample, so an old ID can't end up
meaning two things. A piece's ID can't be changed on its own; change the
sample it was cut from. Samples are not renumbered in the emails, links or
notes people kept: the owner's email is how they find out.

Project samples use their project's code instead of initials, with
the project's own counter, e.g. `UMIN1-2026-001`, whoever receives them.

If an edit moves a sample between thin film or bulk and project (or to another
project), its ID no longer starts with what it should, so the sample page asks
what to do. An admin is offered the new ID (the next free number under the
owner's initials or the project's code) and can update it or keep the old one.
Anyone else can keep the ID, or **Ask an admin to fix it**, which sends the
admins a suggestion (Suggestions inbox) naming the sample. Nothing changes
until an admin recodes it. Pieces are skipped: change the ID of the sample
they were cut from.

Everyone sets their display name and initials (2–4 letters, unique) on first
login; they're asked again until they do. Once someone has samples, only an
admin can change their initials (Configurations → Users).

### Sample types

Each type is explained beside its button on the new-sample form.

- **Thin film:** a sample we deposited ourselves. A substrate from the library,
  dimensions, and optionally the film material (a sample is just its substrate
  until it's deposited). The film is picked from a shared dropdown list, like
  the ones on the step forms ("+ Add new…" adds one), so every sample spells it
  the same way and filtering by film finds them all. A value typed in a
  different case or with extra spaces is saved with the list's spelling.
  Migration `0013` started the list from the films already on samples, merging
  spellings that only differed in case or spaces into the most used one.
- **Bulk:** a bulk crystal or membrane, e.g. a 5×5 mm piece of a library
  substrate. **External ID** holds the identifier given by whoever cut it.
- **Project:** a commercial sample, or any sample sent for a project or
  collaboration, thin film or not. Choose its project from the Partners tab
  (for a commercial sample, a project for its supplier) and describe the sample
  (both required); optionally add their own ID or the product/batch number, and
  a spec sheet (PDF or photo). Its owner is the researcher who receives it.

There used to be a separate *Commercial* type. A migration (`0010`) turned
those samples, and the old *Collaboration* ones, into *Project*. Commercial
samples keep their ID, supplier and spec sheet, and have no project yet: the
next time one is edited it asks for one (the ID keeps its initials until an
admin changes it, see above).

### Substrate library

The **Substrates** tab lists the substrates samples are made from, with
thickness, orientation, polishing, size, supplier, batch number, notes and spec files
(PDF or photos). Anyone can add one; whoever added it and admins can edit
it. A substrate used by any sample can't be deleted.

### Projects (the Partners tab)

The **Partners** tab lists the projects: collaborations with universities and
centres that send us samples, and the companies we buy commercial samples
from. For each: name, institution or company, code, country,
contact person and email, notes. One institution can have several projects,
each with its own samples. The institution field suggests the ones already
entered, so each is spelled the same way. The code (2–6 letters or digits)
works like a researcher's initials in sample IDs, so it can't be anyone's
initials (and initials can't be a project's code). It's fixed once a sample
uses it. Anyone can add a project; whoever added it and admins can edit it,
and a project with samples can't be deleted. Search can group results by
project, and the CSV has `project` and `institution` columns.

### Timeline

Steps and analyses share one timeline per sample, ordered by an explicit
`position`. Dates are optional and record the day only:

- A new dated entry goes before the first entry with a later date, so after
  any already on the same day; an undated one is appended. Changing an
  entry's date moves it the same way; other edits leave it where it is.
- The ↑/↓ arrows move entries freely: to order entries from the same day,
  or to override the dates altogether.
- **Sort by date** puts the dated entries back in date order, keeping the
  order you chose within a day; undated entries keep their places.

**Planned entries.** **Plan a step** on the sample page opens the step form
with **Planned, not done yet** ticked (the box is on every step and analysis
form). A planned entry sits on the timeline like the others, with a dashed
amber border, a *Planned* badge and its date shown as "for <date>". Until it
is done it is left out of search (the entries table, the filters and the
technique dropdown), the CSV exports, deposition rates and plots, and what a
piece inherits. **Mark as done** on its card opens the edit form with the box
unticked: check the values, the date included, fill in what was only known on
the day (for a deposition, the base and working pressure) and save. The flag is
the `planned` column on `process_steps` and `analyses` (migration `0016`).

**Deposition duration calculator.** The Deposition form has **Target
thickness** (nm) and **Rate used for the time** (nm/min) before the Duration:
filling both in works the duration out (thickness ÷ rate, as min:s), on a
planned deposition or any other. **Use the last known rate** under the rate
fills it in with the rate of the latest deposition you can see whose machine,
target, gas, gas flow and power match those filled in on the form (empty ones
match anything), measured if it was measured (even when a rate was also typed
on it), and says which deposition that is. Both values are kept on the entry, so a planned deposition records the
rate its time came from. They're separate from the Deposition rate field (the
rate actually achieved), so they don't count as rates in search and plots.
Migration `0016` adds the two fields to an existing Deposition type, before its
Duration, keeping any changes an admin made to it.

### Photos and files

Each step and analysis card on a sample's page has **📷 Add photos** (opens
the camera or gallery on a phone; pick several at once) and **📎 Attach
files**. Uploads start as soon as files are chosen, and you can also drag
files onto a card (images count as photos). The step and analysis forms take
photos and files too.

To add the same photos or files to several entries at once, across samples,
use the **Add files** tab (`/attach`, `routers/attach.py`). Filter by type
(one step or analysis type, or any step / any analysis), date range (with
**Today** and **Yesterday** shortcuts), sample or notes, and **Done by me**
(on by default: entries you performed). Only entries you can edit are listed,
newest first, up to 300. Tick them (or tick all), choose photos and/or files
in the fields above the list and press **Add to the ticked entries**: each file is stored once, in the
first ticked entry's folder, and shared by the others, as for a run.

- **Photos** larger than 2560 px or 2 MB are rotated upright, downscaled and
  saved as JPEG (quality 85, stepped down if needed to stay under 2 MB;
  about 0.5–1 MB for a typical phone photo). Smaller photos are kept as
  uploaded. iPhone HEIC photos are converted to JPEG. Re-encoding drops
  metadata such as GPS location.
- **Files** are always stored exactly as uploaded, so raw data images
  (e.g. 16-bit TIFFs from SEM/AFM) keep full quality.
- Every image gets a small thumbnail for the timeline; click it for the
  full-size file.

The limits are settings (`PHOTO_MAX_PX`, `PHOTO_MAX_MB`, `PHOTO_JPEG_QUALITY`,
`THUMB_PX`) and can be overridden in `.env`. This needs Pillow and
pillow-heif from `requirements.txt`; after updating, rebuild the container
with `docker compose up -d --build`. Without them, photos are stored
unchanged and shown without thumbnails.

On disk, `uploads/` has one folder per sample ID and, inside it, one per
step or analysis (its date, or the upload date if it has none, and its
technique), so the folder can be browsed without the app. Files keep the
names they were uploaded with:

```
uploads/
  ASS-2026-001/
    sample.json                           ← the sample's record (see below)
    spec sheet.pdf                        ← the sample's own files
    2026-10-20_Deposition/
      IMG_1234.jpg
      thumbs/                             ← timeline previews
    2026-10-22_XRD-HRXRD/
      scan 01 (final).raw
      scan 01 (final) (2).raw             ← same name taken: (2), (3), …
  substrates/
    Si-100-wafer/datasheet.pdf
  studies/
    3-Contacts-on-Ga2O3/                   ← a study (<id>-<title>, kept if it's renamed)
      study.json                           ← the study's record (see below)
      paper.pdf                            ← files on its notes
```

Only characters Windows can't store in a name (`<>:"|?*`) are replaced by
`_`. Folders are fixed when the file is uploaded: changing an entry's type
or date later doesn't move its files. A file shared by several samples (a
run) is stored once, in the folder of the sample it was uploaded on. The
database still links every file to its entry, so keep `uploads/` and the
database together (see Backups).

**A file is stored only once.** Each attachment keeps a SHA-256 hash of its
file. Uploading a file identical to one already stored, under any name and on
any entry, doesn't store it again: the new attachment points at the stored
file, as with a run, so it can live in another sample's folder. The same file
added twice to the same entry is only attached once. Photos are compared after
downscaling, so the same phone photo matches itself.

**Deleted files wait 30 days in the trash.** Deleting a file, or the step,
analysis or sample it's on, moves the file to
`uploads/.trash/<day deleted>/`, under the same path it had
(`uploads/.trash/2026-11-06/ASS-2026-001/…/scan.raw`). A file another entry
still uses stays where it is. Day folders older than `TRASH_DAYS` (30) are
deleted when the app starts and once a day after. To get a file back, copy it
out of the trash and attach it again. (Before this, deleting an entry or
sample left its files on disk and their records in the database.)

**Duplicates and leftovers from before.** Files stored before migration `0015`
have no hash yet. On the DB host, after updating, run

```bash
docker compose exec app python -m backend.dedupe_files           # report only
docker compose exec app python -m backend.dedupe_files --apply   # do it
```

It hashes every stored file; points all attachments with the same content at
the oldest copy and moves the other copies to the trash; drops the same file
attached twice to one entry; and drops the records of files whose entry or
sample was deleted, moving those files to the trash too, unless something else
uses them. Without `--apply` it only lists what it would do. Files missing
from disk are listed and left alone.

Each sample folder also has a `sample.json`: a copy of everything the
database holds about that sample (details, owner, sharing, substrate,
project, its own timeline with parameters, notes, who did what and when, and
the files of each entry). It is rewritten after every change and for all
samples when the app starts (or on demand:
`docker compose exec app python -m backend.sample_backup`), so it's always current. It's there so that, if
the database is lost, `uploads/` still says what every file is. A piece's
file doesn't repeat the entries it inherits: `cut_from` names the parent
and the Cut step, and they are in the parent's file. Each study's folder
has a `study.json` in the same way (see [Studies](#studies)). Users, entry
types, dropdown values and suggestions aren't in these files; the database
dump is still the real backup.

Mandatory: the substrate for thin-film and bulk samples, a project and a description for project samples, and the type of each step/analysis. `required` in
a type's schema is a hint shown on the form, not enforced.

The tables are created and kept up to date by migrations that run when the
app starts; see [Schema changes (migrations)](#schema-changes-migrations).
Never recreate the database to apply a model change.

### The `sample.json` file

`uploads/<sample ID>/sample.json` is plain JSON, written with UTF-8 and
indented, so it can be read without the app. Top level:

| Key | Meaning |
|---|---|
| `format` | Version of this layout (currently 8: adds `visibility`, `previous_codes`, per-entry `status`/`proposed_by` and `devices`; older files lack them. 4 replaces the types `commercial` and `collaboration` with `project`; 5 adds `planned` on entries; 6 adds `on_step_id`, `on_substrate` and `partial` on steps; 7: a Deposition's `base_pressure` is in 10⁻⁶ Torr, not mTorr; 8 adds `studies`). |
| `written_at` | When the file was last written. |
| `id`, `code`, `previous_codes` | Database id, the sample ID, and any IDs it had before an admin changed it. |
| `label`, `sample_type`, `is_reference`, `visibility`, `tags`, `description`, `film_material`, `substrate_dimensions`, `external_id`, `supplier`, `created_at` | The sample's own details. `sample_type` is `thin_film`, `bulk` or `project`; `visibility` is `personal`, `team` or `public`. |
| `owner`, `requested_by` | `{username, name, initials}` or `null`. |
| `shared_with` | List of `{username, name, initials, can_edit}`. |
| `substrate`, `project` | The library substrate / project it refers to, copied in full (`null` if none). |
| `cut_from` | For a piece: `{sample, cut_step_id, cut_position}`: the parent's ID and where on its timeline the Cut step is. The piece inherits everything before that position; those entries are in the parent's file, not repeated here. |
| `files` | Files attached to the sample itself (e.g. a spec sheet). |
| `devices` | The devices made on the sample: list of `{label, notes}`. |
| `studies` | The studies it is in: list of `{id, title}` (their notes and references are in each study's `study.json`). |
| `timeline` | The sample's own steps and analyses, in order. |

Each `timeline` entry has `id`, `kind` (`step` or `analysis`), `type` (the
technique, e.g. `Annealing`), `position`, `performed_at` (a date), `location`,
`performed_by` (`{username, name, initials}` for a user, `{name}` for someone
without an account, or `null`), `notes`, `run_id` (entries added to several
samples at once share it), `status` (`approved`, or `pending` for an entry a
teammate proposed that the owner hasn't approved), `proposed_by`, `planned`
(`true` for an entry planned and not done yet), `created_at`, on a step
`on_step_id` / `on_substrate` / `partial` (what a deposited layer was put on:
the `id` of another deposition, or the bare substrate, or neither for
everything so far; `partial` when it covers only part of it, see
[Layers](#layers)),
`files` (`file` is the path under `uploads/`, plus `original_name`, `size`,
`mime_type`, `uploaded_by`, `uploaded_at`) and **`parameters`**. An analysis
also has `device`: the label of the device it was measured on, or `null`.

`parameters` is an object keyed by the field keys of the entry's type (see
[Steps and analyses: parameters](#steps-and-analyses-parameters)): numbers as
numbers, text as text, durations as `"min:ss"`. A *variant* (e.g. Annealing's
Furnace/RTA) stores the chosen value under its key and the chosen option's
fields next to it; a ticked *check* stores `true` and its fields next to it; a
*modes* field (e.g. XRD) stores `{mode: {sub-key: value}}`. Keys the type no
longer has stay as they were. Example, trimmed:

```json
{
  "format": 2, "code": "ASS-2026-001", "visibility": "personal",
  "owner": {"username": "ana", "name": "Ana Silva", "initials": "ASS"},
  "substrate": {"name": "Si 100", "material": "Si", "orientation": "(100)", "thickness_um": 525.0, "batch_no": null},
  "timeline": [
    {"id": 1, "kind": "step", "type": "Annealing", "position": 0, "performed_at": "2026-10-22",
     "location": "INESC MN", "performed_by": {"username": "ana", "name": "Ana Silva", "initials": "ASS"},
     "parameters": {"method": "Furnace", "temperature": 800, "duration": 60}, "status": "approved", "files": []},
    {"id": 1, "kind": "analysis", "type": "XRD / HRXRD", "position": 1, "performed_at": "2026-10-23",
     "performed_by": {"name": "Rui (visitor)"}, "parameters": {"mode": "2θ/ω"}, "status": "approved",
     "files": [{"file": "ASS-2026-001/2026-10-23_XRD-HRXRD/scan01.raw", "original_name": "scan01.raw", "size": 1000}]}
  ]
}
```

## Devices on a sample

When several devices come out of one sample, finish the process that makes
them, then click **⚡ Make devices** next to *Cut into pieces*, on the right
of the sample page's buttons (*Add Process Step*, *Plan a step* and *Add
Analysis* are on the left) (the dialog explains it too, and lists
the existing devices so you can remove one): give the labels (D1, D2, …, or just how many) and the date. This puts
a **Devices made** step on the timeline, listing the devices; everything
before it is their shared history. Steps added afterwards, such as annealing,
still go on the sample and so apply to all its devices. It isn't tied to any
particular process, and more devices can be made later with another
**Devices made** step.

An analysis has an optional **Device** field to say which one it was
measured on; left empty, it concerns the whole sample. Removing a device
keeps its analyses, now on the sample as a whole; deleting a *Devices made*
step removes its devices the same way. Pieces cut from the sample inherit
the analyses with their device label. The CSV has a `device` column, and
`sample.json` a `devices` list.

## Cutting a sample into pieces

**✂ Cut into pieces**, next to Add Process Step and Add Analysis on a
sample's page, records a "Cut" step on its timeline and creates one new
sample per piece. It's the only way to add a Cut: Add Process Step doesn't
offer it, and an existing step can't be changed to or from Cut. The form asks for a photo of
the pieces; write each piece's letter next to it so it's clear which is
which. A tick box adds an extra
reference piece (`<ID>-REF`, marked **Reference**). Each piece:

- **inherits** the parent's timeline up to the Cut step. Inherited entries
  show greyed out with "from <parent>" and can only be edited on the parent.
  Nothing is copied, so fixing a parent entry fixes it for every piece.
  Pieces of pieces inherit through the whole chain.
- gets the parent's ID plus a suffix (see Sample IDs) and an optional label.
- copies the parent's type, substrate, film, tags and shares (whoever cuts
  someone else's sample also gets edit access to the pieces).
- belongs to the researcher picked for it on the cut form, by default
  whoever cut it (**Cut by**, you unless you pick someone else; they're
  recorded as the Cut step's performer). A piece given to someone other
  than the parent's owner is assigned as described in
  [Assigning a sample to someone else](#assigning-a-sample-to-someone-else),
  and the parent's owner keeps edit access to it.
- gets its own steps and analyses after the cut, separate from its siblings.

The parent stays usable after the cut, and anything added to it afterwards
belongs to the parent only. Moving the Cut step on the parent's timeline
changes what the pieces inherit. A sample can't be deleted while it has
pieces, and neither can a Cut step that pieces were cut at.

Access to a piece includes its inherited history (entries and files from
before the cut), even without access to the parent. Search matches pieces on
inherited entries, and the CSV marks those rows in `inherited_from`.

## Studies

The **Studies** tab (`/studies`, `routers/studies.py`, permissions in
`backend/studies.py`) is for work that spans several samples: an annealing
series, a contact-metal comparison, a collaboration's batch. A study has a
title, a description and three parts:

- **Samples.** Add one by its ID on the study's page (the field suggests the
  samples you can see), or with **Add to a study…** in the *Studies* row on a
  sample's page, which also lists the studies the sample is in. Only samples
  you can see can be added, and a study's page lists only the samples the
  viewer can see ("and 2 samples you can't see" for the rest). A sample can be
  in several studies; deleting a sample takes it out of them.
- **References.** Paste a DOI (bare, `doi:…` or a `doi.org` link) or any
  link, with an optional note on why it matters. For a DOI the title, authors,
  journal and year are looked up at doi.org (`backend/doi.py`); if that fails
  (no internet on the host, unknown DOI) the reference is kept with the DOI
  and whatever title was typed. **Anyone who can see the study can add a
  reference**; co-owners and whoever added it can remove it.
- **Notes.** Dated notes for literature, thoughts and plans, with an
  optional title, photos and files. They are ordered like a timeline: a new
  or re-dated note goes after the others of its day, and ↑/↓ move it. A note
  can be **about** one of the study's samples, or one of their steps or
  analyses, and links to it. What concerns a single step (its parameters,
  results, files) still belongs on the step. Note files are stored under
  `uploads/studies/<id>-<title>/`.

**Co-owners.** Whoever creates a study is its first co-owner and can add
others (any user with an account). Every co-owner, and admins, can change
everything: details, samples, notes, co-owners. A study always keeps at least
one. **Who can see it** works as for samples: *Personal*, only its
co-owners; *Team*, also everyone in a co-owner's team (the default);
*Public*, everyone logged in. The tables are `studies`, `study_owners`,
`study_samples`, `study_references` and `study_notes` (migration `0020`).

**Printing.** **🖨 Print / PDF** on a study's page opens it laid out for A4
(`/studies/{id}/print`, `studies/print.html`), like a sample's printable
record: details, co-owners, the samples (only those the reader can see), the
references as a numbered list, and the notes in order with photo previews and
file names. Print it, or choose *Save as PDF* as the printer. A sample's own
printout lists the studies it is in.

**`study.json`.** Next to its notes' files, `uploads/studies/<id>-<title>/`
(named when the study is created, and kept if it's renamed) has a
`study.json`, written like `sample.json`: after every change and for every
study at start-up. Keys: `format` (currently 1), `written_at`, `id`, `title`,
`description`, `visibility`, `created_at`, `created_by`, `owners`
(`{username, name, initials}`), `samples` (`{id, code, label, added_at}`),
`references` (`doi`, `url`, `title`, `authors`, `journal`, `year`, `note`,
`added_by`, `created_at`) and `notes`, in order (`id`, `position`, `noted_on`,
`title`, `text`, `author`, `created_at`, `files` as in `sample.json`, and
`about`: `null`, or `{sample, sample_id, kind, id}` where `kind` is `sample`,
`step` or `analysis` and `id` is the entry's `id` in that sample's
`sample.json` timeline). Deleting a study removes its `study.json`; its
files go to the trash.

## Access and sharing

Every logged-in user sees every sample's summary: ID, label, type,
materials, substrate, tags, which techniques were used, and the researcher. Details (description,
parameters, notes, dates and files) are visible to:

- the sample's owner (the researcher who created it),
- admins,
- users the owner has shared the sample with,
- the **coordinators** of the owner's team, who have the owner's rights (see [Teams](#teams)),
- anyone the sample's **visibility** lets in.

**Visibility** is set per sample, when it is created and at any time later,
either on the sample's *Edit* page or under *Sharing* (owner or admin): **Personal** (only the people above),
**Team** (the default: also everyone in the owner's team) or **Public** (everyone logged
in). A piece cut from a sample starts with its parent's visibility. Visibility
only decides who can *see* details; changing a sample still needs an explicit
**Edit** share (or being the owner or an admin).

### Teams

A team is a group inside the lab (separate from [Projects](#projects), which
are outside collaborators). Teams are meant to run themselves with little
admin input, in three tiers:

| | Can do |
|---|---|
| **Admin** | Everything. Only admins create, rename and delete teams, appoint and remove **coordinators**, move people between teams, change sample IDs, edit entry types and dropdown lists, and make other admins. |
| **Coordinator** (of one team) | Has the **owner's rights on every sample owned by a member of their team**: view, edit, share, change visibility, delete, and hand to another member of the team (straight away, no confirmation). Answers proposals and access requests (below). On the **My team** page: adds people who have no team, removes members (not coordinators), creates accounts for new members (they join the team and get the usual welcome email) and resets members' passwords. |
| **Member** | Their own samples, anything shared with them, what a sample's visibility shows them, and *proposing* entries on teammates' samples. |

Admins manage teams under *Configurations → Teams*. **Send a message** (Configurations) emails everyone, one team's
members or one person, each with their own copy; it needs email configured. People normally belong to
one team; the data model allows several, and a coordinator's rights apply to
each team they coordinate. Management actions (deleting or handing over
samples, sharing, approvals, accounts, team changes) are recorded in the
**Activity log**, which admins see in full and a team's coordinators see for
their own members. Ordinary editing isn't logged.

### What a share gives

Sharing a sample with **View** gives everything on it: parameters, notes,
dates and files of all its steps and analyses, not only the list of steps.
**Edit** adds the ability to add and change steps, analyses and files. Neither
lets the person delete the sample or manage its sharing.

Owners share from the **Sharing** panel on a sample's page, or select
several samples on the **Search** page and share them at once. Each share
is **View** (read details and download files) or **Edit** (also add and
change steps, analyses and files). Only the owner, an admin or a coordinator
of the owner's team can delete a sample or change who it's shared with. Samples without an owner are open to
everyone; admins can assign an owner from the sample's Edit form.

### Proposing entries on a teammate's sample

Anyone in the owner's team can **propose** a process step or analysis on the
owner's sample (the *Propose* buttons on its page), even without view or edit
access. The proposal stays out of the timeline, exports, search and the
inherited history of pieces until it is approved, and the owner is emailed.
The author sees and can change or withdraw their own proposal meanwhile.

- The **owner** approves or declines it from the *Approvals* page, or on the
  sample; so can a **coordinator** of the owner's team (and admins), at any
  time, so a sample whose owner is away isn't stuck. Declining deletes the
  proposal and its files and tells the author.
- Approving puts the entry on the timeline (by its date, or last) and emails
  the author.

### Requesting access

On a sample you can't see or edit, **Request access** asks the owner for
*See the details* or *Edit*, with an optional message. The owner is emailed
and answers on the *Approvals* page; approving creates the share (View or
Edit) and the requester is told. A coordinator of the owner's team (or an
admin) can answer too. Requesters can withdraw a pending request. The sidebar shows
how many things are waiting for you.

### Who performed a step or analysis

**Performed by** on a step or analysis is a list of users (you by default),
plus **Someone else** to type a name for someone without an account; pick
them from the list later, once they have one. A user chosen here can see and
edit that entry (parameters, notes, date, photos and files) even without
access to the rest of the sample, and gets an email saying so. Adding,
deleting and reordering entries still needs edit access to the sample.

### Assigning a sample to someone else

A sample can be given to another researcher in three places:

- the **Researcher** field on the New Sample form. The sample then gets
  their initials (e.g. `BOB-2026-004`);
- the **Researcher** field on the Edit form, for the sample's owner (e.g.
  give the original to whoever does the deposition and keep the pieces);
- the **Researcher** column on the cut form, per piece.

When an admin assigns it, it goes straight to them. Otherwise the new owner
has to confirm it:

- They get an email with links to the samples (if SMTP is set up and they
  have an email address). They also see a badge on **Samples** and a list
  at the top of that page.
- Until they answer, the sample shows "awaiting confirmation" and whoever
  assigned it has edit access, which they keep afterwards.
- On the sample's page they can **Accept** it, or **Decline** it, which
  gives it back to whoever assigned it, by email too. The ID never changes.

## Suggestions

Everyone has a **💡 Suggestions** tab to send an idea, problem or question;
it records which page they came from. Admins see everything in the
**Inbox** tab (badge = open suggestions), filter by open/solved, reply, and
mark suggestions solved or reopen them. Each suggestion is a thread: the
author sees replies on their Suggestions page (with a badge for unread
replies) and can answer back.

## Language and dark mode

The **PT / EN** switch at the bottom of the sidebar picks the language; on a
first visit it follows the browser, and Portuguese if the browser asks for
neither. The ☾ / ☀ button switches dark mode (it starts from the system
setting and is remembered per browser). Emails are sent in both languages,
Portuguese first.

Templates and messages are written in English and wrapped in `_()` (Jinja)
or `t(request, …)` (Python); the Portuguese is in `backend/translations/`,
one module per area, merged into one dictionary (see `backend/i18n.py`). Text
without an entry shows in English. Technical terms and metadata stay in
English in both languages: sample types, step/analysis types and techniques,
dropdown values (machines, Furnace/RTA, XRD modes, …), units and polishing.
Parameter labels (Method, Duration, …) are translated. Dark
mode remaps the Tailwind colour classes in `base.html`, so a page using a new
colour may need a line there.

## Search and export

The **Search** tab filters samples by free text, researcher, sample type,
material, technique and tag, and groups results by researcher, year, type,
material, technique or tag. **Export results
(CSV)** downloads the matching samples, with details left blank for
samples you can't view. Free-text search only matches details you can see.
Filtering by a technique also lists that technique's entries on the matching
samples above them, newest first (undated ones last): date, sample, one
column per parameter (with units), where, performed by and notes. Entries
on samples you can't view are left out, unless you performed them; an entry a
piece inherits is listed once, under the sample it is recorded on.

The search form then also shows **<technique> parameters**, one filter per
field of that technique that some listed entry has (long texts aside, and
fields no entry fills in left out, so the form stays short enough to see the
plot and table; a filter in use stays): dropdowns and methods (e.g.
Target, Machine, Annealing's Furnace/RTA) pick one of the values in use,
numbers take a min–max range (ends included; entries without a number there
drop out), and text fields match what they contain. Only entries matching all
of them are listed, and only samples with such an entry are left, in the list
and in the CSV export (query parameters `pf.<key>`, `min.<key>`, `max.<key>`).
E.g. Thin film + Deposition + Target Ga2O3 lists every Ga2O3 deposition,
newest first, with its power, gas flow and rate. A number field's min box
also takes a value that isn't a number, e.g. a gas flow of `20/5`, and then
matches it exactly. For Deposition, the rate column (and its filter) is the
typed Deposition rate, marked *typed* (with the measured rate noted next to
it when that differs: *typed; measured 10 nm/min*), else the measured rate,
marked *measured*/*average of n*; a plot above the table shows the rates of
the entries listed over time (the measured rate where there is one), one line per set of machine, target, gas, gas flow and power (the eight
with most depositions; narrow the filters for the rest). Each set keeps its
colour when filters change. Hovering a point shows the sample and rate;
clicking opens it. Searching with a technique chosen jumps down to its
entries table.

**Columns** above the table picks which parameter columns are shown (and
where, performed by, notes). The choice is remembered per technique in each
person's browser (`localStorage`), so everyone keeps their own.
Admins can download the whole database from the admin page. The CSV has one row per step/analysis, with a
`param:<key>` column per parameter.

### Steps and analyses: parameters

Each step or analysis type has its own fields, filled in on the form:

- **Numbers** have their own box and unit (pressures are in mTorr and can be typed as `1e-4`,
  except a Deposition's base pressure, in 10⁻⁶ Torr: `2` is 2×10⁻⁶ Torr;
  a decimal comma works too). Base pressures stored before migration `0019`
  (asked in mTorr, though some were typed in Torr) were each read as Torr,
  mTorr or 10⁻⁶ Torr, whichever puts it nearest 10⁻⁶ Torr (`1e-6` and
  `1e-3` both become 1), and converted; the migration logs each conversion,
  and warns about values that aren't numbers or end up outside 10⁻⁸–10⁻⁴ Torr. Durations like the deposition time take
  min:s (`12:30`), or plain minutes (`12`).
- **Dropdowns** (machine, technique, target, atmosphere, …) offer values
  saved earlier. **+ Add new…** types a new one, which is then offered to
  everyone.
- Some types ask first which **variant** it is, and then show that variant's
  fields: Annealing → Furnace (temperature, duration) or RTA (atmosphere,
  temperature, duration, ramp); XRD / HRXRD; RBS or RBS/Channeling; etc.
- **XRD / HRXRD** has **modes** (2θ/ω, rocking curve, grazing incidence, …):
  tick the ones measured, or add another, and fill in each one's range, step,
  acquisition time and configuration.
- **Where** (CTN, INESC MN, FCUL, or another institute) is on every step and
  analysis; it's a dropdown too. On a new entry it starts at the chosen
  type's usual place, and follows the type until Where is changed by hand:
  INESC MN for Deposition, Etching, Lithography, CMP, Ellipsometry,
  Hall / 4-probe, Profilometry and SEM; FCUL for AFM; empty for TEM and XPS
  (done elsewhere); CTN for the rest. Admins change a type's usual place
  under Configurations ("Usually done at"); migration `0014` set these. Every technique has an **Equipment**
  dropdown (Machine on Deposition) with its own list, and equipment belongs
  to a place: the dropdown only offers what's at the place chosen under
  Where (INESC MN has the Alcatel SCM 450, UHV1, UHV2 and SentiFet). A new
  piece of equipment typed on the form is filed under that place. New types
  added under Configurations get the Equipment field automatically.
  Equipment with no place set is offered everywhere. Equipment can also be
  tied to a method: on Annealing, **AnnealSYS is RTA only**, so with *Furnace*
  chosen the Equipment dropdown leaves it out, and with *RTA* chosen it is
  offered (any other equipment suits both). On the form the Equipment
  dropdown sits right after the method, before that method's own fields.
  Equipment typed on the form is
  filed under the method chosen at the time (migration `0011` tagged the
  existing AnnealSYS as RTA). The `applies_to` column of `choice_options` holds
  it; there is no screen for editing it yet.
- **Other parameters** takes anything else as `key: value` lines.

The step types are Deposition (machine: Alcatel SCM 450, UHV1, UHV2, SentiFet;
technique, target, atmosphere, base and working pressure, power, gas flow,
target thickness and the rate used for the time (see the duration calculator
under [Timeline](#timeline)), duration, station, the deposition rate (nm/min) and thickness when known, and a
calibration sample tick box with details), Annealing, Ion
Implantation, Lithography (optical or e-beam), Etching (dry or wet), CMP (slurry
type, dilution, slurry flow (the machine's setting, no unit), pad type, force application, force, rotation, head and base
speed, time, and the thickness removed and removal rate when known; new steps
start with the typical recipe: SF1 Polishing Solutions, Chemomet, central force
of 20 N, same direction, 30 rpm head and base),
Cleaning (where, under the Where every entry has, and details), Cut and Other
Process. The analysis types are XRD / HRXRD, XPS, SEM (the equipment,
e.g. Hitachi S-2500), TEM, RBS, AFM, Raman, Optical Microscopy (mode, e.g.
bright/dark field or DIC, magnifications and observations), Hall / 4-probe,
Ellipsometry
(angles of incidence, and a large box for the optical model), Profilometry
(step height, scan length, stylus force, scan speed, roughness) and Other
Analysis. On the sample page parameters are shown with their labels and
units, and the CSV has one `param:` column per parameter (modes as
`param:modes/Rocking curve/range`).

**Deposition rate, measured.** An Ellipsometry or Profilometry analysis with a
thickness measures the Deposition before it on the timeline, if that is the
only deposition so far (otherwise the thickness is the whole stack's) and
only a Cut or Cleaning came in between (an etch, CMP, anneal, … changes the
thickness, so the measurement doesn't count). Measurements on pieces count for
the parent's deposition. The copies of a deposition in a run are films on
different samples, so each keeps its own measurements (rates and thicknesses
aren't averaged across the run).
Each gives thickness ÷ the deposition's duration in nm/min; the deposition
card lists them (technique, date, sample, thickness → rate) under **Measured
deposition rate**, their average. Nothing is stored: it's worked out from the
analyses, so editing or deleting one updates it. Saving such an analysis says
what the average now is. Only measurements on samples you can view count, for
you. Where a rate can't be worked out (a stack, or no duration), saving the
measurement asks for the rate by hand, filling the Deposition rate field of
that sample's deposition only; **Not now** closes the prompt.
A rate typed in the Deposition rate field (e.g. when configuring the
deposition) is never overridden by a measurement: it stays the deposition's
rate in search, and the card notes it under the measured one. Later
depositions go by the measured rate (Use the last known rate, the rate plot)
when there is one, else the typed one.

**Rate history.** The plot of the rate over time, one line per machine,
target, gas (atmosphere), gas flow and power (case aside), is on the search
page (Search by technique: Deposition); the sample page only lists the
measurements and their average. Undated depositions aren't drawn.
`backend/deposition_rate.py` (the conditions are `CONDITION_KEYS`, the steps
that keep the thickness `THICKNESS_KEEPING_STEPS`), `backend/rate_plot.py`,
`_rate_plot.html`.

### Layers

A thin-film sample's page draws its film stack above the timeline: the
substrate (hatched, not to scale) and one film per Deposition, bottom
first, inherited ones included (a piece shows its parent's films). Planned
depositions are drawn dashed and pale. Films are to scale with each other;
very thin ones are drawn at a minimum height, and the caption says so.

- **Material**: the deposition's Target, else the sample's film material.
  The colour goes by material, so two films of the same material match.
- **Thickness**, the first known of: the average of its thickness
  measurements (as for the measured rate; only a single film can be
  measured), the Thickness typed on the step, the typed Deposition rate ×
  Duration, the Target thickness. The label says which.
- **CMP** with a Thickness removed takes that much off the top films (a film
  polished away goes); planned CMPs are left out.
- Beside each film: the **process steps it went through** after it was
  deposited (annealing, implantation, CMP, …; not Cut or Devices made), with
  their first few parameter values and date. So with *deposit 100 nm, anneal
  1000 °C, deposit 200 nm, anneal 400 °C*, the bottom film lists both
  anneals and the top one only the 400 °C one.
- **What it goes on, and partial layers** (metal contacts through a mask):
  the Deposition form has **Deposited on**: *Everything so far* (the
  default), *The substrate*, or one of the layers already on the sample (its
  timeline before this step, including layers a piece inherits from the
  sample it was cut from), and **Covers only part of it**. A full layer
  spans what it's on; a partial one gets a slice of that, side by side with
  the other partial layers on the same thing, so some of the surface stays
  clear. Each film follows the surface it lands on, so *Ni on part of the
  film, Au on the Ni, Ti on part of the substrate, Au on the Ti* draws two
  pads with clear film around them, and a later full layer drapes over them.
  The label says what it's on ("on part of the Ni", "on the Ti"); the width
  of partial layers is not to scale, and the Total is the thickest column.
  Added to several samples at once, a copy goes on that sample's copy of the
  chosen layer (same run), or on the layer itself if that sample inherits it
  too (sibling pieces), else on everything. Stored on the step as
  `on_step_id`, `on_substrate` and `partial` (migration `0018`); a layer
  whose base is deleted or polished away goes on everything.

Click a film or a step to jump to it on the timeline. Bulk and project
samples have no stack. `backend/layers.py` (stack and geometry),
`_layers.html` (the SVG).

### Printing a sample's record

**🖨 Print / PDF** at the top of a sample's page opens its record laid out
for an A4 sheet, to print or save as a PDF (choose *Save as PDF* as the
printer) and keep with the sample: the summary (ID, type, label, researcher,
substrate, film, project, tags, devices, description), the layers drawing
and the whole timeline, inherited entries included, each with its date,
performer, place, parameters, measured rate, notes and pieces. Photos are
small previews and files are listed by name only; the header has the
sample's link and when it was printed. It shows what the page shows to you:
without access to the details, only the summary. Made by the browser, so
nothing extra is needed on the server: `GET /samples/{id}/print`
(`routers/samples.py`, which shares the page's data with the sample page),
`samples/print.html`.

### One step or analysis on several samples

Things done in parallel (one deposition run, one XRD session) can be
recorded once: **Also add to other samples** on the form lists the samples
you can edit, both when adding an entry and when editing one later. Each
ticked sample gets its own copy, linked as a run ("Also on: …" on the
sample page), and a file field appears next to it for that sample's own
files (e.g. its data). On a new entry, the main photo and file fields go to
every sample (stored once). Editing one copy lists the others, each with its
own file field, and offers to apply the changes to them (not the files).
That copies the whole form onto them, so if it would change or clear a value
another sample already has, you're shown which and asked first;
each copy keeps its own place in its sample's timeline.
The list starts with sibling samples (cut from the same step), then the
same researcher's newest samples, then the rest. For a series where one
parameter changes, tick **What differs between samples?** in that section:
every ticked sample (and the current one) gets a box for it, and Enter moves
to the next sample's box. Empty boxes keep the common value. Only the chosen
method's parameters are offered (Annealing: Furnace or RTA), each once. Deleting a copy only
removes it from that sample.

---

## Adding or changing a step / analysis type

Admins manage types under **Configurations**: add, edit (name, description,
where it's usually done, schema) or delete (only when unused). Editing a schema never changes stored
data: values whose field was removed stay on existing entries and are still
shown. Each type has a `parameter_schema`, a JSON list of fields. Every
field has a `key` and a `label`; its `type` is one of:

| type | entered as | extra keys |
|---|---|---|
| `number` | a number box | `unit`, `placeholder` |
| `duration` | min:s (`12:30`), h:min:s, or plain minutes; stored as `12:30` | `unit`, `placeholder` |
| `text` | a one-line box | `placeholder` |
| `longtext` | a large box | `placeholder` |
| `choice` | a dropdown from a shared list | `list` (the list's name; default: the key); `located: true` for equipment that belongs to a place |
| `variant` | pick one option; each has its own fields | `options`: `[{"value": "RTA", "fields": [...]}]` |
| `check` | a tick box; its fields show when ticked | `fields` |
| `modes` | tick several from a shared list; each gets the same fields | `list`, `fields` |

A `number`, `duration`, `text`, `longtext` or `choice` field can also have a
`default`: the typical value, filled in on the form for a new entry.

For example, Annealing:

```json
[
  {"key": "method", "label": "Method", "type": "variant", "options": [
    {"value": "Furnace", "fields": [
      {"key": "temperature", "label": "Temperature", "type": "number", "unit": "°C"},
      {"key": "duration", "label": "Duration", "type": "number", "unit": "min"}]},
    {"value": "RTA", "fields": [
      {"key": "atmosphere", "label": "Atmosphere", "type": "choice", "list": "atmosphere"},
      {"key": "temperature", "label": "Temperature", "type": "number", "unit": "°C"},
      {"key": "duration", "label": "Duration", "type": "number", "unit": "s"},
      {"key": "ramp", "label": "Ramp", "type": "number", "unit": "°C/s"}]}
  ]}
]
```

The default types and dropdown values are in `backend/seed.py`. They're only
added when missing, so changes made under Configurations are kept.

---

## LAN access

The app binds to `0.0.0.0:8000`.  
Everyone on the same network reaches it at `http://<server-ip>:8000`.

To find the server IP on Windows: `ipconfig` → IPv4 Address.
On Linux: `ip a` or `hostname -I`.

---

## Tests

The tests run the real app on a throwaway SQLite database and a temporary
uploads folder; they never touch Postgres or `uploads/`.

```bash
pip install -r requirements-dev.txt
pytest
```

`tests/test_permissions.py` pins down who can see and do what with a sample
(owner, admin, shared view/edit, performer, stranger). Run it before and after
any change to sharing or access rules.

---

## Schema changes (migrations)

The database structure is versioned with [Alembic](https://alembic.sqlalchemy.org/).
The app applies pending migrations by itself every time it starts
(`backend/migrate.py`), so updating means: pull the code, rebuild, start.
Migrations live in `backend/migrations/versions/`.

### First update to a version with migrations (one time only)

Your existing database was built before migrations existed. The app detects
this (tables, but no `alembic_version` table) and marks it as the baseline
revision `0001`, which is exactly the schema it already has. Nothing in your
data is changed. On the machine that hosts the database:

1. **Back up first**: `docker compose exec backup python3 /backup.py --now` (see [Automatic backups](#automatic-backups)), or by hand (see [Backing up by hand](#backing-up-by-hand)).
2. Pull the new code and rebuild: `git pull`, then `docker compose build app`
   (this installs the new `alembic` dependency).
3. Start it: `docker compose up -d`.
4. Check the log for errors: `docker compose logs app | tail -30`.
5. Check the version was recorded; this should print `0001` (or the newest revision):

   ```bash
   docker compose exec -T db psql -U logbook logbook -c "select * from alembic_version;"
   ```
6. Open the logbook and look at a few samples.

If something fails, `docker compose down`, restore the backup (see
[Restoring](#restoring)) and go back to the previous commit.

### Later updates

Same steps 1–6. The app upgrades the database to the newest revision when it
starts, and `alembic_version` shows the new number.

### Troubleshooting an update

**The page doesn't load after `docker compose up -d`, and `docker compose ps`
still says the app is "Up".** "Up" only means the container started. Read the
log: `docker compose logs --tail 30 app`.

If it ends in `ModuleNotFoundError: No module named '...'` (e.g. `alembic`),
the image is older than the code. `backend/` and `frontend/` are mounted into
the container, so `git pull` updates the code immediately, but Python packages
are baked into the image. Rebuild it:

```bash
docker compose up -d --build app
```

Rebuild after any `git pull` that changes `requirements.txt`. The database
container and its data are not touched. The app only reaches the migrations
once it starts, so the crash above means the database has not been changed.

### For developers: writing a migration

Change `backend/models.py`, then generate and **read** the migration before
committing it (autogenerate misses renames and data changes):

```bash
DATABASE_URL=sqlite+aiosqlite:///scratch.db alembic upgrade head   # empty scratch db at the current revision
DATABASE_URL=sqlite+aiosqlite:///scratch.db alembic revision --autogenerate -m "what changed"
```

Migrations that fill existing rows (e.g. giving old samples a default
visibility) need that written by hand in the same file.

---

## Backups and moving to another machine

Everything the logbook holds is in three places:

| What | Where |
|---|---|
| Database (samples, timelines, users, …) | the `pgdata` Docker volume |
| Uploaded files (photos, data, spec sheets) | the `uploads/` folder |
| Settings (`SECRET_KEY`, `BASE_URL`, SMTP) | `.env` |

> **Careful:** `docker compose down` stops the logbook and keeps the data.
> `docker compose down -v` also **deletes the database**. Only use `-v` when
> you mean to start from scratch.

### Automatic backups

The `backup` service in `docker-compose.yml` (`backup/backup.py`) makes a
snapshot of the database and `uploads/` once a day. It checks every hour, so
if the PC was off at night the day's snapshot is made soon after it's
switched on. It starts with the rest: `docker compose up -d --build`.

```
backups/
  2026-11-06/
    logbook.dump        ← the whole database (pg_dump -Fc)
    uploads/            ← uploads/ as it was that day, without .trash
  2026-11-05/
  …
```

**Kept:** the newest snapshot of each of the last 7 days, 4 weeks and 12
months that have one, so at most about 23 snapshots. Days the PC was off
don't count, so a long gap never deletes everything old. Change the numbers
with `KEEP_DAILY`, `KEEP_WEEKLY` and `KEEP_MONTHLY` in the service's
`environment`.

**Space:** a file that didn't change since the previous snapshot is a hard
link to it, not a copy. Each snapshot looks complete, but together they take
about the size of `uploads/` once, plus each day's new files, plus a few MB of
database dump each. Hard links need a disk formatted ext4 or NTFS (not FAT32
or exFAT). If they don't work where the backups are, every snapshot is a full
copy and the log says so.

**Where:** `./backups` next to `docker-compose.yml`. That's on the same disk
as the logbook, so it protects against mistakes (a deleted sample, a bad
update) but not against the disk failing. To use another disk, e.g. an
external drive, put its path in `.env` and restart:

```bash
BACKUP_DIR=/mnt/backupdrive/logbook
```

The folder must exist and stay mounted. A drive that's sometimes unplugged
gets the snapshots written to the empty mount point instead.

**Checking it works:**

```bash
docker compose logs backup               # "Snapshot 2026-11-06 done …", or the error
ls backups/                              # one folder per day
docker compose exec backup python3 /backup.py --now   # make one now
```

**Restoring from a snapshot:** as in [Restoring](#restoring), but load the
dump with `pg_restore`, and copy the snapshot's `uploads/` back:

```bash
docker compose down -v
docker compose up -d db
docker compose exec -T db pg_restore -U logbook -d logbook --no-owner < backups/2026-11-06/logbook.dump
cp -a backups/2026-11-06/uploads/. uploads/
docker compose up -d
```

To get back a single file, copy it out of a snapshot's `uploads/`. Files
deleted in the last 30 days are also in `uploads/.trash/` (see
[Photos and files](#photos-and-files)).

### Backing up by hand

From the project folder, with the logbook running:

```bash
docker compose exec -T db pg_dump -U logbook logbook > backup_$(date +%Y%m%d).sql
```

Keep that file together with a copy of `uploads/` (and `.env`, somewhere
safe: it holds passwords). The automatic backups above do this daily; by hand is for an extra copy, e.g. before
updating the code.

**Check the backup before relying on it.** The output goes straight into the
file, so a failure shows nothing on screen and leaves an empty or tiny file:

```bash
ls -lh backup_*.sql       # should be well above 0 bytes
head -n 3 backup_*.sql    # starts with "-- PostgreSQL database dump"
tail -n 2 backup_*.sql    # ends with "-- PostgreSQL database dump complete"
```

If Docker needs `sudo`, run `sudo -v` first and give the password before the
dump command; otherwise the password prompt can sit unnoticed while the
command seems to hang. To see errors, run the dump without the redirect, piped
to `head -n 20`.

### Restoring

The dump has to go into an empty database, before the app starts and creates
its own empty tables (the app would otherwise create them and the dump
would clash):

```bash
docker compose down -v                                        # wipes the current database
docker compose up -d db                                       # database only
docker compose exec -T db psql -U logbook logbook < backup_20261021.sql
docker compose up -d                                          # start the app
```

Put the matching `uploads/` folder back in place too.

### Moving to another machine

1. On the old machine, make a backup (above) and copy the `.sql` file,
   `uploads/` and `.env` to the new machine.
2. On the new machine, get the code **at the same commit** as the old one:
   a dump fits the code that wrote it; a newer version brings migrations that
   upgrade it on first start (see [Schema changes](#schema-changes-migrations)).
3. Put `uploads/` and `.env` in the project folder. Keep the same
   `SECRET_KEY`; change `BASE_URL` to the new address so emailed links work.
4. If the new machine isn't WSL2 with mirrored networking, apply the changes in
   [Running on other environments](#running-on-other-environments).
5. Restore the dump: `docker compose up -d db`, then the `psql` line above,
   then `docker compose up -d`.
6. Open the logbook and check a few samples and their files.

If the app was started before the restore (so the dump collides with existing
tables), run `docker compose down -v` on the new machine and repeat step 5.

Without Docker, use `pg_dump -U logbook logbook > backup.sql` and
`psql -U logbook logbook < backup.sql` against the local PostgreSQL, again
into an empty database.
