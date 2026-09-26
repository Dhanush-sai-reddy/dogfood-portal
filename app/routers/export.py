from __future__ import annotations

import csv
import io
from collections.abc import Iterable, Iterator
from typing import Literal

from fastapi import APIRouter, Query
from fastapi.responses import StreamingResponse

from app.deps import DbSession, Organizer
from app.services import export as export_service

router = APIRouter(tags=["export"])


def _csv_response(rows: Iterable[list[str]], filename: str) -> StreamingResponse:
    """One CSV line per row, sent as the row is produced.

    `rows` is a generator over the caller's still-open session, so the body has to
    be streamed rather than buffered: FastAPI unwinds a `yield` dependency's exit
    stack only after the response has been sent, so the session the query is
    walking outlives the handler.
    """

    def generate() -> Iterator[str]:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        for row in rows:
            buffer.seek(0)
            buffer.truncate(0)
            writer.writerow(row)
            yield buffer.getvalue()

    return StreamingResponse(
        generate(),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


@router.get("/api/export.csv")
def export_scores(db: DbSession, organizer: Organizer) -> StreamingResponse:
    return _csv_response(export_service.row_stream(db), "dogfood-scores.csv")


@router.get("/api/export")
def export_stage(
    db: DbSession,
    organizer: Organizer,
    stage: Literal["submissions", "scores"] = Query("scores"),
) -> StreamingResponse:
    if stage == "submissions":
        return _csv_response(
            export_service.submission_stream(db), "dogfood-submissions.csv"
        )
    return _csv_response(export_service.row_stream(db), "dogfood-scores.csv")
