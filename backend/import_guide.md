# Preparing samples for the Logbook's Import

This file is for an AI assistant (Claude Code or similar). Put it in the folder holding the old sample records,
named `CLAUDE.md`, and ask the assistant to help turn them into files for the Logbook's **Samples → Import**.
Talk to the person in their own language (often Portuguese); this file is in English.

## What the Logbook is

A lab logbook for thin-film samples (a web app). Each sample has a generated ID (`<initials>-<year>-<n>`, e.g.
`AS-2019-004`), a type, a substrate, tags, files, and a **timeline**: process steps (Deposition, Annealing,
Implantation…) and analyses (XRD, RBS, SEM…), in order, each with a date, who did it, where, typed parameters,
notes and files. A **Cut** step splits a sample into pieces (`-A`, `-B`, `-REF`), which inherit the timeline up to
the cut and carry on with their own.

Import reads samples written up as JSON, checks everything and shows what would be created (IDs, owners,
entries, pieces, files) with errors and warnings. **Nothing is saved until the person clicks Import**, and an
upload with any error changes nothing, so it is safe to upload, read the messages, fix and upload again.

## Your job

1. Look at what the person has: notebooks typed up, spreadsheets, folders of photos and measurement files.
   Read before writing anything.
2. Ask about what you can't tell from the files, rather than guess: whose samples they are (`owner` or `team`),
   which year, which substrate, what an abbreviation means. **Never invent data**: leave out a date, a value or
   a person that isn't known, and say what is known in `notes` ("March 2019, day not recorded").
3. Write the JSON, usually with a small script (Python is fine) when there are many samples, so it can be rerun
   after a fix. Keep the person's original files untouched; build the output in a separate folder.
4. Check the JSON parses (`python -m json.tool file.json`) and that every path in `files` exists.
5. Zip it (see below) and tell the person to upload it at **Samples → Import → Check**, then to paste back any
   errors or warnings the page shows so you can fix them.

## Files and the zip

Upload one `.json` file, several, or a `.zip` holding `.json` files plus the photos and files they name. A good
layout is one folder per sample:

```
import.zip
├── ZnO-on-Si-2019/
│   ├── sample.json
│   ├── photos/overview.jpg
│   └── xrd/scan.xy
└── GaN-batch-3/
    ├── sample.json
    └── rbs/spectrum.dat
```

Paths in `files` are relative to the `.json` file that names them (`"photos/overview.jpg"` above). A zip may
unpack to at most 2 GB. For big data, make several smaller zips (one sample per zip if the server stops
answering); each upload is checked and imported on its own.

## The JSON

A `.json` file holds one sample (an object), a list of them, or `{"samples": [...]}`. **Unknown fields are
errors**, so a typo is never silently lost: use exactly the field names below.

```json
{
  "label": "ZnO on Si", "sample_type": "thin_film", "owner": "asousa", "year": 2019,
  "substrate": "Si (100)", "film_material": "ZnO", "substrate_dimensions": "10x10 mm",
  "tags": ["old"], "description": "From the 2019 notebook, p. 12",
  "visibility": "team", "files": ["photos/overview.jpg"], "studies": ["ZnO annealing"],
  "timeline": [
    {"kind": "step", "type": "Deposition", "performed_at": "2019-03-04", "performed_by": "asousa",
     "location": "CTN", "parameters": {"target": "ZnO", "thickness": 100, "duration": "12:30"},
     "notes": "first try", "files": ["photos/after-dep.jpg"], "ref": "zno"},
    {"kind": "analysis", "type": "XRD / HRXRD", "performed_at": "2019-03-10", "files": ["xrd/scan.xy"]},
    {"kind": "cut", "performed_at": "2019-04-01", "method": "Diamond saw", "pieces": [
      {"label": "contacts", "timeline": [
        {"kind": "step", "type": "Deposition", "on": "zno", "partial": true, "parameters": {"target": "Au"}}]},
      {"label": "spare", "owner": "bob"},
      {"is_reference": true}]}
  ]
}
```

### Sample fields

| Field | Meaning |
|---|---|
| `owner` | Username of the researcher it belongs to (initials or full name also work if no one else has them). Someone else's sample waits for them to confirm it after the import. |
| `team` | Instead of `owner`, when nobody is known: the sample belongs to the team and its ID starts with the team's name. Only the team's members (and admins) can import a team's samples. With neither, the sample belongs to whoever uploads it. |
| `year` | The year in its ID. If left out: the year of its first dated entry, else this year. Samples are numbered in date order. |
| `sample_type` | `thin_film` (default), `bulk` or `project`. |
| `substrate` | A thin film or bulk sample's substrate, by its exact name in the Substrates library (listed below). If one is missing, the person adds it in the Logbook first. |
| `project` | A project sample's project, by code or name; a project sample also needs a `description`. |
| `label`, `film_material`, `substrate_dimensions`, `external_id`, `description`, `tags` (a list), `is_reference` (true/false) | As on the sample form. |
| `visibility` | `personal`, `team` (default) or `public`. |
| `files` | Files attached to the sample itself. |
| `studies` | Titles of studies to add the sample to; only studies the uploader co-owns (listed below). |
| `timeline` | Its steps, analyses and cuts, oldest first. |

### Timeline entries

| Field | Meaning |
|---|---|
| `kind` | `step`, `analysis` or `cut`. |
| `type` | The step or analysis type, exactly as named in the list below. `Devices made` can't be imported. |
| `performed_at` | `YYYY-MM-DD`; leave it out if the day isn't known. |
| `performed_by` | A username, or any name for someone without an account. |
| `location`, `notes` | Free text. |
| `parameters` | The type's parameters **by key** (the keys listed below, not the labels). Numbers may use a decimal comma; durations as minutes or `min:ss`; tick boxes as `true`; "modes" as `{"mode": {"sub-key": value}}`; a "variant" as its chosen value under its key with the option's own keys beside it. Keys the type doesn't have are kept as extra parameters, with a warning. New dropdown values are added to their lists. |
| `procedure` | The title of the procedure followed (optional). |
| `files` | Files for the entry (spectra, photos, reports). |
| `ref`, `on`, `partial` | Depositions only. `ref` names a deposition so that a later one (on this sample or on a piece cut after it) can sit on it with `"on": "<ref>"`; `"on": "substrate"` puts it on the bare substrate; `"partial": true` means it covers only part (contacts, a mask). This builds the film-stack drawing. |
| `pieces` | Cuts only; a cut also takes `method`, `performed_at`, `performed_by`, `location`, `notes`, `files`. One object per piece: `label`, `substrate_dimensions`, `description`, `tags`, `files`, `studies`, `is_reference` (at most one per cut), `owner` or `team` (default: the parent's), and its own `timeline` after the cut, which can hold further cuts. |

### Tips

- Put entries in the order they happened; undated ones go where they belong in that order.
- One measurement = one analysis entry, with its data files; several runs on the same day are separate entries.
- If a parameter really isn't on the type's list, it's fine as an extra key (it gives a warning, not an error),
  but first check whether one of the listed keys means the same thing.
- What doesn't fit anywhere goes in the sample's `description` or the entry's `notes`.
- Pieces don't repeat the parent's entries from before the cut; they inherit them.
- The page shows errors (nothing imported until fixed) and warnings (worth a look); fix and upload again.

## This logbook's names

Generated by the Logbook for the person who downloaded this file, on {generated}. Types, parameters and lists
change: download a fresh copy from the Import page if this one is old.
