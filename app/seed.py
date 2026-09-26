from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
import random
from dataclasses import dataclass, field
from pathlib import Path

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.audit import seed_session
from app.config import Settings
from app.models import (
    Assignment, Event, JudgeProfile, Project, RubricCriterion, Score, SeedState,
    SessionRow, Team, TeamMember, Track, User, utcnow,
)
from app.security import COOKIE_NAME, DEMO_PASSWORD_HASH, hash_token

logger = logging.getLogger("dogfood")

DEFAULT_EVENT_ID = "evt_01"
JUDGE_A_ID = "jdg_24"
JUDGE_B_ID = "jdg_26"
ORGANIZER_EMAIL = "organizer@dogfood.test"
PARTICIPANT_EMAIL = "priya1@example.org"

FIXTURE_TOKENS: dict[str, str] = {
    "organizer": "tok_organizer_7f3a91c2",
    "judge_a": "tok_judge_a_91bc44de",
    "judge_b": "tok_judge_b_44de91bc",
    "participant": "tok_participant_2e88prt0",
}
TOKEN_SUBJECTS: dict[str, str] = {
    "organizer": ORGANIZER_EMAIL,
    "judge_a": JUDGE_A_ID,
    "judge_b": JUDGE_B_ID,
    "participant": PARTICIPANT_EMAIL,
}
FIXTURE_TOKEN_EXPIRES = dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc)

RUBRIC = (
    ("functionality", "Functionality", 1.0, 0),
    ("quality", "Quality", 1.0, 1),
    ("innovation", "Innovation", 1.0, 2),
)
DEFAULT_CAPACITY = 10
REVIEWS_PER_PROJECT = 3
ASSIGNMENT_SEED = 20260925


def _parse_ts(value: str) -> dt.datetime:
    return dt.datetime.fromisoformat(value.replace("Z", "+00:00"))


def _member_id(email: str) -> str:
    """Fixture members are identified only by email, and every local part in
    the file is distinct, so the local part is the id."""
    return f"usr_{email.split('@')[0]}"


def load_fixture(path: Path | None = None) -> dict:
    resolved = Path(path) if path else Settings.from_env().fixtures_path
    if not resolved.exists():
        raise FileNotFoundError(
            f"fixtures.json was not found at {resolved}. It is vendored at the repo "
            f"root and copied to /app/fixtures.json in the image."
        )
    with resolved.open(encoding="utf-8") as handle:
        return json.load(handle)


def fixture_checksum(fixture: dict) -> str:
    canonical = json.dumps(fixture, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def apply_reference_data(db: Session, fixture: dict) -> None:
    """Upsert every row the fixture describes, in dependency layers.

    Each layer is flushed before the layer that points at it is merged. No model
    declares a `relationship()` for the foreign keys this seeder writes, and
    SQLAlchemy orders a flush by mapper name — `judge_profiles` and
    `team_members` both sort ahead of `users`, `projects` ahead of `teams` — so a
    single trailing flush would insert children before their parents and fail the
    foreign key. `merge` is an upsert, which is what lets a second call be a
    no-op instead of a unique-constraint violation.
    """
    seed_session(db)
    event = fixture["event"]
    db.merge(
        Event(
            id=event["id"],
            name=event["name"],
            submissions_close=_parse_ts(event["submissions_close"]),
            status="active",
        )
    )
    db.flush()

    for track in fixture["tracks"]:
        db.merge(Track(id=track["id"], name=track["name"], event_id=event["id"]))

    # The fixtures contain no organizer and no participant, only judges and team
    # members, so the seed invents exactly two records and derives every other
    # role from the collection the record appears in.
    db.merge(
        User(
            id="usr_organizer",
            email=ORGANIZER_EMAIL,
            name="Fixture Organizer",
            password_hash=DEMO_PASSWORD_HASH,
            role="organizer",
            org="DOGFOOD",
        )
    )
    for judge in fixture["judges"]:
        db.merge(
            User(
                id=judge["id"],
                email=judge["email"],
                name=judge["name"],
                password_hash=DEMO_PASSWORD_HASH,
                role="judge",
                org=None,
            )
        )
    db.flush()

    for judge in fixture["judges"]:
        db.merge(
            JudgeProfile(
                user_id=judge["id"],
                track_ids=list(judge["tracks"]),
                capacity=DEFAULT_CAPACITY,
            )
        )
    db.flush()

    for team in fixture["teams"]:
        db.merge(Team(id=team["id"], name=team["name"], event_id=event["id"]))
        for email in team["members"]:
            member_id = _member_id(email)
            if db.get(User, member_id) is None:
                db.merge(
                    User(
                        id=member_id,
                        email=email,
                        name=email.split("@")[0].replace("_", " ").title(),
                        password_hash=DEMO_PASSWORD_HASH,
                        role="participant",
                        org=None,
                    )
                )
    db.flush()

    for team in fixture["teams"]:
        for email in team["members"]:
            db.merge(TeamMember(team_id=team["id"], user_id=_member_id(email)))
    db.flush()

    for project in fixture["projects"]:
        db.merge(
            Project(
                id=project["id"],
                team_id=project["team"],
                track_id=project["track"],
                title=project["title"],
                summary=project.get("summary", ""),
                repo_url=project.get("repo_url"),
                is_draft=False,
                submitted_at=_parse_ts(project["submitted_at"]),
                updated_at=_parse_ts(project["submitted_at"]),
            )
        )
    db.flush()

    for key, label, weight, position in RUBRIC:
        db.merge(
            RubricCriterion(
                id=f"rubric_{event['id']}_{key}",
                event_id=event["id"],
                key=key,
                label=label,
                weight=weight,
                max_score=5,
                position=position,
            )
        )

    for score in fixture["scores"]:
        comment = (score.get("comment") or "").strip() or None
        db.merge(
            Score(
                id=f"score_{score['judge']}_{score['project']}",
                judge_id=score["judge"],
                project_id=score["project"],
                criteria=dict(score["criteria"]),
                comment=comment,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
    db.flush()


def apply_fixture_sessions(db: Session) -> None:
    for label, token in FIXTURE_TOKENS.items():
        subject = TOKEN_SUBJECTS[label]
        if label.startswith("judge_"):
            user_id = subject
        else:
            user = db.scalar(select(User).where(User.email == subject))
            if user is None:
                raise RuntimeError(
                    f"cannot attach the {label} token: no user {subject} was seeded"
                )
            user_id = user.id
        token_hash = hash_token(token)
        # `merge` cannot key these rows: `sessions.id` is autoincrement and the
        # seeder never sets it, so a second application would insert a
        # duplicate and collide with the unique `token_hash`. The hash is the
        # natural key, so look it up and rewrite the row in place.
        row = db.scalar(select(SessionRow).where(SessionRow.token_hash == token_hash))
        if row is None:
            row = SessionRow(token_hash=token_hash)
            db.add(row)
        row.user_id = user_id
        row.expires_at = FIXTURE_TOKEN_EXPIRES
        row.revoked = False
    db.flush()


def auth_header_lines() -> list[str]:
    return [f"  {label:<11} Cookie: {COOKIE_NAME}={token}" for label, token in FIXTURE_TOKENS.items()]


def print_auth_headers() -> None:
    print("seeded. test logins:", flush=True)
    for line in auth_header_lines():
        print(line, flush=True)


@dataclass(frozen=True)
class AssignmentReport:
    added: int
    total: int
    min_reviews: int
    max_reviews: int
    relaxations: int
    team_conflicts: list[str] = field(default_factory=list)
    over_capacity: list[str] = field(default_factory=list)
    orphaned_scores: list[str] = field(default_factory=list)


def assignment_feasibility(
    db: Session, *, reviews_per_project: int = REVIEWS_PER_PROJECT,
    capacity: int = DEFAULT_CAPACITY,
) -> list[str]:
    """The gate. An empty list means every track can reach the target."""
    projects_per_track = dict(
        db.execute(select(Project.track_id, func.count()).group_by(Project.track_id)).all()
    )
    judges_per_track: dict[str, int] = {}
    for profile in db.scalars(select(JudgeProfile)).all():
        for track_id in profile.track_ids:
            judges_per_track[track_id] = judges_per_track.get(track_id, 0) + 1

    problems: list[str] = []
    for track_id, project_count in sorted(projects_per_track.items()):
        judge_count = judges_per_track.get(track_id, 0)
        slots = judge_count * capacity
        needed = project_count * reviews_per_project
        if slots < needed:
            name = db.scalar(select(Track.name).where(Track.id == track_id)) or track_id
            problems.append(
                f"track {track_id} ({name}): {project_count} projects need {needed} "
                f"reviews but {judge_count} judges offer {slots} slots"
            )
    return problems


def augment_assignments(
    db: Session,
    *,
    reviews_per_project: int = REVIEWS_PER_PROJECT,
    capacity: int = DEFAULT_CAPACITY,
    seed: int = ASSIGNMENT_SEED,
) -> AssignmentReport:
    seed_session(db)
    problems = assignment_feasibility(
        db, reviews_per_project=reviews_per_project, capacity=capacity
    )
    if problems:
        raise RuntimeError("judge assignment is infeasible:\n  " + "\n  ".join(problems))

    rng = random.Random(seed)
    team_of = dict(db.execute(select(Project.id, Project.team_id)).all())
    track_of = dict(db.execute(select(Project.id, Project.track_id)).all())
    judge_tracks = {
        row.user_id: set(row.track_ids) for row in db.scalars(select(JudgeProfile)).all()
    }
    judge_capacity = {
        row.user_id: row.capacity for row in db.scalars(select(JudgeProfile)).all()
    }

    score_pairs = {(s.judge_id, s.project_id) for s in db.scalars(select(Score)).all()}

    # Repair team duplicates: keep the earlier submission, orphan the later score.
    per_judge: dict[str, list[str]] = {}
    for judge_id, project_id in score_pairs:
        per_judge.setdefault(judge_id, []).append(project_id)
    pairs: set[tuple[str, str]] = set(score_pairs)
    for judge_id, project_ids in per_judge.items():
        seen_teams: set[str] = set()
        for project_id in sorted(
            project_ids, key=lambda p: (team_of[p], track_of[p], p)
        ):
            team_id = team_of[project_id]
            if team_id in seen_teams:
                pairs.discard((judge_id, project_id))
            else:
                seen_teams.add(team_id)

    load: dict[str, int] = {}
    seen_teams_by_judge: dict[str, set[str]] = {}
    for judge_id, project_id in pairs:
        load[judge_id] = load.get(judge_id, 0) + 1
        seen_teams_by_judge.setdefault(judge_id, set()).add(team_of[project_id])

    reviews: dict[str, int] = {project_id: 0 for project_id in team_of}
    for _, project_id in pairs:
        reviews[project_id] += 1

    order = sorted(
        team_of,
        key=lambda p: (
            -max(0, reviews_per_project - reviews[p]),
            sum(1 for tracks in judge_tracks.values() if track_of[p] in tracks),
            p,
        ),
    )

    added = 0
    relaxations = 0
    for project_id in order:
        track_id = track_of[project_id]
        team_id = team_of[project_id]
        while reviews[project_id] < reviews_per_project:
            eligible = [
                judge_id
                for judge_id, tracks in judge_tracks.items()
                if track_id in tracks
                and team_id not in seen_teams_by_judge.get(judge_id, set())
                and load.get(judge_id, 0) < judge_capacity.get(judge_id, capacity)
            ]
            if not eligible:
                # Dropping the team rule is not permission to re-pick a judge who
                # already reviews this project. `pairs.add` would silently no-op
                # on a pair already in the set while the counters below advanced
                # anyway, so the project would never reach its target and the
                # report would describe the loop's intent rather than the data.
                # The strict branch above needs no such guard: a judge already on
                # the project has necessarily already seen its team.
                eligible = [
                    judge_id
                    for judge_id, tracks in judge_tracks.items()
                    if track_id in tracks
                    and (judge_id, project_id) not in pairs
                    and load.get(judge_id, 0) < judge_capacity.get(judge_id, capacity)
                ]
                if not eligible:
                    raise RuntimeError(
                        f"project {project_id} in track {track_id} cannot reach "
                        f"{reviews_per_project} reviews: every eligible judge is at "
                        f"capacity. Add a judge to the track or raise the capacity."
                    )
                relaxations += 1
            rng.shuffle(eligible)
            judge_id = eligible[0]
            pairs.add((judge_id, project_id))
            load[judge_id] = load.get(judge_id, 0) + 1
            seen_teams_by_judge.setdefault(judge_id, set()).add(team_id)
            reviews[project_id] += 1
            added += 1

    existing_scores = score_pairs
    for judge_id, project_id in sorted(pairs):
        db.merge(
            Assignment(
                id=f"asg_{judge_id}_{project_id}",
                judge_id=judge_id,
                project_id=project_id,
                status="submitted" if (judge_id, project_id) in existing_scores else "pending",
                assigned_at=utcnow(),
            )
        )
    db.flush()

    # Read the result back rather than trusting the loop's own arithmetic. Every
    # field below makes a claim about the stored rows, so a bug in the fill
    # cannot make the report overstate what it achieved -- a report that
    # overstates its own success is the failure this whole task exists to
    # prevent. `added` and `relaxations` stay counters, because those describe
    # what the algorithm did rather than what it produced.
    stored_pairs = {
        (row.judge_id, row.project_id) for row in db.scalars(select(Assignment)).all()
    }
    review_counts: dict[str, int] = {project_id: 0 for project_id in team_of}
    stored_load: dict[str, int] = {}
    teams_by_judge: dict[str, dict[str, list[str]]] = {}
    for judge_id, project_id in sorted(stored_pairs):
        review_counts[project_id] = review_counts.get(project_id, 0) + 1
        stored_load[judge_id] = stored_load.get(judge_id, 0) + 1
        teams_by_judge.setdefault(judge_id, {}).setdefault(team_of[project_id], []).append(
            project_id
        )

    # Sorted, because `stored_pairs` and the dicts built from it iterate in an
    # order that depends on string hashing. A pinned seed fixes the shuffle, not
    # that, and a report whose ordering varies between interpreters is not
    # reproducible either.
    team_conflicts = sorted(
        f"{judge_id} sees {team_id} twice"
        for judge_id, by_team in teams_by_judge.items()
        for team_id, members in by_team.items()
        if len(members) > 1
    )
    over_capacity = [
        f"{judge_id} has {stored_load[judge_id]} projects "
        f"(capacity {judge_capacity.get(judge_id, capacity)})"
        for judge_id in sorted(stored_load)
        if stored_load[judge_id] > judge_capacity.get(judge_id, capacity)
    ]
    orphaned_scores = sorted(
        f"{judge_id}/{project_id}" for judge_id, project_id in score_pairs - stored_pairs
    )

    return AssignmentReport(
        added=added,
        total=len(stored_pairs),
        min_reviews=min(review_counts.values()),
        max_reviews=max(review_counts.values()),
        relaxations=relaxations,
        team_conflicts=team_conflicts,
        over_capacity=over_capacity,
        orphaned_scores=orphaned_scores,
    )


def ensure_seeded(db: Session, fixture: dict | None = None) -> bool:
    """Idempotent, keyed on a content checksum.

    A row count cannot detect a changed fixture and a git sha cannot detect a
    schema change; the content checksum detects both.
    """
    data = fixture if fixture is not None else load_fixture()
    checksum = fixture_checksum(data)
    row = db.get(SeedState, "fixtures")
    if row is not None and row.checksum == checksum:
        logger.info("seed: already applied (checksum %s)", checksum[:12])
        return False

    apply_reference_data(db, data)
    report = augment_assignments(db)
    apply_fixture_sessions(db)
    db.merge(SeedState(key="fixtures", checksum=checksum, applied_at=utcnow()))
    logger.info(
        "seed: applied %d assignments (%d added, min %d reviews) checksum %s",
        report.total, report.added, report.min_reviews, checksum[:12],
    )
    for note in report.team_conflicts + report.over_capacity + report.orphaned_scores:
        logger.warning("seed: %s", note)
    return True
