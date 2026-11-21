"""Read the hand-built company seed CSV."""

from __future__ import annotations

import csv
from pathlib import Path
from typing import cast

from ghostjob_pipelines.models import Ats, Company

REPO_ROOT = Path(__file__).resolve().parents[2]
SEED_CSV = REPO_ROOT / "seeds" / "companies.csv"
REQUIRED = ["company_name", "ats", "board_token", "industry", "size_bucket", "hq_state"]
VALID_ATS = {"greenhouse", "lever", "ashby"}
INDUSTRIES = {"tech", "finance", "healthcare", "retail", "consulting"}
SIZE_BUCKETS = {"1-200", "201-1000", "1001-5000", "5001+"}


def read_companies(path: Path = SEED_CSV) -> list[Company]:
    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        missing = [c for c in REQUIRED if c not in (reader.fieldnames or [])]
        if missing:
            raise ValueError(f"{path} is missing columns: {missing}")
        rows = list(reader)

    companies: list[Company] = []
    seen_names: set[str] = set()
    seen_boards: set[tuple[str, str]] = set()
    for i, row in enumerate(rows, start=2):
        name, ats, token = (
            row["company_name"].strip(),
            row["ats"].strip(),
            row["board_token"].strip(),
        )
        if ats not in VALID_ATS:
            raise ValueError(f"line {i}: unknown ats {ats!r}")
        if row["industry"] not in INDUSTRIES:
            raise ValueError(f"line {i}: unknown industry {row['industry']!r}")
        if row["size_bucket"] not in SIZE_BUCKETS:
            raise ValueError(f"line {i}: unknown size_bucket {row['size_bucket']!r}")
        if name in seen_names or (ats, token) in seen_boards:
            continue  # duplicates are skipped, first one wins
        seen_names.add(name)
        seen_boards.add((ats, token))
        companies.append(
            Company(
                name=name,
                ats=cast(Ats, ats),
                board_token=token,
                industry=row["industry"],
                size_bucket=row["size_bucket"],
                hq_state=row["hq_state"].strip(),
            )
        )
    return companies
