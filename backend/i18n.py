"""Portuguese / English.

Templates and messages are written in English and wrapped in _() (templates)
or t(request, …) (Python); the Portuguese comes from the PT dictionaries in
backend/translations/. Text with no entry is shown in English. The language
is picked with the switch in the sidebar (kept in the session), or from the
browser's language on the first visit; Portuguese if the browser has neither.
"""
import importlib
import pkgutil
from starlette.requests import Request

from backend import translations

LANGS = {"pt": "Português", "en": "English"}

PT: dict[str, str] = {}
for _mod in pkgutil.iter_modules(translations.__path__):
    PT.update(importlib.import_module(f"{translations.__name__}.{_mod.name}").PT)


def get_lang(request: Request) -> str:
    lang = request.session.get("lang")
    if lang in LANGS:
        return lang
    for part in request.headers.get("accept-language", "").split(","):
        code = part.split(";")[0].strip()[:2].lower()
        if code in LANGS:
            return code
    return "pt"


def translate(lang: str, text: str, **values) -> str:
    """`text` in `lang`; {name} placeholders are filled from `values`."""
    if lang == "pt":
        text = PT.get(text, text)
    return text.format(**values) if values else text


def t(request: Request, text: str, **values) -> str:
    return translate(get_lang(request), text, **values)
