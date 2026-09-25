from __future__ import annotations

from collections.abc import Callable
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ROLES, User
from app.security import COOKIE_NAME, resolve_session

DbSession = Annotated[Session, Depends(get_db)]


def current_session(request: Request, db: DbSession) -> User | None:
    return resolve_session(db, request.cookies.get(COOKIE_NAME))


def require_user(request: Request, db: DbSession) -> User:
    user = current_session(request, db)
    if user is None:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="authentication required",
        )
    return user


def require_role(*roles: str) -> Callable[..., User]:
    unknown = set(roles) - set(ROLES)
    if unknown:
        raise ValueError(f"unknown role(s): {sorted(unknown)}")

    def dependency(request: Request, db: DbSession) -> User:
        user = require_user(request, db)
        if user.role not in roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"this action requires one of: {', '.join(sorted(roles))}",
            )
        return user

    # `Depends(require_role(...))` records the closure this factory returns as the
    # route's dependant call, never the factory itself, so the route walk in
    # `tests/test_deps_isolation.py` recognises a guard by this marker instead of by
    # identity. The roles ride along so a guard that admits the wrong one is caught.
    dependency.__role_guard__ = frozenset(roles)
    return dependency


CurrentUser = Annotated[User, Depends(require_user)]
Judge = Annotated[User, Depends(require_role("judge"))]
Participant = Annotated[User, Depends(require_role("participant", "organizer", "admin"))]
Organizer = Annotated[User, Depends(require_role("organizer", "admin"))]
Admin = Annotated[User, Depends(require_role("admin"))]
