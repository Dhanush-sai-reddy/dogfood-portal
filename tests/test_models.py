import datetime as dt

import pytest
from sqlalchemy import select, text, update
from sqlalchemy.exc import IntegrityError

from app.db import create_engine_for_tests
from app.models import (
    AUDIT_TRIGGERS, Assignment, AuditLog, Base, Event, Project, Score, Team,
    Track, User, utcnow,
)

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


@pytest.fixture
def session():
    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with factory() as db:
        db.add(Event(id="evt_01", name="E", submissions_close=NOW, status="active"))
        # Tracks and teams both point at the event, so land it first rather than
        # leaning on `Event` sorting ahead of them by class name.
        db.flush()
        db.add(Track(id="trk_01", name="T", event_id="evt_01"))
        db.add(Team(id="tm_01", name="T", event_id="evt_01"))
        db.add(User(id="jdg_01", email="j@example.org", name="J",
                    password_hash="x", role="judge", org=None))
        # The schema links parents to children with bare foreign keys rather than
        # relationships, so the unit of work orders one flush by class name, not
        # by dependency. The project points at the rows above, so land them first.
        db.flush()
        db.add(Project(id="prj_01", team_id="tm_01", track_id="trk_01", title="T",
                       summary="s", repo_url=None, is_draft=False,
                       submitted_at=NOW, updated_at=NOW))
        db.commit()
        yield db


def test_email_is_unique(session):
    session.add(User(id="u2", email="j@example.org", name="B",
                     password_hash="x", role="judge", org=None))
    with pytest.raises(IntegrityError):
        session.commit()


def test_score_is_unique_per_judge_and_project(session):
    session.add(Score(id="s1", judge_id="jdg_01", project_id="prj_01",
                      criteria={"functionality": 4, "quality": 4, "innovation": 4},
                      comment=None, created_at=NOW, updated_at=NOW))
    session.commit()
    session.add(Score(id="s2", judge_id="jdg_01", project_id="prj_01",
                      criteria={"functionality": 5, "quality": 5, "innovation": 5},
                      comment=None, created_at=NOW, updated_at=NOW))
    with pytest.raises(IntegrityError):
        session.commit()


def test_assignment_is_unique_per_judge_and_project(session):
    session.add(Assignment(id="a1", judge_id="jdg_01", project_id="prj_01",
                           status="pending", assigned_at=NOW))
    session.commit()
    session.add(Assignment(id="a2", judge_id="jdg_01", project_id="prj_01",
                           status="pending", assigned_at=NOW))
    with pytest.raises(IntegrityError):
        session.commit()


def test_event_is_closed_when_the_close_date_has_passed(session):
    event = Event(id="evt_01", name="Sample Hack 2026",
                  submissions_close=dt.datetime(2026, 3, 1, 18, 0, tzinfo=dt.timezone.utc),
                  status="active")
    assert event.is_open() is False
    assert event.is_open(dt.datetime(2026, 2, 28, tzinfo=dt.timezone.utc)) is True


def test_frozen_event_is_never_open(session):
    event = Event(id="evt_01", name="E",
                  submissions_close=dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc),
                  status="frozen")
    assert event.is_open() is False


def test_audit_log_is_append_only():
    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with engine.begin() as conn:
        for statement in AUDIT_TRIGGERS:
            conn.execute(text(statement))

    with factory() as db:
        db.add(AuditLog(actor_id=None, action="create", entity_type="event",
                        entity_id="evt_01", before_json=None, after_json="{}",
                        created_at=NOW))
        db.commit()

        with pytest.raises(IntegrityError):
            db.execute(update(AuditLog).values(action="tampered"))
            db.commit()
        db.rollback()

        with pytest.raises(IntegrityError):
            db.execute(AuditLog.__table__.delete())
            db.commit()
        db.rollback()

        assert db.scalars(select(AuditLog)).one().action == "create"


def test_datetime_from_the_database_compares_against_utcnow(session):
    """The regression the `UtcDateTime` column type exists to prevent.

    SQLite stores no timezone, so before the decorator every one of the twelve
    datetime columns read back naive and each deadline check raised
    `TypeError: can't compare offset-naive and offset-aware datetimes`. The
    comparison is the assertion, so an unfixed column type fails here instead of
    at some later task's call site.
    """
    session.expire_all()

    submitted_at = session.get(Project, "prj_01").submitted_at

    assert submitted_at.tzinfo is not None
    assert submitted_at < utcnow()
    assert utcnow() - submitted_at > dt.timedelta(0)


def test_aware_datetime_reads_back_aware_in_utc_and_equal(session):
    session.expire_all()

    read = session.get(Project, "prj_01").submitted_at

    assert read.tzinfo is dt.timezone.utc
    assert read == NOW


def test_aware_datetime_in_another_offset_is_stored_as_its_utc_instant(session):
    plus_0530 = dt.timezone(dt.timedelta(hours=5, minutes=30))
    local = dt.datetime(2026, 5, 4, 18, 0, tzinfo=plus_0530)
    session.add(Project(id="prj_tz", team_id="tm_01", track_id="trk_01", title="Z",
                        summary="s", submitted_at=local, updated_at=NOW))
    session.commit()
    session.expire_all()

    read = session.get(Project, "prj_tz").submitted_at

    assert read == local
    assert read == dt.datetime(2026, 5, 4, 12, 30, tzinfo=dt.timezone.utc)


def test_naive_datetime_reads_back_as_utc_and_is_neither_rejected_nor_shifted(session):
    naive = dt.datetime(2026, 5, 4, 12, 30, 45, 123456)
    session.add(Project(id="prj_naive", team_id="tm_01", track_id="trk_01", title="N",
                        summary="s", submitted_at=naive, updated_at=NOW))
    session.commit()
    session.expire_all()

    read = session.get(Project, "prj_naive").submitted_at

    assert read == naive.replace(tzinfo=dt.timezone.utc)
    assert read.tzinfo is dt.timezone.utc


def test_null_datetime_round_trips_as_none(session):
    session.add(Project(id="prj_null", team_id="tm_01", track_id="trk_01", title="N",
                        summary="s", submitted_at=None, updated_at=NOW))
    session.commit()
    session.expire_all()

    assert session.get(Project, "prj_null").submitted_at is None


def test_datetime_is_stored_as_the_plain_naive_string_sqlite_expects(session):
    """The on-disk format is a contract: the acceptance tool and the seeded
    fixtures both read what SQLite already wrote, so the decorator must not
    introduce a format of its own."""
    session.add(Project(id="prj_raw", team_id="tm_01", track_id="trk_01", title="R",
                        summary="s",
                        submitted_at=dt.datetime(2026, 5, 4, 12, 30, 45, 123456),
                        updated_at=NOW))
    session.commit()

    stored = session.execute(
        text("SELECT submitted_at FROM projects WHERE id = 'prj_raw'")
    ).scalar_one()

    assert stored == "2026-05-04 12:30:45.123456"
