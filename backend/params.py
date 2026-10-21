"""Free-form `key: value` parameters attached to process steps and analyses.

Stored parameters are never rewritten when a type's schema changes: keys the
schema no longer lists are kept, and keys it newly lists show up empty the
next time the entry is edited.
"""
import json
import math
from datetime import datetime


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


def params_to_text(params: dict | None, schema: list[dict] | None = None) -> str:
    """Existing parameters first, then any schema keys they lack, left empty."""
    params = dict(params or {})
    for field in schema or []:
        params.setdefault(field["key"], "")
    return "\n".join(f"{k}: {v}" for k, v in params.items())


def type_schemas_json(types) -> str:
    """JSON map of type id → list of {key, label, unit, required} for the form JS."""
    return json.dumps({
        str(t.id): [{"key": f["key"], "label": f.get("label", f["key"]),
                     "unit": f.get("unit", ""), "required": bool(f.get("required"))}
                    for f in (t.parameter_schema or [])]
        for t in types
    })


def parse_datetime(value: str):
    return datetime.strptime(value, "%Y-%m-%dT%H:%M") if value else None
