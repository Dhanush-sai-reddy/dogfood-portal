"""Tests for Pairwise Comparison (Elo Judging Mode)."""

from app.security import COOKIE_NAME
from app.seed import FIXTURE_TOKENS


def test_pairwise_arena_requires_judge(live):
    """Pairwise arena is restricted to judges and organizers."""
    live.cookies.set(COOKIE_NAME, FIXTURE_TOKENS["participant"])
    res = live.get("/pairwise")
    assert res.status_code == 403


def test_pairwise_arena_renders_for_judge(live):
    """Judges can view the pairwise comparison arena."""
    live.cookies.set(COOKIE_NAME, FIXTURE_TOKENS["judge_a"])
    res = live.get("/pairwise")
    assert res.status_code == 200
    assert "Pairwise Comparison Arena" in res.text
    assert "Submission A" in res.text
    assert "Submission B" in res.text
