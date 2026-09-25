from __future__ import annotations

import datetime as dt
import hashlib
import json
import logging
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import Settings
from app.models import (
    Event, JudgeProfile, Project, RubricCriterion, Score, SeedState, SessionRow,
    Team, TeamMember, Track, User, utcnow,
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
    # The assignments derived from these scores belong here, inside the same
    # checksum-guarded application, so that a changed fixture regenerates them.
    apply_fixture_sessions(db)
    db.merge(SeedState(key="fixtures", checksum=checksum, applied_at=utcnow()))
    db.flush()
    logger.info("seed: applied fixtures (checksum %s)", checksum[:12])
    return True
