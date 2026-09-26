from __future__ import annotations

from collections.abc import Iterator

from sqlalchemy import select

from app.models import Project, RubricCriterion, Score, Team, Track, User
from app.seed import DEFAULT_EVENT_ID

CSV_HEADER = (
    "project_id", "title", "team", "track", "judge_id", "judge_name",
    "functionality", "quality", "innovation", "composite", "comment",
)
SUBMISSION_HEADER = (
    "project_id", "title", "summary", "team", "track", "repo_url", "submitted_at",
)
DANGEROUS_PREFIXES = ("=", "+", "-", "@", "\t", "\r", "\n")

# The spec's `yield_per(200)`. Every cell of an export comes from text a
# participant typed, so the row count is the one number here an organizer cannot
# bound by hand; the query is walked in batches rather than fetched whole. On
# SQLite this pins the result's row buffer to FETCH_BATCH rows
# (`BufferedRowCursorFetchStrategy.yield_per`) instead of the default 1000, and
# the response body is produced one row at a time as the result is walked.
FETCH_BATCH = 200


def safe_cell(value) -> str:
    """Neutralise spreadsheet formula injection.

    A cell that opens with = + - @ or a control character is executed by Excel
    and Sheets on open. A leading single quote is the only mitigation that
    survives a re-save; quoting alone does not.
    """
    text = "" if value is None else str(value)
    if text.startswith(DANGEROUS_PREFIXES):
        return f"'{text}"
    return text


def composite(criteria: dict[str, int], weights: dict[str, float], max_score: int = 5) -> float:
    """Weighted total, with the weights normalised on read.

    The organizer types raw numbers; dividing by the sum here means a rubric
    saved as 2/1/1 and one saved as 0.5/0.25/0.25 mean the same thing.
    """
    relevant = {k: w for k, w in weights.items() if k in criteria}
    total_weight = sum(relevant.values())
    if total_weight <= 0:
        return 0.0
    return sum(
        (float(criteria[k]) / max_score) * (w / total_weight) for k, w in relevant.items()
    ) * max_score


def _weights(db) -> dict[str, float]:
    return {
        row.key: row.weight
        for row in db.scalars(
            select(RubricCriterion)
            .where(RubricCriterion.event_id == DEFAULT_EVENT_ID)
            .order_by(RubricCriterion.position)
        ).all()
    }


def score_rows(db) -> Iterator[list[str]]:
    """One list per score, produced as the caller walks it.

    The session is the caller's and outlives the handler, so this is a generator
    and not a list: the route hands it straight to the response body, and a row
    nobody has asked for yet is never fetched.
    """
    weights = _weights(db)
    statement = (
        select(Score, Project, Team.name, Track.name, User.name)
        .join(Project, Score.project_id == Project.id)
        .join(Team, Project.team_id == Team.id)
        .join(Track, Project.track_id == Track.id)
        .join(User, Score.judge_id == User.id)
        .order_by(Project.id.asc(), Score.judge_id.asc())
        .execution_options(yield_per=FETCH_BATCH)
    )
    for score, project, team_name, track_name, judge_name in db.execute(statement):
        criteria = dict(score.criteria)
        yield [
            safe_cell(project.id),
            safe_cell(project.title),
            safe_cell(team_name),
            safe_cell(track_name),
            safe_cell(score.judge_id),
            safe_cell(judge_name),
            safe_cell(criteria.get("functionality", "")),
            safe_cell(criteria.get("quality", "")),
            safe_cell(criteria.get("innovation", "")),
            f"{composite(criteria, weights):.4f}",
            safe_cell(score.comment),
        ]


def row_stream(db) -> Iterator[list[str]]:
    yield list(CSV_HEADER)
    yield from score_rows(db)


def submission_stream(db) -> Iterator[list[str]]:
    yield list(SUBMISSION_HEADER)
    statement = (
        select(Project, Team.name, Track.name)
        .join(Team, Project.team_id == Team.id)
        .join(Track, Project.track_id == Track.id)
        .order_by(Project.id.asc())
        .execution_options(yield_per=FETCH_BATCH)
    )
    for project, team_name, track_name in db.execute(statement):
        yield [
            safe_cell(project.id),
            safe_cell(project.title),
            safe_cell(project.summary),
            safe_cell(team_name),
            safe_cell(track_name),
            safe_cell(project.repo_url),
            safe_cell(project.submitted_at),
        ]
