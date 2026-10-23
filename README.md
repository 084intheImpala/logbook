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

> **Note:** `docker-compose.yml` uses normal port publishing, so it works with
> Rancher Desktop (dockerd engine), Docker Desktop and Docker Engine on Linux.
> See [Running on Windows](#running-on-windows-rancher-desktop).

---

## Running on Windows (Rancher Desktop)

1. Install [Rancher Desktop](https://rancherdesktop.io/) (free, no account).
   Under *Preferences → Container Engine*, choose **dockerd (moby)** so the
   `docker` and `docker compose` commands work.
2. Allow the app through the Windows firewall (admin PowerShell), so other
   PCs on the LAN can reach it:

   ```powershell
   New-NetFirewallRule -DisplayName "Logbook 8000" -Direction Inbound -Protocol TCP -LocalPort 8000 -Action Allow
   ```

3. In the project folder: `docker compose up -d`, then create the admin user
   (see Quick start).
4. Set `BASE_URL` in `.env` to the address users will open (e.g.
   `http://<pc-ip>:8000`), so emailed login links point to the right place.

Notes:

- Postgres is published on `127.0.0.1:5432` only (handy for `pg_dump` from the
  host); it is not reachable from the LAN.
- To start the logbook automatically after a reboot, enable *Preferences →
  Application → Behavior → Automatically start at login* in Rancher Desktop.
  The containers use `restart: unless-stopped`.
- If you previously used the old WSL2 host-networking setup, the
  `.wslconfig` settings (`mirrored`, `hostAddressLoopback`) are no longer
  needed.

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
reference piece adds `-REF`. IDs never change, even if the sample changes
owner or the researcher's initials change later. The optional **Label** is
for your own description and doesn't need to be unique.

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
thickness, orientation, polishing, size, supplier, notes and spec files
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

Mandatory: the substrate for thin-film and bulk samples, the description and
spec sheet for commercial ones, and the type of each step/analysis. `required` in
a type's schema is a hint shown on the form, not enforced.

The tables are created on first start from `backend/models.py`. There are no
migrations: after changing a model, recreate the database
(`docker compose down -v`, then `docker compose up -d`), which deletes all
data. Add migrations (e.g. Alembic) before the logbook holds real data.

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
parameters, notes, dates and files) are visible only to:

- the sample's owner (the researcher who created it),
- admins,
- users the owner has shared the sample with.

Owners share from the **Sharing** panel on a sample's page, or select
several samples on the **Search** page and share them at once. Each share
is **View** (read details and download files) or **Edit** (also add and
change steps, analyses and files). Only the owner or an admin can delete a
sample or change who it's shared with. Samples without an owner are open to
everyone; admins can assign an owner from the sample's Edit form.

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
each copy keeps its own place in its sample's timeline. Deleting a copy only
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
its own empty tables:

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
   there are no migrations, so a dump only fits the version that wrote it.
3. Put `uploads/` and `.env` in the project folder. Keep the same
   `SECRET_KEY`; change `BASE_URL` to the new address so emailed links work.
4. On Windows, set up Rancher Desktop first
   ([Running on Windows](#running-on-windows-rancher-desktop)).
5. Restore the dump: `docker compose up -d db`, then the `psql` line above,
   then `docker compose up -d`.
6. Open the logbook and check a few samples and their files.

If the app was started before the restore (so the dump collides with existing
tables), run `docker compose down -v` on the new machine and repeat step 5.

Without Docker, use `pg_dump -U logbook logbook > backup.sql` and
`psql -U logbook logbook < backup.sql` against the local PostgreSQL, again
into an empty database.
