import numpy as np
from pipeline_testkit import HashEncoder

from ghostjob_pipelines.embed import (
    CHUNK_WORDS,
    MAX_CHUNKS,
    boilerplate_lines,
    chunks,
    embed_documents,
    embed_pending,
    strip_boilerplate,
)

ABOUT = "About Acme: we build rockets for everyone."
EEO = "Acme is an equal opportunity employer."


def docs(n: int) -> list[str]:
    return [f"{ABOUT}\nRole {i}: write unique code number {i}.\n{EEO}" for i in range(n)]


def test_boilerplate_lines_found_in_most_postings():
    found = boilerplate_lines(docs(10))
    assert found == {ABOUT.lower(), EEO.lower()}


def test_boilerplate_needs_enough_postings():
    assert boilerplate_lines(docs(4)) == set()


def test_strip_boilerplate_keeps_the_role_text():
    d = docs(10)
    assert strip_boilerplate(d[3], boilerplate_lines(d)) == "Role 3: write unique code number 3."


def test_strip_ignores_case_and_spacing():
    assert (
        strip_boilerplate("  ABOUT acme:   we build rockets for everyone.\nkeep", {ABOUT.lower()})
        == "keep"
    )


def test_chunks_title_leads_and_caps():
    body = " ".join(f"w{i}" for i in range(CHUNK_WORDS * (MAX_CHUNKS + 2)))
    cs = chunks("Data Analyst", body)
    assert len(cs) == MAX_CHUNKS
    assert cs[0].startswith("Data Analyst\nw0 ")
    assert chunks("Data Analyst", "") == ["Data Analyst"]


def test_embed_documents_normalized_and_deterministic():
    enc = HashEncoder()
    v = embed_documents(enc, [("A", "x y z"), ("A", "x y z"), ("B", "totally different words")])
    assert v.shape == (3, 384)
    assert np.allclose(np.linalg.norm(v, axis=1), 1)
    assert np.allclose(v[0], v[1])
    assert v[0] @ v[2] < 0.5
    assert embed_documents(enc, []).shape == (0, 384)


def test_boilerplate_removal_separates_postings():
    """Without stripping, two different roles share most of their text and look alike."""
    enc = HashEncoder()
    shared = " ".join(f"benefit{i}" for i in range(150))
    a, b = f"{shared}\nbuild data pipelines in python", f"{shared}\nsell enterprise software deals"
    raw = embed_documents(enc, [("Role", a), ("Role", b)])
    boiler = boilerplate_lines([a, b, a, b, a])
    clean = embed_documents(
        enc, [("Role", strip_boilerplate(a, boiler)), ("Role", strip_boilerplate(b, boiler))]
    )
    assert raw[0] @ raw[1] > 0.9
    assert clean[0] @ clean[1] < 0.5


def test_embed_pending_fills_nulls_once(conn):
    cid = conn.execute(
        "INSERT INTO companies (name, ats, board_token, industry, size_bucket)"
        " VALUES ('Acme', 'greenhouse', 'acme', 'tech', '1-200') RETURNING id"
    ).fetchone()[0]
    for i, d in enumerate(docs(6)):
        pid = conn.execute(
            "INSERT INTO postings (company_id, source_job_id, first_seen_at, last_seen_at, is_active, title,"
            " title_normalized, location, remote_type, seniority, apply_url, content_hash) VALUES (%s, %s, now(), now(), true,"
            " 'Engineer',"
            " 'engineer', 'NYC', 'onsite', 'mid', 'u', 'h') RETURNING id",
            (cid, str(i)),
        ).fetchone()[0]
        conn.execute(
            "INSERT INTO posting_text (posting_id, description_clean, word_count) VALUES (%s, %s, 10)",
            (pid, d),
        )
    conn.commit()
    assert embed_pending(conn, HashEncoder(), log=False) == 6
    assert embed_pending(conn, HashEncoder(), log=False) == 0
    assert (
        conn.execute("SELECT count(*) FROM posting_text WHERE embedding IS NULL").fetchone()[0] == 0
    )
    assert embed_pending(conn, HashEncoder(), redo_all=True, log=False) == 6
