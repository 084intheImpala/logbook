"""The film stack of a thin-film sample, drawn on its page (inline SVG,
frontend/templates/_layers.html): the substrate, then one layer per Deposition
on its timeline (inherited ones included, so a piece shows its parent's films),
planned depositions drawn dashed.

A layer's material is the deposition's Target, else the sample's film material.
Its thickness is, in order: the average of its thickness measurements (see
deposition_rate.measurements: only a single film can be measured), the
Thickness typed on the step, the typed Deposition rate × Duration, or the
Target thickness. A CMP with a Thickness removed takes that much off the top
layers (planned ones are left out: they haven't happened).

Beside each layer are the process steps it went through after it was
deposited (annealing, implantation, …; not Cut or Devices made), so the bottom
film lists every anneal since and the top one only the last.

A deposition can go on top of a given layer (ProcessStep.on_step_id) or the
bare substrate (on_substrate) instead of on everything so far, and can cover
only part of it (partial: contacts through a mask). Across the drawing, a
layer spans what it's on (the whole width for everything or the substrate);
a partial one gets its own slice of that, side by side with the other partial
layers on the same thing, so some of the surface below stays clear. Each film
follows the surface it lands on (conformal), so the drawing is a profile: Ni
then Au on the Ni, Ti on the substrate then Au on the Ti make two pads."""
from dataclasses import dataclass, field

from backend.lineage import SPECIAL_STEP_TYPES
from backend.params import describe
from backend.deposition_rate import DEPOSITION_TYPE_NAME, RATE_KEY, RatePoint, _number, duration_seconds

CMP_TYPE_NAME = "CMP"
SLOTS = 8   # material colours (--series-1 … --series-8, as in _rate_plot.html)

# Geometry of the drawing, in SVG units
WIDTH = 640
STACK_X, STACK_W = 8, 180
LABEL_X = STACK_X + STACK_W + 40
TOP = 8
FILMS_H = 160        # the films together, when their thicknesses are known
MIN_H = 6            # a very thin film is still drawn this high
UNKNOWN_H = 24       # a film of unknown thickness
SUBSTRATE_H = 44     # not to scale
LINE_H = 14         # a line of label
LABEL_GAP = 6        # between two layers' labels
SUMMARY_VALUES = 3   # parameter values shown for a process beside a layer
PARTIAL_MARGIN = 0.15   # a partial layer leaves this share of its slice clear on each side


@dataclass
class Layer:
    material: str | None
    thickness: float | None          # nm, after any CMP
    source: str | None               # measured | entered | rate | target (None: unknown)
    step: object                     # the Deposition step
    sample: object                   # the sample it is recorded on
    planned: bool = False
    removed: float = 0               # nm taken off by CMP
    n: int = 0                       # measurements averaged
    processes: list = field(default_factory=list)   # steps since: {step, name, summary, planned}
    slot: int = 0                    # colour, by material
    on: "Layer | None" = None        # the layer it was deposited on (None: everything, or the substrate)
    on_substrate: bool = False
    partial: bool = False            # covers only part of what it's on
    span: tuple = (0.0, 1.0)         # across the drawing, as fractions of its width
    geometry: dict = field(default_factory=dict)


def _thickness(step, point: RatePoint | None) -> tuple[float | None, str | None, int]:
    found = [m.thickness for m in point.found] if point else []
    if found:
        return float(f"{sum(found) / len(found):.4g}"), "measured", len(found)
    params = step.parameters or {}
    if (typed := _number(params.get("thickness"))) is not None:
        return typed, "entered", 0
    rate, seconds = _number(params.get(RATE_KEY)), duration_seconds(params.get("duration"))
    if rate and seconds:
        return float(f"{rate * seconds / 60:.4g}"), "rate", 0
    if (target := _number(params.get("target_thickness"))) is not None:
        return target, "target", 0
    return None, None, 0


def summary(step) -> str:
    """The first few parameter values, e.g. "Furnace · 1000 °C · 60 min"."""
    rows = describe(step.parameters, step.step_type.parameter_schema)
    values = [r["value"] for r in rows if "value" in r and not r["long"] and r["value"]]
    return " · ".join(values[:SUMMARY_VALUES])


def _remove(layers: list[Layer], amount: float):
    """Take `amount` nm off the top of the done (not planned) layers."""
    for layer in reversed([l for l in layers if not l.planned]):
        if amount <= 0:
            return
        if layer.thickness is None or layer.thickness > amount:
            layer.removed += amount
            if layer.thickness is not None:
                layer.thickness = float(f"{layer.thickness - amount:.4g}")
            return
        amount -= layer.thickness
        layers.remove(layer)


def stack(sample, items, points: dict[int, RatePoint] | None = None) -> list[Layer]:
    """The layers, bottom first, from `items` (the sample's timeline, planned
    entries included, only those the user may see) and `points`
    (deposition_rate.rate_points, for the measured thicknesses)."""
    points = points or {}
    layers: list[Layer] = []
    for item in items:
        if item.kind != "process":
            continue
        step, params = item.entry, item.entry.parameters or {}
        if item.technique == DEPOSITION_TYPE_NAME:
            thickness, source, n = _thickness(step, points.get(step.id))
            material = str(params.get("target") or "").strip() or sample.film_material
            on_id = getattr(step, "on_step_id", None)
            on = next((l for l in layers if l.step.id == on_id), None) if on_id else None
            layers.append(Layer(material, thickness, source, step, item.source, step.planned, n=n, on=on,
                                on_substrate=on is None and bool(getattr(step, "on_substrate", False)),
                                partial=bool(getattr(step, "partial", False))))
            continue
        if item.technique in SPECIAL_STEP_TYPES:
            continue
        process = {"step": step, "name": item.technique, "summary": summary(step), "planned": step.planned}
        for layer in layers:
            layer.processes.append(process)
        if item.technique == CMP_TYPE_NAME and not step.planned:
            if (amount := _number(params.get("thickness_removed"))) is not None:
                _remove(layers, amount)
    slots: dict[str, int] = {}
    for layer in layers:
        key = (layer.material or "").lower()
        layer.slot = slots.setdefault(key, len(slots) % SLOTS + 1)
    return layers


def _label_h(layer: Layer | None) -> float:
    """Height of a label: material and thickness, how it's known, then one line per process."""
    return LINE_H * (2 + (len(layer.processes) if layer else 0))


def _spread(centres: list[float], heights: list[float], low: float, high: float) -> list[float]:
    """Tops for labels of `heights` (top to bottom), each centred on its
    `centres` where there's room, not overlapping, within [low, high]."""
    tops = []
    for c, h in zip(centres, heights):           # down, not overlapping the one above
        want = c - h / 2
        tops.append(max(want, tops[-1] + heights[len(tops) - 1] + LABEL_GAP) if tops else max(want, low))
    if tops and tops[-1] + heights[-1] > high:   # then back up from the bottom, if that ran over
        tops[-1] = high - heights[-1]
        for i in range(len(tops) - 2, -1, -1):
            tops[i] = min(tops[i], tops[i + 1] - heights[i] - LABEL_GAP)
    return tops                                  # the first may end above `low`: the caller shifts


def _spans(layers: list[Layer]):
    """Where each layer lies across the drawing (Layer.span): what it's on,
    or a slice of that when it's partial, the partial layers on one thing
    side by side in the order they were deposited."""
    def base(layer):   # what it's on, if that's still there (CMP may have taken it)
        return layer.on if any(l is layer.on for l in layers) else None

    counts: dict[int, int] = {}
    for layer in layers:
        if layer.partial:
            counts[id(base(layer))] = counts.get(id(base(layer)), 0) + 1
    taken: dict[int, int] = {}
    for layer in layers:
        under = base(layer)
        a, b = under.span if under is not None else (0.0, 1.0)
        if layer.partial:
            k, i = counts[id(under)], taken.get(id(under), 0)
            taken[id(under)] = i + 1
            w = (b - a) / k
            a, b = a + i * w + PARTIAL_MARGIN * w, a + (i + 1) * w - PARTIAL_MARGIN * w
        layer.span = (a, b)


def diagram(layers: list[Layer]) -> dict | None:
    """The drawing's geometry (top layer drawn on top): each film is an
    outline (`path`) following the surface it was deposited on; its label
    beside the stack, joined by a line to the right end of the film's highest
    part (`end_x`, `mid`). None without layers."""
    if not layers:
        return None
    _spans(layers)
    # The drawing is cut into columns where any layer starts or ends
    edges = sorted({0.0, 1.0} | {x for l in layers for x in l.span})
    columns = list(zip(edges, edges[1:]))
    covers = [[j for j, (a, b) in enumerate(columns) if l.span[0] <= (a + b) / 2 <= l.span[1]] for l in layers]
    # Scale: the thickest column of known films fills FILMS_H
    known_nm = [sum(l.thickness or 0 for l, c in zip(layers, covers) if j in c) for j in range(len(columns))]
    total = max(known_nm)
    scale = FILMS_H / total if total else 0
    film_h = [max(MIN_H, l.thickness * scale) if l.thickness else UNKNOWN_H for l in layers]
    clamped = any(l.thickness and l.thickness * scale < MIN_H for l in layers)
    # Stack them, each on what's below it in every column it covers (heights up from the substrate)
    height = [0.0] * len(columns)
    spans = []
    for layer, cols, h in zip(layers, covers, film_h):
        spans.append([(j, height[j], height[j] + h) for j in cols])
        for j in cols:
            height[j] += h
    films_h = max(height)

    def y(up):   # SVG y of a height above the substrate, before any shift
        return TOP + films_h - up

    for layer, cols, h in zip(layers, spans, film_h):
        # The label's line starts at the right end of the film's highest part
        j, low, high = max(reversed(cols), key=lambda c: c[2])
        layer.geometry = {"h": round(h, 1), "mid": round(y((low + high) / 2), 1),
                          "end_x": round(STACK_X + columns[j][1] * STACK_W, 1)}
    substrate_y = TOP + films_h
    height_px = substrate_y + SUBSTRATE_H + TOP
    # Labels, top to bottom (highest film first; at the same height, the later one)
    order = [l for _, l in sorted(enumerate(layers), key=lambda p: (p[1].geometry["mid"], -p[0]))]
    centres = [l.geometry["mid"] for l in order] + [substrate_y + SUBSTRATE_H / 2]
    heights = [_label_h(l) for l in order] + [_label_h(None)]
    ys = _spread(centres, heights, TOP, height_px - TOP)
    shift = 0.0
    if ys[0] < TOP:                              # more labels than room: shift everything down
        shift = TOP - ys[0]
        ys = [v + shift for v in ys]
        substrate_y += shift
    for layer, cols in zip(layers, spans):
        top = [p for j, _, high in cols for p in ((columns[j][0], high), (columns[j][1], high))]
        bottom = [p for j, low, _ in reversed(cols) for p in ((columns[j][1], low), (columns[j][0], low))]
        points = [f"{STACK_X + x * STACK_W:.1f},{y(up) + shift:.1f}" for x, up in top + bottom]
        layer.geometry["path"] = "M" + " L".join(points) + " Z"
        layer.geometry["mid"] = round(layer.geometry["mid"] + shift, 1)
        layer.geometry["inside"] = layer.geometry["end_x"] < STACK_X + STACK_W - 0.5   # ends before the edge
    for layer, top in zip(order, ys):
        layer.geometry["label_y"] = round(top, 1)
        layer.geometry["lead_y"] = round(top + LINE_H / 2, 1)   # the leader line ends at the first line
    return {
        "width": WIDTH, "height": round(max(substrate_y + SUBSTRATE_H, ys[-1] + heights[-1]) + TOP, 1),
        "x": STACK_X, "w": STACK_W, "label_x": LABEL_X,
        "substrate_y": round(substrate_y, 1), "substrate_h": SUBSTRATE_H,
        "substrate_label_y": round(ys[-1], 1),
        "layers": order,
        "total": float(f"{total:.4g}") if total else None,
        "all_known": all(l.thickness for l in layers),
        "clamped": clamped,
        "partial": any(l.partial for l in layers),
    }
