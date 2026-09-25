import datetime as dt

import pytest
from fastapi import HTTPException
from starlette.requests import Request
from starlette.responses import Response

from app.db import create_engine_for_tests
from app.models import Base, SessionRow, User
from app.security import (
    DEMO_PASSWORD,
    DEMO_PASSWORD_HASH,
    assert_same_origin,
    clear_session_cookie,
    create_session,
    hash_password,
    hash_token,
    new_token,
    resolve_session,
    set_session_cookie,
    verify_password,
)


@pytest.fixture
def db():
    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with factory() as session:
        session.add(User(id="jdg_24", email="d@example.org", name="Diego",
                         password_hash=DEMO_PASSWORD_HASH, role="judge", org=None))
        session.commit()
        yield session


def test_password_roundtrip():
    hashed = hash_password(DEMO_PASSWORD)
    assert hashed != DEMO_PASSWORD
    assert hashed.startswith("$2b$")
    assert verify_password(DEMO_PASSWORD, hashed)
    assert not verify_password("wrong", hashed)


def test_two_hashes_of_one_password_differ():
    assert hash_password(DEMO_PASSWORD) != hash_password(DEMO_PASSWORD)


def test_verify_password_survives_a_malformed_hash():
    assert verify_password(DEMO_PASSWORD, "not-a-bcrypt-hash") is False


def test_token_is_stored_hashed_never_raw(db):
    token = create_session(db, "jdg_24")
    row = db.query(SessionRow).filter(SessionRow.token_hash == hash_token(token)).one()
    assert row.token_hash == hash_token(token)
    assert row.token_hash != token


def test_resolve_session_returns_the_user(db):
    user = resolve_session(db, create_session(db, "jdg_24"))
    assert user is not None and user.id == "jdg_24"


def test_resolve_session_rejects_garbage_and_none(db):
    assert resolve_session(db, "not-a-real-token") is None
    assert resolve_session(db, None) is None
    assert resolve_session(db, "") is None


def test_resolve_session_rejects_a_revoked_token(db):
    token = create_session(db, "jdg_24")
    row = db.query(SessionRow).filter(SessionRow.token_hash == hash_token(token)).one()
    row.revoked = True
    db.commit()
    assert resolve_session(db, token) is None


def test_resolve_session_rejects_an_expired_token(db):
    token = create_session(db, "jdg_24")
    row = db.query(SessionRow).filter(SessionRow.token_hash == hash_token(token)).one()
    row.expires_at = dt.datetime(2000, 1, 1, tzinfo=dt.timezone.utc)
    db.commit()
    assert resolve_session(db, token) is None


def test_new_token_is_long_and_unique():
    assert len(new_token()) >= 32
    assert new_token() != new_token()


def test_cookie_is_httponly_secure_and_lax():
    response = Response()
    set_session_cookie(response, "tok_abc", secure=True)
    header = response.headers["set-cookie"]
    assert "sid=tok_abc" in header
    assert "HttpOnly" in header
    assert "Secure" in header
    assert "samesite=lax" in header.lower()


def test_clear_cookie_removes_the_cookie():
    response = Response()
    clear_session_cookie(response)
    header = response.headers["set-cookie"]
    assert "sid=" in header
    assert "Max-Age=0" in header or 'sid=""' in header


def _post(headers: dict[bytes, bytes]) -> Request:
    # An ASGI scope carries headers as (name, value) byte pairs; a mapping is
    # unpacked as a list of keys by starlette and blows up in Headers.get.
    raw = list(headers.items())
    return Request({"type": "http", "method": "POST", "path": "/", "headers": raw,
                    "query_string": b"", "scheme": "http", "server": ("localhost", 8080)})


def test_same_origin_allows_a_matching_origin():
    assert_same_origin(_post({b"host": b"localhost:8080", b"origin": b"http://localhost:8080"}))


def test_same_origin_allows_a_missing_origin():
    # run.py is not a browser and cannot be CSRF'd; the cookie's SameSite=Lax is
    # what protects the browser case.
    assert_same_origin(_post({b"host": b"localhost:8080"}))


def test_same_origin_refuses_a_foreign_origin():
    with pytest.raises(HTTPException) as excinfo:
        assert_same_origin(_post({b"host": b"localhost:8080", b"origin": b"https://evil.example"}))
    assert excinfo.value.status_code == 403
