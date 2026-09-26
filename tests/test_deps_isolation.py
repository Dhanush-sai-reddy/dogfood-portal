from contextlib import contextmanager

import pytest
from fastapi import APIRouter, Depends, FastAPI
from fastapi.testclient import TestClient
from starlette.routing import Mount

import app.db as db_module
import app.security as security
from app.db import create_engine_for_tests
from app.deps import require_role
from app.main import create_app
from app.models import Base, User
from app.security import COOKIE_NAME

GUARDED_PREFIXES = ("/judge", "/api/judge", "/api/export", "/admin", "/organizer")
ROLES = ["organizer", "admin", "judge", "participant"]

# The roles each guarded route admits, written down here so a guard that drifts from
# its route's policy fails a test instead of surprising whoever reads the route later.
# Every task that adds a route under a guarded prefix adds its line.
EXPECTED_ROLES: dict[str, frozenset[str]] = {
    "/admin/audit": frozenset({"organizer", "admin"}),
    "/admin/settings": frozenset({"organizer", "admin"}),
    "/api/export": frozenset({"admin", "organizer"}),
    "/api/export.csv": frozenset({"admin", "organizer"}),
    "/api/judge/scores": frozenset({"judge"}),
    "/judge": frozenset({"judge"}),
    "/judge/score": frozenset({"judge"}),
}


def _iter_dependants(dependant):
    yield dependant
    for child in dependant.dependencies:
        yield from _iter_dependants(child)


def _iter_routes(routes, prefix=""):
    """Yield `(effective path, dependant or None)` for every route the app can serve.

    `include_router` does not flatten. It parks an `_IncludedRouter` in `app.routes`
    that has no `path` at all, so a walk that filters on `getattr(route, "path", "")`
    steps over every included router and passes vacuously — the guard it was checking
    for is never even looked for. The prefix that router swallowed lives on
    `include_context.prefix`, a `Mount` keeps its own on `.path`, and a plain route
    carries whatever is left, so each shape contributes its own piece of the path.
    """
    for route in routes:
        included = getattr(route, "original_router", None)
        if included is not None:
            yield from _iter_routes(
                included.routes, prefix + route.include_context.prefix
            )
        elif isinstance(route, Mount):
            yield from _iter_routes(route.routes, prefix + route.path)
        else:
            yield prefix + getattr(route, "path", ""), getattr(route, "dependant", None)


def _declared_roles(dependant) -> frozenset[str] | None:
    """The roles this route's guards admit, or None when nothing guards it at all.

    A route may carry more than one guard, and then the table has to name every role
    any of them admits, so a widening guard cannot slip past a narrow declaration.
    """
    if dependant is None:
        return None
    markers = [
        marker
        for marker in (
            getattr(d.call, "__role_guard__", None) for d in _iter_dependants(dependant)
        )
        if marker is not None
    ]
    if not markers:
        return None
    return frozenset().union(*markers)


def _guarded(app) -> dict[str, frozenset[str] | None]:
    return {
        path: _declared_roles(dependant)
        for path, dependant in _iter_routes(app.routes)
        if path.startswith(GUARDED_PREFIXES)
    }


@contextmanager
def _served_by(factory):
    """Answer the app's `get_db` from `factory` instead of the real database.

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
    unguarded = sorted(
        path for path, roles in _guarded(create_app()).items() if roles is None
    )
    assert unguarded == [], f"routes reachable without a role guard: {unguarded}"


def test_every_guarded_route_admits_only_its_declared_roles():
    found = _guarded(create_app())
    mismatched = {
        path: (roles, EXPECTED_ROLES.get(path))
        for path, roles in found.items()
        if roles != EXPECTED_ROLES.get(path)
    }
    assert mismatched == {}, f"guard admits the wrong roles: {mismatched}"
    assert set(found) == set(EXPECTED_ROLES), (
        "guarded routes and EXPECTED_ROLES have drifted apart: "
        f"{sorted(set(found) ^ set(EXPECTED_ROLES))}"
    )


def test_the_walk_finds_routes_behind_include_router_and_mount():
    """The tripwire: the walk has to see both hidden shapes, and read their roles.

    Everything else in this file is satisfied by an app with no guarded routes, which
    is exactly the state a change in FastAPI's routing internals would leave behind —
    the walk would find nothing, assert nothing and pass. This one names the routes it
    expects, so a version bump reds it instead of quietly checking nothing. The pins
    are exact, so coupling to this shape is the cheaper trade.
    """
    judge = APIRouter()

    @judge.get("/scores")
    def scores(user=Depends(require_role("judge"))):
        return {"role": user.role}

    organizer = APIRouter()

    @organizer.get("/roster")
    def roster(user=Depends(require_role("organizer", "admin"))):
        return {"role": user.role}

    app = FastAPI()
    app.include_router(judge, prefix="/judge")
    app.mount("/organizer", organizer)

    found = _guarded(app)
    assert found["/judge/scores"] == frozenset({"judge"})
    assert found["/organizer/roster"] == frozenset({"organizer", "admin"})


@pytest.fixture
def probe_app():
    app = FastAPI()

    @app.get("/judge/scores")
    def scores(user=Depends(require_role("judge"))):
        return {"role": user.role}

    @app.get("/judge/nobody")
    def nobody(user=Depends(require_role())):
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
        client.cookies.set(COOKIE_NAME, token)
        response = client.get("/judge/scores")
        assert response.status_code == (200 if role == "judge" else 403), role
        if role == "judge":
            assert response.json() == {"role": "judge"}, role
        client.cookies.clear()


def test_require_role_with_no_roles_admits_nobody(probe_app):
    """The fail-closed default: an empty allow-list denies every role, not every one
    but the last. A guard written with a forgotten argument must not read as open."""
    client, tokens = probe_app
    for role, token in tokens.items():
        client.cookies.set(COOKIE_NAME, token)
        assert client.get("/judge/nobody").status_code == 403, role
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
        for index, role in enumerate(("organizer", "admin")):
            db.add(User(id=f"o{index}", email=f"{role}@example.org", name=role,
                        password_hash=security.DEMO_PASSWORD_HASH, role=role, org=None))
        db.commit()
        tokens = {
            role: security.create_session(db, f"o{index}")
            for index, role in enumerate(("organizer", "admin"))
        }
        db.commit()
    with _served_by(factory), TestClient(app) as client:
        for role, token in tokens.items():
            client.cookies.set(COOKIE_NAME, token)
            response = client.get("/organizer/thing")
            assert response.status_code == 200, role
            assert response.json() == {"role": role}, role
            client.cookies.clear()
