"""DOIs on a study's references: recognising one, and looking up the paper.

`parse` tells a DOI (bare, "doi:…" or a doi.org link) from any other link.
`lookup` asks doi.org for the paper's title, authors, journal and year
(CSL JSON, the format every DOI registrar answers in). It is best-effort: on
any failure (no network, unknown DOI, slow answer) the reference is kept
with what was typed in.
"""
import json
import logging
import re
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

from starlette.concurrency import run_in_threadpool

log = logging.getLogger("uvicorn.error")

DOI_RE = re.compile(r"^10\.\d{4,9}/\S+$")
_PREFIXES = re.compile(r"^(?:doi:\s*|https?://(?:dx\.)?doi\.org/)", re.IGNORECASE)
TIMEOUT = 6   # seconds


@dataclass
class Paper:
    title: str | None = None
    authors: str | None = None
    journal: str | None = None
    year: int | None = None


def parse(text: str) -> tuple[str | None, str | None]:
    """(doi, url) from what was typed: a DOI gives (doi, None), a link (None, url)."""
    text = text.strip()
    candidate = urllib.parse.unquote(_PREFIXES.sub("", text)).rstrip(".")
    if DOI_RE.match(candidate):
        return candidate, None
    if text and not re.match(r"^https?://", text, re.IGNORECASE):
        text = f"https://{text}"
    return None, text or None


def _authors(people: list[dict]) -> str | None:
    names = [" ".join(p for p in (a.get("given"), a.get("family")) if p) or a.get("literal") or ""
             for a in people]
    names = [n for n in names if n]
    if not names:
        return None
    return ", ".join(names) if len(names) <= 6 else f"{', '.join(names[:6])} et al."


def _paper(data: dict) -> Paper:
    def first(value):
        return (value[0] if value else None) if isinstance(value, list) else value
    year = None
    for key in ("published", "published-print", "published-online", "issued"):
        parts = (data.get(key) or {}).get("date-parts") or [[None]]
        if parts and parts[0] and parts[0][0]:
            year = int(parts[0][0])
            break
    return Paper(title=first(data.get("title")), authors=_authors(data.get("author") or []),
                 journal=first(data.get("container-title")), year=year)


def _fetch_csl(doi: str) -> dict | None:
    request = urllib.request.Request(
        f"https://doi.org/{urllib.parse.quote(doi, safe='/')}",
        headers={"Accept": "application/vnd.citationstyles.csl+json", "User-Agent": "logbook (DOI lookup)"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, TimeoutError, ValueError, OSError) as exc:
        log.info("DOI lookup for %s failed: %s", doi, exc)
        return None


async def lookup(doi: str) -> Paper | None:
    data = await run_in_threadpool(_fetch_csl, doi)
    return _paper(data) if isinstance(data, dict) else None
