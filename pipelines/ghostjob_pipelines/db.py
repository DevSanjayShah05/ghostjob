"""Database connection and a tiny migration runner (plain numbered .sql files)."""

from __future__ import annotations

import os
from pathlib import Path

import psycopg

from ghostjob_pipelines.seeds import REPO_ROOT

MIGRATIONS_DIR = REPO_ROOT / "db" / "migrations"
DEFAULT_URL = "postgresql://ghostjob:ghostjob@localhost:5432/ghostjob"


def database_url() -> str:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url
    env_file = REPO_ROOT / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("DATABASE_URL="):
                return line.split("=", 1)[1].strip()
    return DEFAULT_URL


def connect(url: str | None = None) -> psycopg.Connection:
    return psycopg.connect(url or database_url())


def migrate(conn: psycopg.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply any .sql files not yet recorded in schema_migrations, in filename order."""
    conn.execute(
        "CREATE TABLE IF NOT EXISTS schema_migrations ("
        " filename text PRIMARY KEY, applied_at timestamptz NOT NULL DEFAULT now())"
    )
    done = {r[0] for r in conn.execute("SELECT filename FROM schema_migrations")}
    applied: list[str] = []
    for path in sorted(migrations_dir.glob("*.sql")):
        if path.name in done:
            continue
        with conn.transaction():
            conn.execute(path.read_text())
            conn.execute("INSERT INTO schema_migrations (filename) VALUES (%s)", (path.name,))
        applied.append(path.name)
    conn.commit()
    return applied
