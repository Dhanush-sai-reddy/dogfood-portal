import datetime as dt

import pytest
from sqlalchemy import func, select

from app.db import create_engine_for_tests
from app.models import (
    Assignment, AuditLog, Base, Event, JudgeProfile, Project, RubricCriterion,
    Score, SeedState, SessionRow, Team, Track, User,
)
from app.security import COOKIE_NAME, DEMO_PASSWORD_HASH, hash_token
from app.seed import (
    DEFAULT_EVENT_ID, FIXTURE_TOKENS, JUDGE_A_ID, JUDGE_B_ID, ORGANIZER_EMAIL,
    PARTICIPANT_EMAIL, apply_fixture_sessions, apply_reference_data,
    auth_header_lines, ensure_seeded, fixture_checksum, load_fixture,
)


@pytest.fixture
def seeded():
    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    fixture = load_fixture()
    with factory() as db:
        apply_reference_data(db, fixture)
        db.commit()
        yield db, fixture


@pytest.fixture
def db():
    """An empty schema, for the tests that seed it themselves through the entry
    point a boot actually calls."""
    _engine, factory = create_engine_for_tests()
    with factory() as session:
        yield session


def _count(db, model) -> int:
    return db.scalar(select(func.count()).select_from(model))


def test_load_fixture_reads_the_vendored_copy():
    fixture = load_fixture()
    assert fixture["event"]["id"] == "evt_01"
    assert fixture["event"]["submissions_close"] == "2026-03-01T18:00:00Z"


def test_load_fixture_names_the_path_it_wanted():
    from pathlib import Path

    with pytest.raises(FileNotFoundError) as excinfo:
        load_fixture(Path("/nonexistent/fixtures.json"))
    assert "fixtures.json" in str(excinfo.value)


def test_every_fixture_collection_is_reproduced(seeded):
    db, fixture = seeded
    assert _count(db, Track) == len(fixture["tracks"]) == 8
    assert _count(db, Team) == len(fixture["teams"]) == 40
    assert _count(db, Project) == len(fixture["projects"]) == 41
    assert _count(db, Score) == len(fixture["scores"]) == 126
    assert _count(db, User) == 91 + 30 + 1


def test_event_close_date_is_seeded_verbatim_and_is_already_past(seeded):
    """Acceptance check 3 depends on this exact line."""
    db, _ = seeded
    event = db.get(Event, DEFAULT_EVENT_ID)
    assert event.submissions_close == dt.datetime(2026, 3, 1, 18, 0, tzinfo=dt.timezone.utc)
    assert event.is_open() is False


def test_organizer_is_synthesized_and_participant_is_a_real_fixture_member(seeded):
    db, fixture = seeded
    organizer = db.scalar(select(User).where(User.email == ORGANIZER_EMAIL))
    participant = db.scalar(select(User).where(User.email == PARTICIPANT_EMAIL))
    assert organizer is not None and organizer.role == "organizer"
    assert participant is not None and participant.role == "participant"
    assert PARTICIPANT_EMAIL in fixture["teams"][0]["members"]


def test_every_fixture_member_becomes_a_participant(seeded):
    db, fixture = seeded
    members = {email for team in fixture["teams"] for email in team["members"]}
    roles = {
        user.email: user.role
        for user in db.scalars(select(User).where(User.email.in_(list(members)))).all()
    }
    assert len(roles) == 91
    assert set(roles.values()) == {"participant"}


def test_judges_get_their_fixture_track_ids_and_capacity(seeded):
    db, fixture = seeded
    for judge in fixture["judges"]:
        profile = db.get(JudgeProfile, judge["id"])
        assert profile is not None
        assert sorted(profile.track_ids) == sorted(judge["tracks"])
        assert profile.capacity == 10


def test_all_seeded_users_share_one_precomputed_hash(seeded):
    db, _ = seeded
    assert set(db.scalars(select(User.password_hash)).all()) == {DEMO_PASSWORD_HASH}


def test_the_duplicate_submission_is_stored_not_merged(seeded):
    db, _ = seeded
    titles = db.scalars(select(Project.title).where(Project.team_id == "tm_07")).all()
    assert sorted(titles) == ["Dry Harbour", "Dry Harbour"]
    assert _count(db, Project) == 41


def test_rubric_has_the_three_weighted_criteria(seeded):
    db, _ = seeded
    criteria = db.scalars(
        select(RubricCriterion).order_by(RubricCriterion.position)
    ).all()
    assert [c.key for c in criteria] == ["functionality", "quality", "innovation"]
    assert [c.label for c in criteria] == ["Functionality", "Quality", "Innovation"]
    assert all(c.max_score == 5 for c in criteria)
    assert sum(c.weight for c in criteria) == pytest.approx(3.0)


def test_empty_fixture_comments_become_null_not_empty_strings(seeded):
    db, _ = seeded
    comments = db.scalars(select(Score.comment)).all()
    assert sum(1 for c in comments if c is None) == 51
    assert all(c is None or c.strip() for c in comments)


def test_applying_twice_changes_nothing(seeded):
    db, fixture = seeded
    models = (Track, Team, Project, Score, User, RubricCriterion)
    before = {m: _count(db, m) for m in models}
    apply_reference_data(db, fixture)
    db.commit()
    assert {m: _count(db, m) for m in models} == before


def test_fixed_tokens_attach_to_the_right_users(seeded):
    db, fixture = seeded
    apply_fixture_sessions(db)
    db.commit()
    assert _count(db, SessionRow) == 4
    judge_emails = {judge["id"]: judge["email"] for judge in fixture["judges"]}
    expected = {
        "organizer": ORGANIZER_EMAIL,
        "judge_a": judge_emails[JUDGE_A_ID],
        "judge_b": judge_emails[JUDGE_B_ID],
        "participant": PARTICIPANT_EMAIL,
    }
    for label, token in FIXTURE_TOKENS.items():
        row = db.scalar(
            select(SessionRow).where(SessionRow.token_hash == hash_token(token))
        )
        assert row is not None, label
        user = db.get(User, row.user_id)
        assert user.email == expected[label]
        assert row.expires_at.year == 2099
        assert row.revoked is False


def test_the_tokens_are_the_four_fixed_literals():
    """Literals, not generated. `docker compose down -v` re-seeds, and a random
    token would 401 every header in .dogfood.toml on the second boot."""
    assert FIXTURE_TOKENS == {
        "organizer": "tok_organizer_7f3a91c2",
        "judge_a": "tok_judge_a_91bc44de",
        "judge_b": "tok_judge_b_44de91bc",
        "participant": "tok_participant_2e88prt0",
    }


def test_checksum_tracks_content_not_mtime():
    base = load_fixture()
    mutated = dict(base, event=dict(base["event"], name="Changed"))
    assert fixture_checksum(base) != fixture_checksum(mutated)
    assert fixture_checksum(base) == fixture_checksum(load_fixture())


def test_reference_data_creates_no_assignments_sessions_or_audit_rows(seeded):
    db, _ = seeded
    assert _count(db, Assignment) == 0
    assert _count(db, SessionRow) == 0
    assert _count(db, AuditLog) == 0
    assert _count(db, SeedState) == 0


def test_ensure_seeded_applies_the_vendored_fixture_once(db):
    assert ensure_seeded(db) is True
    db.commit()
    assert _count(db, Project) == 41
    assert _count(db, Score) == 126
    assert _count(db, SessionRow) == 4
    assert _count(db, Assignment) == 0
    assert db.get(SeedState, "fixtures").checksum == fixture_checksum(load_fixture())
    # A second boot on the same fixture is a no-op, not a second application.
    assert ensure_seeded(db) is False
    db.commit()
    assert _count(db, Project) == 41
    assert _count(db, Score) == 126
    assert _count(db, SessionRow) == 4


def test_ensure_seeded_reapplies_when_the_fixture_content_changes(db):
    assert ensure_seeded(db) is True
    db.commit()
    base = load_fixture()
    changed = dict(base, event=dict(base["event"], name="Renamed Hack"))
    assert ensure_seeded(db, changed) is True
    db.commit()
    assert db.get(Event, DEFAULT_EVENT_ID).name == "Renamed Hack"
    assert db.get(SeedState, "fixtures").checksum == fixture_checksum(changed)
    # The four tokens are re-attached, never duplicated.
    assert _count(db, SessionRow) == 4


def test_auth_header_lines_carry_every_token_under_the_cookie_name():
    lines = auth_header_lines()
    assert len(lines) == len(FIXTURE_TOKENS) == 4
    for label, token in FIXTURE_TOKENS.items():
        assert any(line.startswith(f"  {label}") for line in lines), label
        assert any(f"{COOKIE_NAME}={token}" in line for line in lines), label
