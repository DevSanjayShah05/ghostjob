"""Run dbt against DATABASE_URL (or the local dev DB).

    uv run python analytics/run_dbt.py build
    uv run python analytics/run_dbt.py docs generate

It splits DATABASE_URL into the DBT_PG* variables that profiles.yml reads, then runs dbt from this
folder, so the pipeline and dbt always point at the same database.
"""

from __future__ import annotations

import os
import subprocess
import sys
from pathlib import Path
from urllib.parse import parse_qs, unquote, urlparse

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent / "pipelines"))

from ghostjob_pipelines.db import database_url  # noqa: E402


def dbt_env(url: str) -> dict[str, str]:
    u = urlparse(url)
    query = parse_qs(u.query)
    return {
        "DBT_PGHOST": u.hostname or "localhost",
        "DBT_PGPORT": str(u.port or 5432),
        "DBT_PGUSER": unquote(u.username or ""),
        "DBT_PGPASSWORD": unquote(u.password or ""),
        "DBT_PGDATABASE": u.path.lstrip("/") or "postgres",
        "DBT_PGSSLMODE": query.get("sslmode", ["prefer"])[0],
    }


def main(argv: list[str]) -> int:
    env = {**os.environ, **dbt_env(database_url())}
    cmd = ["dbt", *argv, "--project-dir", str(HERE), "--profiles-dir", str(HERE)]
    return subprocess.call(cmd, cwd=HERE, env=env)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:] or ["build"]))
