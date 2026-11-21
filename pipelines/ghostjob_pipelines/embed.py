"""Embed posting text with all-MiniLM-L6-v2 (384 dims, runs locally, no API cost).

    uv run python -m ghostjob_pipelines.embed            # embed every posting whose embedding is NULL
    uv run python -m ghostjob_pipelines.embed --all      # re-embed everything (after changing this file)

Two details matter for repost detection:

1. **Company boilerplate is removed first.** Many companies start every description with the same "About us"
   block and end with the same benefits and EEO text. MiniLM reads only the first 256 tokens, so without this
   step every posting at a company looks nearly identical. A line counts as boilerplate when it appears in at
   least 30% (and at least 3) of the company's active postings.
2. **Long text is embedded in chunks and averaged.** The remaining text is split into ~180-word chunks (at most
   4), each chunk is embedded, and the average is L2-normalized. The title always leads the first chunk.

Embeddings are set to NULL by load.py whenever a posting's text changes, so the daily run only embeds what's new.
"""

from __future__ import annotations

import argparse
import os
import sys
import time
from collections import Counter
from collections.abc import Iterable, Sequence
from typing import Protocol

import numpy as np
import psycopg

from ghostjob_pipelines import db

MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"
DIM = 384
BOILERPLATE_MIN_SHARE = 0.3
BOILERPLATE_MIN_COUNT = 3
BOILERPLATE_MIN_POSTINGS = 5
CHUNK_WORDS = 180
MAX_CHUNKS = 4


class Encoder(Protocol):
    def encode(self, texts: Sequence[str]) -> np.ndarray:
        """Return one L2-normalized row per text, shape (len(texts), DIM)."""
        ...


class MiniLM:
    def __init__(self, batch_size: int = 64) -> None:
        from sentence_transformers import SentenceTransformer  # heavy import, only when needed

        # CPU by default (GitHub Actions). Set GHOSTJOB_EMBED_DEVICE=mps for a faster local backfill on a Mac.
        self.model = SentenceTransformer(
            MODEL_NAME, device=os.environ.get("GHOSTJOB_EMBED_DEVICE", "cpu")
        )
        self.batch_size = batch_size

    def encode(self, texts: Sequence[str]) -> np.ndarray:
        out = self.model.encode(
            list(texts),
            batch_size=self.batch_size,
            normalize_embeddings=True,
            show_progress_bar=False,
            convert_to_numpy=True,
        )
        return np.asarray(out, dtype=np.float32)


# --------------------------------------------------------------------------- pure helpers


def _norm_line(line: str) -> str:
    return " ".join(line.lower().split())


def boilerplate_lines(descriptions: Iterable[str]) -> set[str]:
    """Lines (normalized) that appear in at least 30% and at least 3 of these descriptions."""
    docs = list(descriptions)
    if len(docs) < BOILERPLATE_MIN_POSTINGS:
        return set()
    counts: Counter[str] = Counter()
    for d in docs:
        counts.update({_norm_line(ln) for ln in d.splitlines() if ln.strip()})
    threshold = max(BOILERPLATE_MIN_COUNT, BOILERPLATE_MIN_SHARE * len(docs))
    return {ln for ln, n in counts.items() if n >= threshold}


def strip_boilerplate(description: str, boilerplate: set[str]) -> str:
    return "\n".join(
        ln for ln in description.splitlines() if ln.strip() and _norm_line(ln) not in boilerplate
    )


def chunks(title: str, body: str) -> list[str]:
    """Title + body split into at most MAX_CHUNKS chunks of ~CHUNK_WORDS words. Never empty."""
    words = body.split()
    parts = [
        " ".join(words[i : i + CHUNK_WORDS])
        for i in range(0, min(len(words), CHUNK_WORDS * MAX_CHUNKS), CHUNK_WORDS)
    ]
    if not parts:
        return [title]
    parts[0] = f"{title}\n{parts[0]}"
    return parts


def embed_documents(encoder: Encoder, docs: Sequence[tuple[str, str]]) -> np.ndarray:
    """(title, body) pairs -> one L2-normalized vector per document (mean of its chunk vectors)."""
    if not docs:
        return np.zeros((0, DIM), dtype=np.float32)
    all_chunks: list[str] = []
    owner: list[int] = []
    for i, (title, body) in enumerate(docs):
        cs = chunks(title, body)
        all_chunks.extend(cs)
        owner.extend([i] * len(cs))
    vecs = encoder.encode(all_chunks)
    out = np.zeros((len(docs), vecs.shape[1]), dtype=np.float32)
    np.add.at(out, np.asarray(owner), vecs)
    norms = np.linalg.norm(out, axis=1, keepdims=True)
    return out / np.where(norms == 0, 1, norms)


# --------------------------------------------------------------------------- database


def embed_pending(
    conn: psycopg.Connection, encoder: Encoder, *, redo_all: bool = False, log: bool = True
) -> int:
    """Embed every posting with a NULL embedding (or every posting). Returns how many were embedded."""
    from pgvector.psycopg import register_vector

    register_vector(conn)
    where = "" if redo_all else "WHERE t.embedding IS NULL"
    todo = conn.execute(
        f"SELECT DISTINCT p.company_id FROM posting_text t JOIN postings p ON p.id = t.posting_id {where}"
    ).fetchall()
    total = 0
    t0 = time.monotonic()
    for (company_id,) in todo:
        rows = conn.execute(
            """
            SELECT p.id, p.title, t.description_clean, p.is_active, t.embedding IS NULL
            FROM postings p JOIN posting_text t ON t.posting_id = p.id
            WHERE p.company_id = %s
            """,
            (company_id,),
        ).fetchall()
        # Boilerplate is learned from the company's open postings (all of them, if none are open).
        basis = [r[2] for r in rows if r[3]] or [r[2] for r in rows]
        boiler = boilerplate_lines(basis)
        pending = [r for r in rows if redo_all or r[4]]
        vecs = embed_documents(encoder, [(r[1], strip_boilerplate(r[2], boiler)) for r in pending])
        with conn.cursor() as cur:
            cur.executemany(
                "UPDATE posting_text SET embedding = %s WHERE posting_id = %s",
                [(v, r[0]) for v, r in zip(vecs, pending, strict=True)],
            )
        conn.commit()
        total += len(pending)
        if log:
            print(f"  company {company_id}: {len(pending)} embedded ({total} total)", flush=True)
    if log:
        print(f"embedded {total} postings in {time.monotonic() - t0:.0f}s")
    return total


def load_embeddings(conn: psycopg.Connection, ids: Sequence[int]) -> dict[int, np.ndarray]:
    from pgvector.psycopg import register_vector

    register_vector(conn)
    rows = conn.execute(
        "SELECT posting_id, embedding FROM posting_text WHERE posting_id = ANY(%s) AND embedding IS NOT NULL",
        (list(ids),),
    )
    return {int(pid): _as_array(vec) for pid, vec in rows}


def _as_array(vec: object) -> np.ndarray:
    """pgvector returns numpy arrays or Vector objects depending on version and format."""
    to_numpy = getattr(vec, "to_numpy", None)
    return np.asarray(to_numpy() if to_numpy else vec, dtype=np.float32)


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawTextHelpFormatter)
    ap.add_argument("--all", action="store_true", help="re-embed every posting")
    args = ap.parse_args(argv)
    with db.connect() as conn:
        db.migrate(conn)
        embed_pending(conn, MiniLM(), redo_all=args.all)
    return 0


if __name__ == "__main__":
    sys.exit(main())
