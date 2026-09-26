from __future__ import annotations

from fastapi import APIRouter, Query, Request, HTTPException
from fastapi.responses import RedirectResponse
from sqlalchemy import func, select

from app.deps import DbSession, Organizer
from app.models import AuditLog, Event
from app.security import assert_same_origin
from app.seed import DEFAULT_EVENT_ID
from app.templating import render

router = APIRouter(tags=["admin"])

PAGE_SIZE = 50


@router.get("/admin/settings")
def settings_get(request: Request, db: DbSession, organizer: Organizer):
    event = db.get(Event, DEFAULT_EVENT_ID)
    config = event.judging_config if event and event.judging_config else {
        "methodology": "rubric",
        "scale_min": 1,
        "scale_max": 5,
        "points_pool_total": 100,
        "blind_judging": False,
        "comment_required": False,
    }
    return render(request, "admin_settings.html", config=config)


@router.post("/admin/settings")
async def settings_post(request: Request, db: DbSession, organizer: Organizer):
    assert_same_origin(request)
    form = await request.form()
    event = db.get(Event, DEFAULT_EVENT_ID)
    if event is None:
        raise HTTPException(status_code=404, detail="event not found")
    
    methodology = str(form.get("methodology", "rubric"))
    try:
        scale_min = int(form.get("scale_min", 1))
        scale_max = int(form.get("scale_max", 5))
        points_pool_total = int(form.get("points_pool_total", 100))
    except ValueError:
        raise HTTPException(status_code=422, detail="invalid numeric values")

    blind_judging = form.get("blind_judging") == "true"
    comment_required = form.get("comment_required") == "true"

    event.judging_config = {
        "methodology": methodology,
        "scale_min": scale_min,
        "scale_max": scale_max,
        "points_pool_total": points_pool_total,
        "blind_judging": blind_judging,
        "comment_required": comment_required,
    }
    db.commit()
    return RedirectResponse("/admin/settings", status_code=303)


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
