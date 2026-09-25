from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.config import Settings
from app.deps import CurrentUser, DbSession
from app.models import SessionRow, User
from app.security import (
    assert_same_origin, clear_session_cookie, create_session, hash_token, set_session_cookie,
    verify_password,
)
from app.templating import render

router = APIRouter(tags=["auth"])


async def read_credentials(request: Request) -> tuple[str, str]:
    if request.headers.get("content-type", "").startswith("application/json"):
        payload = await request.json()
        return str(payload.get("email", "")).strip().lower(), str(payload.get("password", ""))
    form = await request.form()
    return str(form.get("email", "")).strip().lower(), str(form.get("password", ""))


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", error=None, email="")


@router.post("/login")
async def login(request: Request, db: DbSession):
    assert_same_origin(request)
    email, password = await read_credentials(request)
    user = db.scalar(select(User).where(User.email == email))
    # One branch for "no such user" and "wrong password": a different response
    # would turn the login form into an address book.
    if user is None or not verify_password(password, user.password_hash):
        return render(
            request, "login.html",
            error="That email and password do not match.", email=email,
        )
    token = create_session(db, user.id)
    db.commit()
    redirect = RedirectResponse("/projects", status_code=303)
    set_session_cookie(redirect, token, secure=Settings.from_env().secure_cookies)
    return redirect


@router.post("/logout")
def logout(request: Request, db: DbSession):
    assert_same_origin(request)
    token = request.cookies.get(Settings.from_env().cookie_name)
    if token:
        row = db.scalar(
            select(SessionRow).where(SessionRow.token_hash == hash_token(token))
        )
        if row is not None:
            row.revoked = True
            db.commit()
    redirect = RedirectResponse("/projects", status_code=303)
    clear_session_cookie(redirect)
    return redirect


@router.get("/whoami")
def whoami(user: CurrentUser) -> dict[str, str]:
    return {"id": user.id, "email": user.email, "role": user.role}
