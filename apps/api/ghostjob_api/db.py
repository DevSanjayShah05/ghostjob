"""Database helpers. Phase 0 only needs a reachability check."""

import psycopg


def ping(database_url: str, timeout_s: int = 2) -> bool:
    """Return True if Postgres answers `SELECT 1` within the timeout."""
    try:
        with psycopg.connect(database_url, connect_timeout=timeout_s) as conn:
            conn.execute("SELECT 1")
        return True
    except psycopg.Error:
        return False
