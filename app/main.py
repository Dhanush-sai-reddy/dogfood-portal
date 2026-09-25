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

    from app.routers import auth, gallery

    application.mount(
        "/static", StaticFiles(directory=str(REPO_ROOT / "app" / "static")), name="static"
    )
    application.include_router(auth.router)
    application.include_router(gallery.router)
    return application


app = create_app()
