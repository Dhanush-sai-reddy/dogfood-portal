from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent


@dataclass(frozen=True)
class Settings:
    database_url: str
    fixtures_path: Path
    cookie_name: str = "sid"
    session_ttl_days: int = 7
    secure_cookies: bool = False
    host: str = "0.0.0.0"
    port: int = 8080

    @classmethod
    def from_env(cls) -> "Settings":
        return cls(
            database_url=os.environ.get(
                "DOGFOOD_DATABASE_URL",
                f"sqlite+pysqlite:///{REPO_ROOT / 'data' / 'dogfood.db'}",
            ),
            fixtures_path=Path(
                os.environ.get("DOGFOOD_FIXTURES", REPO_ROOT / "fixtures.json")
            ),
            cookie_name=os.environ.get("DOGFOOD_COOKIE_NAME", "sid"),
            session_ttl_days=int(os.environ.get("DOGFOOD_SESSION_TTL_DAYS", "7")),
            secure_cookies=os.environ.get("DOGFOOD_SECURE_COOKIES", "0") == "1",
            host=os.environ.get("DOGFOOD_HOST", "0.0.0.0"),
            port=int(os.environ.get("DOGFOOD_PORT", "8080")),
        )
