from __future__ import annotations

import datetime as dt
from typing import Any

from sqlalchemy import (
    JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, TypeDecorator,
    UniqueConstraint,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship

SCHEMA_VERSION = 1

ROLE_ADMIN = "admin"
ROLE_ORGANIZER = "organizer"
ROLE_JUDGE = "judge"
ROLE_PARTICIPANT = "participant"
ROLES = (ROLE_ADMIN, ROLE_ORGANIZER, ROLE_JUDGE, ROLE_PARTICIPANT)


def utcnow() -> dt.datetime:
    return dt.datetime.now(dt.timezone.utc)


class UtcDateTime(TypeDecorator):
    """A datetime column that always reads back as an aware UTC value.

    SQLite has no native timezone storage, so a plain `DateTime(timezone=True)`
    hands back naive datetimes. Comparing one of those against `utcnow()` then
    raises `TypeError: can't compare offset-naive and offset-aware datetimes`,
    and twelve columns across eight tables have that shape: session expiry,
    submission deadlines and audit ordering among them. Converting once, here,
    is what keeps every call site free of a guard.

    Storage is unchanged. A naive value is written as it is, on the convention
    that it is already UTC, and an aware one is converted to UTC before its
    tzinfo is dropped, so the text on disk stays the plain
    `YYYY-MM-DD HH:MM:SS.ffffff` that SQLite already wrote.
    """

    impl = DateTime
    cache_ok = True

    def process_bind_param(
        self, value: dt.datetime | None, dialect
    ) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value
        return value.astimezone(dt.timezone.utc).replace(tzinfo=None)

    def process_result_value(
        self, value: dt.datetime | None, dialect
    ) -> dt.datetime | None:
        if value is None:
            return None
        if value.tzinfo is None:
            return value.replace(tzinfo=dt.timezone.utc)
        return value.astimezone(dt.timezone.utc)


class Base(DeclarativeBase):
    pass


class Event(Base):
    __tablename__ = "events"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    submissions_close: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="active")
    judging_config: Mapped[dict[str, Any]] = mapped_column(
        JSON,
        nullable=False,
        default=lambda: {
            "methodology": "rubric",
            "scale_min": 1,
            "scale_max": 5,
            "points_pool_total": 100,
            "blind_judging": False,
            "comment_required": False,
        },
    )

    def is_open(self, at: dt.datetime | None = None) -> bool:
        moment = at or utcnow()
        close = self.submissions_close
        if close.tzinfo is None:
            close = close.replace(tzinfo=dt.timezone.utc)
        return self.status != "frozen" and moment < close


class Track(Base):
    __tablename__ = "tracks"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    email: Mapped[str] = mapped_column(String(200), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    password_hash: Mapped[str] = mapped_column(String(120), nullable=False)
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    org: Mapped[str | None] = mapped_column(String(200), nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class SessionRow(Base):
    __tablename__ = "sessions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, nullable=False)
    revoked: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)

    user: Mapped[User] = relationship(lazy="joined")


class JudgeProfile(Base):
    __tablename__ = "judge_profiles"

    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    track_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    capacity: Mapped[int] = mapped_column(Integer, nullable=False, default=10)


class Team(Base):
    __tablename__ = "teams"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    name: Mapped[str] = mapped_column(String(200), nullable=False)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)

    members: Mapped[list["TeamMember"]] = relationship(back_populates="team")


class TeamMember(Base):
    __tablename__ = "team_members"

    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), primary_key=True)
    user_id: Mapped[str] = mapped_column(ForeignKey("users.id"), primary_key=True)
    joined_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)

    team: Mapped[Team] = relationship(back_populates="members")


class Project(Base):
    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    team_id: Mapped[str] = mapped_column(ForeignKey("teams.id"), nullable=False)
    track_id: Mapped[str] = mapped_column(ForeignKey("tracks.id"), nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    summary: Mapped[str] = mapped_column(Text, nullable=False, default="")
    repo_url: Mapped[str | None] = mapped_column(String(500), nullable=True)
    is_draft: Mapped[bool] = mapped_column(Boolean, default=False, nullable=False)
    submitted_at: Mapped[dt.datetime | None] = mapped_column(UtcDateTime, nullable=True)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class RubricCriterion(Base):
    __tablename__ = "rubric_criteria"
    __table_args__ = (UniqueConstraint("event_id", "key", name="uq_rubric_event_key"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    event_id: Mapped[str] = mapped_column(ForeignKey("events.id"), nullable=False)
    key: Mapped[str] = mapped_column(String(64), nullable=False)
    label: Mapped[str] = mapped_column(String(120), nullable=False)
    weight: Mapped[float] = mapped_column(nullable=False, default=1.0)
    max_score: Mapped[int] = mapped_column(Integer, nullable=False, default=5)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


class Assignment(Base):
    __tablename__ = "assignments"
    __table_args__ = (UniqueConstraint("judge_id", "project_id", name="uq_assignment_pair"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    judge_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False, default="pending")
    assigned_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class Score(Base):
    __tablename__ = "scores"
    __table_args__ = (UniqueConstraint("judge_id", "project_id", name="uq_score_pair"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    judge_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    criteria: Mapped[dict[str, Any]] = mapped_column(JSON, nullable=False)
    comment: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)
    updated_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class PairwiseVote(Base):
    __tablename__ = "pairwise_votes"
    __table_args__ = (UniqueConstraint("judge_id", "project_a_id", "project_b_id", name="uq_pairwise_vote"),)

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    judge_id: Mapped[str] = mapped_column(ForeignKey("users.id"), nullable=False)
    project_a_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    project_b_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    winner_id: Mapped[str] = mapped_column(ForeignKey("projects.id"), nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class AuditLog(Base):
    __tablename__ = "audit_log"

    id: Mapped[int] = mapped_column(Integer, primary_key=True, autoincrement=True)
    actor_id: Mapped[str | None] = mapped_column(String(64), nullable=True)
    action: Mapped[str] = mapped_column(String(16), nullable=False)
    entity_type: Mapped[str] = mapped_column(String(64), nullable=False)
    entity_id: Mapped[str] = mapped_column(String(64), nullable=False)
    before_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    after_json: Mapped[str | None] = mapped_column(Text, nullable=True)
    created_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


class SeedState(Base):
    __tablename__ = "seed_state"

    key: Mapped[str] = mapped_column(String(64), primary_key=True)
    checksum: Mapped[str] = mapped_column(String(64), nullable=False)
    applied_at: Mapped[dt.datetime] = mapped_column(UtcDateTime, default=utcnow)


AUDIT_TRIGGERS = (
    """
    CREATE TRIGGER IF NOT EXISTS audit_log_no_update
    BEFORE UPDATE ON audit_log
    BEGIN
      SELECT RAISE(ABORT, 'audit_log is append-only');
    END
    """,
    """
    CREATE TRIGGER IF NOT EXISTS audit_log_no_delete
    BEFORE DELETE ON audit_log
    BEGIN
      SELECT RAISE(ABORT, 'audit_log is append-only');
    END
    """,
)
