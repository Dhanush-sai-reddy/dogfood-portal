import pytest
from sqlalchemy import func, select

from app.db import create_engine_for_tests
from app.models import Assignment, Base, JudgeProfile, Project, Score, Track
from app.seed import (
    apply_reference_data, assignment_feasibility, augment_assignments, load_fixture,
)


@pytest.fixture
def seeded():
    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with factory() as db:
        apply_reference_data(db, load_fixture())
        db.commit()
        yield db


def _reviews(db) -> dict[str, int]:
    return {
        project_id: count
        for project_id, count in db.execute(
            select(Score.project_id, func.count()).group_by(Score.project_id)
        ).all()
    }


def test_every_track_passes_the_feasibility_gate(seeded):
    assert assignment_feasibility(seeded) == []


def test_the_gate_names_an_undercovered_track(seeded):
    """Silently relaxing the gate is how a project ships with one review."""
    for profile in seeded.scalars(select(JudgeProfile)).all():
        profile.track_ids = [t for t in profile.track_ids if t != "trk_01"]
    seeded.commit()
    problems = assignment_feasibility(seeded)
    assert len(problems) == 1
    assert "trk_01" in problems[0] and "Developer tools" in problems[0]


def test_every_project_reaches_three_reviews(seeded):
    report = augment_assignments(seeded)
    counts = dict(
        seeded.execute(
            select(Assignment.project_id, func.count()).group_by(Assignment.project_id)
        ).all()
    )
    assert len(counts) == 41
    assert report.min_reviews == 3
    assert report.max_reviews == 5


def test_the_report_matches_the_verified_fixture_outcome(seeded):
    report = augment_assignments(seeded)
    assert report.added == 10
    assert report.total == 131
    assert report.relaxations == 3
    assert report.team_conflicts == ["jdg_26 sees tm_07 twice"]
    assert report.over_capacity == ["jdg_24 has 11 projects (capacity 10)"]
    assert report.orphaned_scores == ["jdg_19/prj_41", "jdg_21/prj_41"]


def test_no_assignment_is_cross_track(seeded):
    augment_assignments(seeded)
    track_of = dict(seeded.execute(select(Project.id, Project.track_id)).all())
    judge_tracks = {
        row.user_id: set(row.track_ids)
        for row in seeded.scalars(select(JudgeProfile)).all()
    }
    offenders = [
        (a.judge_id, a.project_id)
        for a in seeded.scalars(select(Assignment)).all()
        if track_of[a.project_id] not in judge_tracks[a.judge_id]
    ]
    assert offenders == []


def test_the_only_team_conflict_is_the_reported_one(seeded):
    augment_assignments(seeded)
    team_of = dict(seeded.execute(select(Project.id, Project.team_id)).all())
    seen: dict[tuple[str, str], str] = {}
    conflicts = []
    for assignment in seeded.scalars(select(Assignment)).all():
        key = (assignment.judge_id, team_of[assignment.project_id])
        if key in seen:
            conflicts.append(f"{key[0]} sees {key[1]} twice")
        seen[key] = assignment.project_id
    assert conflicts == ["jdg_26 sees tm_07 twice"]


def test_no_new_assignment_pushes_a_judge_past_capacity(seeded):
    """jdg_24 arrives at 11 from the fixture; the fill must not make it worse."""
    augment_assignments(seeded)
    load = dict(
        seeded.execute(
            select(Assignment.judge_id, func.count()).group_by(Assignment.judge_id)
        ).all()
    )
    assert load["jdg_24"] == 11
    assert sorted(load, key=lambda j: -load[j])[:3] == ["jdg_24", "jdg_26", "jdg_29"]


def test_augmentation_is_deterministic(seeded):
    first = augment_assignments(seeded)
    pairs_a = sorted(
        (a.judge_id, a.project_id) for a in seeded.scalars(select(Assignment)).all()
    )

    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with factory() as other:
        apply_reference_data(other, load_fixture())
        other.commit()
        second = augment_assignments(other)
        pairs_b = sorted(
            (a.judge_id, a.project_id) for a in other.scalars(select(Assignment)).all()
        )

    assert first == second
    assert pairs_a == pairs_b


def _pairs(db) -> set[tuple[str, str]]:
    return {(a.judge_id, a.project_id) for a in db.scalars(select(Assignment)).all()}


def test_a_different_seed_can_produce_a_different_fill(seeded):
    """If the seed does nothing, the stored seed is not a reproducibility record.
    Any one alternate seed might coincidentally draw the same fill, so this asks
    a few of them: what matters is that the seed is not inert."""
    augment_assignments(seeded)
    default = frozenset(_pairs(seeded))
    fills = set()
    for seed in (7, 11, 13, 17):
        engine, factory = create_engine_for_tests()
        Base.metadata.create_all(engine)
        with factory() as other:
            apply_reference_data(other, load_fixture())
            other.commit()
            augment_assignments(other, seed=seed)
            fills.add(frozenset(_pairs(other)))
    assert fills - {default}, "no alternate seed changed the fill"


def test_assignment_status_reflects_whether_a_score_exists(seeded):
    """A score whose assignment was dropped as a duplicate has no row to be
    "submitted" against. Reporting it as submitted would invent a review."""
    augment_assignments(seeded)
    pairs = _pairs(seeded)
    scored = {
        (a.judge_id, a.project_id)
        for a in seeded.scalars(select(Assignment)).all()
        if a.status == "submitted"
    }
    existing = {
        (s.judge_id, s.project_id) for s in seeded.scalars(select(Score)).all()
    }
    assert scored == existing & pairs
    # The two scores for prj_41 that lost their duplicate row. jdg_26 scored it
    # too, but was re-assigned prj_41 during the top-up, so it is not orphaned.
    assert existing - pairs == {("jdg_19", "prj_41"), ("jdg_21", "prj_41")}


def test_a_second_augmentation_adds_nothing(seeded):
    """Two boots in a row must not stack a second copy of every assignment.
    The report still counts the same additions on the second pass because it is
    derived from the score pairs rather than from the stored rows, so the row
    count and the pair set are the assertions that matter here."""
    augment_assignments(seeded)
    before = seeded.scalar(select(func.count()).select_from(Assignment))
    pairs_before = _pairs(seeded)
    augment_assignments(seeded)
    assert seeded.scalar(select(func.count()).select_from(Assignment)) == before == 131
    assert _pairs(seeded) == pairs_before
