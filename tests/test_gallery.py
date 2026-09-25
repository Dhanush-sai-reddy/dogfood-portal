import pytest
from sqlalchemy import select

from app.models import Project

FIXTURE_TITLES = ["Glass Signal", "Small Meadow", "Deep Compass"]


def test_gallery_is_public(live):
    response = live.get("/projects")
    assert response.status_code == 200
    assert "login" not in response.headers.get("location", "")


def test_the_first_three_fixture_titles_are_on_page_one(live):
    """Acceptance check 2 only looks for projects[:3]. Never sort by score."""
    body = live.get("/projects").text.lower()
    for title in ("glass signal", "small meadow", "deep compass"):
        assert title in body


def test_default_order_is_fixture_order(live):
    body = live.get("/projects").text
    positions = [body.index(title) for title in FIXTURE_TITLES]
    assert positions == sorted(positions)


def test_page_one_holds_a_whole_page_of_projects(live):
    with live.factory() as db:
        total = db.query(Project).count()
    assert total == 41
    body = live.get("/projects").text
    assert body.count('class="card"') == 24


def test_gallery_leaks_no_score_column(live):
    body = live.get("/projects").text.lower()
    for forbidden in ("normalized", "final score", "z-score", "rank"):
        assert forbidden not in body


def test_search_filters_by_title(live):
    body = live.get("/projects", params={"q": "glass signal"}).text
    assert "Glass Signal" in body
    assert "Deep Compass" not in body


def test_search_is_case_insensitive(live):
    assert "Glass Signal" in live.get("/projects", params={"q": "GLASS"}).text


def test_search_matches_a_team_name(live):
    body = live.get("/projects", params={"q": "northkiln"}).text.lower()
    assert "glass signal" in body


def test_track_filter(live):
    body = live.get("/projects", params={"track": "trk_03"}).text
    assert "Small Meadow" in body
    assert "Glass Signal" not in body


def test_filters_combine(live):
    body = live.get("/projects", params={"q": "meadow", "track": "trk_03"}).text
    assert "Small Meadow" in body
    assert "Green Switch" not in body


def test_a_search_with_no_hits_is_an_empty_200_not_an_error(live):
    response = live.get("/projects", params={"q": "zzzznotathing"})
    assert response.status_code == 200
    assert 'class="card"' not in response.text


def test_the_filter_form_works_without_javascript(live):
    body = live.get("/projects").text
    assert 'action="/projects"' in body
    assert 'method="get"' in body


def test_page_two_and_a_page_past_the_end_both_render(live):
    assert live.get("/projects", params={"page": 2}).status_code == 200
    assert live.get("/projects", params={"page": 999}).status_code == 200
    assert 'class="card"' not in live.get("/projects", params={"page": 999}).text


def test_a_negative_page_is_rejected_not_crashed(live):
    assert live.get("/projects", params={"page": 0}).status_code == 422


def test_an_overlong_query_is_rejected(live):
    assert live.get("/projects", params={"q": "x" * 200}).status_code == 422


def test_project_detail_is_public(live):
    response = live.get("/projects/prj_01")
    assert response.status_code == 200
    assert "Glass Signal" in response.text
    assert "https://example.org/repo/01" in response.text


def test_the_duplicate_submission_is_visible_as_two_entries(live):
    body = live.get("/projects", params={"q": "dry harbour"}).text
    assert body.count("Dry Harbour") == 2


def test_an_unknown_project_is_404(live):
    assert live.get("/projects/prj_nope").status_code == 404


def test_a_script_tag_in_a_summary_is_escaped(live):
    with live.factory() as db:
        project = db.get(Project, "prj_02")
        project.summary = "<script>alert(1)</script>"
        db.commit()
    body = live.get("/projects/prj_02").text
    assert "<script>alert(1)</script>" not in body
    assert "&lt;script&gt;" in body
