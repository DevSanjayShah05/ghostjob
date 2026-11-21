"""Diff one company's jobs today against what's stored, and write the changes.

For each company and run date:
- a job we've never seen      -> new posting (first_seen_at = now)
- a job we have, same content -> last_seen_at = now
- a job we have, new content  -> fields + text updated, raw JSON stored again
- a closed job that came back -> reopened (times_reopened + 1)
- an active job that's gone   -> closed (is_active = false, closed_at = now)
Every posting touched gets a row in posting_snapshots for the run date (is_present true/false).
That row carries content_hash / source_updated_at only when they changed (see 001_core.sql).
Re-running the same day is safe: snapshots are upserted, and nothing is double counted.
"""

from __future__ import annotations

import json
import zlib
from dataclasses import dataclass, fields
from datetime import date, datetime
from typing import Any

import psycopg

from ghostjob_pipelines.clean import CleanJob
from ghostjob_pipelines.models import RawJob

# A board that suddenly returns zero jobs is more likely an API hiccup than every job closing at
# once. If a company had at least this many active postings, an empty fetch closes nothing.
SUSPECT_EMPTY_MIN_ACTIVE = 5


@dataclass
class Counts:
    seen: int = 0
    new: int = 0
    changed: int = 0
    reopened: int = 0
    closed: int = 0

    def __iadd__(self, other: Counts) -> Counts:
        for f in fields(self):
            setattr(self, f.name, getattr(self, f.name) + getattr(other, f.name))
        return self


def encode_payload(payload: dict[str, Any]) -> tuple[bytes, int]:
    raw = json.dumps(payload, separators=(",", ":"), ensure_ascii=False).encode()
    return zlib.compress(raw, 9), len(raw)


def decode_payload(blob: bytes) -> Any:
    return json.loads(zlib.decompress(blob))


def active_count(conn: psycopg.Connection, company_id: int) -> int:
    row = conn.execute(
        "SELECT count(*) FROM postings WHERE company_id = %s AND is_active", (company_id,)
    ).fetchone()
    return int(row[0]) if row else 0


def _posting_values(c: CleanJob, raw: RawJob) -> dict[str, Any]:
    s = c.salary
    return {
        "title": c.title,
        "title_normalized": c.title_normalized,
        "location": c.location,
        "remote_type": c.remote_type,
        "department": c.department,
        "seniority": c.seniority,
        "employment_type": c.employment_type,
        "apply_url": c.apply_url,
        "salary_min": s.min if s else None,
        "salary_max": s.max if s else None,
        "salary_currency": s.currency if s else None,
        "salary_source": s.source if s else None,
        "source_created_at": raw.source_created_at,
        "source_updated_at": raw.source_updated_at,
        "content_hash": c.content_hash,
    }


def apply_company_snapshot(
    conn: psycopg.Connection,
    *,
    run_id: int,
    run_date: date,
    now: datetime,
    company_id: int,
    jobs: list[tuple[RawJob, CleanJob]],
) -> Counts:
    """Write one company's jobs for one run. Call inside a transaction."""
    counts = Counts()
    existing: dict[str, tuple[int, str, bool, datetime | None]] = {
        r[0]: (r[1], r[2], r[3], r[4])
        for r in conn.execute(
            "SELECT source_job_id, id, content_hash, is_active, source_updated_at FROM postings"
            " WHERE company_id = %s",
            (company_id,),
        )
    }
    # Postings already written in this run (a same-day re-run) shouldn't count as new or changed.
    already_today = {
        r[0]
        for r in conn.execute(
            "SELECT p.source_job_id FROM posting_snapshots s JOIN postings p ON p.id = s.posting_id"
            " WHERE p.company_id = %s AND s.snapshot_date = %s AND s.is_present",
            (company_id, run_date),
        )
    }

    seen_ids: set[str] = set()
    snapshots: list[tuple[Any, ...]] = []
    touch_ids: list[int] = []  # unchanged postings: only last_seen_at moves (one batched UPDATE)
    full_updates: list[dict[str, Any]] = []
    texts: list[tuple[Any, ...]] = []
    raws: list[tuple[Any, ...]] = []
    for raw, c in jobs:
        if c.source_job_id in seen_ids:  # some boards list the same job twice
            continue
        seen_ids.add(c.source_job_id)
        counts.seen += 1
        vals = _posting_values(c, raw)
        prev = existing.get(c.source_job_id)

        if prev is None:
            # New postings are inserted one by one because we need their ids (~1k a day).
            row = conn.execute(
                """
                INSERT INTO postings (company_id, source_job_id, first_seen_at, last_seen_at,
                    is_active, title, title_normalized, location, remote_type, department,
                    seniority, employment_type, apply_url, salary_min, salary_max,
                    salary_currency, salary_source, source_created_at, source_updated_at,
                    content_hash)
                VALUES (%(company_id)s, %(source_job_id)s, %(now)s, %(now)s, true, %(title)s,
                    %(title_normalized)s, %(location)s, %(remote_type)s, %(department)s,
                    %(seniority)s, %(employment_type)s, %(apply_url)s, %(salary_min)s,
                    %(salary_max)s, %(salary_currency)s, %(salary_source)s,
                    %(source_created_at)s, %(source_updated_at)s, %(content_hash)s)
                RETURNING id
                """,
                {**vals, "company_id": company_id, "source_job_id": c.source_job_id, "now": now},
            ).fetchone()
            assert row is not None
            posting_id = int(row[0])
            counts.new += 1
            content_changed = True
            updated_changed = raw.source_updated_at is not None
        else:
            posting_id, old_hash, was_active, old_updated = prev
            content_changed = old_hash != c.content_hash
            updated_changed = raw.source_updated_at != old_updated
            reopened = not was_active
            if content_changed or updated_changed or reopened:
                full_updates.append(
                    {**vals, "now": now, "reopened": int(reopened), "id": posting_id}
                )
            else:
                touch_ids.append(posting_id)
            if c.source_job_id not in already_today:
                counts.changed += content_changed
                counts.reopened += reopened

        if content_changed:
            texts.append((posting_id, c.description_clean, c.word_count, now))
            blob, size = encode_payload(raw.payload)
            raws.append((run_id, company_id, c.source_job_id, c.content_hash, now, blob, size))
        snapshots.append(
            (
                posting_id,
                run_date,
                run_id,
                raw.source_updated_at if updated_changed else None,
                c.content_hash if content_changed else None,
                True,
            )
        )

    with conn.cursor() as cur:
        if touch_ids:
            cur.execute(
                "UPDATE postings SET last_seen_at = %s WHERE id = ANY(%s)", (now, touch_ids)
            )
        cur.executemany(
            """
            UPDATE postings SET
                last_seen_at = %(now)s, is_active = true, closed_at = NULL,
                times_reopened = times_reopened + %(reopened)s,
                title = %(title)s, title_normalized = %(title_normalized)s,
                location = %(location)s, remote_type = %(remote_type)s,
                department = %(department)s, seniority = %(seniority)s,
                employment_type = %(employment_type)s, apply_url = %(apply_url)s,
                salary_min = %(salary_min)s, salary_max = %(salary_max)s,
                salary_currency = %(salary_currency)s, salary_source = %(salary_source)s,
                source_created_at = COALESCE(source_created_at, %(source_created_at)s),
                source_updated_at = %(source_updated_at)s, content_hash = %(content_hash)s
            WHERE id = %(id)s
            """,
            full_updates,
        )
        cur.executemany(
            """
            INSERT INTO posting_text (posting_id, description_clean, word_count, updated_at)
            VALUES (%s, %s, %s, %s)
            ON CONFLICT (posting_id) DO UPDATE SET description_clean = EXCLUDED.description_clean,
                word_count = EXCLUDED.word_count, embedding = NULL, updated_at = EXCLUDED.updated_at
            """,
            texts,
        )
        cur.executemany(
            "INSERT INTO raw_jobs (run_id, company_id, source_job_id, content_hash, fetched_at,"
            " payload_gz, payload_bytes) VALUES (%s, %s, %s, %s, %s, %s, %s)",
            raws,
        )

    gone = [
        (sid, pid)
        for sid, (pid, _h, active, _u) in existing.items()
        if active and sid not in seen_ids
    ]
    if gone:
        conn.execute(
            "UPDATE postings SET is_active = false, closed_at = %s WHERE id = ANY(%s)",
            (now, [pid for _sid, pid in gone]),
        )
    for _sid, pid in gone:
        snapshots.append((pid, run_date, run_id, None, None, False))
    counts.closed = len(gone)

    with conn.cursor() as cur:
        cur.executemany(
            """
            INSERT INTO posting_snapshots (posting_id, snapshot_date, run_id, source_updated_at,
                content_hash, is_present)
            VALUES (%s, %s, %s, %s, %s, %s)
            ON CONFLICT (posting_id, snapshot_date) DO UPDATE SET run_id = EXCLUDED.run_id,
                source_updated_at = COALESCE(EXCLUDED.source_updated_at,
                                             posting_snapshots.source_updated_at),
                content_hash = COALESCE(EXCLUDED.content_hash, posting_snapshots.content_hash),
                is_present = EXCLUDED.is_present
            """,
            snapshots,
        )
    return counts
