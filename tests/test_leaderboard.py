"""Tests for the public live leaderboard."""


def test_leaderboard_renders(live):
    """The leaderboard page is public and renders ranked submissions."""
    res = live.get("/leaderboard")
    assert res.status_code == 200
    assert "Live Leaderboard" in res.text
    assert "Glass Signal" in res.text  # top project from fixture order / score
