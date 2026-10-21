"""The Jinja environment shared by all routers, with _() for translations."""
from fastapi.templating import Jinja2Templates
from jinja2 import pass_context

from backend.i18n import LANGS, get_lang, t


@pass_context
def _gettext(ctx, text: str, **values) -> str:
    return t(ctx["request"], text, **values)


templates = Jinja2Templates(directory="frontend/templates")
templates.env.globals.update(_=_gettext, get_lang=get_lang, LANGS=LANGS)
