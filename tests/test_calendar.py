"""Tests for the hackathon calendar and schedule view."""


def test_calendar_page_renders(live):
    """The calendar page is public and renders milestone schedule items."""
    res = live.get("/calendar")
    assert res.status_code == 200
    assert "Hackathon Schedule" in res.text
    assert "Submissions Deadline" in res.text
    assert "Judging Window Starts" in res.text
