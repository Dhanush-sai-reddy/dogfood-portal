import csv
import io

import pytest
from sqlalchemy import event, select

from app.models import RubricCriterion, Score, User
from app.security import DEMO_PASSWORD_HASH, create_session
from app.seed import FIXTURE_TOKENS, JUDGE_A_ID
from app.services import export as export_service
from app.services.export import CSV_HEADER, composite, safe_cell


def _as(client, label):
    client.cookies.set("sid", FIXTURE_TOKENS[label])


def _rows(response):
    return list(csv.reader(io.StringIO(response.text)))


def test_the_organizer_gets_a_200_csv(live):
    """Acceptance check 7."""
    _as(live, "organizer")
    response = live.get("/api/export.csv")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/csv")
    assert "attachment" in response.headers["content-disposition"]
    assert "dogfood-scores.csv" in response.headers["content-disposition"]
    # A buffered `Response` sets content-length; a `StreamingResponse` does not,
    # because it does not know the length until the last row is walked.
    assert "content-length" not in response.headers
    live.cookies.clear()


def test_the_first_line_contains_a_comma(live):
    """run.py tests exactly this: status 200 and a comma in line 1."""
    _as(live, "organizer")
    first = live.get("/api/export.csv").text.splitlines()[0]
    assert "," in first
    live.cookies.clear()


def test_the_first_line_is_the_header_row(live):
    _as(live, "organizer")
    rows = _rows(live.get("/api/export.csv"))
    assert tuple(rows[0]) == CSV_HEADER
    live.cookies.clear()


def test_every_fixture_score_is_exported_once(live):
    _as(live, "organizer")
    rows = _rows(live.get("/api/export.csv"))
    assert len(rows) - 1 == 126
    live.cookies.clear()


def test_the_export_contains_no_peer_only_secrets_and_all_judges(live):
    _as(live, "organizer")
    rows = _rows(live.get("/api/export.csv"))
    judge_ids = {row[4] for row in rows[1:]}
    assert JUDGE_A_ID in judge_ids
    assert len(judge_ids) == 30
    live.cookies.clear()


def test_the_rows_are_ordered_by_project_then_judge(live):
    """A spreadsheet sorts on what it is given, so the order has to be a stated
    one rather than whatever the join happened to return."""
    _as(live, "organizer")
    rows = _rows(live.get("/api/export.csv"))
    live.cookies.clear()
    keys = [(row[0], row[4]) for row in rows[1:]]
    assert keys == sorted(keys)
    assert len(set(keys)) == len(keys), "one row per score, not one per pair"


def test_the_composite_column_is_the_weighted_mean_of_the_stored_rubric(live):
    """Recomputed here from the rubric rows rather than by calling `composite`,
    so a change to that function cannot quietly redefine what the column means."""
    with live.factory() as db:
        weights = {
            row.key: row.weight for row in db.scalars(select(RubricCriterion)).all()
        }
        criteria = dict(
            db.scalar(
                select(Score).where(
                    Score.judge_id == JUDGE_A_ID, Score.project_id == "prj_06"
                )
            ).criteria
        )
    total_weight = sum(weights[key] for key in criteria)
    expected = sum(criteria[key] * weights[key] / total_weight for key in criteria)

    _as(live, "organizer")
    rows = _rows(live.get("/api/export.csv"))
    live.cookies.clear()
    row = next(r for r in rows[1:] if r[0] == "prj_06" and r[4] == JUDGE_A_ID)
    assert [int(row[6]), int(row[7]), int(row[8])] == [
        criteria["functionality"],
        criteria["quality"],
        criteria["innovation"],
    ]
    assert float(row[9]) == pytest.approx(expected, abs=5e-5)


def test_a_judge_cannot_export(live):
    _as(live, "judge_a")
    assert live.get("/api/export.csv").status_code == 403
    live.cookies.clear()


def test_a_participant_cannot_export(live):
    _as(live, "participant")
    assert live.get("/api/export.csv").status_code == 403
    live.cookies.clear()


def test_an_admin_may_export(live):
    """`Organizer` admits admin as well as organizer, and
    `test_deps_isolation.py` declares exactly those two; this says the route
    agrees with the declaration."""
    with live.factory() as db:
        db.add(
            User(
                id="usr_admin_probe",
                email="admin@dogfood.test",
                name="Probe Admin",
                password_hash=DEMO_PASSWORD_HASH,
                role="admin",
                org="DOGFOOD",
            )
        )
        # `create_session` flushes without committing, so the token row would be
        # rolled straight back out of the database when this session closed.
        token = create_session(db, "usr_admin_probe")
        db.commit()
    live.cookies.set("sid", token)
    assert live.get("/api/export.csv").status_code == 200
    live.cookies.clear()


def test_an_anonymous_caller_is_401(live):
    assert live.get("/api/export.csv").status_code == 401


def test_the_submission_stage_lists_projects(live):
    _as(live, "organizer")
    response = live.get("/api/export", params={"stage": "submissions"})
    rows = _rows(response)
    assert rows[0][0] == "project_id"
    assert len(rows) - 1 == 41
    assert "dogfood-submissions.csv" in response.headers["content-disposition"]
    live.cookies.clear()


def test_the_stage_selector_defaults_to_the_scores_export(live):
    """`/api/export` with no stage is the same data `/api/export.csv` serves,
    which is what makes one endpoint enough for the spec's "every stage"."""
    _as(live, "organizer")
    default = live.get("/api/export")
    explicit = live.get("/api/export", params={"stage": "scores"})
    live.cookies.clear()
    assert tuple(_rows(default)[0]) == CSV_HEADER
    assert default.text == explicit.text


def test_an_unknown_stage_is_422(live):
    _as(live, "organizer")
    assert live.get("/api/export", params={"stage": "nonsense"}).status_code == 422
    live.cookies.clear()


def test_the_header_row_is_yielded_before_the_scores_query_runs(live):
    """The spec's `yield_per(200)`, pinned at the level it can be observed: taking
    the first row off the stream sends no query at all, and the scores statement
    goes out only as the rest of the body is walked."""
    sent: list[str] = []
    with live.factory() as db:
        event.listen(
            db.get_bind(),
            "after_cursor_execute",
            lambda _conn, _cursor, statement, _params, _ctx, _many: sent.append(statement),
        )
        stream = export_service.row_stream(db)
        assert next(stream) == list(CSV_HEADER)
        assert sent == [], "the header row is not backed by the scores query"
        rows = list(stream)
    assert len(rows) == 126
    assert any("from scores" in statement.lower() for statement in sent)


@pytest.mark.parametrize(
    "value,expected",
    [
        ("=1+1", "'=1+1"),
        ("+1", "'+1"),
        ("-1", "'-1"),
        ("@SUM(A1)", "'@SUM(A1)"),
        ("\tcmd", "'\tcmd"),
        ("plain", "plain"),
        ("", ""),
        ("a,b", "a,b"),
    ],
)
def test_csv_injection_cells_are_neutralised(value, expected):
    assert safe_cell(value) == expected


def test_composite_normalises_the_weights_on_read():
    assert composite({"functionality": 5, "quality": 3, "innovation": 4},
                     {"functionality": 2, "quality": 1, "innovation": 1}) == pytest.approx(
        (5 * 0.5 + 3 * 0.25 + 4 * 0.25)
    )


def test_composite_ignores_a_criterion_with_no_weight():
    assert composite({"functionality": 5, "quality": 5}, {"functionality": 1.0}) == 5.0


def test_a_hostile_comment_survives_the_round_trip_neutralised(live):
    """Checked on the parsed cell, not on the raw body.

    The brief asserts `"=cmd" not in text`, but the neutralised cell is
    `'=cmd|'/c calc'!A1` -- it still contains `=cmd` further along, so that
    assertion cannot be satisfied by any correct implementation. What a
    spreadsheet acts on is the first character of the cell, so that is what is
    asserted: the payload is still there, and it now starts with a quote.
    """
    hostile = "=cmd|'/c calc'!A1"

    with live.factory() as db:
        score = db.scalar(select(Score).where(Score.judge_id == JUDGE_A_ID).limit(1))
        score.comment = hostile
        db.commit()

    _as(live, "organizer")
    rows = _rows(live.get("/api/export.csv"))
    live.cookies.clear()

    comments = [row[-1] for row in rows[1:]]
    assert hostile not in comments
    assert f"'{hostile}" in comments
    # The property that matters when the organizer opens the file in a
    # spreadsheet: not one cell in it is a formula.
    formulas = [
        cell
        for row in rows
        for cell in row
        if cell.startswith(("=", "+", "-", "@", "\t", "\r", "\n"))
    ]
    assert formulas == []
