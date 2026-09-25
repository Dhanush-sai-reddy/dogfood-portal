from __future__ import annotations

import logging
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from sqlalchemy import create_engine, event, text
from sqlalchemy.engine import Engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.config import Settings
from app.models import AUDIT_TRIGGERS, SCHEMA_VERSION, Base, SeedState

logger = logging.getLogger("dogfood")


def configure_sqlite(dbapi_connection, _connection_record) -> None:
    """Set the PRAGMAs on every connection, because they are connection-scoped.

    Setting them once at engine creation is a no-op for every handle after the
    first, which is exactly how foreign keys end up unenforced and the join
    graph quietly rots.
    """
    cursor = dbapi_connection.cursor()
    cursor.execute("PRAGMA journal_mode=WAL")
    cursor.execute("PRAGMA foreign_keys=ON")
    cursor.execute("PRAGMA busy_timeout=5000")
    cursor.close()


settings = Settings.from_env()
_db_path = settings.database_url.removeprefix("sqlite+pysqlite:///")
if _db_path and _db_path != ":memory:":
    Path(_db_path).parent.mkdir(parents=True, exist_ok=True)

engine = create_engine(
    settings.database_url,
    connect_args={"check_same_thread": False, "timeout": 30},
    future=True,
)
event.listen(engine, "connect", configure_sqlite)
SessionLocal = sessionmaker(bind=engine, autoflush=False, expire_on_commit=False)


def create_engine_for_tests() -> tuple[Engine, sessionmaker[Session]]:
    test_engine = create_engine(
        "sqlite+pysqlite://",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
        future=True,
    )
    event.listen(test_engine, "connect", configure_sqlite)
    return test_engine, sessionmaker(bind=test_engine, autoflush=False, expire_on_commit=False)


def get_db() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


@contextmanager
def session_scope() -> Iterator[Session]:
    db = SessionLocal()
    try:
        yield db
        db.commit()
    except Exception:
        db.rollback()
        raise
    finally:
        db.close()


def init_db() -> None:
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in AUDIT_TRIGGERS:
            conn.execute(text(statement))
    with SessionLocal() as db:
        row = db.get(SeedState, "schema_version")
        if row is None:
            db.add(SeedState(key="schema_version", checksum=str(SCHEMA_VERSION)))
            db.commit()
        elif row.checksum != str(SCHEMA_VERSION):
            raise RuntimeError(
                f"schema version mismatch: the database says {row.checksum} and the "
                f"code says {SCHEMA_VERSION}. This project ships no migrations; reset "
                f"with `docker compose down -v` (the data is re-seeded from "
                f"fixtures.json in milliseconds)."
            )
