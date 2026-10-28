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
Project           (collaboration: name, partner institution, code used in its samples' IDs, contact)
Sample            (generated ID, type, optional label and tags)
 ├── ProcessStep  (can repeat types, e.g. two annealings)
 │    └── Attachment (uploaded files)
 └── Analysis     (XRD, RBS, SEM, …)
      └── Attachment (data files, images)
```

### Sample IDs

Every sample gets an ID when it's created: the researcher's initials, the
year, and that researcher's counter for the year, e.g. `ASS-2026-001`. Pieces
cut from it add `-A`, `-B`, … (pieces of pieces `-1`, `-2`, …), and a
reference piece adds `-REF`. IDs don't change when the sample changes
owner or the researcher's initials change later. Only an admin can change one,
for a sample created under the wrong owner or type (see below). The optional
**Label** is for your own description and doesn't need to be unique.

**Changing an ID (admins).** On the sample's *Edit* page, *Change the sample
ID* gives it the next free number under a researcher's initials or a project's
code (or an ID you type). Its pieces are renamed with it (`ASS-2026-005-A`
becomes `UMIN-2026-001-A`), the folders in `uploads/` are renamed and the
stored file names updated, and the owner gets an email listing the old and new
IDs. The old ID is kept on the sample (shown as *Previously*, searchable, and
in the exports) and is never given to another sample, so an old ID can't end up
meaning two things. A piece's ID can't be changed on its own; change the
sample it was cut from. Samples are not renumbered in the emails, links or
notes people kept: the owner's email is how they find out.

Collaboration samples use their project's code instead of initials, with
the project's own counter, e.g. `UMIN1-2026-001`, whoever receives them.

Everyone sets their display name and initials (2–4 letters, unique) on first
login; they're asked again until they do. Once someone has samples, only an
admin can change their initials (Configurations → Users).

### Sample types

- **Thin film:** a substrate from the library, dimensions, and optionally the
  film material (a sample is just its substrate until it's deposited).
- **Bulk:** a piece of a library substrate, e.g. a 5×5 mm piece of a wafer.
  **External ID** holds the identifier given by whoever cut it.
- **Commercial:** a description, supplier, product/batch number, and the
  spec sheet (PDF or photo), which is required.
- **Collaboration:** any sample sent by another university or centre, thin
  film or not. Choose its project from the Projects tab and describe the
  sample (both required); optionally add their own ID for it. Its owner is
  the researcher who receives it.

### Substrate library

The **Substrates** tab lists the substrates samples are made from, with
thickness, orientation, polishing, size, supplier, batch number, notes and spec files
(PDF or photos). Anyone can add one; whoever added it and admins can edit
it. A substrate used by any sample can't be deleted.

### Projects

The **Projects** tab lists collaboration projects with universities and
centres that send us samples: name, partner institution, code, country,
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

### Photos and files

Each step and analysis card on a sample's page has **📷 Add photos** (opens
the camera or gallery on a phone; pick several at once) and **📎 Attach
files**. Uploads start as soon as files are chosen, and you can also drag
files onto a card (images count as photos). The step and analysis forms take
photos and files too.

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
```

Only characters Windows can't store in a name (`<>:"|?*`) are replaced by
`_`. Folders are fixed when the file is uploaded: changing an entry's type
or date later doesn't move its files. A file shared by several samples (a
run) is stored once, in the folder of the sample it was uploaded on. The
database still links every file to its entry, so keep `uploads/` and the
database together (see Backups).

Each sample folder also has a `sample.json`: a copy of everything the
database holds about that sample (details, owner, sharing, substrate,
project, its own timeline with parameters, notes, who did what and when, and
the files of each entry). It is rewritten after every change and for all
samples when the app starts (or on demand:
`docker compose exec app python -m backend.sample_backup`), so it's always current. It's there so that, if
the database is lost, `uploads/` still says what every file is. A piece's
file doesn't repeat the entries it inherits: `cut_from` names the parent
and the Cut step, and they are in the parent's file. Users, entry types,
dropdown values and suggestions aren't in these files; the database dump is
still the real backup.

Mandatory: the substrate for thin-film and bulk samples, the description and
spec sheet for commercial ones, and the type of each step/analysis. `required` in
a type's schema is a hint shown on the form, not enforced.

The tables are created and kept up to date by migrations that run when the
app starts; see [Schema changes (migrations)](#schema-changes-migrations).
Never recreate the database to apply a model change.

### The `sample.json` file

`uploads/<sample ID>/sample.json` is plain JSON, written with UTF-8 and
indented, so it can be read without the app. Top level:

| Key | Meaning |
|---|---|
| `format` | Version of this layout (currently 3: adds `visibility`, `previous_codes`, per-entry `status`/`proposed_by` and `devices`; older files lack them). |
| `written_at` | When the file was last written. |
| `id`, `code`, `previous_codes` | Database id, the sample ID, and any IDs it had before an admin changed it. |
| `label`, `sample_type`, `is_reference`, `visibility`, `tags`, `description`, `film_material`, `substrate_dimensions`, `external_id`, `supplier`, `created_at` | The sample's own details. `sample_type` is `thin_film`, `bulk`, `commercial` or `collaboration`; `visibility` is `personal`, `team` or `public`. |
| `owner`, `requested_by` | `{username, name, initials}` or `null`. |
| `shared_with` | List of `{username, name, initials, can_edit}`. |
| `substrate`, `project` | The library substrate / collaboration project it refers to, copied in full (`null` if none). |
| `cut_from` | For a piece: `{sample, cut_step_id, cut_position}`: the parent's ID and where on its timeline the Cut step is. The piece inherits everything before that position; those entries are in the parent's file, not repeated here. |
| `files` | Files attached to the sample itself (e.g. a spec sheet). |
| `devices` | The devices made on the sample: list of `{label, notes}`. |
| `timeline` | The sample's own steps and analyses, in order. |

Each `timeline` entry has `id`, `kind` (`step` or `analysis`), `type` (the
technique, e.g. `Annealing`), `position`, `performed_at` (a date), `location`,
`performed_by` (`{username, name, initials}` for a user, `{name}` for someone
without an account, or `null`), `notes`, `run_id` (entries added to several
samples at once share it), `status` (`approved`, or `pending` for an entry a
teammate proposed that the owner hasn't approved), `proposed_by`, `created_at`,
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
them, then use **Process done: make devices** under *Devices* on the sample's
page: give the labels (D1, D2, …, or just how many) and the date. This puts
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

## Access and sharing

Every logged-in user sees every sample's summary: ID, label, type,
materials, substrate, tags, which techniques were used, and the researcher. Details (description,
parameters, notes, dates and files) are visible to:

- the sample's owner (the researcher who created it),
- admins,
- users the owner has shared the sample with,
- the **coordinators** of the owner's team, who have the owner's rights (see [Teams](#teams)),
- anyone the sample's **visibility** lets in.

**Visibility** is set per sample, when it is created and later under
*Sharing* (owner or admin): **Personal** (the default: only the people above),
**Team** (also everyone in the owner's team) or **Public** (everyone logged
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

Admins manage teams under *Configurations → Teams*. People normally belong to
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
Admins can download the whole database from the admin page. The CSV has one row per step/analysis, with a
`param:<key>` column per parameter.

### Steps and analyses: parameters

Each step or analysis type has its own fields, filled in on the form:

- **Numbers** have their own box and unit (pressures are in mTorr and can be typed as `1e-4`;
  a decimal comma works too). Durations like the deposition time take
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
- **Where** (CTN, INESC MN, or another institute) is on every step and
  analysis; it's a dropdown too. Every technique has an **Equipment**
  dropdown (Machine on Deposition) with its own list, and equipment belongs
  to a place: the dropdown only offers what's at the place chosen under
  Where (INESC MN has the Alcatel SCM 450, UHV1, UHV2 and SentiFet). A new
  piece of equipment typed on the form is filed under that place. New types
  added under Configurations get the Equipment field automatically.
  Equipment with no place set is offered everywhere.
- **Other parameters** takes anything else as `key: value` lines.

The step types are Deposition (machine: Alcatel SCM 450, UHV1, UHV2, SentiFet;
technique, target, atmosphere, base and working pressure, power, gas flow,
duration, station, the deposition rate and thickness when known, and a
calibration sample tick box with details), Annealing, Ion
Implantation, Lithography (optical or e-beam), Etching (dry or wet), Cut and
Other Process. The analysis types are XRD / HRXRD, XPS, SEM (the equipment,
e.g. Hitachi S-2500), TEM, RBS, AFM, Raman, Optical Microscopy (mode, e.g.
bright/dark field or DIC, magnifications and observations), Hall / 4-probe,
Ellipsometry
(angles of incidence, and a large box for the optical model), Profilometry
(step height, scan length, stylus force, scan speed, roughness) and Other
Analysis. On the sample page parameters are shown with their labels and
units, and the CSV has one `param:` column per parameter (modes as
`param:modes/Rocking curve/range`).

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
to the next sample's box. Empty boxes keep the common value. Deleting a copy only
removes it from that sample.

---

## Adding or changing a step / analysis type

Admins manage types under **Configurations**: add, edit (name, description,
schema) or delete (only when unused). Editing a schema never changes stored
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

1. **Back up first** (see [Backing up](#backing-up)), and keep a copy of `uploads/`.
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

### Backing up

From the project folder, with the logbook running:

```bash
docker compose exec -T db pg_dump -U logbook logbook > backup_$(date +%Y%m%d).sql
```

Keep that file together with a copy of `uploads/` (and `.env`, somewhere
safe: it holds passwords). Do this regularly, e.g. weekly, and before
updating the code.

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
