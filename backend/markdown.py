"""Markdown for text people write in the logbook (procedures).

CommonMark plus tables. Raw HTML is shown as text, not run, and links to
javascript:/data: URLs aren't made (markdown-it's own checks), so what one
user writes can't run scripts in another's browser. Single line breaks are
kept, as people type them.
"""
from markdown_it import MarkdownIt
from markupsafe import Markup

_md = MarkdownIt("commonmark", {"html": False, "breaks": True}).enable("table")


def render(text: str | None) -> Markup:
    return Markup(_md.render(text or ""))
