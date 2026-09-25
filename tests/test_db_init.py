import pytest
from sqlalchemy import create_engine, event
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import app.db
from app.db import configure_sqlite
from app.models import SCHEMA_VERSION, SeedState

AUDIT_TRIGGER_NAMES = {"audit_log_no_update", "audit_log_no_delete"}


@pytest.fixture
def wired(monkeypatch):
    """Point `init_db` at an in-memory database, leaving the real one alone.

    The engine is built here instead of via `create_engine_for_tests`, which
    installs the audit triggers itself. These tests exist to cover `init_db`, so
    the trigger install has to be the one thing `init_db` alone does: borrow its
    PRAGMA wiring, and nothing else. Going through the factory would hand the
    tests their triggers up front, and they would then pass with `init_db`'s
    trigger loop deleted.
    """
    engine = create_engine(
        "sqlite+pysqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    event.listen(engine, "connect", configure_sqlite)
    try:
        factory = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)
        monkeypatch.setattr(app.db, "engine", engine)
        monkeypatch.setattr(app.db, "SessionLocal", factory)
        yield engine, factory
    finally:
        event.remove(engine, "connect", configure_sqlite)
        engine.dispose()


def _trigger_names(engine):
    with engine.connect() as conn:
        return {
            row[0]
            for row in conn.exec_driver_sql(
                "SELECT name FROM sqlite_master WHERE type = 'trigger'"
            )
        }


def test_init_db_creates_the_schema_and_the_audit_triggers(wired):
    engine, factory = wired

    app.db.init_db()

    assert AUDIT_TRIGGER_NAMES <= _trigger_names(engine)
    with factory() as db:
        row = db.get(SeedState, "schema_version")
        assert row is not None
        assert row.checksum == str(SCHEMA_VERSION)


def test_init_db_is_idempotent(wired):
    app.db.init_db()
    app.db.init_db()


def test_init_db_raises_when_the_stored_schema_version_differs(wired):
    _, factory = wired
    app.db.init_db()
    with factory() as db:
        db.get(SeedState, "schema_version").checksum = "0"
        db.commit()

    with pytest.raises(RuntimeError, match="schema version mismatch"):
        app.db.init_db()


def test_the_test_harness_installs_the_audit_triggers():
    """A bare `create_engine_for_tests` must hand back production's protection.

    This is the harness every later task builds fixtures from, and the guards
    that make it honest are spread thin: `tests/test_models.py` installs the
    triggers itself, so nothing else in the suite would notice the factory
    stopped doing it. The factory is used with no `init_db` and no setup of any
    kind, because any setup here would be the thing putting the triggers in
    place and the assertion would be measuring that instead.
    """
    engine, _ = app.db.create_engine_for_tests()

    assert AUDIT_TRIGGER_NAMES <= _trigger_names(engine)


def test_production_engine_has_the_pragmas_and_the_audit_triggers():
    """The module level engine is the only one the app ever uses, and it is wired
    at import time. Assert that on the real engine rather than on a fixture copy,
    so dropping either the `connect` hook or the trigger install is a red test
    instead of a gap nobody notices until a later task writes to `audit_log`.

    The triggers are dropped first, because `init_db` installs them with `IF NOT
    EXISTS`: on a database that already has them, an assertion that they are
    present would pass even with the install removed.
    """
    with app.db.engine.begin() as conn:
        conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_log_no_update")
        conn.exec_driver_sql("DROP TRIGGER IF EXISTS audit_log_no_delete")
    try:
        app.db.init_db()

        with app.db.engine.connect() as conn:
            assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"
            assert conn.exec_driver_sql("PRAGMA foreign_keys").scalar() == 1
            assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000

        assert AUDIT_TRIGGER_NAMES <= _trigger_names(app.db.engine)
    finally:
        app.db.init_db()
