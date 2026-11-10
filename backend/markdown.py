"""Markdown for text people write in the logbook (procedures).

CommonMark plus tables. Raw HTML is shown as text, not run, and links to
javascript:/data: URLs aren't made (markdown-it's own checks), so what one
user writes can't run scripts in another's browser. Single line breaks are
kept, as people type them.

LaTeX maths between $…$ (inline) or $$…$$ (on its own) is kept as escaped
TeX in <span class="math inline"> / <div class="math block">, which KaTeX
draws in the browser (frontend/templates/_katex.html). The opening $ can't be
followed by a space nor the closing one preceded by one, so "$5 and $10"
stays text; \$ is a plain dollar.
"""
from markdown_it import MarkdownIt
from markupsafe import Markup
from mdit_py_plugins.dollarmath import dollarmath_plugin

_md = (MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("table")
       .use(dollarmath_plugin, allow_space=False, allow_digits=False))


def render(text: str | None) -> Markup:
    return Markup(_md.render(text or ""))
