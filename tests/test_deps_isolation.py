from contextlib import contextmanager

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

import app.db as db_module
import app.security as security
from app.db import create_engine_for_tests
from app.deps import require_role
from app.main import create_app
from app.models import Base, User

GUARDED_PREFIXES = ("/judge", "/api/judge", "/api/export", "/admin", "/organizer")
ROLES = ["organizer", "admin", "judge", "participant"]


def _iter_dependants(dependant):
    yield dependant
    for child in dependant.dependencies:
        yield from _iter_dependants(child)


@contextmanager
def _served_by(factory):
    """Answer the probe app's `get_db` from `factory` instead of the real database.

    `get_db` resolves `SessionLocal` out of `app.db`'s namespace on every call, so
    swapping the module attribute is the seam an in-memory engine reaches a route
    through. Without it a probe app authenticates against the file-backed
    `data/dogfood.db` and every request is a 401, whatever the test seeded.
    """
    original = db_module.SessionLocal
    db_module.SessionLocal = factory
    try:
        yield
    finally:
        db_module.SessionLocal = original


def test_every_guarded_route_declares_a_role_guard():
    app = create_app()
    offenders = sorted(
        route.path
        for route in app.routes
        if getattr(route, "path", "").startswith(GUARDED_PREFIXES)
        and not any(
            d.call is require_role for d in _iter_dependants(route.dependant)
        )
    )
    assert offenders == [], f"routes reachable without a role guard: {offenders}"


@pytest.fixture
def probe_app():
    app = FastAPI()

    @app.get("/judge/scores")
    def scores(user=Depends(require_role("judge"))):
        return {"role": user.role}

    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with factory() as db:
        for index, role in enumerate(ROLES):
            db.add(User(id=f"u{index}", email=f"{role}@example.org", name=role,
                        password_hash=security.DEMO_PASSWORD_HASH, role=role, org=None))
        db.commit()
        tokens = {
            role: security.create_session(db, f"u{index}")
            for index, role in enumerate(ROLES)
        }
        # `create_session` flushes without committing, and closing this session
        # would roll the token rows straight back out of the database.
        db.commit()
    with _served_by(factory), TestClient(app) as client:
        yield client, tokens


def test_missing_session_is_401_not_403(probe_app):
    client, _ = probe_app
    assert client.get("/judge/scores").status_code == 401


def test_correctness_matrix_judge_is_the_only_one_allowed_in(probe_app):
    """The spec's FIG. 02: judges see their own work, nobody else's."""
    client, tokens = probe_app
    for role, token in tokens.items():
        client.cookies.set("sid", token)
        assert client.get("/judge/scores").status_code == (
            200 if role == "judge" else 403
        ), role
        client.cookies.clear()


def test_require_role_rejects_an_unknown_role_at_import_time():
    with pytest.raises(ValueError):
        require_role("wizard")


def test_organizer_and_admin_are_both_allowed_where_declared():
    app = FastAPI()

    @app.get("/organizer/thing")
    def thing(user=Depends(require_role("organizer", "admin"))):
        return {"role": user.role}

    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with factory() as db:
        db.add(User(id="o", email="o@example.org", name="O",
                    password_hash=security.DEMO_PASSWORD_HASH,
                    role="organizer", org=None))
        db.commit()
        token = security.create_session(db, "o")
        db.commit()
    with _served_by(factory), TestClient(app) as client:
        client.cookies.set("sid", token)
        assert client.get("/organizer/thing").status_code == 200
