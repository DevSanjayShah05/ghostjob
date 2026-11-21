"""End-to-end run with the saved fixtures standing in for the live APIs."""

from datetime import date

import httpx
from pipeline_testkit import load_fixture, mock_client

from ghostjob_pipelines.models import Company
from ghostjob_pipelines.run import quality_check, run

COMPANIES = [
    Company("Airbnb", "greenhouse", "airbnb", "tech", "5001+", "CA"),
    Company("Palantir", "lever", "palantir", "tech", "1001-5000", "CO"),
    Company("OpenAI", "ashby", "openai", "tech", "1001-5000", "CA"),
    Company("Broken Co", "greenhouse", "broken", "retail", "1-200", "NY"),
]


def test_two_runs_track_new_and_closed(conn, fixture_client):
    run_id, status, t = run(conn, COMPANIES, fixture_client, run_date=date(2026, 11, 1), log=False)
    # Broken Co's board 404s on purpose: 1 of 4 boards failing is > 20%, so the run fails.
    assert status == "failed"
    assert (t.seen, t.new) == (6, 6)
    fetches = dict(
        conn.execute(
            "SELECT c.name, f.status FROM company_fetches f JOIN companies c ON c.id = f.company_id"
            " WHERE f.run_id = %s",
            (run_id,),
        ).fetchall()
    )
    assert fetches["Broken Co"] == "error" and fetches["Airbnb"] == "ok"

    # Second day: drop one Greenhouse job from the board.
    gh = load_fixture("greenhouse_airbnb.json")
    gh["jobs"] = gh["jobs"][:1]
    lever = load_fixture("lever_palantir.json")
    ashby = load_fixture("ashby_openai.json")

    def handler(request: httpx.Request) -> httpx.Response:
        host = request.url.host
        if host == "boards-api.greenhouse.io" and "airbnb" in request.url.path:
            return httpx.Response(200, json=gh)
        if host == "api.lever.co":
            return httpx.Response(200, json=lever)
        if host == "api.ashbyhq.com":
            return httpx.Response(200, json=ashby)
        return httpx.Response(404)

    with mock_client(handler) as client:
        run_id2, status2, t2 = run(
            conn, COMPANIES[:3], client, run_date=date(2026, 11, 2), log=False
        )
    assert status2 == "success"
    assert (t2.seen, t2.new, t2.closed) == (5, 0, 1)
    row = conn.execute(
        "SELECT status, postings_seen, postings_closed, companies_failed FROM pipeline_runs"
        " WHERE id = %s",
        (run_id2,),
    ).fetchone()
    assert row == ("success", 5, 1, 0)
    # Broken Co was dropped from the list, so it is no longer tracked.
    tracked = conn.execute("SELECT is_tracked FROM companies WHERE name = 'Broken Co'").fetchone()
    assert tracked == (False,)


def test_empty_board_does_not_close_everything(conn, fixture_client):
    run(conn, COMPANIES[:1], fixture_client, run_date=date(2026, 11, 1), log=False)
    conn.execute(
        "INSERT INTO postings (company_id, source_job_id, title, title_normalized, remote_type,"
        " seniority, first_seen_at, last_seen_at, content_hash)"
        " SELECT (SELECT company_id FROM postings LIMIT 1), 'extra' || g, 't', 't', 'unknown',"
        " 'mid', now(), now(), 'h' FROM generate_series(1, 5) g"
    )
    conn.commit()

    with mock_client(lambda r: httpx.Response(200, json={"jobs": []})) as client:
        _, _, t = run(conn, COMPANIES[:1], client, run_date=date(2026, 11, 2), log=False)
    assert t.closed == 0
    status = conn.execute(
        "SELECT status FROM company_fetches ORDER BY run_id DESC LIMIT 1"
    ).fetchone()
    assert status == ("suspect_empty",)


def test_subset_run_keeps_other_companies_tracked(conn, fixture_client):
    run(conn, COMPANIES[:3], fixture_client, only=["Airbnb"], log=False)
    tracked = conn.execute("SELECT count(*) FROM companies WHERE is_tracked").fetchone()
    assert tracked == (3,)
    trig = conn.execute("SELECT trigger FROM pipeline_runs").fetchone()
    assert trig == ("manual-subset",)


def test_quality_check_rules():
    ok = quality_check(seen=1000, failed=0, total=150, recent_seen=[1000] * 7, partial_run=False)
    assert ok.status == "success"
    few = quality_check(seen=1000, failed=3, total=150, recent_seen=[1000], partial_run=False)
    assert few.status == "partial"
    many = quality_check(seen=1000, failed=40, total=150, recent_seen=[1000], partial_run=False)
    assert many.status == "failed"
    drop = quality_check(seen=400, failed=0, total=150, recent_seen=[1000] * 7, partial_run=False)
    assert drop.status == "failed" and "average" in drop.notes
    subset = quality_check(seen=10, failed=0, total=2, recent_seen=[1000], partial_run=True)
    assert subset.status == "success"
    first = quality_check(seen=10, failed=0, total=150, recent_seen=[], partial_run=False)
    assert first.status == "success"
