from datetime import UTC, date, datetime, timedelta

import numpy as np

from ghostjob_pipelines import reposts
from ghostjob_pipelines.reposts import Posting, find_links, similarity_stats

T0 = datetime(2026, 6, 1, tzinfo=UTC)


def vec(seed: int, noise: float = 0.0, base: int | None = None) -> np.ndarray:
    """A unit vector; with `base`, a small perturbation of that base vector."""
    rng = np.random.default_rng(base if base is not None else seed)
    v = rng.normal(size=384)
    if base is not None:
        v = v + noise * np.random.default_rng(seed + 1000).normal(size=384)
    return (v / np.linalg.norm(v)).astype(np.float32)


def p(pid, day, *, closed=None, loc="NYC", active=None, title="Data Analyst") -> Posting:
    closed_at = T0 + timedelta(days=closed) if closed is not None else None
    return Posting(
        pid,
        1,
        title,
        loc,
        T0 + timedelta(days=day),
        closed_at,
        closed is None if active is None else active,
    )


def test_closed_then_reposted():
    ps = [p(1, 0, closed=40), p(2, 45)]
    links = find_links(ps, {1: vec(1), 2: vec(1)})
    assert [(k.posting_id, k.previous_posting_id, k.link_type, k.gap_days) for k in links] == [
        (2, 1, "closed_then_reposted", 5)
    ]


def test_closed_too_long_ago_is_not_linked():
    ps = [p(1, 0, closed=10), p(2, 10 + reposts.LOOKBACK_DAYS + 1)]
    assert find_links(ps, {1: vec(1), 2: vec(1)}) == []


def test_republished_while_open_needs_same_location_and_gap():
    e = {1: vec(1), 2: vec(1), 3: vec(1), 4: vec(1)}
    assert [k.link_type for k in find_links([p(1, 0), p(2, 35)], e)] == ["republished_while_open"]
    assert (
        find_links([p(1, 0), p(3, 35, loc="Austin")], e) == []
    )  # another city: a separate opening
    assert find_links([p(1, 0), p(4, 3)], e) == []  # same batch, not a repost


def test_dissimilar_text_is_not_linked():
    assert find_links([p(1, 0, closed=20), p(2, 25)], {1: vec(1), 2: vec(2)}) == []


def test_chain_links_to_most_recent_predecessor():
    e = {i: vec(1) for i in (1, 2, 3)}
    ps = [p(1, 0, closed=30), p(2, 31, closed=70), p(3, 72)]
    links = {k.posting_id: k.previous_posting_id for k in find_links(ps, e)}
    assert links == {2: 1, 3: 2}


def test_overlap_then_close_is_not_a_closed_repost():
    """B appeared while A was still open (and A closed later): only the open rule can apply."""
    e = {1: vec(1), 2: vec(1)}
    assert find_links([p(1, 0, closed=50), p(2, 10)], e) == []
    assert [k.link_type for k in find_links([p(1, 0, closed=50), p(2, 40)], e)] == [
        "republished_while_open"
    ]


def test_similarity_stats():
    base = vec(7)
    e = {1: base, 2: vec(8, 0.01, base=7), 3: vec(9, 0.01, base=7), 4: vec(4), 5: vec(5), 6: vec(6)}
    ps = [p(1, 0), p(2, 0), p(3, 40), p(4, 5), p(5, 9), p(6, 20, closed=30)]
    out = similarity_stats(ps, e)
    assert 6 not in out  # closed postings get no stats
    assert out[1][0] == 1  # posting 2 is a same-day copy (ignored), posting 3 counts
    assert out[3][0] == 2
    assert out[4][0] == 0
    assert out[1][1] is not None and out[1][1] > out[4][1]


def test_similarity_stats_small_company_has_no_centroid():
    out = similarity_stats([p(1, 0), p(2, 5)], {1: vec(1), 2: vec(2)})
    assert out[1][1] is None


def _insert(conn, cid, sid, start, *, closed=None, title="Data Analyst", loc="NYC"):
    pid = conn.execute(
        "INSERT INTO postings (company_id, source_job_id, first_seen_at, last_seen_at, is_active, closed_at, title,"
        " title_normalized, location, remote_type, seniority, apply_url, source_created_at, content_hash)"
        " VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, 'onsite', 'mid',"
        " 'u', %s, 'h') RETURNING id",
        (cid, sid, start, start, closed is None, closed, title, title.lower(), loc, start),
    ).fetchone()[0]
    conn.execute(
        "INSERT INTO posting_text (posting_id, description_clean, word_count, embedding) VALUES (%s, 'x', 1, %s)",
        (pid, "[" + ",".join(str(float(x)) for x in vec(1)) + "]"),
    )
    return pid


def test_run_writes_links_and_stats_idempotently(conn):
    cid = conn.execute(
        "INSERT INTO companies (name, ats, board_token, industry, size_bucket)"
        " VALUES ('Acme', 'greenhouse', 'acme', 'tech', '1-200') RETURNING id"
    ).fetchone()[0]
    today = date(2026, 11, 20)
    t = datetime(2026, 11, 1, tzinfo=UTC)
    a = _insert(conn, cid, "a", t - timedelta(days=60), closed=t - timedelta(days=10))
    b = _insert(conn, cid, "b", t - timedelta(days=5))
    c = _insert(conn, cid, "c", t + timedelta(days=30))
    conn.commit()
    for _ in range(2):
        assert reposts.run(conn, today=today, log=False) == (2, 2)
    rows = conn.execute(
        "SELECT posting_id, previous_posting_id, link_type FROM repost_links ORDER BY posting_id"
    ).fetchall()
    assert rows == [(b, a, "closed_then_reposted"), (c, b, "republished_while_open")]
    near = dict(conn.execute("SELECT posting_id, near_dup_open FROM posting_similarity").fetchall())
    assert near == {b: 1, c: 1}


def test_title_key_keeps_seniority_and_team():
    assert reposts.title_key("Data Analyst (Remote)") == reposts.title_key("data analyst - remote")
    assert reposts.title_key("Senior Buyer, Connected Warfare") != reposts.title_key(
        "Buyer, Autonomous Airpower"
    )
    assert reposts.title_key("Engineering Manager") != reposts.title_key(
        "Engineering Manager - Realtime"
    )
    assert reposts.title_key("C++ Engineer") == "c++ engineer"
