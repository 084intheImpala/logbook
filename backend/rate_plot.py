"""A small time plot of deposition rates (inline SVG, drawn by
frontend/templates/_rate_plot.html): one line per set of deposition
conditions (machine, target, gas, gas flow, power), dated depositions only."""
import math
from datetime import date, timedelta

from backend.deposition_rate import CONDITION_KEYS, RatePoint, conditions

SLOTS = 8   # categorical colours (--series-1 … --series-8 in _rate_plot.html)
WIDTH, HEIGHT = 640, 220
LEFT, RIGHT, TOP, BOTTOM = 48, 16, 26, 28


def condition_label(step) -> str:
    """e.g. "UHV1 · Ga2O3 · Ar + O2 · 20 sccm · 100 W" (— for what's missing)."""
    params = step.parameters or {}
    units = {f["key"]: f.get("unit", "") for f in step.step_type.parameter_schema or []}
    parts = []
    for key in CONDITION_KEYS:
        value = params.get(key)
        if value in (None, ""):
            parts.append("—")
        else:
            value = f"{value:g}" if isinstance(value, float) else str(value)
            parts.append(f"{value} {units.get(key, '')}".strip() if isinstance(params.get(key), (int, float)) else value)
    return " · ".join(parts)


def _nice_step(span: float) -> float:
    raw = span / 4 or 1
    power = 10 ** math.floor(math.log10(raw))
    return next(m * power for m in (1, 2, 2.5, 5, 10) if m * power >= raw)


def build(points: list[RatePoint], ranks: dict[tuple, int], highlight: int | None = None) -> dict | None:
    """The plot of `points` (dated, with a rate), one series per conditions,
    or None if there's nothing to draw. `ranks` gives each set of conditions
    its colour slot (from all depositions, so filtering doesn't repaint
    the lines that stay); `highlight` is a step id to ring."""
    dated = [p for p in points if p.step.performed_at and p.rate is not None]
    if not dated:
        return None
    groups: dict[tuple, list[RatePoint]] = {}
    for p in sorted(dated, key=lambda p: (p.step.performed_at, p.step.id)):
        groups.setdefault(conditions(p.step), []).append(p)
    # The busiest SLOTS sets are drawn; the rest are only counted
    shown = sorted(groups, key=lambda c: (-len(groups[c]), ranks.get(c, 1 << 30)))[:SLOTS]
    hidden = len(groups) - len(shown)
    slots, free = {}, [s for s in range(SLOTS)]
    for c in shown:   # a set keeps its own slot when it has one
        if ranks.get(c, SLOTS) < SLOTS:
            slots[c] = ranks[c]
            free.remove(ranks[c])
    for c in shown:
        if c not in slots:
            slots[c] = free.pop(0)

    drawn = [p for c in shown for p in groups[c]]
    first, last = min(p.step.performed_at for p in drawn), max(p.step.performed_at for p in drawn)
    if first == last:
        first, last = first - timedelta(days=15), last + timedelta(days=15)
    top_rate = max(p.rate for p in drawn)
    step = _nice_step(top_rate)
    y_max = step * math.ceil(top_rate * 1.05 / step)
    plot_w, plot_h = WIDTH - LEFT - RIGHT, HEIGHT - TOP - BOTTOM

    def x(d: date) -> float:
        return round(LEFT + (d - first).days / (last - first).days * plot_w, 1)

    def y(rate: float) -> float:
        return round(TOP + plot_h - rate / y_max * plot_h, 1)

    span = (last - first).days
    fmt = "%Y-%m-%d" if span < 400 else "%Y-%m"
    x_ticks = [{"x": x(first + timedelta(days=round(span * i / 3))),
                "label": (first + timedelta(days=round(span * i / 3))).strftime(fmt)} for i in range(4)]
    y_ticks = [{"y": y(step * i), "label": f"{step * i:g}"} for i in range(int(round(y_max / step)) + 1)]
    series = []
    for c in shown:
        pts = [{"x": x(p.step.performed_at), "y": y(p.rate), "rate": p.rate, "n": p.n, "date": p.step.performed_at,
                "sample": p.sample, "step_id": p.step.id, "highlight": p.step.id == highlight} for p in groups[c]]
        series.append({"slot": slots[c] + 1, "label": condition_label(groups[c][0].step),
                       "path": "M" + " L".join(f"{p['x']},{p['y']}" for p in pts), "points": pts})
    return {"width": WIDTH, "height": HEIGHT, "left": LEFT, "right": WIDTH - RIGHT, "top": TOP,
            "bottom": TOP + plot_h, "x_ticks": x_ticks, "y_ticks": y_ticks, "series": series, "hidden": hidden,
            "undated": len([p for p in points if p.rate is not None and not p.step.performed_at])}


def ranks(points) -> dict[tuple, int]:
    """Each set of conditions' colour slot: the busiest first, over all depositions given."""
    counts: dict[tuple, int] = {}
    for p in points:
        if p.rate is not None:
            counts[conditions(p.step)] = counts.get(conditions(p.step), 0) + 1
    order = sorted(counts, key=lambda c: (-counts[c], [str(v) for v in c]))
    return {c: i for i, c in enumerate(order)}
