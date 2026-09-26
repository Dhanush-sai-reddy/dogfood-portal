from __future__ import annotations

from fastapi import APIRouter, Query, Request
from sqlalchemy import func, select

from app.deps import DbSession, Organizer
from app.models import AuditLog
from app.templating import render

router = APIRouter(tags=["admin"])

PAGE_SIZE = 50


@router.get("/admin/audit")
def audit_log(
    request: Request,
    db: DbSession,
    organizer: Organizer,
    actor: str = Query("", max_length=64),
    action: str = Query("", max_length=16),
    entity_type: str = Query("", max_length=64),
    page: int = Query(1, ge=1),
):
    conditions = []
    if actor:
        conditions.append(AuditLog.actor_id == actor)
    if action:
        conditions.append(AuditLog.action == action)
    if entity_type:
        conditions.append(AuditLog.entity_type == entity_type)
    total = db.scalar(select(func.count()).select_from(AuditLog).where(*conditions)) or 0
    rows = db.scalars(
        select(AuditLog)
        .where(*conditions)
        .order_by(AuditLog.id.desc())
        .offset((page - 1) * PAGE_SIZE)
        .limit(PAGE_SIZE)
    ).all()
    actions = sorted(set(db.scalars(select(AuditLog.action)).all()))
    return render(
        request,
        "admin_audit.html",
        rows=rows,
        actions=actions,
        total=total,
        page=page,
        page_size=PAGE_SIZE,
        actor=actor,
        action=action,
        entity_type=entity_type,
    )
