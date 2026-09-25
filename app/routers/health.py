from fastapi import APIRouter

from app.models import SCHEMA_VERSION

router = APIRouter(tags=["health"])


@router.get("/health")
def health() -> dict[str, object]:
    return {"status": "ok", "schema_version": SCHEMA_VERSION}
