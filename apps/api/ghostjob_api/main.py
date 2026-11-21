"""FastAPI entry point.

Run locally with: make api  (or: uv run uvicorn ghostjob_api.main:app --app-dir apps/api)
"""

from datetime import datetime
from typing import Annotated, Literal

from fastapi import Depends, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel

from ghostjob_api import __version__, db
from ghostjob_api.config import Settings, get_settings

app = FastAPI(title="GhostJob API", version=__version__)

app.add_middleware(
    CORSMiddleware,
    allow_origins=get_settings().cors_origins,
    allow_methods=["GET", "POST", "DELETE"],
    allow_headers=["*"],
)


class Health(BaseModel):
    status: Literal["ok"]
    db: Literal["ok", "unavailable"]
    version: str
    # Filled in from the pipeline_runs and postings tables once they exist (Phase 1).
    last_run_at: datetime | None = None
    postings_active: int | None = None


@app.get("/health", response_model=Health)
def health(settings: Annotated[Settings, Depends(get_settings)]) -> Health:
    """The API process is up. `db` reports whether Postgres is reachable."""
    db_state: Literal["ok", "unavailable"] = (
        "ok" if db.ping(settings.database_url) else "unavailable"
    )
    return Health(status="ok", db=db_state, version=__version__)
