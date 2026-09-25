from __future__ import annotations

from urllib.parse import urlsplit

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import RedirectResponse
from pydantic import BaseModel, Field, ValidationError, field_validator
from sqlalchemy import func, select

from app.deps import DbSession, Participant
from app.models import Event, Project, TeamMember, Track, utcnow
from app.security import assert_same_origin
from app.seed import DEFAULT_EVENT_ID
from app.templating import render

router = APIRouter(tags=["projects"])


class SubmissionIn(BaseModel):
    title: str = Field(min_length=3, max_length=200)
    summary: str = Field(default="", max_length=4000)
    track_id: str = Field(default="", max_length=64)
    repo_url: str | None = Field(default=None, max_length=500)

    @field_validator("repo_url")
    @classmethod
    def _http_only(cls, value: str | None) -> str | None:
        """`project_detail.html` drops this straight into an `href`, so the column is
        a sink for anyone who can post a form. Autoescaping stops the value breaking
        out of the attribute; it does nothing about the value being a `javascript:`
        URL, so the scheme is decided here, where the input arrives. Empty is the
        absence of a link, not a link to nowhere, so it normalises to `None`.
        """
        if value is None:
            return None
        stripped = value.strip()
        if not stripped:
            return None
        if urlsplit(stripped).scheme.lower() not in ("http", "https"):
            raise ValueError("repo_url must be an http or https URL")
        return stripped


async def read_payload(request: Request) -> dict:
    """run.py posts JSON; the browser posts a form. Accept both.

    A body that claims to be JSON and is not yields `{}` rather than raising:
    `json.JSONDecodeError` and `UnicodeDecodeError` are both `ValueError`, and
    letting one out of a route body is a 500, which is a different class of answer
    from a rejected submission. So does a body that is valid JSON but not an
    object. Both then fail the `title` rule, so a malformed submission and an empty
    one get the same answer.
    """
    if request.headers.get("content-type", "").startswith("application/json"):
        try:
            payload = await request.json()
        except ValueError:
            return {}
        return payload if isinstance(payload, dict) else {}
    form = await request.form()
    return {
        key: (value if isinstance(value, str) else "")
        for key, value in form.items()
    }


def assert_event_open(db: DbSession) -> Event:
    event = db.get(Event, DEFAULT_EVENT_ID)
    if event is None:
        raise HTTPException(status_code=503, detail="no event is configured")
    if not event.is_open():
        raise HTTPException(
            status_code=409,
            detail=(
                f"submissions are closed: {event.name} closed at "
                f"{event.submissions_close.isoformat()}"
            ),
        )
    return event


def _is_closed(db: DbSession) -> bool:
    """Whether a form should announce that its own post will be refused. A missing
    event reads as closed: the form is a courtesy, and a missing event is a 503 once
    the post actually arrives."""
    event = db.get(Event, DEFAULT_EVENT_ID)
    return event is None or not event.is_open()


def _validate(db: DbSession, payload: dict) -> SubmissionIn:
    try:
        parsed = SubmissionIn.model_validate(payload)
    except ValidationError as exc:
        # `include_context=False` drops the `ctx` entry, which for a failed validator
        # is the `ValueError` itself. `detail` goes through `jsonable_encoder`, and a
        # response body that only serialises because an encoder knows how to stringify
        # an exception is a 500 waiting for the next version.
        raise HTTPException(
            status_code=422, detail=exc.errors(include_url=False, include_context=False)
        ) from exc
    if parsed.track_id and db.get(Track, parsed.track_id) is None:
        raise HTTPException(status_code=422, detail=f"unknown track {parsed.track_id}")
    return parsed


def _team_of(db: DbSession, user_id: str) -> str:
    team_id = db.scalar(select(TeamMember.team_id).where(TeamMember.user_id == user_id))
    if team_id is None:
        raise HTTPException(
            status_code=409,
            detail="you are not on a team yet, so there is nothing to submit to",
        )
    return team_id


def _track_choices(db: DbSession) -> list[tuple[str, str]]:
    return list(db.execute(select(Track.id, Track.name).order_by(Track.name)).all())


def _new_project_id(db: DbSession) -> str:
    # Monotonic, not hash-derived: a hash of (user, title, now) collides with a
    # fixture id on restart under PYTHONHASHSEED randomisation. The `n` also sorts
    # every submission after `prj_41` in the gallery's `id ASC` order.
    count = db.scalar(select(func.count()).select_from(Project)) or 0
    return f"prj_n{count + 1:04d}"


@router.get("/projects/new")
def submit_form(request: Request, db: DbSession, me: Participant):
    return render(
        request,
        "submit.html",
        tracks=_track_choices(db),
        form={},
        error=None,
        closed=_is_closed(db),
    )


@router.post("/projects/new")
async def submit(request: Request, db: DbSession, me: Participant):
    assert_same_origin(request)
    assert_event_open(db)  # before validation, on purpose
    parsed = _validate(db, await read_payload(request))
    team_id = _team_of(db, me.id)
    track_id = parsed.track_id or _track_choices(db)[0][0]
    project = Project(
        id=_new_project_id(db),
        team_id=team_id,
        track_id=track_id,
        title=parsed.title,
        summary=parsed.summary,
        repo_url=parsed.repo_url,
        is_draft=False,
        submitted_at=utcnow(),
        updated_at=utcnow(),
    )
    db.add(project)
    db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)


def _owned_project(db: DbSession, project_id: str, user_id: str) -> Project:
    project = db.get(Project, project_id)
    if project is None:
        raise HTTPException(status_code=404, detail="no such project")
    team_ids = set(
        db.scalars(
            select(TeamMember.team_id).where(TeamMember.user_id == user_id)
        ).all()
    )
    if project.team_id not in team_ids:
        raise HTTPException(
            status_code=403, detail="this project belongs to another team"
        )
    return project


@router.get("/projects/{project_id}/edit")
def edit_form(request: Request, db: DbSession, me: Participant, project_id: str):
    project = _owned_project(db, project_id, me.id)
    return render(
        request,
        "edit_project.html",
        project=project,
        tracks=_track_choices(db),
        form={"title": project.title, "summary": project.summary,
              "track_id": project.track_id, "repo_url": project.repo_url or ""},
        error=None,
        closed=_is_closed(db),
    )


@router.post("/projects/{project_id}/edit")
async def edit(request: Request, db: DbSession, me: Participant, project_id: str):
    assert_same_origin(request)
    assert_event_open(db)
    project = _owned_project(db, project_id, me.id)
    parsed = _validate(db, await read_payload(request))
    project.title = parsed.title
    project.summary = parsed.summary
    project.track_id = parsed.track_id or project.track_id
    project.repo_url = parsed.repo_url
    project.updated_at = utcnow()
    db.commit()
    return RedirectResponse(f"/projects/{project.id}", status_code=303)
