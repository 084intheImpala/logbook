"""Types added in Admin (schemas in admin_types.json: Transmittance, PIXE, Photoconductivity,
Spectral response, Lift-off): valid, and their labels and placeholders are in Portuguese."""
import json
from pathlib import Path

from backend.i18n import translate
from backend.params import validate_schema

TYPES = json.loads((Path(__file__).parent / "admin_types.json").read_text(encoding="utf-8"))


def _fields(schema):
    for f in schema:
        yield f
        yield from _fields(f.get("fields") or [])
        for option in f.get("options") or []:
            yield from _fields(option.get("fields") or [])


def test_the_schemas_are_valid():
    for name, schema in TYPES.items():
        assert validate_schema(schema) is None, name


def test_every_label_and_placeholder_is_translated():
    missing = [text for schema in TYPES.values() for f in _fields(schema)
               for text in (f["label"], f.get("placeholder")) if text and translate("pt", text) == text]
    assert not missing
