from datetime import UTC, datetime

import httpx
import pytest
from pipeline_testkit import load_fixture, mock_client

from ghostjob_pipelines.connectors import get_connector
from ghostjob_pipelines.connectors.ashby import AshbyConnector
from ghostjob_pipelines.connectors.base import parse_epoch_ms, parse_iso
from ghostjob_pipelines.connectors.greenhouse import GreenhouseConnector
from ghostjob_pipelines.connectors.lever import LeverConnector
from ghostjob_pipelines.http import FetchError
from ghostjob_pipelines.models import Company

GH = Company("Airbnb", "greenhouse", "airbnb", "tech", "5001+", "CA")
LV = Company("Palantir", "lever", "palantir", "tech", "1001-5000", "CO")
AB = Company("OpenAI", "ashby", "openai", "tech", "1001-5000", "CA")


def test_greenhouse_maps_fields(fixture_client):
    jobs = get_connector("greenhouse", fixture_client).fetch_jobs(GH)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.source_job_id.isdigit()
    assert j.title and j.location and j.apply_url.startswith("https://")
    assert "&lt;" not in j.description_html  # entity-escaped HTML was unescaped
    assert j.source_created_at is not None and j.source_updated_at is not None
    assert j.salary is not None and j.salary.currency == "USD" and j.salary.source == "structured"
    assert jobs[1].salary is None
    assert j.payload["id"] == int(j.source_job_id)


def test_greenhouse_prefers_usd_range():
    job = load_fixture("greenhouse_airbnb.json")["jobs"][0]
    job["pay_input_ranges"] = [
        {"min_cents": 5_000_000, "max_cents": 6_000_000, "currency_type": "EUR"},
        {"min_cents": 10_000_000, "max_cents": 12_000_000, "currency_type": "USD"},
    ]
    s = GreenhouseConnector.to_raw(job).salary
    assert s is not None and (s.min, s.max, s.currency) == (100_000, 120_000, "USD")


def test_lever_maps_fields(fixture_client):
    jobs = get_connector("lever", fixture_client).fetch_jobs(LV)
    assert len(jobs) == 2
    j = jobs[0]
    assert j.title == "Administrative Business Partner"
    assert j.apply_url.startswith("https://jobs.lever.co/palantir/")
    assert j.workplace_type in {"hybrid", "remote", "onsite", "unspecified"}
    assert j.source_created_at is not None and j.source_created_at.tzinfo is not None
    assert j.source_updated_at is None  # Lever has no "updated" stamp


def test_lever_salary_range_hourly_is_annualized():
    job = load_fixture("lever_palantir.json")[0]
    job["salaryRange"] = {"min": 40, "max": 50, "currency": "USD", "interval": "per-hour-wage"}
    s = LeverConnector.to_raw(job).salary
    assert s is not None and (s.min, s.max) == (40 * 2080, 50 * 2080)


def test_lever_pages_through_results():
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        skip = int(request.url.params["skip"])
        calls.append(skip)
        n = 100 if skip == 0 else 7
        return httpx.Response(200, json=[{"id": f"job-{skip + i}", "text": "X"} for i in range(n)])

    with mock_client(handler) as client:
        jobs = LeverConnector(client).fetch_jobs(LV)
    assert calls == [0, 100]
    assert len(jobs) == 107


def test_ashby_maps_fields_and_compensation(fixture_client):
    jobs = get_connector("ashby", fixture_client).fetch_jobs(AB)
    assert len(jobs) == 2
    j = jobs[0]
    assert (
        j.salary is not None and j.salary.min and j.salary.max and j.salary.source == "structured"
    )
    assert jobs[1].salary is None
    assert j.source_created_at is not None
    assert j.apply_url.startswith("https://jobs.ashbyhq.com/openai/")


def test_ashby_skips_unlisted_and_annualizes_hourly():
    data = load_fixture("ashby_openai.json")
    data["jobs"][1]["isListed"] = False
    data["jobs"][0]["compensation"] = {
        "summaryComponents": [
            {"compensationType": "Salary", "interval": "1 HOUR", "minValue": 30, "maxValue": 40}
        ]
    }

    with mock_client(lambda r: httpx.Response(200, json=data)) as client:
        jobs = AshbyConnector(client).fetch_jobs(AB)
    assert len(jobs) == 1
    assert jobs[0].salary is not None and jobs[0].salary.min == 30 * 2080


def test_retries_then_succeeds():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        if attempts["n"] < 3:
            return httpx.Response(503)
        return httpx.Response(200, json={"jobs": []})

    with mock_client(handler) as client:
        assert GreenhouseConnector(client).fetch_jobs(GH) == []
    assert attempts["n"] == 3


def test_not_found_raises_without_retry():
    attempts = {"n": 0}

    def handler(request: httpx.Request) -> httpx.Response:
        attempts["n"] += 1
        return httpx.Response(404)

    with mock_client(handler) as client, pytest.raises(FetchError, match="404"):
        GreenhouseConnector(client).fetch_jobs(GH)
    assert attempts["n"] == 1


def test_network_error_gives_up():
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    with mock_client(handler) as client, pytest.raises(FetchError, match="gave up"):
        GreenhouseConnector(client).fetch_jobs(GH)


def test_sends_user_agent():
    seen = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["ua"] = request.headers["user-agent"]
        return httpx.Response(200, json={"jobs": []})

    with mock_client(handler) as client:
        GreenhouseConnector(client).fetch_jobs(GH)
    assert seen["ua"].startswith("GhostJobBot/")


def test_unknown_ats():
    with mock_client(lambda r: httpx.Response(200)) as client, pytest.raises(ValueError):
        get_connector("workday", client)


def test_date_parsers():
    assert parse_iso("2026-11-11T07:32:56-05:00") == datetime(2026, 11, 11, 12, 32, 56, tzinfo=UTC)
    assert parse_iso("2026-11-05T02:20:02.702Z") is not None
    assert parse_iso("2026-11-05T02:20:02") == datetime(2026, 11, 5, 2, 20, 2, tzinfo=UTC)
    assert parse_iso("not a date") is None and parse_iso(None) is None
    assert parse_epoch_ms(1786469891368) is not None
    assert parse_epoch_ms("123") is None and parse_epoch_ms(True) is None
