from __future__ import annotations

from fastapi import Request
from fastapi.templating import Jinja2Templates

from app.config import REPO_ROOT, Settings

templates = Jinja2Templates(directory=str(REPO_ROOT / "app" / "templates"))
templates.env.globals["settings"] = Settings.from_env()


def render(request: Request, name: str, **context):
    """Every page gets the current user, so no route can forget to pass it."""
    from app.db import SessionLocal
    from app.security import COOKIE_NAME, resolve_session

    if "user" not in context:
        with SessionLocal() as db:
            context["user"] = resolve_session(db, request.cookies.get(COOKIE_NAME))
    return templates.TemplateResponse(request, name, context)
