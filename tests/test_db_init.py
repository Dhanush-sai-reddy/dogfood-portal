import pytest

import app.db
from app.models import SCHEMA_VERSION, SeedState


@pytest.fixture
def wired(monkeypatch):
    """Point `init_db` at an in-memory database, leaving the real one alone."""
    engine, factory = app.db.create_engine_for_tests()
    monkeypatch.setattr(app.db, "engine", engine)
    monkeypatch.setattr(app.db, "SessionLocal", factory)
    return engine, factory


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

    assert _trigger_names(engine) == {"audit_log_no_update", "audit_log_no_delete"}
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
            triggers = {
                row[0]
                for row in conn.exec_driver_sql(
                    "SELECT name FROM sqlite_master WHERE type = 'trigger'"
                )
            }

        assert triggers == {"audit_log_no_update", "audit_log_no_delete"}
    finally:
        app.db.init_db()
