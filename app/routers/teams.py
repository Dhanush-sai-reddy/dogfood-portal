from __future__ import annotations

import secrets
from fastapi import APIRouter, Form, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy import select

from app.deps import DbSession, CurrentUser
from app.models import Team, TeamMember, User
from app.templating import render

router = APIRouter(tags=["teams"])


@router.get("/teams/new")
def new_team_form(request: Request, user: CurrentUser):
    if not user or user.role not in ("participant", "organizer", "admin"):
        raise HTTPException(status_code=403, detail="Participant access required")
    return render(request, "team_new.html")


@router.post("/teams/new")
def create_team(
    request: Request,
    db: DbSession,
    user: CurrentUser,
    name: str = Form(...),
):
    if not user or user.role not in ("participant", "organizer", "admin"):
        raise HTTPException(status_code=403, detail="Participant access required")

    # Check if user already in a team
    existing = db.scalar(
        select(TeamMember).where(TeamMember.user_id == user.id)
    )
    if existing:
        raise HTTPException(status_code=400, detail="You are already in a team")

    team_id = f"tm_{secrets.token_hex(4)}"
    invite_code = secrets.token_hex(6)
    team = Team(id=team_id, name=name.strip(), invite_code=invite_code)
    db.add(team)
    db.flush()

    member = TeamMember(team_id=team_id, user_id=user.id)
    db.add(member)
    db.commit()

    return RedirectResponse(url=f"/teams/{team_id}", status_code=status.HTTP_303_SEE_OTHER)


@router.get("/teams/{team_id}")
def team_detail(request: Request, db: DbSession, user: CurrentUser, team_id: str):
    team = db.get(Team, team_id)
    if not team:
        raise HTTPException(status_code=404, detail="Team not found")

    members = db.scalars(
        select(User)
        .join(TeamMember, User.id == TeamMember.user_id)
        .where(TeamMember.team_id == team_id)
    ).all()

    is_member = any(m.id == user.id for m in members) if user else False

    return render(request, "team_detail.html", team=team, members=members, is_member=is_member)


@router.post("/teams/join")
def join_team(db: DbSession, user: CurrentUser, invite_code: str = Form(...)):
    if not user or user.role not in ("participant", "organizer", "admin"):
        raise HTTPException(status_code=403, detail="Participant access required")

    existing = db.scalar(
        select(TeamMember).where(TeamMember.user_id == user.id)
    )
    if existing:
        raise HTTPException(status_code=400, detail="You are already in a team")

    team = db.scalar(select(Team).where(Team.invite_code == invite_code.strip()))
    if not team:
        raise HTTPException(status_code=404, detail="Invalid invite code")

    # Check team size limit (max 4 members)
    count = db.scalar(select(TeamMember).where(TeamMember.team_id == team.id))
    if count and count >= 4:
        raise HTTPException(status_code=400, detail="Team is full (max 4 members)")

    member = TeamMember(team_id=team.id, user_id=user.id)
    db.add(member)
    db.commit()

    return RedirectResponse(url=f"/teams/{team.id}", status_code=status.HTTP_303_SEE_OTHER)
