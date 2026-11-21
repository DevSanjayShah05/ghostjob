"""A polite HTTP client: clear User-Agent, timeout, delay between requests, retries with backoff."""

from __future__ import annotations

import time
from typing import Any

import httpx

USER_AGENT = "GhostJobBot/0.1 (+https://github.com/DevSanjayShah05/ghostjob)"
RETRY_STATUS = {429, 500, 502, 503, 504}


class FetchError(RuntimeError):
    pass


class PoliteClient:
    def __init__(
        self,
        delay_s: float = 1.5,
        timeout_s: float = 30.0,
        max_retries: int = 3,
        backoff_s: float = 2.0,
        transport: httpx.BaseTransport | None = None,
    ) -> None:
        self.delay_s = delay_s
        self.max_retries = max_retries
        self.backoff_s = backoff_s
        self._last_request = 0.0
        self._client = httpx.Client(
            headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
            timeout=timeout_s,
            follow_redirects=True,
            transport=transport,
        )

    def _wait_turn(self) -> None:
        gap = time.monotonic() - self._last_request
        if gap < self.delay_s:
            time.sleep(self.delay_s - gap)
        self._last_request = time.monotonic()

    def get_json(self, url: str, params: dict[str, Any] | None = None) -> Any:
        last_error = ""
        for attempt in range(self.max_retries + 1):
            self._wait_turn()
            try:
                r = self._client.get(url, params=params)
            except httpx.HTTPError as e:
                last_error = f"{type(e).__name__}: {e}"
            else:
                if r.status_code == 200:
                    return r.json()
                if r.status_code not in RETRY_STATUS:
                    raise FetchError(f"HTTP {r.status_code} for {url}")
                last_error = f"HTTP {r.status_code}"
            if attempt < self.max_retries:
                time.sleep(self.backoff_s * (2**attempt))
        raise FetchError(f"gave up after {self.max_retries + 1} tries: {last_error} ({url})")

    def close(self) -> None:
        self._client.close()

    def __enter__(self) -> PoliteClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()
