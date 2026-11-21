from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import UTC, datetime

from ghostjob_pipelines.http import PoliteClient
from ghostjob_pipelines.models import Company, RawJob


class Connector(ABC):
    """Every ATS connector exposes the same method, so the pipeline doesn't care which ATS it is."""

    ats: str

    def __init__(self, client: PoliteClient) -> None:
        self.client = client

    @abstractmethod
    def fetch_jobs(self, company: Company) -> list[RawJob]: ...


def parse_iso(value: object) -> datetime | None:
    if not value or not isinstance(value, str):
        return None
    try:
        dt = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def parse_epoch_ms(value: object) -> datetime | None:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return None
    return datetime.fromtimestamp(value / 1000, tz=UTC)
