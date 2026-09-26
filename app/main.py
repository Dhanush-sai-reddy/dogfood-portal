from __future__ import annotations

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI

from app.config import REPO_ROOT, Settings
from app.routers import health

logger = logging.getLogger("dogfood")


@asynccontextmanager
async def lifespan(application: FastAPI):
    settings: Settings = application.state.settings
    logger.info("database %s", settings.database_url)
    from app.db import init_db

    init_db()
    yield
    logger.info("stopped")


def create_app() -> FastAPI:
    application = FastAPI(
        title="DOGFOOD portal",
        version="0.1.0",
        lifespan=lifespan,
    )
    application.state.settings = Settings.from_env()
    application.include_router(health.router)
    from fastapi.staticfiles import StaticFiles

    from app.routers import admin, auth, export, gallery, judge, projects

    application.mount(
        "/static", StaticFiles(directory=str(REPO_ROOT / "app" / "static")), name="static"
    )
    application.include_router(auth.router)
    # Before the gallery, because the first match wins and the gallery's
    # `GET /projects/{project_id}` would otherwise answer `/projects/new` with a
    # project whose id is the literal string "new". Three segments, so
    # `/projects/{project_id}/edit` could not collide either way.
    application.include_router(projects.router)
    application.include_router(gallery.router)
    application.include_router(judge.router)
    application.include_router(export.router)
    application.include_router(admin.router)
    return application


app = create_app()
