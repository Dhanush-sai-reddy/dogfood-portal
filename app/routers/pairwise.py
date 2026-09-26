from __future__ import annotations

import random
import secrets
from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.deps import DbSession, CurrentUser
from app.models import PairwiseVote, Project, Team, Track, User
from app.templating import render

router = APIRouter(prefix="/pairwise", tags=["pairwise"])


@router.get("")
def pairwise_arena(request: Request, db: DbSession, user: CurrentUser):
    if not user or user.role not in ("judge", "organizer", "admin"):
        raise HTTPException(status_code=403, detail="Judge access required")

    projects = db.scalars(select(Project)).all()
    if len(projects) < 2:
        raise HTTPException(status_code=400, detail="Not enough projects for pairwise comparison")

    # Pick two random distinct projects
    p_a, p_b = random.sample(projects, 2)
    team_a = db.get(Team, p_a.team_id)
    team_b = db.get(Team, p_b.team_id)

    return render(
        request,
        "pairwise.html",
        project_a=p_a,
        project_b=p_b,
        team_a=team_a,
        team_b=team_b,
    )


@router.post("/vote")
def cast_pairwise_vote(
    db: DbSession,
    user: CurrentUser,
    project_a_id: str = Form(...),
    project_b_id: str = Form(...),
    winner_id: str = Form(...),
):
    if not user or user.role not in ("judge", "organizer", "admin"):
        raise HTTPException(status_code=403, detail="Judge access required")

    if winner_id not in (project_a_id, project_b_id):
        raise HTTPException(status_code=400, detail="Invalid winner selection")

    vote_id = f"pw_{secrets.token_hex(8)}"
    vote = PairwiseVote(
        id=vote_id,
        judge_id=user.id,
        project_a_id=project_a_id,
        project_b_id=project_b_id,
        winner_id=winner_id,
    )
    db.add(vote)
    db.commit()

    return RedirectResponse(url="/pairwise", status_code=status.HTTP_303_SEE_OTHER)
