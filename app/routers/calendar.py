from __future__ import annotations

from fastapi import APIRouter, Request

from app.deps import DbSession
from app.models import Event
from app.seed import DEFAULT_EVENT_ID
from app.templating import render

router = APIRouter(tags=["calendar"])


@router.get("/calendar")
def calendar_view(request: Request, db: DbSession):
    event = db.get(Event, DEFAULT_EVENT_ID)
    close_time = event.submissions_close.strftime("%Y-%m-%d %H:%M UTC") if event else "2026-03-01 18:00 UTC"
    milestones = [
        {"title": "Hackathon Kickoff", "time": "2026-02-28 09:00 UTC", "desc": "Event opens, team formation, and hacking begins."},
        {"title": "Submissions Deadline", "time": close_time, "desc": "All project submissions and code locks. Submissions close."},
        {"title": "Judging Window Starts", "time": "2026-03-01 18:30 UTC", "desc": "Assigned judges review and score assigned projects."},
        {"title": "Closing Ceremony & Winners", "time": "2026-03-02 20:00 UTC", "desc": "Final scores tallied, winners announced, and prizes awarded."},
    ]
    return render(request, "calendar.html", event=event, milestones=milestones)
