"""A CLAUDE.md for preparing an import: the fixed instructions in import_guide.md (the format,
how to lay out the zip, what to ask) followed by this logbook's names, so an AI assistant writes
types, parameter keys and substrates exactly as the import expects them. The names are
those the import itself looks up (sample_import.Lookups), as the downloading user sees them.
Downloaded from the Import page (GET /samples/import/CLAUDE.md).
"""
from datetime import datetime
from pathlib import Path

from sqlalchemy.ext.asyncio import AsyncSession

from backend.lineage import SPECIAL_STEP_TYPES
from backend.models import User
from backend.sample_import import Lookups, team_prefix

TEXT = Path(__file__).with_name("import_guide.md")


def _field(f: dict, depth: int = 0) -> list[str]:
    """One parameter as a Markdown list item: key, label, kind, unit/list/default, and nested fields."""
    kind = f.get("type", "text")
    bits = [kind]
    if f.get("unit"):
        bits.append(f"in {f['unit']}")
    if kind in ("choice", "modes"):
        bits.append(f"values from the list `{f.get('list') or f['key']}`, new ones allowed")
    if f.get("default") not in (None, ""):
        bits.append(f"usually {f['default']}")
    lines = [f"{'  ' * depth}- `{f['key']}`: {f.get('label', f['key'])} ({', '.join(bits)})"]
    if kind == "variant":
        for option in f.get("options", []):
            lines.append(f"{'  ' * (depth + 1)}- `\"{f['key']}\": \"{option['value']}\"`, with:")
            for sub in option.get("fields", []):
                lines += _field(sub, depth + 2)
    elif kind == "check" and f.get("fields"):
        lines.append(f"{'  ' * (depth + 1)}- when true, also:")
        for sub in f["fields"]:
            lines += _field(sub, depth + 2)
    elif kind == "modes" and f.get("fields"):
        lines.append(f"{'  ' * (depth + 1)}- each mode: `{{\"<mode>\": {{…}}}}` with:")
        for sub in f["fields"]:
            lines += _field(sub, depth + 2)
    return lines


def _types(title: str, types: dict, skip=()) -> list[str]:
    out = [f"### {title}", ""]
    for t in sorted(types.values(), key=lambda t: t.name.lower()):
        if t.name in skip:
            continue
        out.append(f"**{t.name}**" + (f": {t.description.strip()}" if t.description else ""))
        out.append("")
        schema = t.parameter_schema or []
        out += [line for f in schema for line in _field(f)] if schema else ["- (no parameters)"]
        out.append("")
    return out


async def guide(db: AsyncSession, user: User) -> str:
    look = await Lookups().load(db, user)
    out = ["", *_types("Step types (`\"kind\": \"step\"`)", look.step_types, skip=SPECIAL_STEP_TYPES),
           *_types("Analysis types (`\"kind\": \"analysis\"`)", look.analysis_types)]

    out += ["### Substrates (`substrate`)", ""]
    for s in sorted(look.substrates, key=lambda s: s.name.lower()):
        details = ", ".join(x for x in (s.material, s.orientation, s.size, s.supplier) if x)
        out.append(f"- `{s.name}`" + (f" ({details})" if details else ""))
    out += ["" if look.substrates else "- (none yet)", ""]

    teams = [t for t in look.teams if team_prefix(t)]
    out += ["### Teams (`team`)", ""]
    out += [f"- `{t.name}` (IDs start `{team_prefix(t)}-`)" for t in sorted(teams, key=lambda t: t.name.lower())]
    out += ["" if teams else "- (none can own samples)", ""]

    out += ["### Projects (`project`, for `\"sample_type\": \"project\"`)", ""]
    out += [f"- `{p.code}`: {p.name}" for p in sorted(look.projects, key=lambda p: p.code or "")]
    out += ["" if look.projects else "- (none)", ""]

    out += ["### Procedures you can see (`procedure`)", ""]
    out += [f"- `{p.title}`" for p in sorted(look.procedures, key=lambda p: p.title.lower())]
    out += ["" if look.procedures else "- (none)", ""]

    out += ["### Studies you co-own (`studies`)", ""]
    out += [f"- `{s.title}`" for s in look.studies]
    out += ["" if look.studies else "- (none)", ""]

    generated = datetime.now().strftime("%Y-%m-%d")
    return TEXT.read_text(encoding="utf-8").replace("{generated}", generated) + "\n".join(out)
