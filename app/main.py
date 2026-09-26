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

    from app.db import init_db, session_scope
    from app.seed import ensure_seeded, print_auth_headers

    init_db()
    with session_scope() as db:
        ensure_seeded(db)
        # The spec's story: the seeder prints the logins the checker needs.
        # Fixed tokens, so `docker compose down -v` cannot invalidate them.
        # AMENDED IN REVIEW (task 5): printed UNCONDITIONALLY, not gated on
        # `ensure_seeded` returning True. The Global Constraints and the
        # organizer's `.dogfood.toml` both require the headers on EVERY boot
        # ("your seed script prints these when the portal boots"), and the
        # checker never logs in — it only attaches them. Gating the print
        # silences it on exactly the second boot an operator is most likely to
        # be reading the log for.
        print_auth_headers()
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

    from app.routers import admin, auth, calendar, export, gallery, judge, leaderboard, pairwise, projects, teams

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
    application.include_router(calendar.router)
    application.include_router(leaderboard.router)
    application.include_router(teams.router)
    application.include_router(pairwise.router)
    return application


app = create_app()
