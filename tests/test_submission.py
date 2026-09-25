import datetime as dt

import pytest
from sqlalchemy import func, select

from app.models import Event, Project, User
from app.security import COOKIE_NAME, create_session
from app.seed import DEFAULT_EVENT_ID, FIXTURE_TOKENS


def _as(client, label):
    client.cookies.set(COOKIE_NAME, FIXTURE_TOKENS[label])


def _session_for(client, user_id, email, role):
    """A session for a user the fixtures do not carry.

    `create_session` flushes without committing, so the commit has to happen
    inside the same `with` block: closing the session first would roll the token
    row straight back out of the database and every request below it would be a
    401 rather than the answer under test.
    """
    with client.factory() as db:
        db.add(User(id=user_id, email=email, name=email.split("@")[0],
                    password_hash="x", role=role, org=None))
        db.commit()
        token = create_session(db, user_id)
        db.commit()
    client.cookies.set(COOKIE_NAME, token)
    return token


def _reopen(client):
    with client.factory() as db:
        event = db.get(Event, DEFAULT_EVENT_ID)
        event.submissions_close = dt.datetime(2099, 1, 1, tzinfo=dt.timezone.utc)
        db.commit()


def test_the_submit_page_needs_a_session(live):
    assert live.get("/projects/new").status_code == 401


def test_the_submit_page_is_refused_to_a_judge(live):
    _as(live, "judge_a")
    assert live.get("/projects/new").status_code == 403
    live.cookies.clear()


def test_the_submit_page_renders_for_a_participant(live):
    _as(live, "participant")
    response = live.get("/projects/new")
    assert response.status_code == 200
    assert 'action="/projects/new"' in response.text
    live.cookies.clear()


def test_the_submit_page_offers_the_seeded_tracks(live):
    _as(live, "participant")
    assert "Developer tools" in live.get("/projects/new").text
    live.cookies.clear()


def test_the_submit_page_says_so_when_the_deadline_has_passed(live):
    """The form stays up on purpose; the refusal is the backend's job."""
    _as(live, "participant")
    assert "Submissions are closed" in live.get("/projects/new").text
    live.cookies.clear()
    _reopen(live)
    _as(live, "participant")
    assert "Submissions are closed" not in live.get("/projects/new").text
    live.cookies.clear()


def test_a_closed_event_refuses_a_json_submission_with_409(live):
    """Acceptance check 3. The exact status, not merely any 4xx."""
    _as(live, "participant")
    response = live.post(
        "/projects/new",
        json={"title": "dogfood-late-submission-probe", "summary": "probe"},
    )
    assert response.status_code == 409
    assert "closed" in response.json()["detail"].lower()
    live.cookies.clear()


def test_a_closed_event_refuses_a_form_submission_too(live):
    _as(live, "participant")
    response = live.post(
        "/projects/new",
        data={"title": "probe", "summary": "probe", "track_id": "trk_01"},
    )
    assert response.status_code == 409
    live.cookies.clear()


def test_a_refused_submission_creates_no_row(live):
    with live.factory() as db:
        before = db.scalar(select(func.count()).select_from(Project))
    _as(live, "participant")
    live.post("/projects/new", json={"title": "probe", "summary": "probe"})
    live.cookies.clear()
    with live.factory() as db:
        assert db.scalar(select(func.count()).select_from(Project)) == before == 41


def test_the_deadline_outranks_body_validation(live):
    """Otherwise check 3 passes because of a 422 rather than the deadline."""
    _as(live, "participant")
    assert live.post("/projects/new", json={}).status_code == 409
    live.cookies.clear()


def test_an_anonymous_submission_is_401_not_409(live):
    assert live.post("/projects/new", json={"title": "probe"}).status_code == 401


def test_an_open_event_accepts_a_submission(live):
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/new",
        json={"title": "Late Night Lantern", "summary": "A test project.",
              "track_id": "trk_01", "repo_url": "https://example.org/x"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].startswith("/projects/prj_")
    live.cookies.clear()


def test_an_accepted_submission_lands_in_the_gallery(live):
    _reopen(live)
    _as(live, "participant")
    location = live.post(
        "/projects/new",
        json={"title": "Kettle Song", "summary": "Another test.", "track_id": "trk_01"},
        follow_redirects=False,
    ).headers["location"]
    live.cookies.clear()
    assert "Kettle Song" in live.get("/projects", params={"q": "kettle"}).text
    assert "Kettle Song" in live.get(location).text


def test_a_new_project_lands_after_every_fixture_in_gallery_order(live):
    """`'0'` sorts before `'n'`, which is the whole reason for the `prj_n` prefix."""
    _reopen(live)
    _as(live, "participant")
    location = live.post(
        "/projects/new",
        json={"title": "Late Night Lantern", "summary": "s", "track_id": "trk_01"},
        follow_redirects=False,
    ).headers["location"]
    live.cookies.clear()
    assert location.removeprefix("/projects/") == "prj_n0042"
    assert "Late Night Lantern" not in live.get("/projects").text
    body = live.get("/projects", params={"page": 2}).text
    assert body.index("Dry Harbour") < body.index("Late Night Lantern")


def test_an_open_event_rejects_a_missing_title(live):
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/new", json={"summary": "no title", "track_id": "trk_01"}
    )
    assert response.status_code == 422
    live.cookies.clear()


def test_an_open_event_rejects_a_short_title(live):
    _reopen(live)
    _as(live, "participant")
    assert live.post(
        "/projects/new", json={"title": "ab", "track_id": "trk_01"}
    ).status_code == 422
    live.cookies.clear()


def test_an_open_event_rejects_an_unknown_track(live):
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/new", json={"title": "Valid Title", "track_id": "trk_99"}
    )
    assert response.status_code == 422
    live.cookies.clear()


@pytest.mark.parametrize(
    "body",
    [
        b'{"title": "Broken"',
        b"[1, 2, 3]",
        b'"a bare string"',
        b"not json at all",
    ],
)
def test_a_json_body_that_is_not_a_submission_is_422_not_500(live, body):
    """A body the route cannot read is a bad request. Letting `ValueError` out of a
    route body is a 500, which is a different class of answer from a refusal."""
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/new", content=body, headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    live.cookies.clear()


def test_a_non_string_title_is_422_not_500(live):
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/new", json={"title": 42, "track_id": "trk_01"}
    )
    assert response.status_code == 422
    live.cookies.clear()


@pytest.mark.parametrize(
    "repo_url",
    [
        "javascript:alert(1)",
        "java\tscript:alert(1)",
        "data:text/html,<script>alert(1)</script>",
        "vbscript:msgbox(1)",
        "//evil.example/x",
        "not-a-url",
    ],
)
def test_a_repo_url_that_is_not_http_is_refused(live, repo_url):
    """`project_detail.html` puts repo_url straight into an href, so the column is a
    sink: autoescaping stops attribute breakout but not a `javascript:` URL."""
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/new",
        json={"title": "Sink Probe", "summary": "s", "track_id": "trk_01",
              "repo_url": repo_url},
    )
    assert response.status_code == 422
    live.cookies.clear()
    with live.factory() as db:
        titles = db.scalars(select(Project.title).where(
            Project.title == "Sink Probe")).all()
        assert list(titles) == []


def test_a_submitted_repo_url_reaches_the_detail_page(live):
    _reopen(live)
    _as(live, "participant")
    location = live.post(
        "/projects/new",
        json={"title": "Hooked", "summary": "s", "track_id": "trk_01",
              "repo_url": "https://example.org/hooked"},
        follow_redirects=False,
    ).headers["location"]
    live.cookies.clear()
    assert 'href="https://example.org/hooked"' in live.get(location).text


def test_an_empty_repo_url_stores_no_link(live):
    _reopen(live)
    _as(live, "participant")
    location = live.post(
        "/projects/new",
        json={"title": "Linkless", "summary": "s", "track_id": "trk_01",
              "repo_url": ""},
        follow_redirects=False,
    ).headers["location"]
    live.cookies.clear()
    with live.factory() as db:
        project = db.get(Project, location.removeprefix("/projects/"))
        assert project.repo_url is None
    assert "Repository" not in live.get(location).text


def test_editing_cannot_smuggle_a_javascript_repo_url(live):
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/prj_01/edit",
        data={"title": "Glass Signal", "summary": "s", "track_id": "trk_04",
              "repo_url": "javascript:alert(1)"},
    )
    assert response.status_code == 422
    live.cookies.clear()
    with live.factory() as db:
        assert db.get(Project, "prj_01").repo_url == "https://example.org/repo/01"


def test_a_submitter_without_a_team_is_refused(live):
    _reopen(live)
    _session_for(live, "usr_lonely", "lonely@example.org", "participant")
    response = live.post(
        "/projects/new", json={"title": "No Team", "track_id": "trk_01"}
    )
    assert response.status_code == 409
    assert "team" in response.json()["detail"].lower()
    live.cookies.clear()


def test_a_participant_cannot_edit_another_teams_project(live):
    _as(live, "participant")
    assert live.get("/projects/prj_02/edit").status_code == 403
    live.cookies.clear()


def test_editing_another_teams_project_is_refused_on_post(live):
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/prj_02/edit",
        data={"title": "Hijacked", "summary": "s", "track_id": "trk_03"},
    )
    assert response.status_code == 403
    live.cookies.clear()
    with live.factory() as db:
        assert db.get(Project, "prj_02").title == "Small Meadow"


def test_an_organizer_or_admin_cannot_edit_a_project_they_do_not_own(live):
    """Self-service, not an admin surface: role does not widen ownership."""
    for role in ("organizer", "admin"):
        _reopen(live)
        if role == "organizer":
            _as(live, "organizer")
        else:
            _session_for(live, "usr_admin", "admin@dogfood.test", "admin")
        assert live.get("/projects/prj_01/edit").status_code == 403, role
        assert live.post(
            "/projects/prj_01/edit",
            data={"title": "Hijacked", "summary": "s", "track_id": "trk_04"},
        ).status_code == 403, role
        live.cookies.clear()
    with live.factory() as db:
        assert db.get(Project, "prj_01").title == "Glass Signal"


def test_a_participant_can_open_their_own_edit_form(live):
    _as(live, "participant")
    response = live.get("/projects/prj_01/edit")
    assert response.status_code == 200
    assert "Glass Signal" in response.text
    live.cookies.clear()


def test_the_edit_form_posts_to_the_project_and_is_prefilled(live):
    _as(live, "participant")
    body = live.get("/projects/prj_01/edit").text
    assert 'action="/projects/prj_01/edit"' in body
    assert "https://example.org/repo/01" in body
    live.cookies.clear()


def test_the_edit_form_says_so_when_the_deadline_has_passed(live):
    _as(live, "participant")
    assert "this edit will be refused" in live.get("/projects/prj_01/edit").text
    live.cookies.clear()


def test_editing_an_unknown_project_is_404(live):
    _as(live, "participant")
    response = live.get("/projects/prj_nope/edit")
    # The route's own 404, not the router's "no path matched", which is also a 404.
    assert response.status_code == 404
    assert response.json()["detail"] == "no such project"
    live.cookies.clear()


def test_editing_after_the_deadline_is_refused(live):
    _as(live, "participant")
    response = live.post(
        "/projects/prj_01/edit",
        data={"title": "Renamed", "summary": "s", "track_id": "trk_04"},
    )
    assert response.status_code == 409
    live.cookies.clear()


def test_the_edit_deadline_also_outranks_body_validation(live):
    _as(live, "participant")
    assert live.post("/projects/prj_01/edit", data={}).status_code == 409
    live.cookies.clear()


def test_editing_before_the_deadline_works(live):
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/prj_01/edit",
        data={"title": "Glass Signal v2", "summary": "Sharper.", "track_id": "trk_04"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    live.cookies.clear()
    assert "Glass Signal v2" in live.get("/projects/prj_01").text


def test_a_cross_origin_form_post_is_refused(live):
    _reopen(live)
    _as(live, "participant")
    response = live.post(
        "/projects/new",
        data={"title": "Evil", "summary": "x", "track_id": "trk_01"},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    live.cookies.clear()


def test_a_matching_origin_post_is_allowed(live):
    """The gate compares against Host; it does not refuse every Origin it sees.
    An absent Origin is the other half, and `test_an_open_event_accepts_a_submission`
    posts one with no Origin at all."""
    _reopen(live)
    _as(live, "participant")
    host = live.get("/projects/new").request.headers["host"]
    response = live.post(
        "/projects/new",
        data={"title": "Same Origin", "summary": "x", "track_id": "trk_01"},
        headers={"Origin": f"http://{host}"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    live.cookies.clear()
