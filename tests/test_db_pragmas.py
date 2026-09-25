import pytest
from sqlalchemy import create_engine, event, text
from sqlalchemy.exc import IntegrityError

from app.db import configure_sqlite, create_engine_for_tests
from app.models import Base


def _fresh():
    engine, _ = create_engine_for_tests()
    Base.metadata.create_all(engine)
    return engine


def test_foreign_keys_are_enforced():
    engine = _fresh()
    with engine.begin() as conn:
        with pytest.raises(IntegrityError):
            conn.execute(
                text(
                    "INSERT INTO projects (id, team_id, track_id, title, summary,"
                    " repo_url, is_draft, submitted_at, updated_at) VALUES"
                    " ('prj_x','tm_nope','trk_01','t','s',NULL,0,'2026-01-01','2026-01-01')"
                )
            )


def test_journal_mode_is_wal(tmp_path):
    """A file database on purpose. SQLite reports `journal_mode` as `memory` for
    a `:memory:` database, so asserting WAL against the in-memory test engine
    would only ever pass for the shape production does not have."""
    engine = create_engine(
        f"sqlite+pysqlite:///{tmp_path / 'wal.db'}",
        connect_args={"check_same_thread": False},
        future=True,
    )
    event.listen(engine, "connect", configure_sqlite)
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA journal_mode").scalar().lower() == "wal"


def test_busy_timeout_is_set():
    engine = _fresh()
    with engine.connect() as conn:
        assert conn.exec_driver_sql("PRAGMA busy_timeout").scalar() == 5000
