"""Diff logic against a real Postgres (skipped if the DB isn't running)."""

from datetime import UTC, date, datetime

from ghostjob_pipelines.clean import clean_job
from ghostjob_pipelines.load import apply_company_snapshot, decode_payload
from ghostjob_pipelines.models import RawJob


def job(jid: str, body: str = "same text", title: str = "Data Analyst", updated: int = 0) -> tuple:
    raw = RawJob(
        jid,
        title,
        "Remote",
        f"<p>{body}</p>",
        f"https://x/{jid}",
        source_updated_at=datetime(2026, 10, 1 + updated, tzinfo=UTC),
        payload={"id": jid, "body": body},
    )
    return raw, clean_job(raw)


def setup_company(conn) -> tuple[int, int]:
    cid = conn.execute(
        "INSERT INTO companies (name, ats, board_token, industry, size_bucket)"
        " VALUES ('Acme', 'greenhouse', 'acme', 'tech', '1-200') RETURNING id"
    ).fetchone()[0]
    rid = conn.execute(
        "INSERT INTO pipeline_runs (run_date, trigger) VALUES ('2026-11-01', 'test') RETURNING id"
    ).fetchone()[0]
    return cid, rid


def day(conn, cid, rid, d: int, jobs):
    with conn.transaction():
        return apply_company_snapshot(
            conn,
            run_id=rid,
            run_date=date(2026, 11, d),
            now=datetime(2026, 11, d, 6, tzinfo=UTC),
            company_id=cid,
            jobs=jobs,
        )


def postings(conn):
    return {
        r[0]: r[1:]
        for r in conn.execute(
            "SELECT source_job_id, is_active, first_seen_at::date, last_seen_at::date,"
            " closed_at::date, times_reopened FROM postings"
        )
    }


def test_new_changed_closed_reopened(conn):
    cid, rid = setup_company(conn)

    c1 = day(conn, cid, rid, 1, [job("A"), job("B"), job("C")])
    assert (c1.seen, c1.new, c1.changed, c1.closed, c1.reopened) == (3, 3, 0, 0, 0)

    # Day 2: A unchanged, B's text changed, C gone, D new.
    c2 = day(conn, cid, rid, 2, [job("A"), job("B", "new text"), job("D")])
    assert (c2.seen, c2.new, c2.changed, c2.closed, c2.reopened) == (3, 1, 1, 1, 0)
    p = postings(conn)
    assert p["A"][:3] == (True, date(2026, 11, 1), date(2026, 11, 2))
    assert p["C"][0] is False and p["C"][3] == date(2026, 11, 2)

    # Day 3: C comes back (a repost under the same ID), D disappears.
    c3 = day(conn, cid, rid, 3, [job("A"), job("B", "new text"), job("C")])
    assert (c3.new, c3.changed, c3.closed, c3.reopened) == (0, 0, 1, 1)
    p = postings(conn)
    assert p["C"][0] is True and p["C"][3] is None and p["C"][4] == 1
    assert p["C"][1] == date(2026, 11, 1)  # first_seen_at never moves

    snaps = conn.execute(
        "SELECT p.source_job_id, s.snapshot_date, s.is_present FROM posting_snapshots s"
        " JOIN postings p ON p.id = s.posting_id ORDER BY 1, 2"
    ).fetchall()
    c_history = [(d.day, present) for sid, d, present in snaps if sid == "C"]
    assert c_history == [(1, True), (2, False), (3, True)]


def test_raw_and_text_only_stored_on_change(conn):
    cid, rid = setup_company(conn)
    day(conn, cid, rid, 1, [job("A")])
    day(conn, cid, rid, 2, [job("A")])
    day(conn, cid, rid, 3, [job("A", "edited")])
    blobs = conn.execute("SELECT payload_gz FROM raw_jobs ORDER BY id").fetchall()
    assert [decode_payload(b[0])["body"] for b in blobs] == ["same text", "edited"]
    text = conn.execute("SELECT description_clean FROM posting_text").fetchone()[0]
    assert text == "edited"


def test_snapshots_mark_only_changes(conn):
    """content_hash / source_updated_at are set on the day they change, NULL otherwise."""
    cid, rid = setup_company(conn)
    day(conn, cid, rid, 1, [job("A")])  # new
    day(conn, cid, rid, 2, [job("A")])  # nothing changed
    day(conn, cid, rid, 3, [job("A", updated=5)])  # date refreshed, same text
    day(conn, cid, rid, 4, [job("A", "edited", updated=6)])  # real edit
    rows = conn.execute(
        "SELECT snapshot_date, source_updated_at IS NOT NULL, content_hash IS NOT NULL"
        " FROM posting_snapshots ORDER BY 1"
    ).fetchall()
    assert [(d.day, u, h) for d, u, h in rows] == [
        (1, True, True),
        (2, False, False),
        (3, True, False),  # the "fake freshness" signal: refreshed with no content change
        (4, True, True),
    ]
    # A same-day re-run must not erase the change markers.
    day(conn, cid, rid, 4, [job("A", "edited", updated=6)])
    again = conn.execute(
        "SELECT source_updated_at IS NOT NULL, content_hash IS NOT NULL FROM posting_snapshots"
        " WHERE snapshot_date = '2026-11-04'"
    ).fetchone()
    assert again == (True, True)


def test_same_day_rerun_is_idempotent(conn):
    cid, rid = setup_company(conn)
    day(conn, cid, rid, 1, [job("A"), job("B")])
    day(conn, cid, rid, 2, [job("A"), job("C")])
    again = day(conn, cid, rid, 2, [job("A"), job("C")])
    assert (again.new, again.changed, again.closed, again.reopened) == (0, 0, 0, 0)
    n = conn.execute("SELECT count(*) FROM posting_snapshots WHERE snapshot_date = '2026-11-02'")
    assert n.fetchone()[0] == 3  # A, C present; B absent


def test_duplicate_ids_in_one_fetch_count_once(conn):
    cid, rid = setup_company(conn)
    c = day(conn, cid, rid, 1, [job("A"), job("A")])
    assert (c.seen, c.new) == (1, 1)
