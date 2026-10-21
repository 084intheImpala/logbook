from contextlib import asynccontextmanager
from fastapi import FastAPI, Request, Form
from fastapi.responses import RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.sessions import SessionMiddleware

from backend.config import settings
from backend.database import create_tables, AsyncSessionLocal
from backend.routers import samples, steps, analyses, files, admin, search, substrates, suggestions
from backend.routers import auth as auth_router
from backend.auth import RequiresLoginException, RequiresProfileException
from backend.seed import seed_types
from backend.i18n import LANGS


@asynccontextmanager
async def lifespan(app: FastAPI):
    await create_tables()
    async with AsyncSessionLocal() as session:
        await seed_types(session)
    yield


app = FastAPI(title=settings.APP_TITLE, lifespan=lifespan)

app.add_middleware(
    SessionMiddleware,
    secret_key=settings.SECRET_KEY,
    session_cookie="logbook_session",
    max_age=60 * 60 * 24 * 30,  # 30 days
    https_only=False,            # set True in production with HTTPS
)

app.mount("/static", StaticFiles(directory="frontend/static"), name="static")

app.include_router(auth_router.router, tags=["auth"])
app.include_router(search.router)
app.include_router(substrates.router)
app.include_router(suggestions.router)
app.include_router(samples.router, prefix="/samples", tags=["samples"])
app.include_router(steps.router, prefix="/samples", tags=["steps"])
app.include_router(analyses.router, prefix="/samples", tags=["analyses"])
app.include_router(files.router)
app.include_router(admin.router)


@app.exception_handler(RequiresLoginException)
async def requires_login_handler(request: Request, exc: RequiresLoginException):
    return RedirectResponse(url=f"/login?next={request.url.path}", status_code=302)


@app.exception_handler(RequiresProfileException)
async def requires_profile_handler(request: Request, exc: RequiresProfileException):
    return RedirectResponse(url="/profile", status_code=302)


@app.get("/")
async def root():
    return RedirectResponse("/samples/")


@app.post("/lang")
async def set_language(request: Request, lang: str = Form(...), back: str = Form("/")):
    """The PT/EN switch in the sidebar."""
    if lang in LANGS:
        request.session["lang"] = lang
    return RedirectResponse(back if back.startswith("/") and not back.startswith("//") else "/", status_code=303)
