import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from app.main import create_app

    with TestClient(create_app()) as test_client:
        yield test_client


@pytest.fixture
def live():
    """A seeded portal on an in-memory database, with SessionLocal swapped in."""
    from fastapi.testclient import TestClient

    from app.db import create_engine_for_tests
    from app.main import create_app
    from app.models import Base
    from app.seed import ensure_seeded
    import app.db as db_module

    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with factory() as db:
        ensure_seeded(db)
        db.commit()

    original = db_module.SessionLocal
    db_module.SessionLocal = factory
    try:
        with TestClient(create_app()) as client:
            client.factory = factory
            yield client
    finally:
        db_module.SessionLocal = original
