"""Daily ingestion run.

    uv run python -m ghostjob_pipelines.run                  # all companies in seeds/companies.csv
    uv run python -m ghostjob_pipelines.run --limit 5        # quick local test
    uv run python -m ghostjob_pipelines.run --only Stripe --only Ramp

Exit codes: 0 = success or partial (a few boards failed), 2 = failed the data-quality check.
"""

from __future__ import annotations

import argparse
import sys
import time
from dataclasses import dataclass
from datetime import UTC, date, datetime

import psycopg

from ghostjob_pipelines import db
from ghostjob_pipelines.clean import clean_job
from ghostjob_pipelines.connectors import get_connector
from ghostjob_pipelines.http import FetchError, PoliteClient
from ghostjob_pipelines.load import (
    SUSPECT_EMPTY_MIN_ACTIVE,
    Counts,
    active_count,
    apply_company_snapshot,
)
from ghostjob_pipelines.models import Company
from ghostjob_pipelines.seeds import read_companies

# Data-quality rules (spec section 7).
DROP_THRESHOLD = 0.5  # fail if we see < 50% of the 7-run average number of postings
MAX_FAILED_SHARE = 0.2  # fail if more than 20% of company boards error out


def sync_companies(conn: psycopg.Connection, companies: list[Company]) -> list[Company]:
    """Upsert the seed CSV into `companies`; mark companies no longer in the CSV as untracked."""
    out: list[Company] = []
    for c in companies:
        row = conn.execute(
            """
            INSERT INTO companies (name, ats, board_token, industry, size_bucket, hq_state, is_tracked)
            VALUES (%s, %s, %s, %s, %s, %s, true)
            ON CONFLICT (name) DO UPDATE SET ats = EXCLUDED.ats, board_token = EXCLUDED.board_token,
                industry = EXCLUDED.industry, size_bucket = EXCLUDED.size_bucket,
                hq_state = EXCLUDED.hq_state, is_tracked = true
            RETURNING id
            """,
            (c.name, c.ats, c.board_token, c.industry, c.size_bucket, c.hq_state or None),
        ).fetchone()
        assert row is not None
        out.append(Company(**{**c.__dict__, "id": int(row[0])}))
    conn.execute(
        "UPDATE companies SET is_tracked = false WHERE NOT (name = ANY(%s))",
        ([c.name for c in companies],),
    )
    conn.commit()
    return out


@dataclass
class QualityResult:
    status: str
    notes: str


def quality_check(
    *, seen: int, failed: int, total: int, recent_seen: list[int], partial_run: bool
) -> QualityResult:
    notes: list[str] = []
    status = "success"
    if failed:
        status = "partial"
        notes.append(f"{failed}/{total} boards failed")
    if total and failed / total > MAX_FAILED_SHARE:
        status = "failed"
        notes.append(f"more than {MAX_FAILED_SHARE:.0%} of boards failed")
    if recent_seen and not partial_run:
        avg = sum(recent_seen) / len(recent_seen)
        if seen < DROP_THRESHOLD * avg:
            status = "failed"
            notes.append(
                f"saw {seen} postings vs a recent average of {avg:.0f} (< {DROP_THRESHOLD:.0%})"
            )
    return QualityResult(status, "; ".join(notes))


def recent_postings_seen(conn: psycopg.Connection, before_run_id: int, n: int = 7) -> list[int]:
    rows = conn.execute(
        "SELECT postings_seen FROM pipeline_runs WHERE id < %s AND status IN ('success', 'partial')"
        " AND trigger <> 'manual-subset' AND postings_seen IS NOT NULL ORDER BY id DESC LIMIT %s",
        (before_run_id, n),
    ).fetchall()
    return [int(r[0]) for r in rows]


def run(
    conn: psycopg.Connection,
    companies: list[Company],
    client: PoliteClient,
    *,
    trigger: str = "manual",
    run_date: date | None = None,
    only: list[str] | None = None,
    log: bool = True,
) -> tuple[int, str, Counts]:
    """Sync every company in `companies`, then fetch all of them (or only the names in `only`)."""
    db.migrate(conn)
    companies = sync_companies(conn, companies)
    partial_run = only is not None
    if only is not None:
        wanted = {n.lower() for n in only}
        companies = [c for c in companies if c.name.lower() in wanted]
    now = datetime.now(UTC)
    run_date = run_date or now.date()
    row = conn.execute(
        "INSERT INTO pipeline_runs (run_date, trigger, companies_total) VALUES (%s, %s, %s) RETURNING id",
        (run_date, "manual-subset" if partial_run else trigger, len(companies)),
    ).fetchone()
    assert row is not None
    run_id = int(row[0])
    conn.commit()

    totals = Counts()
    failed = 0
    for i, c in enumerate(companies, 1):
        assert c.id is not None
        t0 = time.monotonic()
        status, error, n = "ok", None, 0
        try:
            raws = get_connector(c.ats, client).fetch_jobs(c)
            n = len(raws)
            if n == 0 and active_count(conn, c.id) >= SUSPECT_EMPTY_MIN_ACTIVE:
                status, error = "suspect_empty", "board returned 0 jobs; nothing closed"
            else:
                jobs = [(r, clean_job(r)) for r in raws]
                with conn.transaction():
                    counts = apply_company_snapshot(
                        conn, run_id=run_id, run_date=run_date, now=now, company_id=c.id, jobs=jobs
                    )
                totals += counts
        except (FetchError, ValueError, KeyError, psycopg.Error) as e:
            status, error = "error", f"{type(e).__name__}: {e}"[:500]
        if status != "ok":
            failed += 1
        conn.execute(
            "INSERT INTO company_fetches (run_id, company_id, status, jobs_found, duration_ms, error)"
            " VALUES (%s, %s, %s, %s, %s, %s)",
            (run_id, c.id, status, n, int((time.monotonic() - t0) * 1000), error),
        )
        conn.commit()
        if log:
            print(f"[{i:>3}/{len(companies)}] {status:<13} {n:>5} jobs  {c.name}", flush=True)

    q = quality_check(
        seen=totals.seen,
        failed=failed,
        total=len(companies),
        recent_seen=recent_postings_seen(conn, run_id),
        partial_run=partial_run,
    )
    conn.execute(
        """
        UPDATE pipeline_runs SET finished_at = now(), status = %s, companies_ok = %s,
            companies_failed = %s, postings_seen = %s, postings_new = %s, postings_closed = %s,
            postings_reopened = %s, postings_changed = %s, quality_notes = %s
        WHERE id = %s
        """,
        (
            q.status,
            len(companies) - failed,
            failed,
            totals.seen,
            totals.new,
            totals.closed,
            totals.reopened,
            totals.changed,
            q.notes or None,
            run_id,
        ),
    )
    conn.commit()
    return run_id, q.status, totals


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--limit", type=int, help="only the first N companies (a partial run)")
    ap.add_argument("--only", action="append", default=[], help="company name (repeatable)")
    ap.add_argument("--trigger", default="manual", choices=["manual", "cron"])
    args = ap.parse_args(argv)

    companies = read_companies()
    only: list[str] | None = None
    if args.only:
        only = args.only
    elif args.limit:
        only = [c.name for c in companies[: args.limit]]

    with db.connect() as conn, PoliteClient() as client:
        run_id, status, t = run(conn, companies, client, trigger=args.trigger, only=only)
        notes_row = conn.execute(
            "SELECT quality_notes FROM pipeline_runs WHERE id = %s", (run_id,)
        ).fetchone()

    print(
        f"\nrun {run_id}: {status.upper()}  seen={t.seen} new={t.new} changed={t.changed} "
        f"reopened={t.reopened} closed={t.closed}"
    )
    if notes_row and notes_row[0]:
        print(f"quality: {notes_row[0]}")
    return 2 if status == "failed" else 0


if __name__ == "__main__":
    sys.exit(main())
