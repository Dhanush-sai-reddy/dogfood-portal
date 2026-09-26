import datetime as dt

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import DatabaseError

from app.db import create_engine_for_tests, install_audit_triggers
from app.models import AuditLog, Base, Project, Score
from app.seed import FIXTURE_TOKENS, JUDGE_A_ID, apply_reference_data, augment_assignments, load_fixture

NOW = dt.datetime(2026, 1, 1, tzinfo=dt.timezone.utc)


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model)) or 0


def _rows(db) -> list[AuditLog]:
    return list(db.scalars(select(AuditLog).order_by(AuditLog.id)).all())


def _create_project(db, actor, project_id="prj_t1", title="Audit Probe"):
    db.info["actor_id"] = actor
    db.add(
        Project(id=project_id, team_id="tm_01", track_id="trk_01", title=title,
                summary="written by a test", repo_url=None, is_draft=False,
                submitted_at=NOW, updated_at=NOW)
    )
    db.commit()


def _seeded_engine():
    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    install_audit_triggers(engine)
    return engine, factory


@pytest.fixture
def db():
    """A second session on a seeded engine, so auditing is live again.

    Deliberately not the session the seeder used: `seed_session` suspends
    auditing for the session it marks and nothing clears it, so a fixture that
    reused it would leave every write below silently unlogged, and the failures
    would read as a broken listener rather than as a broken fixture. The engine
    is one shared connection, so the committed fixture is visible here.
    """
    _engine, factory = _seeded_engine()
    with factory() as seeder:
        apply_reference_data(seeder, load_fixture())
        augment_assignments(seeder)
        seeder.commit()
    with factory() as session:
        yield session


def test_seeding_a_fixture_writes_no_audit_rows():
    """A seeder that wrote ~170 rows describing our own fixture would bury the
    mutations worth reading. The flag is what silences the listener."""
    _engine, factory = _seeded_engine()
    with factory() as seeder:
        apply_reference_data(seeder, load_fixture())
        augment_assignments(seeder)
        seeder.commit()
        assert seeder.info.get("audit_suspended") is True
        assert _count(seeder, AuditLog) == 0


def test_the_flag_is_per_session_so_a_later_write_is_still_audited():
    """Load-bearing: the suppression is scoped to the session that seeds, so
    every request session afterwards is audited normally."""
    _engine, factory = _seeded_engine()
    with factory() as seeder:
        apply_reference_data(seeder, load_fixture())
        seeder.commit()
        assert seeder.info.get("audit_suspended") is True
    with factory() as writer:
        assert writer.info.get("audit_suspended") is None
        _create_project(writer, JUDGE_A_ID, project_id="prj_fresh")
        assert _count(writer, AuditLog) == 1


def test_a_new_project_is_audited_with_its_actor(db):
    _create_project(db, JUDGE_A_ID)
    entry = _rows(db)[0]
    assert entry.action == "create"
    assert entry.entity_type == "projects"
    assert entry.entity_id == "prj_t1"
    assert entry.actor_id == JUDGE_A_ID
    assert entry.before_json is None
    assert '"Audit Probe"' in entry.after_json


def test_an_edit_records_the_old_and_the_new_value(db):
    _create_project(db, JUDGE_A_ID)
    project = db.get(Project, "prj_t1")
    project.title = "Renamed Probe"
    db.commit()
    entry = _rows(db)[1]
    assert entry.action == "update"
    assert '"Audit Probe"' in entry.before_json
    assert '"Renamed Probe"' in entry.after_json
    assert "summary" not in entry.before_json


def test_a_second_project_is_a_second_entry_not_a_replacement(db):
    _create_project(db, JUDGE_A_ID, project_id="prj_t1", title="Audit Probe")
    _create_project(db, JUDGE_A_ID, project_id="prj_t2", title="Second Probe")
    assert [entry.entity_id for entry in _rows(db)] == ["prj_t1", "prj_t2"]


def test_rescoring_is_an_update_and_not_a_second_create(db):
    score = db.scalar(select(Score).where(Score.judge_id == JUDGE_A_ID).limit(1))
    # A value that differs from whatever the fixture happens to hold. `criteria`
    # is a plain JSON column, so assigning the value it already carries is
    # correctly not a change at all, and the row would be silent rather than
    # logged.
    changed = 0 if score.criteria["functionality"] else 5
    score.criteria = dict(score.criteria, functionality=changed)
    db.commit()
    entries = [e for e in _rows(db) if e.entity_type == "scores"]
    assert len(entries) == 1
    assert entries[0].action == "update"
    assert "functionality" in entries[0].before_json
    assert f'"functionality": {changed}' in entries[0].after_json


def test_a_write_with_no_identity_is_recorded_as_a_system_action(db):
    _create_project(db, None)
    assert _rows(db)[0].actor_id is None


def test_touching_only_a_timestamp_writes_nothing(db):
    project = db.get(Project, "prj_01")
    project.updated_at = NOW
    db.commit()
    assert _count(db, AuditLog) == 0


def test_the_audit_log_is_never_audited(db):
    _create_project(db, JUDGE_A_ID)
    _create_project(db, JUDGE_A_ID, project_id="prj_t2", title="Second Probe")
    assert len(_rows(db)) == 2
    assert not [e for e in _rows(db) if e.entity_type == "audit_log"]


def test_the_audit_log_refuses_an_update(db):
    _create_project(db, JUDGE_A_ID)
    _rows(db)[0].action = "tampered"
    with pytest.raises(DatabaseError, match="append-only"):
        db.commit()
    db.rollback()
    assert _count(db, AuditLog) == 1


def test_the_audit_log_refuses_a_delete(db):
    _create_project(db, JUDGE_A_ID)
    db.delete(_rows(db)[0])
    with pytest.raises(DatabaseError, match="append-only"):
        db.commit()
    db.rollback()
    assert _count(db, AuditLog) == 1


def test_the_organizer_sees_the_entry(live):
    with live.factory() as db:
        _create_project(db, JUDGE_A_ID)
    live.cookies.set("sid", FIXTURE_TOKENS["organizer"])
    response = live.get("/admin/audit")
    live.cookies.clear()
    assert response.status_code == 200
    assert "projects/prj_t1" in response.text
    assert "create" in response.text
    assert JUDGE_A_ID in response.text


def test_the_newest_entry_is_first(live):
    with live.factory() as db:
        _create_project(db, JUDGE_A_ID, project_id="prj_t1", title="First")
        _create_project(db, JUDGE_A_ID, project_id="prj_t2", title="Second")
    live.cookies.set("sid", FIXTURE_TOKENS["organizer"])
    text = live.get("/admin/audit").text
    live.cookies.clear()
    assert text.index("prj_t2") < text.index("prj_t1")


def test_the_page_filters_by_actor(live):
    with live.factory() as db:
        _create_project(db, JUDGE_A_ID, project_id="prj_t1", title="First")
    with live.factory() as db:
        db.info["actor_id"] = "prt_1"
        _create_project(db, "prt_1", project_id="prj_t2", title="Second")
    live.cookies.set("sid", FIXTURE_TOKENS["organizer"])
    text = live.get("/admin/audit", params={"actor": "prt_1"}).text
    live.cookies.clear()
    assert "prj_t2" in text
    assert "prj_t1" not in text


def test_the_page_filters_by_entity_type(live):
    with live.factory() as db:
        _create_project(db, JUDGE_A_ID)
    live.cookies.set("sid", FIXTURE_TOKENS["organizer"])
    everything = live.get("/admin/audit").text
    scores_only = live.get("/admin/audit", params={"entity_type": "scores"}).text
    live.cookies.clear()
    assert "projects/prj_t1" in everything
    assert "projects/prj_t1" not in scores_only


def test_a_judge_cannot_read_the_audit_log(live):
    live.cookies.set("sid", FIXTURE_TOKENS["judge_a"])
    assert live.get("/admin/audit").status_code == 403
    live.cookies.clear()


def test_a_participant_cannot_read_the_audit_log(live):
    live.cookies.set("sid", FIXTURE_TOKENS["participant"])
    assert live.get("/admin/audit").status_code == 403
    live.cookies.clear()


def test_an_anonymous_caller_is_401(live):
    assert live.get("/admin/audit").status_code == 401
