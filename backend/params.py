"""Parameters of process steps and analyses, described by their type's schema.

A schema is a JSON list of fields. Every field has a `key` and a `label`;
its `type` decides how it's entered and stored:

- "number": an input box, with an optional `unit`. Stored as a number.
- "duration": typed as min:s ("12:30"), h:min:s or plain minutes ("12");
  stored as "min:ss" text, e.g. "12:30".
- "text": a one-line text box (`placeholder` optional).
- "longtext": a big text box, for things like an optical model.
- "choice": a dropdown from the shared list named `list` (default: the key).
  Typing a new value adds it to the list for everyone. With "located": true
  (equipment), each value belongs to a place: the form only offers what's at
  the place chosen under Where, and a new value is filed under that place.
- "variant": pick one of `options` ([{"value": ..., "fields": [...]}]); each
  option has its own fields, e.g. Annealing → Furnace or RTA. The choice and
  the chosen option's fields are stored side by side.
- "check": a tick box, stored as true when ticked; its `fields` are shown
  (and stored side by side) only when it's ticked, e.g. Calibration sample →
  details.
- "modes": tick one or more values from the shared list `list` (new ones can
  be added); each ticked mode gets the sub-fields in `fields`. Stored as
  {mode: {sub-key: value}}, e.g. XRD → rocking curve, 2θ/ω.

Stored parameters are never rewritten when a schema changes: keys the schema
no longer has stay on old entries and are shown as they are. Keys outside the
schema can also be typed as `key: value` lines (the "extra parameters").
"""
import json
import math
import re
from datetime import date, datetime

FIELD_TYPES = ("number", "duration", "text", "longtext", "choice", "variant", "check", "modes")
SEP = "::"   # form field names: p::<key>, and p::<key>::<mode>::<sub-key> for modes


# ── Free "key: value" lines ──────────────────────────────────────────────────

def parse_params(text: str) -> dict:
    """Parse 'key: value' lines into a dict. Empty values are kept as ''."""
    params = {}
    for line in text.strip().splitlines():
        if ":" not in line:
            continue
        k, _, v = line.partition(":")
        k, v = k.strip(), v.strip()
        if k:
            params[k] = _coerce(v)
    return params


def _coerce(v: str):
    for cast in (int, float):
        try:
            n = cast(v)
        except ValueError:
            continue
        return n if math.isfinite(n) else v
    return v


def params_to_text(params: dict) -> str:
    return "\n".join(f"{k}: {v}" for k, v in params.items())


# ── Schemas ──────────────────────────────────────────────────────────────────

def option_list(field: dict) -> str:
    """The shared list a choice or modes field draws from."""
    return field.get("list") or field["key"]


def _side_fields(field: dict) -> list[list[dict]]:
    """Sub-field lists stored side by side with `field`: a variant's options'
    fields and a check's fields (not modes', which are nested per mode)."""
    if field.get("type") == "variant":
        return [o.get("fields") or [] for o in field.get("options", [])]
    if field.get("type") == "check":
        return [field.get("fields") or []]
    return []


def schema_keys(schema: list[dict] | None) -> set[str]:
    """Every top-level parameter key a schema can store (variant and check fields included)."""
    keys = set()
    for f in schema or []:
        keys.add(f["key"])
        for fields in _side_fields(f):
            keys |= schema_keys(fields)
    return keys


def located_lists(schema: list[dict] | None) -> set[str]:
    """Lists whose values belong to a place (choice fields with "located": true)."""
    names = set()
    for f in schema or []:
        if f.get("type") == "choice" and f.get("located"):
            names.add(option_list(f))
        for fields in _side_fields(f):
            names |= located_lists(fields)
    return names


def equipment_field(type_name: str) -> dict:
    """The Equipment dropdown every technique starts with: its own list
    (e.g. "ellipsometry_equipment"), filtered by the place under Where."""
    slug = re.sub(r"[^a-z0-9]+", "_", type_name.lower()).strip("_") or "other"
    return {"key": "equipment", "label": "Equipment", "type": "choice", "list": f"{slug}_equipment", "located": True}


def with_equipment(schema: list[dict], type_name: str) -> list[dict]:
    """`schema` with an Equipment field first, unless it already has
    equipment (a "located" dropdown, e.g. Deposition's Machine)."""
    return schema if located_lists(schema) else [equipment_field(type_name)] + schema


def validate_schema(schema, path="") -> str | None:
    """Why `schema` isn't a valid list of fields (in English), or None."""
    if not isinstance(schema, list) or not all(isinstance(f, dict) for f in schema):
        return f"{path or 'The schema'} must be a JSON list of objects."
    keys = [str(f.get("key", "")).strip() for f in schema]
    if not all(keys):
        return f'Every field{" in " + path if path else ""} needs a "key".'
    if len(set(keys)) != len(keys):
        return f'Keys must be unique{" in " + path if path else ""}.'
    for f, k in zip(schema, keys):
        if ":" in k:
            return f'Keys cannot contain ":" ({k}).'
        f["key"] = k
        kind = f.get("type", "text")
        if kind not in FIELD_TYPES:
            return f'{k}: unknown type "{kind}" (use {", ".join(FIELD_TYPES)}).'
        if kind == "variant":
            options = f.get("options")
            if not isinstance(options, list) or not options or not all(
                    isinstance(o, dict) and str(o.get("value", "")).strip() for o in options):
                return f'{k}: a variant needs "options": [{{"value": "...", "fields": [...]}}, ...].'
            for o in options:
                error = validate_schema(o.setdefault("fields", []), f"{k} → {o['value']}")
                if error:
                    return error
        if kind in ("modes", "check"):
            error = validate_schema(f.setdefault("fields", []), k)
            if error:
                return error
    return None


# ── Reading a submitted form ─────────────────────────────────────────────────

def normalize_duration(raw: str) -> str:
    """'12:30' (min:s), '1:02:30' (h:min:s) or plain minutes ('12', '1.5')
    as 'min:ss'; anything else is kept as typed."""
    parts = raw.replace(",", ".").split(":")
    try:
        if len(parts) == 1:
            seconds = round(float(parts[0]) * 60)
        elif len(parts) == 2:
            seconds = int(parts[0] or 0) * 60 + round(float(parts[1]))
        elif len(parts) == 3:
            seconds = int(parts[0] or 0) * 3600 + int(parts[1]) * 60 + round(float(parts[2]))
        else:
            return raw
    except ValueError:
        return raw
    return f"{seconds // 60}:{seconds % 60:02d}" if seconds >= 0 else raw


def _value(field: dict, raw: str):
    raw = (raw or "").strip()
    if not raw:
        return None
    if field.get("type") == "duration":
        return normalize_duration(raw)
    if field.get("type") == "number":
        coerced = _coerce(raw.replace(",", "."))   # decimal comma allowed
        return coerced if isinstance(coerced, (int, float)) else raw  # keep what was typed rather than lose it
    return raw


def parse_form(form, schema: list[dict] | None, prefix="p") -> tuple[dict, list[tuple[str, str]]]:
    """Parameters from a submitted entry form, and the (list, value) pairs of
    any dropdown values that may be new. Empty fields are left out."""
    params, picked = {}, []
    for f in schema or []:
        key, kind, name = f["key"], f.get("type", "text"), f"{prefix}{SEP}{f['key']}"
        if kind == "modes":
            modes = {}
            for mode in dict.fromkeys(m.strip() for m in form.getlist(name) if m.strip()):
                sub, sub_picked = parse_form(form, f.get("fields"), f"{name}{SEP}{mode}")
                modes[mode] = sub
                picked += [(option_list(f), mode)] + sub_picked
            if modes:
                params[key] = modes
            continue
        if kind == "check":
            if form.get(name):
                params[key] = True
                sub, sub_picked = parse_form(form, f.get("fields"), prefix)
                params |= sub
                picked += sub_picked
            continue
        value = _value(f, form.get(name, ""))
        if value is None:
            continue
        params[key] = value
        if kind == "choice":
            picked.append((option_list(f), value))
        if kind == "variant":
            option = next((o for o in f.get("options", []) if o["value"] == value), None)
            if option:
                sub, sub_picked = parse_form(form, option.get("fields"), prefix)
                params |= sub
                picked += sub_picked
    return params, picked


# ── Showing stored parameters ────────────────────────────────────────────────

def format_value(value, unit: str = "") -> str:
    if value is True:
        return "✓"
    if isinstance(value, float):
        value = f"{value:g}"
    return f"{value} {unit}".strip() if unit and value != "" else str(value)


def describe(params: dict | None, schema: list[dict] | None) -> list[dict]:
    """Rows for display, in schema order: {label, value, long} for plain
    values, {label, rows} for each mode. Keys the schema doesn't know (e.g.
    from an older schema, or typed as extra parameters) come last, as is."""
    params = dict(params or {})
    rows = []

    def walk(fields, values):
        for f in fields or []:
            key, kind = f["key"], f.get("type", "text")
            if key not in values:
                continue
            value = values.pop(key)
            label = f.get("label") or key
            if kind == "modes" and isinstance(value, dict):
                for mode, sub in value.items():
                    sub = dict(sub or {})
                    sub_rows = []
                    for sf in f.get("fields") or []:
                        if sf["key"] in sub:
                            sub_rows.append({"label": sf.get("label") or sf["key"],
                                             "value": format_value(sub.pop(sf["key"]), sf.get("unit", "")),
                                             "long": sf.get("type") == "longtext"})
                    sub_rows += [{"label": k, "value": format_value(v), "long": False} for k, v in sub.items()]
                    rows.append({"label": mode, "group": label, "rows": sub_rows})
                continue
            rows.append({"label": label, "value": format_value(value, f.get("unit", "")),
                         "long": kind == "longtext"})
            if kind == "variant":
                option = next((o for o in f.get("options", []) if o["value"] == value), None)
                if option:
                    walk(option.get("fields"), values)
            if kind == "check" and value is True:
                walk(f.get("fields"), values)

    walk(schema, params)
    for key, value in params.items():
        if isinstance(value, dict):
            rows.append({"label": key, "group": "", "rows": [
                {"label": k, "value": format_value(v), "long": False} for k, v in flatten(value).items()]})
        else:
            rows.append({"label": key, "value": format_value(value), "long": False})
    return rows


def flatten(params: dict | None, prefix: str = "") -> dict:
    """Nested parameters (modes) as flat 'modes/Rocking curve/range' keys, for CSV and search."""
    flat = {}
    for k, v in (params or {}).items():
        name = f"{prefix}/{k}" if prefix else str(k)
        if isinstance(v, dict):
            flat |= flatten(v, name)
        else:
            flat[name] = v
    return flat


def extra_params(params: dict | None, schema: list[dict] | None) -> dict:
    """Stored parameters outside the schema, shown as editable 'key: value' lines."""
    known = schema_keys(schema)
    return {k: v for k, v in (params or {}).items() if k not in known and not isinstance(v, dict)}


def parse_date(value: str) -> date | None:
    """The date from a form's date field (entries record the day, not the time)."""
    return datetime.strptime(value[:10], "%Y-%m-%d").date() if value else None
