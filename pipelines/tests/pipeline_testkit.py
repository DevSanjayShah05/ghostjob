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
