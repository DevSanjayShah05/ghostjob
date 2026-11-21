from __future__ import annotations

import os
from collections.abc import Iterator

import httpx
import psycopg
import pytest
from pipeline_testkit import load_fixture, mock_client

from ghostjob_pipelines import db
from ghostjob_pipelines.http import PoliteClient

TEST_DB_URL = os.environ.get(
    "TEST_DATABASE_URL", "postgresql://ghostjob:ghostjob@localhost:5432/ghostjob_test"
)


@pytest.fixture
def fixture_client() -> Iterator[PoliteClient]:
    """Serves the saved Greenhouse / Lever / Ashby fixtures by host."""

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if "broken" in request.url.path:
            return httpx.Response(404)
        if host == "boards-api.greenhouse.io":
            return httpx.Response(200, json=load_fixture("greenhouse_airbnb.json"))
        if host == "api.lever.co":
            return httpx.Response(200, json=load_fixture("lever_palantir.json"))
        if host == "api.ashbyhq.com":
            return httpx.Response(200, json=load_fixture("ashby_openai.json"))
        return httpx.Response(404)

    with mock_client(handler) as client:
        yield client


def _ensure_test_database(url: str) -> None:
    info = psycopg.conninfo.conninfo_to_dict(url)
    name = info["dbname"]
    admin = psycopg.conninfo.make_conninfo(url, dbname="postgres")
    with psycopg.connect(admin, autocommit=True, connect_timeout=2) as conn:
        exists = conn.execute("SELECT 1 FROM pg_database WHERE datname = %s", (name,)).fetchone()
        if not exists:
            conn.execute(f'CREATE DATABASE "{name}"')


@pytest.fixture(scope="session")
def _migrated_db() -> str:
    try:
        _ensure_test_database(TEST_DB_URL)
        with psycopg.connect(TEST_DB_URL, connect_timeout=2) as conn:
            conn.execute("DROP SCHEMA public CASCADE")
            conn.execute("CREATE SCHEMA public")
            conn.commit()
            db.migrate(conn)
    except psycopg.OperationalError as e:
        if os.environ.get("REQUIRE_DB"):
            raise
        pytest.skip(f"Postgres not reachable for DB tests ({e}). Run `make db`.")
    return TEST_DB_URL


@pytest.fixture
def conn(_migrated_db: str) -> Iterator[psycopg.Connection]:
    with psycopg.connect(_migrated_db) as c:
        c.execute(
            "TRUNCATE companies, pipeline_runs, company_fetches, raw_jobs, postings,"
            " posting_snapshots, posting_text RESTART IDENTITY CASCADE"
        )
        c.commit()
        yield c
