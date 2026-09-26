from __future__ import annotations

from fastapi import APIRouter, Request
from sqlalchemy import func, select

from app.deps import DbSession
from app.models import Project, Score, Team, Track
from app.templating import render

router = APIRouter(tags=["leaderboard"])


@router.get("/leaderboard")
def leaderboard(request: Request, db: DbSession):
    # Query projects with team and track names, plus average/total scores
    stmt = (
        select(
            Project.id,
            Project.title,
            Project.summary,
            Team.name.label("team_name"),
            Track.name.label("track_name"),
            func.coalesce(func.avg(func.json_extract(Score.criteria, '$.functionality') + 
                                  func.json_extract(Score.criteria, '$.quality') + 
                                  func.json_extract(Score.criteria, '$.innovation')), 0).label("avg_score"),
            func.count(Score.id).label("score_count"),
        )
        .join(Team, Project.team_id == Team.id)
        .join(Track, Project.track_id == Track.id)
        .outerjoin(Score, Project.id == Score.project_id)
        .group_by(Project.id)
        .order_by(func.coalesce(func.avg(func.json_extract(Score.criteria, '$.functionality') + 
                                       func.json_extract(Score.criteria, '$.quality') + 
                                       func.json_extract(Score.criteria, '$.innovation')), 0).desc())
    )
    rows = db.execute(stmt).all()
    rankings = [
        {
            "rank": idx + 1,
            "project_id": row.id,
            "title": row.title,
            "summary": row.summary,
            "team_name": row.team_name,
            "track_name": row.track_name,
            "score": round(row.avg_score, 2),
            "score_count": row.score_count,
        }
        for idx, row in enumerate(rows)
    ]
    return render(request, "leaderboard.html", rankings=rankings)
