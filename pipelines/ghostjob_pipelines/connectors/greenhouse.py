"""Greenhouse Job Board API (public, no key).

Docs: https://developers.greenhouse.io/job-board.html
"""

from __future__ import annotations

import html
from typing import Any

from ghostjob_pipelines.connectors.base import Connector, parse_iso
from ghostjob_pipelines.models import Company, RawJob, Salary

BASE = "https://boards-api.greenhouse.io/v1/boards/{token}/jobs"


def _salary(job: dict[str, Any]) -> Salary | None:
    # Only present when requested with pay_transparency=true and the company publishes it.
    # A posting can list one range per region; prefer USD so salaries are comparable.
    ranges = job.get("pay_input_ranges") or []
    ranges = sorted(ranges, key=lambda r: r.get("currency_type") != "USD")
    for r in ranges:
        lo, hi = r.get("min_cents"), r.get("max_cents")
        if lo or hi:
            return Salary(
                min=lo / 100 if lo else None,
                max=hi / 100 if hi else None,
                currency=r.get("currency_type"),
                source="structured",
            )
    return None


class GreenhouseConnector(Connector):
    ats = "greenhouse"

    def fetch_jobs(self, company: Company) -> list[RawJob]:
        data = self.client.get_json(
            BASE.format(token=company.board_token),
            params={"content": "true", "pay_transparency": "true"},
        )
        return [self.to_raw(j) for j in data.get("jobs", [])]

    @staticmethod
    def to_raw(job: dict[str, Any]) -> RawJob:
        depts = job.get("departments") or []
        return RawJob(
            source_job_id=str(job["id"]),
            title=(job.get("title") or "").strip(),
            location=((job.get("location") or {}).get("name") or "").strip(),
            # Greenhouse returns the HTML entity-escaped (&lt;p&gt;...), so unescape once.
            description_html=html.unescape(job.get("content") or ""),
            apply_url=job.get("absolute_url") or "",
            department=depts[0]["name"] if depts else None,
            source_created_at=parse_iso(job.get("first_published")),
            source_updated_at=parse_iso(job.get("updated_at")),
            salary=_salary(job),
            payload=job,
        )
