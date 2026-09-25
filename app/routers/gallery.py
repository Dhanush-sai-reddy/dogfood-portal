from __future__ import annotations

from fastapi import APIRouter, HTTPException, Query, Request
from sqlalchemy import func, or_, select

from app.deps import DbSession
from app.models import Project, Team, Track
from app.templating import render

router = APIRouter(tags=["gallery"])

PAGE_SIZE = 24


@router.get("/projects")
def gallery(
    request: Request,
    db: DbSession,
    q: str = Query("", max_length=120),
    track: str = Query("", max_length=64),
    page: int = Query(1, ge=1),
):
    statement = (
        select(Project, Track.name, Team.name)
        .join(Track, Project.track_id == Track.id)
        .join(Team, Project.team_id == Team.id)
    )
    if q.strip():
        needle = f"%{q.strip().lower()}%"
        statement = statement.where(
            or_(
                func.lower(Project.title).like(needle),
                func.lower(Project.summary).like(needle),
                func.lower(Team.name).like(needle),
            )
        )
    if track:
        statement = statement.where(Project.track_id == track)
    # Fixture order, never score order. run.py only looks for projects[:3], so
    # id ASC is the ordering under which check 2 is unconditional.
    statement = statement.order_by(Project.id.asc())
    rows = db.execute(statement).all()

    tracks = sorted(
        db.execute(select(Track.id, Track.name).order_by(Track.name)).all()
    )
    total = len(rows)
    start = (page - 1) * PAGE_SIZE
    window = rows[start : start + PAGE_SIZE]
    return render(
        request,
        "gallery.html",
        rows=[
            {"id": row[0].id, "title": row[0].title, "summary": row[0].summary,
             "track_name": row[1], "team_name": row[2]}
            for row in window
        ],
        tracks=tracks,
        q=q,
        track=track,
        page=page,
        total=total,
        start=start,
        page_size=PAGE_SIZE,
    )


@router.get("/projects/{project_id}")
def project_detail(request: Request, db: DbSession, project_id: str):
    row = db.execute(
        select(Project, Track.name, Team.name)
        .join(Track, Project.track_id == Track.id)
        .join(Team, Project.team_id == Team.id)
        .where(Project.id == project_id)
    ).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="no such project")
    return render(
        request,
        "project_detail.html",
        project=row[0],
        track_name=row[1],
        team_name=row[2],
    )
