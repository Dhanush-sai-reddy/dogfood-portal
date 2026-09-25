from __future__ import annotations

from fastapi import APIRouter, Request
from fastapi.responses import RedirectResponse
from sqlalchemy import select
from starlette.concurrency import run_in_threadpool

from app.config import Settings
from app.deps import CurrentUser, DbSession
from app.models import SessionRow, User
from app.security import (
    COOKIE_NAME, assert_same_origin, clear_session_cookie, create_session, hash_token,
    set_session_cookie, verify_password,
)
from app.templating import render

router = APIRouter(tags=["auth"])

# A bcrypt hash of a 32-byte random secret that was discarded the moment it was
# hashed, so no password can ever verify against it. It exists to be compared
# against when the submitted address matches nobody: bcrypt costs the same to
# reject as to accept, so spending that cost unconditionally is what makes a miss
# as slow as a hit. `DEMO_PASSWORD_HASH` would have done the timing job, but its
# plaintext is `dogfood-demo`, the password every seeded user has, so a miss
# carrying it would verify True. Here it cannot.
DUMMY_PASSWORD_HASH = "$2b$12$IEVqTY0R5zNvmdbySDv0LuTUPtuX3QEW9J5CiSwwSuVTk4XLokDtK"


def _text(value: object) -> str:
    """Only a string is a credential.

    `str(None)` is `"None"` and `str(5)` is `"5"`, so a bare coercion would let a
    JSON `null` authenticate as a user whose address is `none` with the literal
    password `None`. Anything that is not a string — a number, a null, a nested
    object, an uploaded file in a multipart field — is not a credential at all.
    """
    return value if isinstance(value, str) else ""


def _address(value: object) -> str:
    return _text(value).strip().lower()


async def read_credentials(request: Request) -> tuple[str, str]:
    """The submitted address and password, or two empty strings.

    A JSON body that is not an object, or is not JSON at all, yields empty
    credentials rather than raising, so it lands in the same failed-login branch as
    a wrong password instead of answering 500. An unauthenticated 5xx is a
    different class of response from a rejected login, and the branch that renders
    "do not match" is the only one this route should have.
    """
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            payload = await request.json()
        except ValueError:
            # `JSONDecodeError` and `UnicodeDecodeError` are both `ValueError`.
            payload = None
        if not isinstance(payload, dict):
            return "", ""
        return _address(payload.get("email")), _text(payload.get("password"))
    form = await request.form()
    return _address(form.get("email")), _text(form.get("password"))


@router.get("/login")
def login_page(request: Request):
    return render(request, "login.html", error=None, email="")


@router.post("/login")
async def login(request: Request, db: DbSession):
    assert_same_origin(request)
    email, password = await read_credentials(request)
    user = db.scalar(select(User).where(User.email == email))
    # Always spend the hash, hit or miss. `user is None or not verify_password(...)`
    # short-circuits, and while the two answers are byte-identical their durations
    # are not: bcrypt at twelve rounds is ~600 ms against a millisecond or two, so
    # the clock alone would confirm which addresses are registered.
    # `verify_password` is synchronous and CPU-bound, so it goes to a worker thread
    # — called from an `async def` route it would hold the event loop for the length
    # of one hash and stall every other request behind it.
    hashed = user.password_hash if user is not None else DUMMY_PASSWORD_HASH
    verified = await run_in_threadpool(verify_password, password, hashed)
    # One branch for "no such user" and "wrong password": a different response
    # would turn the login form into an address book.
    if user is None or not verified:
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
    token = request.cookies.get(COOKIE_NAME)
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
