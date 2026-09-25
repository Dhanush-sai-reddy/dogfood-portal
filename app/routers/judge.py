from __future__ import annotations

import datetime as dt

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ValidationError
from sqlalchemy import select

from app.deps import DbSession, Judge
from app.models import (
    Assignment, JudgeProfile, Project, RubricCriterion, Score, utcnow,
)
from app.security import assert_same_origin
from app.seed import DEFAULT_EVENT_ID
from app.templating import render

router = APIRouter(tags=["judge"])

CRITERION_KEYS = ("functionality", "quality", "innovation")


class ScoreOut(BaseModel):
    project_id: str
    project_title: str
    track_id: str
    criteria: dict[str, int]
    comment: str | None
    updated_at: dt.datetime


class ScoreIn(BaseModel):
    project_id: str = Field(max_length=64)
    criteria: dict[str, int]
    comment: str | None = Field(default=None, max_length=4000)


def judge_track_ids(db, judge) -> list[str]:
    """The tracks this judge is scoped to.

    An empty list is the fail-closed sentinel, not a wildcard: a judge with no
    profile, or a profile with no tracks, is scoped to nothing and so sees nothing.
    `IN ()` is false in SQL, which is the behaviour wanted here, and the only thing
    standing between a misconfigured judge and the whole event.
    """
    profile = db.get(JudgeProfile, judge.id)
    return list(profile.track_ids) if profile is not None else []


def _scoped_scores(db, judge):
    """The one query behind both surfaces. Identity is the session's, never the
    request's: it is the WHERE clause, so a row that is not this judge's own cannot
    reach either the API or the console."""
    return (
        select(Score, Project)
        .join(Project, Score.project_id == Project.id)
        .where(
            Score.judge_id == judge.id,
            Project.track_id.in_(judge_track_ids(db, judge)),
        )
        .order_by(Project.id.asc())
    )


def own_scores(db, judge) -> list[ScoreOut]:
    return [
        ScoreOut(
            project_id=project.id,
            project_title=project.title,
            track_id=project.track_id,
            criteria=dict(score.criteria),
            comment=score.comment,
            updated_at=score.updated_at,
        )
        for score, project in db.execute(_scoped_scores(db, judge)).all()
    ]


def _own_assignments(db, judge) -> list[tuple[Assignment, Project]]:
    """The rows the console lists: this judge's assignments, in this judge's tracks.

    Deliberately carries no score data. The values the console renders come from
    `own_scores` alone, so a second query reading somebody else's score cannot be
    written here without the console showing it.
    """
    return db.execute(
        select(Assignment, Project)
        .join(Project, Assignment.project_id == Project.id)
        .where(
            Assignment.judge_id == judge.id,
            Project.track_id.in_(judge_track_ids(db, judge)),
        )
        .order_by(Project.id.asc())
    ).all()


async def read_score_payload(request: Request) -> dict:
    """The browser posts a form; run.py posts JSON. Accept both.

    A body that claims JSON and is not yields `{}` rather than raising, and criterion
    values are handed to the validator as the strings a form sends rather than cast
    here: `int("great")` is a `ValueError` inside a route body, which is a 500 where a
    malformed score deserves the same 422 an empty one gets.
    """
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            payload = await request.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}
    form = await request.form()
    payload: dict = {}
    for criterion in CRITERION_KEYS:
        value = form.get(criterion)
        if value not in (None, ""):
            payload.setdefault("criteria", {})[criterion] = value
    payload["project_id"] = str(form.get("project_id", ""))
    payload["comment"] = str(form.get("comment", "")) or None
    return payload


@router.get("/api/judge/scores")
def my_scores(request: Request, db: DbSession, judge: Judge) -> list[ScoreOut]:
    # A judge may only ever read their own scores. Identity comes from the session;
    # the parameter is only ever allowed to agree with it.
    requested = request.query_params.get("judge")
    if requested is not None and requested != judge.id:
        raise HTTPException(
            status_code=403, detail="judges may only read their own scores"
        )
    return own_scores(db, judge)


@router.get("/judge")
def console(request: Request, db: DbSession, judge: Judge) -> None:
    rubric = db.scalars(
        select(RubricCriterion)
        .where(RubricCriterion.event_id == DEFAULT_EVENT_ID)
        .order_by(RubricCriterion.position)
    ).all()
    scores = {row.project_id: row for row in own_scores(db, judge)}
    return render(
        request,
        "judge_console.html",
        rows=[
            {
                "project_id": project.id,
                "title": project.title,
                "status": assignment.status,
                "criteria": dict(scores[project.id].criteria) if project.id in scores else {},
                "comment": scores[project.id].comment if project.id in scores else None,
            }
            for assignment, project in _own_assignments(db, judge)
        ],
        rubric=[{"key": c.key, "label": c.label, "weight": c.weight,
                 "max_score": c.max_score} for c in rubric],
    )


@router.post("/judge/score")
async def save_score(request: Request, db: DbSession, judge: Judge):
    assert_same_origin(request)
    try:
        payload = ScoreIn.model_validate(await read_score_payload(request))
    except ValidationError as exc:
        # As in `projects.py`: `detail` goes through `jsonable_encoder`, and an
        # exception in `ctx` is a 500 waiting for the next version.
        raise HTTPException(
            status_code=422, detail=exc.errors(include_url=False, include_context=False)
        ) from exc

    assignment = db.scalar(
        select(Assignment).where(
            Assignment.judge_id == judge.id,
            Assignment.project_id == payload.project_id,
        )
    )
    if assignment is None:
        raise HTTPException(status_code=403, detail="that project is not assigned to you")

    allowed = judge_track_ids(db, judge)
    project = db.get(Project, payload.project_id)
    if project is None or project.track_id not in allowed:
        raise HTTPException(status_code=403, detail="that project is outside your tracks")

    existing = db.scalar(
        select(Score).where(
            Score.judge_id == judge.id, Score.project_id == payload.project_id
        )
    )
    if existing is None:
        db.add(
            Score(
                id=f"score_{judge.id}_{payload.project_id}",
                judge_id=judge.id,
                project_id=payload.project_id,
                criteria=payload.criteria,
                comment=payload.comment,
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
    else:
        existing.criteria = payload.criteria
        existing.comment = payload.comment
        existing.updated_at = utcnow()
    assignment.status = "submitted"
    db.commit()

    if request.headers.get("content-type", "").startswith("application/json"):
        return {"saved": True, "project_id": payload.project_id}
    return RedirectResponse("/judge", status_code=303)
