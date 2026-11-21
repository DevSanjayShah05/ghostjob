"""Lever Postings API (public, no key). robots.txt asks for a 1s crawl delay; we use 1.5s.

Docs: https://github.com/lever/postings-api
"""

from __future__ import annotations

from typing import Any

from ghostjob_pipelines.connectors.base import Connector, parse_epoch_ms
from ghostjob_pipelines.models import Company, RawJob, Salary

BASE = "https://api.lever.co/v0/postings/{token}"
PAGE = 100


def _salary(job: dict[str, Any]) -> Salary | None:
    s = job.get("salaryRange")
    if not s or not (s.get("min") or s.get("max")):
        return None
    lo, hi = s.get("min"), s.get("max")
    if (s.get("interval") or "").startswith("per-hour"):
        lo, hi = (lo * 2080 if lo else None), (hi * 2080 if hi else None)
    return Salary(min=lo, max=hi, currency=s.get("currency"), source="structured")


def _description(job: dict[str, Any]) -> str:
    parts = [job.get("description") or ""]
    for lst in job.get("lists") or []:
        parts.append(f"<h3>{lst.get('text', '')}</h3><ul>{lst.get('content', '')}</ul>")
    parts.append(job.get("additional") or "")
    return "\n".join(p for p in parts if p)


class LeverConnector(Connector):
    ats = "lever"

    def fetch_jobs(self, company: Company) -> list[RawJob]:
        jobs: list[dict[str, Any]] = []
        skip = 0
        while True:
            page = self.client.get_json(
                BASE.format(token=company.board_token),
                params={"mode": "json", "skip": skip, "limit": PAGE},
            )
            if not isinstance(page, list):
                break
            jobs.extend(page)
            if len(page) < PAGE:
                break
            skip += PAGE
        return [self.to_raw(j) for j in jobs]

    @staticmethod
    def to_raw(job: dict[str, Any]) -> RawJob:
        cats = job.get("categories") or {}
        return RawJob(
            source_job_id=str(job["id"]),
            title=(job.get("text") or "").strip(),
            location=(cats.get("location") or "").strip(),
            description_html=_description(job),
            apply_url=job.get("hostedUrl") or job.get("applyUrl") or "",
            department=cats.get("team") or cats.get("department"),
            employment_type=cats.get("commitment"),
            workplace_type=job.get("workplaceType"),
            source_created_at=parse_epoch_ms(job.get("createdAt")),
            salary=_salary(job),
            payload=job,
        )
