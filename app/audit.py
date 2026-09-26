from __future__ import annotations

import datetime as dt
import json
import logging
from typing import Any

from sqlalchemy import event, inspect
from sqlalchemy.orm import Session

from app.models import Assignment, AuditLog, Project, Score

logger = logging.getLogger("dogfood.audit")

AUDITED_MODELS: tuple[type, ...] = (Project, Score, Assignment)
SKIP_COLUMNS = frozenset({"created_at", "updated_at", "assigned_at"})
REDACTED_COLUMNS = frozenset({"password_hash"})
ACTOR_KEY = "actor_id"
SUSPENDED_KEY = "audit_suspended"


def _plain(value: Any) -> Any:
    if isinstance(value, (dt.date, dt.datetime)):
        return value.isoformat()
    return value


def _dumps(data: dict[str, Any]) -> str:
    return json.dumps(data, sort_keys=True, default=str)


def _columns(obj) -> list[str]:
    return [
        column.name
        for column in obj.__table__.columns
        if column.name not in SKIP_COLUMNS and column.name not in REDACTED_COLUMNS
    ]


def _after(obj) -> dict[str, Any]:
    return {name: _plain(getattr(obj, name, None)) for name in _columns(obj)}


def _before(obj) -> dict[str, Any]:
    """Only the attributes that actually changed, with their previous values.

    `history.deleted` is the old value; an attribute that went from None to
    "x" has no deleted value, which correctly leaves it out of `before_json`.
    """
    state = inspect(obj)
    before: dict[str, Any] = {}
    for attribute in state.attrs:
        if attribute.key in SKIP_COLUMNS or attribute.key in REDACTED_COLUMNS:
            continue
        if not attribute.history.has_changes():
            continue
        for old in attribute.history.deleted:
            before[attribute.key] = _plain(old)
            break
    return before


def _log(session: Session, obj, action: str, before: dict | None, after: dict | None) -> None:
    session.add(
        AuditLog(
            actor_id=session.info.get(ACTOR_KEY),
            action=action,
            entity_type=obj.__tablename__,
            entity_id=str(obj.id),
            before_json=_dumps(before) if before else None,
            after_json=_dumps(after) if after else None,
        )
    )


@event.listens_for(Session, "before_flush")
def record_audit(session: Session, _flush_context, _instances) -> None:
    """Append one row per business change. Registered for every Session.

    `session.add` inside `before_flush` is the documented way to add rows to
    the same flush; nothing here can recurse because AuditLog is not one of
    AUDITED_MODELS.
    """
    if session.info.get(SUSPENDED_KEY):
        return
    for obj in session.new:
        if isinstance(obj, AUDITED_MODELS):
            _log(session, obj, "create", None, _after(obj))
    for obj in session.dirty:
        if not isinstance(obj, AUDITED_MODELS):
            continue
        if not session.is_modified(obj, include_collections=False):
            continue
        before = _before(obj)
        if before:
            _log(session, obj, "update", before, _after(obj))
    for obj in session.deleted:
        if isinstance(obj, AUDITED_MODELS):
            _log(session, obj, "delete", _after(obj), None)


def seed_session(db: Session) -> None:
    """Mark this session as a fixture import so its writes are not audited.

    Per session, not per engine: a request session is a different object and
    stays fully audited.
    """
    db.info[SUSPENDED_KEY] = True
