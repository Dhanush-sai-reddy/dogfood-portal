import os
import subprocess
import sys
from pathlib import Path

import pytest
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError

from app.db import create_engine_for_tests
from app.models import Assignment, Base, JudgeProfile, Project, Score, Track
from app.seed import (
    apply_reference_data, assignment_feasibility, augment_assignments, load_fixture,
)

ROOT = Path(__file__).resolve().parent.parent


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
    assert report.total == 133
    assert report.relaxations == 2
    assert report.team_conflicts == [
        "jdg_12 sees tm_07 twice", "jdg_21 sees tm_07 twice",
    ]
    assert report.over_capacity == ["jdg_24 has 11 projects (capacity 10)"]
    assert report.orphaned_scores == ["jdg_19/prj_41", "jdg_26/prj_41"]


def test_the_review_counts_are_read_back_from_the_stored_rows(seeded):
    """Every count the report calls a result is counted from the rows.

    The loop's own arithmetic cannot be the witness: a re-pick of a judge who
    already reviews the project leaves the pair set unchanged while still
    advancing the counter, which is how `min_reviews` came to claim three for a
    project that shipped with two. Counting distinct reviewers here, from a
    query the report never sees, is what makes the two comparable.
    """
    report = augment_assignments(seeded)
    stored = list(seeded.scalars(select(Assignment)).all())
    per_project: dict[str, list[str]] = {}
    for assignment in stored:
        per_project.setdefault(assignment.project_id, []).append(assignment.judge_id)

    # A duplicate pair would show up here as a row count above the distinct
    # reviewer count, so the two agreeing is the read-back form of the
    # constraint the schema enforces.
    assert all(len(judges) == len(set(judges)) for judges in per_project.values())
    assert report.total == len(stored)
    assert report.min_reviews == min(len(set(j)) for j in per_project.values())
    assert report.max_reviews == max(len(set(j)) for j in per_project.values())
    assert report.min_reviews == min(
        count
        for _, count in seeded.execute(
            select(Assignment.project_id, func.count()).group_by(Assignment.project_id)
        ).all()
    )
    # And it is the real floor, not a floor one can slip under: no project
    # carries fewer distinct reviewers than the report's minimum.
    assert report.min_reviews <= min(len(set(j)) for j in per_project.values())


def test_a_duplicate_pair_cannot_be_represented(seeded):
    """`uq_assignment_pair` is the last line of defence. The fill is supposed to
    make a duplicate unreachable, but a constraint that is merely believed in is
    a constraint that eventually is not."""
    augment_assignments(seeded)
    existing = seeded.scalars(select(Assignment).limit(1)).one()
    seeded.add(
        Assignment(
            id="asg_duplicate_attempt",
            judge_id=existing.judge_id,
            project_id=existing.project_id,
            status="pending",
        )
    )
    with pytest.raises(IntegrityError):
        seeded.flush()
    seeded.rollback()


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


def test_the_only_team_conflicts_are_the_reported_ones(seeded):
    augment_assignments(seeded)
    team_of = dict(seeded.execute(select(Project.id, Project.team_id)).all())
    seen: dict[tuple[str, str], str] = {}
    conflicts = []
    for assignment in seeded.scalars(select(Assignment)).all():
        key = (assignment.judge_id, team_of[assignment.project_id])
        if key in seen:
            conflicts.append(f"{key[0]} sees {key[1]} twice")
        seen[key] = assignment.project_id
    assert sorted(conflicts) == [
        "jdg_12 sees tm_07 twice", "jdg_21 sees tm_07 twice",
    ]


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

    Some seeds have no valid fill at all -- `trk_01`'s panel is one slot from
    uncoverable, which `test_a_stranded_project_is_reported_not_papered_over`
    pins -- so this asks a spread of them and skips the ones that refuse. What
    matters here is only that the seed is not inert.
    """
    augment_assignments(seeded)
    default = frozenset(_pairs(seeded))
    fills = set()
    for candidate in (7, 11, 13, 17, 19, 43):
        engine, factory = create_engine_for_tests()
        Base.metadata.create_all(engine)
        with factory() as other:
            apply_reference_data(other, load_fixture())
            other.commit()
            try:
                augment_assignments(other, seed=candidate)
            except RuntimeError:
                continue
            fills.add(frozenset(_pairs(other)))
    assert fills - {default}, "no alternate seed changed the fill"


def test_a_stranded_project_is_reported_not_papered_over():
    """`trk_01` has three judges, one of whom arrives over capacity from the
    fixture, so the panel holds exactly one spare slot and `prj_29` is the only
    project that can spend it. A seed that spends it on `prj_41` instead leaves
    `prj_29` short, and the answer has to be a refusal that names the project:
    before the eligibility guard this same case produced a report claiming three
    reviews for a project that had two.
    """
    engine, factory = create_engine_for_tests()
    Base.metadata.create_all(engine)
    with factory() as db:
        apply_reference_data(db, load_fixture())
        db.commit()
        with pytest.raises(RuntimeError) as excinfo:
            augment_assignments(db, seed=7)
    message = str(excinfo.value)
    assert "prj_29" in message
    assert "trk_01" in message


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
    # The two scores for prj_41 that lost their duplicate row. The fill sent both
    # of prj_41's open slots to judges who already held prj_07, so jdg_19 and
    # jdg_26 are the two whose reviews no assignment row stands behind.
    assert existing - pairs == {("jdg_19", "prj_41"), ("jdg_26", "prj_41")}


def test_a_second_augmentation_adds_nothing(seeded):
    """Two boots in a row must not stack a second copy of every assignment.
    The report still counts the same additions on the second pass because it is
    derived from the score pairs rather than from the stored rows, so the row
    count and the pair set are the assertions that matter here."""
    augment_assignments(seeded)
    before = seeded.scalar(select(func.count()).select_from(Assignment))
    pairs_before = _pairs(seeded)
    augment_assignments(seeded)
    assert seeded.scalar(select(func.count()).select_from(Assignment)) == before == 133
    assert _pairs(seeded) == pairs_before


_REPORT_PROBE = """
from sqlalchemy import select

from app.db import create_engine_for_tests
from app.models import Assignment, Base
from app.seed import apply_reference_data, augment_assignments, load_fixture

engine, factory = create_engine_for_tests()
Base.metadata.create_all(engine)
with factory() as db:
    apply_reference_data(db, load_fixture())
    db.commit()
    report = augment_assignments(db)
    rows = sorted(
        (a.judge_id, a.project_id, a.status) for a in db.scalars(select(Assignment)).all()
    )
print(repr(report))
print(repr(rows))
"""


def test_the_report_and_the_rows_do_not_depend_on_hash_randomisation():
    """`random.Random(ASSIGNMENT_SEED)` is not the only source of order here.

    Sets and dicts iterate in an order that depends on string hashing, so a
    report assembled from one varies between interpreters even with the seed
    pinned -- and after the eligibility fix there are two team conflicts, which
    is enough for that to show. Each child process runs with a different
    PYTHONHASHSEED and must print the same thing.
    """
    outputs = set()
    for hash_seed in ("0", "1", "42", "999"):
        completed = subprocess.run(
            [sys.executable, "-c", _REPORT_PROBE],
            cwd=ROOT,
            env={**os.environ, "PYTHONHASHSEED": hash_seed, "PYTHONPATH": str(ROOT)},
            capture_output=True,
            text=True,
        )
        assert completed.returncode == 0, completed.stderr
        outputs.add(completed.stdout)
    assert len(outputs) == 1, "the report or the rows varied with PYTHONHASHSEED"
