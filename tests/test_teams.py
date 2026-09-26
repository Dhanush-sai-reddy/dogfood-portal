"""Tests for team formation and invite code flow."""

from app.security import COOKIE_NAME
from app.seed import FIXTURE_TOKENS


def test_create_team_and_join(live):
    """Participants can view team details."""
    live.cookies.set(COOKIE_NAME, FIXTURE_TOKENS["participant"])
    res_team = live.get("/teams/tm_01")
    assert res_team.status_code == 200
    assert "NorthKiln" in res_team.text
