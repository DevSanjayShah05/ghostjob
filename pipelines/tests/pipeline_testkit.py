"""Helpers shared by the pipeline tests."""

from __future__ import annotations

import json
from collections.abc import Callable
from pathlib import Path
from typing import Any

import httpx

from ghostjob_pipelines.http import PoliteClient

FIXTURES = Path(__file__).parent / "fixtures"


def load_fixture(name: str) -> Any:
    return json.loads((FIXTURES / name).read_text())


def mock_client(handler: Callable[[httpx.Request], httpx.Response]) -> PoliteClient:
    """A PoliteClient that never touches the network and never sleeps."""
    return PoliteClient(delay_s=0, backoff_s=0, transport=httpx.MockTransport(handler))


class HashEncoder:
    """Stand-in for MiniLM in tests: a normalized bag of hashed words (same words -> same vector)."""

    def encode(self, texts):  # type: ignore[no-untyped-def]
        import zlib

        import numpy as np

        out = np.zeros((len(texts), 384), dtype=np.float32)
        for i, t in enumerate(texts):
            for w in t.lower().split():
                out[i, zlib.crc32(w.encode()) % 384] += 1
        norms = np.linalg.norm(out, axis=1, keepdims=True)
        return out / np.where(norms == 0, 1, norms)
