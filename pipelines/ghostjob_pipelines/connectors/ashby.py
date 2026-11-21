"""Ashby public job posting API (no key).

Docs: https://developers.ashbyhq.com/docs/public-job-posting-api
"""

from __future__ import annotations

from typing import Any

from ghostjob_pipelines.connectors.base import Connector, parse_iso
from ghostjob_pipelines.models import Company, RawJob, Salary

BASE = "https://api.ashbyhq.com/posting-api/job-board/{token}"
HOURS_PER_YEAR = 2080


def _salary(job: dict[str, Any]) -> Salary | None:
    comp = job.get("compensation") or {}
    for c in comp.get("summaryComponents") or []:
        if c.get("compensationType") != "Salary":
            continue
        lo, hi = c.get("minValue"), c.get("maxValue")
        if not (lo or hi):
            continue
        if "HOUR" in (c.get("interval") or ""):
            lo = lo * HOURS_PER_YEAR if lo else None
            hi = hi * HOURS_PER_YEAR if hi else None
        return Salary(min=lo, max=hi, currency=c.get("currencyCode"), source="structured")
    return None


class AshbyConnector(Connector):
    ats = "ashby"

    def fetch_jobs(self, company: Company) -> list[RawJob]:
        data = self.client.get_json(
            BASE.format(token=company.board_token), params={"includeCompensation": "true"}
        )
        return [self.to_raw(j) for j in data.get("jobs", []) if j.get("isListed", True)]

    @staticmethod
    def to_raw(job: dict[str, Any]) -> RawJob:
        workplace = job.get("workplaceType")
        if not workplace and job.get("isRemote"):
            workplace = "Remote"
        return RawJob(
            source_job_id=str(job["id"]),
            title=(job.get("title") or "").strip(),
            location=(job.get("location") or "").strip(),
            description_html=job.get("descriptionHtml") or "",
            apply_url=job.get("jobUrl") or job.get("applyUrl") or "",
            department=job.get("department") or job.get("team"),
            employment_type=job.get("employmentType"),
            workplace_type=workplace,
            source_created_at=parse_iso(job.get("publishedAt")),
            salary=_salary(job),
            payload=job,
        )
