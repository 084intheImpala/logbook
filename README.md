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

### Substrate library

The **Substrates** tab lists the substrates samples are made from, with
thickness, orientation, polishing, size, supplier, notes and spec files
(PDF or photos). Anyone can add one; whoever added it and admins can edit
it. A substrate used by any sample can't be deleted.

### Timeline

Steps and analyses share one timeline per sample, ordered by an explicit
`position`. Dates are optional: a new dated entry is slotted in
chronologically, an undated one is appended. On the sample page, the ↑/↓
arrows reorder entries and **Sort by date** reorders the dated ones.

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

Mandatory: the substrate for thin-film and bulk samples, the description and
spec sheet for commercial ones, and the type of each step/analysis. `required` in
a type's schema is a hint shown on the form, not enforced.

The tables are created on first start from `backend/models.py`. There are no
migrations: after changing a model, recreate the database
(`docker compose down -v`, then `docker compose up -d`), which deletes all
data. Add migrations (e.g. Alembic) before the logbook holds real data.

## Cutting a sample into pieces

**✂ Cut into pieces** on a sample's page records a "Cut" step on its
timeline and creates one new sample per piece. A tick box adds an extra
reference piece (`<ID>-REF`, marked **Reference**). Each piece:

- **inherits** the parent's timeline up to the Cut step. Inherited entries
  show greyed out with "from <parent>" and can only be edited on the parent.
  Nothing is copied, so fixing a parent entry fixes it for every piece.
  Pieces of pieces inherit through the whole chain.
- gets the parent's ID plus a suffix (see Sample IDs) and an optional label.
- copies the parent's type, substrate, film, tags and shares (whoever cuts
  someone else's sample also gets edit access to the pieces).
- belongs to the researcher picked for it on the cut form, by default the
  parent's owner. A piece given to someone else is assigned as described in
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
parameter names, polishing. Dark
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

### Process step types (seeded)
- Deposition, Annealing, Ion Implantation, Lithography, Etching, Other

### Analysis types (seeded)
- XRD, XPS, SEM, TEM, RBS, AFM, Raman, Hall/4-probe, Ellipsometry, SIMS, Other

Add or edit types at **Configurations** in the sidebar (admins only).

---

## Adding a new step / analysis type

Admins manage types under **Configurations** in the sidebar: add, edit
(name, description, schema) or delete (only when unused). Editing a schema
never changes stored data: removed keys stay on existing entries, and new
keys show up empty the next time an entry is edited. Each type has a
`parameter_schema` — a JSON list of field descriptors:

```json
[
  {"key": "temperature", "label": "Temperature", "type": "number", "unit": "°C", "required": true},
  {"key": "atmosphere",  "label": "Atmosphere",  "type": "text",   "unit": "",   "placeholder": "e.g. Ar"}
]
```

Fields: `key` (internal), `label` (display), `type` (`number` | `text`),
`unit`, `required`, `placeholder`.

---

## LAN access

The app binds to `0.0.0.0:8000`.  
Everyone on the same network reaches it at `http://<server-ip>:8000`.

To find the server IP on Windows: `ipconfig` → IPv4 Address.
On Linux: `ip a` or `hostname -I`.

---

## Backups

```bash
# Dump the database
pg_dump -U logbook logbook > backup_$(date +%Y%m%d).sql

# Restore
psql -U logbook logbook < backup_20240101.sql
```

Uploaded files live in `uploads/` — back that folder up too.
