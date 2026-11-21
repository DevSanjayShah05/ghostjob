"""Check that every board token in a seed CSV returns jobs.

    uv run python -m ghostjob_pipelines.validate_seeds [--csv seeds/companies.csv] [--report out.csv]

Exit code 1 if any company returns an error or zero jobs.
"""

from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

from ghostjob_pipelines.connectors import get_connector
from ghostjob_pipelines.http import FetchError, PoliteClient
from ghostjob_pipelines.seeds import SEED_CSV, read_companies


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--csv", type=Path, default=SEED_CSV)
    ap.add_argument("--report", type=Path, help="write a CSV with one row per company")
    args = ap.parse_args(argv)

    companies = read_companies(args.csv)
    rows: list[dict[str, object]] = []
    bad = 0
    with PoliteClient(max_retries=1) as client:
        for i, c in enumerate(companies, 1):
            try:
                n = len(get_connector(c.ats, client).fetch_jobs(c))
                status = "ok" if n > 0 else "empty"
                error = ""
            except FetchError as e:
                n, status, error = 0, "error", str(e)
            bad += status != "ok"
            rows.append({**c.__dict__, "jobs": n, "status": status, "error": error})
            print(f"[{i:>3}/{len(companies)}] {status:<5} {n:>5}  {c.ats:<10} {c.name}", flush=True)

    if args.report:
        with args.report.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=list(rows[0]))
            w.writeheader()
            w.writerows(rows)
    ok = len(rows) - bad
    total = sum(int(str(r["jobs"])) for r in rows)
    print(f"\n{ok}/{len(rows)} companies OK, {total} jobs total, {bad} empty or failing")
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
