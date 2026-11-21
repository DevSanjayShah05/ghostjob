"""Link reposts ("same job, new ID") and compute per-posting similarity stats.

    uv run python -m ghostjob_pipelines.reposts

Runs after embed.py. Candidates are postings at the same company with the same title (lowercased, punctuation
removed; stricter than the spec's normalized title, see title_key) and cosine similarity >= 0.92 (spec section 3,
step 5). A newer posting B is linked to an older posting A when either:

- **closed_then_reposted** (the spec's rule): A closed, and B appeared on or after the day A closed, within 180 days.
- **republished_while_open**: A was still open when B appeared, both are at the same location, and B was published
  30+ days after A. (Same-day copies of one job in several cities are not reposts, which is why the location must
  match and the gap must be at least 30 days.)

Each posting links to its most recent qualifying predecessor only, so a job reposted three times forms a chain
A <- B <- C rather than every pair. Links are kept once found (they record history), and re-running is safe.

Also recomputed daily for every open posting (table posting_similarity):
- near_dup_open: other open postings at the company with cosine >= 0.92, ignoring copies published within a day of
  each other (multi-city batches).
- boilerplate_similarity: cosine to the average of the company's other open postings (companies with 5+ open).
"""

from __future__ import annotations

import re
import sys
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta

import numpy as np
import psycopg

from ghostjob_pipelines import db
from ghostjob_pipelines.embed import load_embeddings

SIM_THRESHOLD = 0.92
LOOKBACK_DAYS = 180
REPUBLISH_MIN_GAP_DAYS = 30
SAME_BATCH_DAYS = 1
MIN_POSTINGS_FOR_CENTROID = 5


@dataclass(frozen=True)
class Posting:
    id: int
    company_id: int
    title: str
    location: str
    start: datetime  # ATS publish date, or the day we first saw it
    closed_at: datetime | None
    is_active: bool


@dataclass(frozen=True)
class Link:
    posting_id: int
    previous_posting_id: int
    link_type: str
    similarity: float
    gap_days: int


def _loc(s: str) -> str:
    return " ".join(s.lower().split())


def title_key(title: str) -> str:
    """Lowercase, punctuation removed. Seniority and team words are kept on purpose.

    The spec groups candidates by title_normalized, but that strips seniority and team ("Senior Buyer, Connected
    Warfare" and "Buyer, Autonomous Airpower" both become "buyer"). With a shared company template, those pairs
    pass the 0.92 similarity bar and become false reposts. Real reposts almost always keep the title.
    """
    return " ".join(re.sub(r"[^a-z0-9+#]+", " ", title.lower()).split())


def find_links(postings: list[Posting], emb: dict[int, np.ndarray]) -> list[Link]:
    """All repost links among postings of one company + normalized title."""
    ps = sorted((p for p in postings if p.id in emb), key=lambda p: (p.start, p.id))
    if len(ps) < 2:
        return []
    mat = np.stack([emb[p.id] for p in ps])
    sims = mat @ mat.T
    links: list[Link] = []
    for j, b in enumerate(ps):
        best: Link | None = None
        best_start: datetime | None = None
        for i in range(j):
            a = ps[i]
            sim = min(1.0, float(sims[i, j]))  # float rounding can give 1.0000002
            if sim < SIM_THRESHOLD or a.start >= b.start:
                continue
            link: Link | None = None
            open_when_b_appeared = a.closed_at is None or a.closed_at > b.start
            if a.closed_at is not None and not open_when_b_appeared:
                gap = (b.start - a.closed_at).days
                if 0 <= gap <= LOOKBACK_DAYS:
                    link = Link(b.id, a.id, "closed_then_reposted", sim, gap)
            elif _loc(a.location) == _loc(b.location):
                gap = (b.start - a.start).days
                if gap >= REPUBLISH_MIN_GAP_DAYS:
                    link = Link(b.id, a.id, "republished_while_open", sim, gap)
            if link and (best_start is None or a.start > best_start):
                best, best_start = link, a.start
        if best:
            links.append(best)
    return links


def similarity_stats(
    postings: list[Posting], emb: dict[int, np.ndarray]
) -> dict[int, tuple[int, float | None]]:
    """For one company's open postings: id -> (near_dup_open, boilerplate_similarity)."""
    ps = [p for p in postings if p.is_active and p.id in emb]
    if not ps:
        return {}
    mat = np.stack([emb[p.id] for p in ps])
    sims = mat @ mat.T
    starts = np.array([p.start.timestamp() for p in ps]) / 86400
    other_batch = np.abs(starts[:, None] - starts[None, :]) > SAME_BATCH_DAYS
    near = ((sims >= SIM_THRESHOLD) & other_batch).sum(
        axis=1
    )  # the diagonal is never "other batch"
    out: dict[int, tuple[int, float | None]] = {}
    total = mat.sum(axis=0)
    n = len(ps)
    for k, p in enumerate(ps):
        boiler: float | None = None
        if n >= MIN_POSTINGS_FOR_CENTROID:
            centroid = (total - mat[k]) / (n - 1)
            norm = float(np.linalg.norm(centroid))
            boiler = float(mat[k] @ centroid / norm) if norm else None
        out[p.id] = (int(near[k]), boiler)
    return out


def load_postings(conn: psycopg.Connection, today: date) -> list[Posting]:
    rows = conn.execute(
        """
        SELECT p.id, p.company_id, p.title, p.location,
               COALESCE(p.source_created_at, p.first_seen_at), p.closed_at, p.is_active
        FROM postings p JOIN posting_text t ON t.posting_id = p.id
        WHERE t.embedding IS NOT NULL AND (p.is_active OR p.closed_at >= %s)
        """,
        (today - timedelta(days=LOOKBACK_DAYS),),
    ).fetchall()
    return [Posting(*r) for r in rows]


def run(
    conn: psycopg.Connection, *, today: date | None = None, log: bool = True
) -> tuple[int, int]:
    """Detect links and refresh similarity stats. Returns (links written, postings with stats)."""
    today = today or datetime.now(UTC).date()
    postings = load_postings(conn, today)
    emb = load_embeddings(conn, [p.id for p in postings])
    by_company: dict[int, list[Posting]] = defaultdict(list)
    for p in postings:
        by_company[p.company_id].append(p)

    links: list[Link] = []
    stats: dict[int, tuple[int, float | None]] = {}
    for ps in by_company.values():
        by_title: dict[str, list[Posting]] = defaultdict(list)
        for p in ps:
            by_title[title_key(p.title)].append(p)
        for group in by_title.values():
            links.extend(find_links(group, emb))
        stats.update(similarity_stats(ps, emb))

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO repost_links (posting_id, previous_posting_id, link_type, similarity, gap_days,
                                      detected_on)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (posting_id, previous_posting_id) DO UPDATE SET
                link_type = EXCLUDED.link_type, similarity = EXCLUDED.similarity,
                gap_days = EXCLUDED.gap_days
            """,
            [
                (k.posting_id, k.previous_posting_id, k.link_type, k.similarity, k.gap_days, today)
                for k in links
            ],
        )
        cur.executemany(
            """
            INSERT INTO posting_similarity (posting_id, near_dup_open, boilerplate_similarity, computed_on)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (posting_id) DO UPDATE SET near_dup_open = EXCLUDED.near_dup_open,
                boilerplate_similarity = EXCLUDED.boilerplate_similarity,
                computed_on = EXCLUDED.computed_on
            """,
            [(pid, near, boiler, today) for pid, (near, boiler) in stats.items()],
        )
    conn.commit()
    if log:
        by_type: dict[str, int] = defaultdict(int)
        for k in links:
            by_type[k.link_type] += 1
        print(
            f"repost links: {len(links)} {dict(by_type)}; similarity stats for {len(stats)} postings"
        )
    return len(links), len(stats)


def main() -> int:
    with db.connect() as conn:
        db.migrate(conn)
        run(conn)
    return 0


if __name__ == "__main__":
    sys.exit(main())
