from __future__ import annotations

import datetime as dt
import hashlib
import secrets
from urllib.parse import urlsplit

import bcrypt
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from starlette.requests import Request
from starlette.responses import Response

from app.config import Settings
from app.models import SessionRow, User, utcnow

BCRYPT_ROUNDS = 12
COOKIE_NAME = Settings.from_env().cookie_name
DEMO_PASSWORD = "dogfood-demo"
DEMO_PASSWORD_HASH = bcrypt.hashpw(
    DEMO_PASSWORD.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
).decode("utf-8")


def hash_password(plain: str) -> str:
    return bcrypt.hashpw(
        plain.encode("utf-8"), bcrypt.gensalt(rounds=BCRYPT_ROUNDS)
    ).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except ValueError:
        return False


def hash_token(token: str) -> str:
    return hashlib.sha256(token.encode("utf-8")).hexdigest()


def new_token() -> str:
    return secrets.token_urlsafe(32)


def create_session(db: Session, user_id: str, ttl_days: int | None = None) -> str:
    ttl = ttl_days if ttl_days is not None else Settings.from_env().session_ttl_days
    token = new_token()
    db.add(
        SessionRow(
            token_hash=hash_token(token),
            user_id=user_id,
            expires_at=utcnow() + dt.timedelta(days=ttl),
            revoked=False,
        )
    )
    db.flush()
    return token


def resolve_session(db: Session, token: str | None) -> User | None:
    if not token:
        return None
    row = db.scalar(select(SessionRow).where(SessionRow.token_hash == hash_token(token)))
    if row is None or row.revoked:
        return None
    expires_at = row.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=dt.timezone.utc)
    if expires_at <= utcnow():
        return None
    return row.user


def set_session_cookie(response: Response, token: str, secure: bool = False) -> None:
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        secure=secure,
        samesite="lax",
        max_age=Settings.from_env().session_ttl_days * 86400,
        path="/",
    )


def clear_session_cookie(response: Response) -> None:
    response.delete_cookie(COOKIE_NAME, path="/")


def assert_same_origin(request: Request) -> None:
    """Refuse a request whose `Origin` is present and does not match `Host`.

    The invariant is one-directional: no `Origin` means the request is treated as
    same-origin (a CLI client sends none, and the cookie's SameSite=Lax covers the
    browser), but a present `Origin` must be verifiable: a `Host` header has to
    exist and its netloc has to match it. `Origin: null`, which browsers send from
    sandboxed iframes, `file://` pages and `data:` URLs, parses to an empty netloc
    and is therefore not verifiable; refusing it is the point. Anything less than
    fail-closed here leaves the gate contributing nothing on exactly the requests
    it exists to catch.
    """
    origin = request.headers.get("origin")
    if not origin:
        return
    host = request.headers.get("host", "")
    if not host or urlsplit(origin).netloc != host:
        raise HTTPException(status_code=403, detail="cross-origin request refused")
