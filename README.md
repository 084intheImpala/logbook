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
Sample
 ├── ProcessStep  (ordered 0, 1, 2, …; can repeat types, e.g. two annealings)
 │    └── Attachment (uploaded files)
 └── Analysis     (XRD, RBS, SEM, …)
      └── Attachment (data files, images)
```

### Process step types (seeded)
- Deposition, Annealing, Ion Implantation, Lithography, Etching, Other

### Analysis types (seeded)
- XRD, XPS, SEM, TEM, RBS, AFM, Raman, Hall/4-probe, Ellipsometry, SIMS, Other

Add new types at **Step & Analysis Types** in the sidebar.

---

## Adding a new step / analysis type

Go to the **Step & Analysis Types** page in the sidebar. Each type has a
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
