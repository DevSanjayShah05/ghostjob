"""Plain data types shared by connectors, cleaning and loading."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Literal

Ats = Literal["greenhouse", "lever", "ashby"]
RemoteType = Literal["remote", "hybrid", "onsite", "unknown"]


@dataclass(frozen=True)
class Company:
    name: str
    ats: Ats
    board_token: str
    industry: str = ""
    size_bucket: str = ""
    hq_state: str = ""
    id: int | None = None


@dataclass
class Salary:
    min: float | None = None
    max: float | None = None
    currency: str | None = None
    source: Literal["structured", "text"] | None = None


@dataclass
class RawJob:
    """One posting as the ATS returned it, mapped onto a common shape.

    `payload` keeps the untouched JSON so it can always be re-processed later.
    """

    source_job_id: str
    title: str
    location: str
    description_html: str
    apply_url: str
    department: str | None = None
    employment_type: str | None = None
    workplace_type: str | None = None  # the ATS's own remote/hybrid/onsite field, if any
    source_created_at: datetime | None = None
    source_updated_at: datetime | None = None
    salary: Salary | None = None  # structured salary from the ATS, if it provides one
    payload: dict[str, Any] = field(default_factory=dict)
