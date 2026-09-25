import re

from sqlalchemy import func, select

from app.models import Assignment, JudgeProfile, Project, Score, utcnow
from app.security import COOKIE_NAME
from app.seed import FIXTURE_TOKENS, JUDGE_A_ID, JUDGE_B_ID

PEER_COMMENT = "PEER COMMENT MUST NOT RENDER"


def _as(client, label):
    client.cookies.set(COOKIE_NAME, FIXTURE_TOKENS[label])


def _assigned_to_a(live):
    """`(project_id, title)` for everything judge A was actually given."""
    with live.factory() as db:
        return db.execute(
            select(Project.id, Project.title)
            .join(Assignment, Assignment.project_id == Project.id)
            .where(Assignment.judge_id == JUDGE_A_ID)
            .order_by(Project.id)
        ).all()


def _first_assignment(live):
    with live.factory() as db:
        return db.scalar(
            select(Assignment.project_id)
            .where(Assignment.judge_id == JUDGE_A_ID)
            .order_by(Assignment.project_id)
            .limit(1)
        )


def _drop_tracks(live, judge_id):
    with live.factory() as db:
        profile = db.get(JudgeProfile, judge_id)
        profile.track_ids = []
        db.commit()


def test_a_judge_reads_their_own_scores_with_200(live):
    """Acceptance check 4."""
    _as(live, "judge_a")
    response = live.get("/api/judge/scores")
    assert response.status_code == 200
    body = response.json()
    assert len(body) == 11
    assert {row["project_id"] for row in body}
    live.cookies.clear()


def test_every_returned_row_belongs_to_the_caller(live):
    _as(live, "judge_a")
    for row in live.get("/api/judge/scores").json():
        assert row["project_id"].startswith("prj_")
    live.cookies.clear()
    with live.factory() as db:
        pairs = {(s.judge_id, s.project_id) for s in db.scalars(select(Score)).all()}
    _as(live, "judge_a")
    assert all(
        (JUDGE_A_ID, row["project_id"]) in pairs
        for row in live.get("/api/judge/scores").json()
    )
    live.cookies.clear()


def test_a_judge_is_refused_another_judges_scores_with_403(live):
    """Acceptance check 5 — the one the spec calls the most important."""
    _as(live, "judge_b")
    response = live.get("/api/judge/scores", params={"judge": JUDGE_A_ID})
    assert response.status_code == 403
    live.cookies.clear()


def test_the_refusal_also_applies_to_an_email_address_instead_of_an_id(live):
    _as(live, "judge_b")
    assert live.get(
        "/api/judge/scores", params={"judge": "diego.herrera@example.org"}
    ).status_code == 403
    live.cookies.clear()


def test_the_refusal_leaks_no_score_data_in_the_body(live):
    _as(live, "judge_b")
    response = live.get("/api/judge/scores", params={"judge": JUDGE_A_ID})
    assert response.status_code == 403
    assert "criteria" not in response.text
    live.cookies.clear()


def test_a_judge_may_name_themselves(live):
    """The other half of the asymmetry: agreeing with the session is allowed, and it
    answers with the same rows. The length assertion is what stops this passing on
    two empty lists."""
    _as(live, "judge_a")
    plain = live.get("/api/judge/scores").json()
    named = live.get("/api/judge/scores", params={"judge": JUDGE_A_ID}).json()
    assert len(plain) == 11
    assert plain == named
    live.cookies.clear()


def test_judge_a_and_judge_b_see_different_rows(live):
    _as(live, "judge_a")
    a = {row["project_id"] for row in live.get("/api/judge/scores").json()}
    live.cookies.clear()
    _as(live, "judge_b")
    b = {row["project_id"] for row in live.get("/api/judge/scores").json()}
    live.cookies.clear()
    assert a != b
    assert len(a) == 11 and len(b) == 10


def test_a_participant_is_refused_with_403(live):
    """Acceptance check 6."""
    _as(live, "participant")
    assert live.get("/api/judge/scores").status_code == 403
    live.cookies.clear()


def test_an_anonymous_caller_is_401(live):
    assert live.get("/api/judge/scores").status_code == 401


def test_an_organizer_is_refused_the_judge_api(live):
    """The organizer has its own surfaces; the judge API stays judge-only."""
    _as(live, "organizer")
    assert live.get("/api/judge/scores").status_code == 403
    live.cookies.clear()


def test_returned_rows_are_confined_to_the_judges_tracks(live):
    """The fixtures only ever score a judge inside their own tracks, so the assertion
    below holds whatever the query does. An out-of-track score row is written first,
    which is what makes the track filter the thing being tested rather than the data."""
    with live.factory() as db:
        allowed = set(db.get(JudgeProfile, JUDGE_A_ID).track_ids)
        assigned = {
            row.project_id
            for row in db.scalars(
                select(Assignment).where(Assignment.judge_id == JUDGE_A_ID)
            ).all()
        }
        outside = db.scalar(
            select(Project.id)
            .where(Project.track_id.not_in(list(allowed)), Project.id.not_in(list(assigned)))
            .limit(1)
        )
        assert outside is not None, "the fixtures must hold a project outside judge A's tracks"
        db.add(
            Score(
                id="score_outside_track",
                judge_id=JUDGE_A_ID,
                project_id=outside,
                criteria={"functionality": 5, "quality": 5, "innovation": 5},
                comment="Outside every track this judge holds.",
                created_at=utcnow(),
                updated_at=utcnow(),
            )
        )
        db.commit()
        track_of = dict(db.execute(select(Project.id, Project.track_id)).all())

    _as(live, "judge_a")
    rows = live.get("/api/judge/scores").json()
    assert len(rows) == 11
    assert outside not in {row["project_id"] for row in rows}
    assert all(track_of[row["project_id"]] in allowed for row in rows)
    live.cookies.clear()


def test_a_judge_with_no_tracks_sees_nothing_rather_than_everything(live):
    """The fail-closed sentinel. An empty track list is not a wildcard: a judge with
    no scoping configured sees no projects, on the API and on the console alike. Read
    the rows first, so this cannot pass by the route answering empty either way.
    """
    _as(live, "judge_a")
    assert len(live.get("/api/judge/scores").json()) == 11
    console = live.get("/judge")
    assert console.status_code == 200
    assert "prj_" in console.text
    live.cookies.clear()

    _drop_tracks(live, JUDGE_A_ID)

    _as(live, "judge_a")
    assert live.get("/api/judge/scores").json() == []
    console = live.get("/judge")
    assert console.status_code == 200
    assert "prj_" not in console.text
    live.cookies.clear()


def test_the_console_shows_only_the_callers_own_rows(live):
    """Acceptance check 4, on the HTML surface. The expected titles come from the
    caller's own assignments, so the assertion cannot name a project this judge was
    never given."""
    assigned = _assigned_to_a(live)
    _as(live, "judge_a")
    body = live.get("/judge").text
    assert body.count("<tr") >= len(assigned)
    for _, title in assigned:
        assert title in body
    live.cookies.clear()


def test_the_console_renders_only_projects_from_the_callers_own_assignments(live):
    """Set equality, not a count: one extra row is a disclosure, one missing row is a
    broken console, and only a set tells the two apart."""
    assigned = {project_id for project_id, _ in _assigned_to_a(live)}
    _as(live, "judge_a")
    body = live.get("/judge").text
    assert set(re.findall(r"prj_[0-9a-z_]+", body)) == assigned
    live.cookies.clear()


def test_the_console_never_renders_a_peers_score(live):
    """Every project the caller is assigned is also assigned to peers, and those peers
    have scored it. Rewrite all of their rows to a value the caller's own data cannot
    contain — a fixture score is never 0 — and none of it may surface, whichever
    peer's row the console happened to read.

    This is what makes the shared query worth having: a console with its own
    peer-inclusive score source passes on the projects where a peer's numbers happen
    to match, and fails on none of them.
    """
    with live.factory() as db:
        assigned = [
            row.project_id
            for row in db.scalars(
                select(Assignment).where(Assignment.judge_id == JUDGE_A_ID)
            ).all()
        ]
        own = db.scalar(
            select(Score).where(
                Score.judge_id == JUDGE_A_ID, Score.project_id == assigned[0]
            )
        )
        peers = db.scalars(
            select(Score).where(
                Score.project_id.in_(assigned), Score.judge_id != JUDGE_A_ID
            )
        ).all()
        assert peers, "the fixtures must hold peer scores on the caller's projects"
        for row in peers:
            row.comment = PEER_COMMENT
            row.criteria = {"functionality": 0, "quality": 0, "innovation": 0}
        db.commit()

    _as(live, "judge_a")
    body = live.get("/judge").text
    # The control, or the two assertions below would also hold on an empty console.
    assert body.count("<tr") == len(assigned) + 1
    assert own.comment in body
    assert f'value="{own.criteria["functionality"]}"' in body
    assert PEER_COMMENT not in body
    assert 'value="0"' not in body
    live.cookies.clear()


def test_the_console_shows_the_rubric_weights(live):
    _as(live, "judge_a")
    body = live.get("/judge").text
    for label in ("Functionality", "Quality", "Innovation"):
        assert label in body
    assert "max 5" in body
    live.cookies.clear()


def test_the_console_is_403_for_a_participant_and_401_for_nobody(live):
    _as(live, "participant")
    assert live.get("/judge").status_code == 403
    live.cookies.clear()
    assert live.get("/judge").status_code == 401


def test_only_a_judge_may_post_a_score(live):
    """The write side carries the same guard as the read side, and a refused post
    leaves no row behind for whoever the caller named."""
    target = _first_assignment(live)
    payload = {
        "project_id": target,
        "criteria": {"functionality": 1, "quality": 1, "innovation": 1},
    }
    with live.factory() as db:
        before = db.scalar(
            select(func.count())
            .select_from(Score)
            .where(Score.judge_id == JUDGE_B_ID, Score.project_id == target)
        )
    assert live.post("/judge/score", json=payload).status_code == 401
    for label in ("participant", "organizer"):
        _as(live, label)
        assert live.post("/judge/score", json=payload).status_code == 403, label
        live.cookies.clear()
    with live.factory() as db:
        after = db.scalar(
            select(func.count())
            .select_from(Score)
            .where(Score.judge_id == JUDGE_B_ID, Score.project_id == target)
        )
        assert after == before


def test_scoring_writes_only_the_callers_own_row(live):
    target = _first_assignment(live)
    _as(live, "judge_a")
    response = live.post(
        "/judge/score",
        json={"project_id": target, "criteria": {"functionality": 5, "quality": 5,
                                                  "innovation": 5},
              "comment": "Excellent", "judge_id": JUDGE_B_ID},
    )
    assert response.status_code == 200
    assert response.json() == {"saved": True, "project_id": target}
    live.cookies.clear()
    with live.factory() as db:
        row = db.scalar(
            select(Score).where(Score.judge_id == JUDGE_A_ID, Score.project_id == target)
        )
        assert row is not None
        assert row.criteria == {"functionality": 5, "quality": 5, "innovation": 5}
        # the spoofed judge_id in the body was ignored, not honoured. This project is
        # already scored, so the write took the update branch; the insert branch is
        # `test_a_first_time_score_is_written_under_the_callers_own_identity`.
        peer = db.scalar(
            select(Score).where(Score.judge_id == JUDGE_B_ID, Score.project_id == target)
        )
        assert peer is None or peer.comment != "Excellent"


def test_a_judge_id_in_the_body_is_ignored_rather_than_refused(live):
    """Silently dropped, not rejected: echoing it back would answer the question
    "does that judge exist?", which is not this route's business."""
    target = _first_assignment(live)
    _as(live, "judge_a")
    response = live.post(
        "/judge/score",
        json={"project_id": target, "criteria": {"functionality": 4, "quality": 4,
                                                  "innovation": 4},
              "judge_id": "jdg_does_not_exist"},
    )
    assert response.status_code == 200
    live.cookies.clear()
    with live.factory() as db:
        row = db.scalar(
            select(Score).where(Score.judge_id == JUDGE_A_ID, Score.project_id == target)
        )
        assert row is not None and row.criteria["functionality"] == 4


def test_a_first_time_score_is_written_under_the_callers_own_identity(live):
    """The insert branch, which the other tests here never reach: judge A has already
    scored every project they were assigned, so an insert has to be arranged before it
    can be tested. A mutation that took `judge_id` from the body instead of the
    session passes every other test in this file while this one is broken."""
    with live.factory() as db:
        assigned = [
            row.project_id
            for row in db.scalars(
                select(Assignment).where(Assignment.judge_id == JUDGE_A_ID)
            ).all()
        ]
        scored = {(s.judge_id, s.project_id) for s in db.scalars(select(Score)).all()}
        # assigned to the caller, already scored by them, and not scored by the peer:
        # so a spoofed write would create a row that nothing else collides with.
        target = next(
            p for p in assigned
            if (JUDGE_A_ID, p) in scored and (JUDGE_B_ID, p) not in scored
        )
        db.delete(
            db.scalar(
                select(Score).where(
                    Score.judge_id == JUDGE_A_ID, Score.project_id == target
                )
            )
        )
        db.commit()

    _as(live, "judge_a")
    response = live.post(
        "/judge/score",
        json={"project_id": target, "criteria": {"functionality": 5, "quality": 4,
                                                  "innovation": 3},
              "comment": "First pass.", "judge_id": JUDGE_B_ID},
    )
    assert response.status_code == 200
    live.cookies.clear()
    with live.factory() as db:
        row = db.scalar(
            select(Score).where(Score.judge_id == JUDGE_A_ID, Score.project_id == target)
        )
        assert row is not None
        assert row.criteria == {"functionality": 5, "quality": 4, "innovation": 3}
        assert row.comment == "First pass."
        assert db.scalar(
            select(Score).where(Score.judge_id == JUDGE_B_ID, Score.project_id == target)
        ) is None


def test_a_cross_origin_score_post_is_refused(live):
    target = _first_assignment(live)
    with live.factory() as db:
        before = db.scalar(
            select(Score.criteria).where(
                Score.judge_id == JUDGE_A_ID, Score.project_id == target
            )
        )
    _as(live, "judge_a")
    response = live.post(
        "/judge/score",
        json={"project_id": target, "criteria": {"functionality": 1, "quality": 1,
                                                  "innovation": 1}},
        headers={"Origin": "https://evil.example"},
    )
    assert response.status_code == 403
    live.cookies.clear()
    with live.factory() as db:
        assert db.scalar(
            select(Score.criteria).where(
                Score.judge_id == JUDGE_A_ID, Score.project_id == target
            )
        ) == before


def test_scoring_an_unassigned_project_is_403(live):
    """Outside the judge's tracks, so not theirs to score."""
    with live.factory() as db:
        allowed = set(db.get(JudgeProfile, JUDGE_A_ID).track_ids)
        foreign = db.scalar(
            select(Project.id).where(Project.track_id.not_in(list(allowed))).limit(1)
        )
    _as(live, "judge_a")
    response = live.post(
        "/judge/score",
        json={"project_id": foreign,
              "criteria": {"functionality": 3, "quality": 3, "innovation": 3}},
    )
    assert response.status_code == 403
    live.cookies.clear()


def test_scoring_an_in_track_but_unassigned_project_is_403(live):
    """The other half of the refusal. The project's track is one of the judge's own,
    so only the assignment check can turn this away."""
    with live.factory() as db:
        allowed = set(db.get(JudgeProfile, JUDGE_A_ID).track_ids)
        assigned = set(
            db.scalars(
                select(Assignment.project_id).where(Assignment.judge_id == JUDGE_A_ID)
            ).all()
        )
        unassigned = db.scalar(
            select(Project.id)
            .where(Project.track_id.in_(list(allowed)), Project.id.not_in(list(assigned)))
            .limit(1)
        )
    assert unassigned is not None, "the fixtures must hold an in-track project judge A lacks"
    _as(live, "judge_a")
    response = live.post(
        "/judge/score",
        json={"project_id": unassigned,
              "criteria": {"functionality": 3, "quality": 3, "innovation": 3}},
    )
    assert response.status_code == 403
    live.cookies.clear()
    with live.factory() as db:
        assert db.scalar(
            select(Score).where(Score.judge_id == JUDGE_A_ID, Score.project_id == unassigned)
        ) is None


def test_rescoring_updates_in_place_rather_than_duplicating(live):
    target = _first_assignment(live)
    _as(live, "judge_a")
    live.post(
        "/judge/score",
        json={"project_id": target, "criteria": {"functionality": 2, "quality": 2,
                                                  "innovation": 2},
              "comment": "Reconsidered."},
    )
    live.cookies.clear()
    with live.factory() as db:
        rows = db.scalars(
            select(Score).where(Score.judge_id == JUDGE_A_ID, Score.project_id == target)
        ).all()
        assert len(rows) == 1
        assert rows[0].criteria["functionality"] == 2
        assert rows[0].comment == "Reconsidered."


def test_the_console_form_post_saves_and_redirects(live):
    """The console submits a form, so the form branch of the payload reader is the
    path the UI actually takes."""
    target = _first_assignment(live)
    _as(live, "judge_a")
    response = live.post(
        "/judge/score",
        data={"project_id": target, "functionality": "4", "quality": "3",
              "innovation": "2", "comment": "Straight from the form."},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"] == "/judge"
    live.cookies.clear()
    with live.factory() as db:
        row = db.scalar(
            select(Score).where(Score.judge_id == JUDGE_A_ID, Score.project_id == target)
        )
        assert row.criteria == {"functionality": 4, "quality": 3, "innovation": 2}
        assert row.comment == "Straight from the form."


def test_a_non_numeric_criterion_is_422_not_500(live):
    target = _first_assignment(live)
    _as(live, "judge_a")
    response = live.post(
        "/judge/score",
        data={"project_id": target, "functionality": "great", "quality": "3",
              "innovation": "2"},
    )
    assert response.status_code == 422
    live.cookies.clear()


def test_a_json_body_that_is_not_a_score_is_422_not_500(live):
    _as(live, "judge_a")
    response = live.post(
        "/judge/score", content=b'{"project_id"', headers={"content-type": "application/json"}
    )
    assert response.status_code == 422
    live.cookies.clear()
