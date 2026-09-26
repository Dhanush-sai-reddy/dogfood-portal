"""Tests for configurable judging methodologies."""

from app.models import Assignment, Event, Score
from app.seed import DEFAULT_EVENT_ID, FIXTURE_TOKENS, JUDGE_A_ID
from sqlalchemy import select


def test_admin_settings_update(live):
    """Organizers can update judging configuration via admin settings."""
    res = live.get("/admin/settings", cookies={"sid": FIXTURE_TOKENS["organizer"]})
    assert res.status_code == 200
    assert "Judging Configuration" in res.text

    res = live.post(
        "/admin/settings",
        data={
            "methodology": "points_pool",
            "scale_min": "0",
            "scale_max": "100",
            "points_pool_total": "100",
            "blind_judging": "true",
            "comment_required": "true",
        },
        cookies={"sid": FIXTURE_TOKENS["organizer"]},
        follow_redirects=False,
    )
    assert res.status_code == 303

    with live.factory() as db:
        event = db.get(Event, DEFAULT_EVENT_ID)
        cfg = event.judging_config
        assert cfg["methodology"] == "points_pool"
        assert cfg["scale_min"] == 0
        assert cfg["scale_max"] == 100
        assert cfg["points_pool_total"] == 100
        assert cfg["blind_judging"] is True
        assert cfg["comment_required"] is True


def test_points_pool_validation(live):
    """Points pool methodology enforces exact total sum."""
    with live.factory() as db:
        event = db.get(Event, DEFAULT_EVENT_ID)
        event.judging_config = {
            "methodology": "points_pool",
            "scale_min": 0,
            "scale_max": 100,
            "points_pool_total": 100,
            "blind_judging": False,
            "comment_required": False,
        }
        db.commit()
        assignment = db.scalar(select(Assignment).where(Assignment.judge_id == JUDGE_A_ID))
        project_id = assignment.project_id if assignment else "prj_01"

    res = live.post(
        "/judge/score",
        json={
            "project_id": project_id,
            "criteria": {"functionality": 30, "quality": 30, "innovation": 20},
            "comment": "good",
        },
        cookies={"sid": FIXTURE_TOKENS["judge_a"]},
    )
    assert res.status_code == 422
    assert "100" in res.text

    res = live.post(
        "/judge/score",
        json={
            "project_id": project_id,
            "criteria": {"functionality": 40, "quality": 30, "innovation": 30},
            "comment": "perfect sum",
        },
        cookies={"sid": FIXTURE_TOKENS["judge_a"]},
    )
    assert res.status_code == 200


def test_comment_required_validation(live):
    """Mandatory comments enforcement."""
    with live.factory() as db:
        event = db.get(Event, DEFAULT_EVENT_ID)
        event.judging_config = {
            "methodology": "rubric",
            "scale_min": 1,
            "scale_max": 5,
            "points_pool_total": 100,
            "blind_judging": False,
            "comment_required": True,
        }
        db.commit()
        assignment = db.scalar(select(Assignment).where(Assignment.judge_id == JUDGE_A_ID))
        project_id = assignment.project_id if assignment else "prj_01"

    res = live.post(
        "/judge/score",
        json={
            "project_id": project_id,
            "criteria": {"functionality": 4, "quality": 4, "innovation": 4},
            "comment": None,
        },
        cookies={"sid": FIXTURE_TOKENS["judge_a"]},
    )
    assert res.status_code == 422
    assert "comment is required" in res.text

    res = live.post(
        "/judge/score",
        json={
            "project_id": project_id,
            "criteria": {"functionality": 4, "quality": 4, "innovation": 4},
            "comment": "Here is my feedback.",
        },
        cookies={"sid": FIXTURE_TOKENS["judge_a"]},
    )
    assert res.status_code == 200
