"""HTTP client for the Câmara dos Deputados open-data API.

Provides a small reusable wrapper around ``requests`` that:
- targets the Câmara API base URL with sensible headers,
- retries transient errors (5xx, timeouts, connection drops) with backoff,
- follows the API's ``links`` rel="next" to collect every page of a listing.

This is intended to be shared by every Câmara source module (deputados, votes,
expenses, ...), so per-source modules only need to know endpoints and params.
"""
from __future__ import annotations

import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional

import requests

DEFAULT_BASE_URL = "https://dadosabertos.camara.leg.br/api/v2"
SENADO_BASE_URL = "https://legis.senado.leg.br/dadosabertos"
DEFAULT_USER_AGENT = (
    "pegada-publica-etl/0.1 (open-source congressional transparency portal; "
    "https://github.com/pegada-publica)"
)


class CamaraClient:
    """Minimal client for the Câmara dos Deputados open-data API."""

    def __init__(
        self,
        base_url: str = DEFAULT_BASE_URL,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        page_delay: float = 0.25,
        timeout: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.page_delay = page_delay
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": user_agent}
        )

    def _get(self, url: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET a single URL, retrying transient errors with exponential backoff."""
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                # 5xx are transient; retry. 4xx are not; raise immediately.
                if response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status is not None and status < 500:
                    raise  # client error — not worth retrying
                last_exc = exc

            if attempt < self.max_retries:
                if self.backoff_base:
                    time.sleep(self.backoff_base * (2 ** attempt))

        assert last_exc is not None
        raise last_exc

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET a single endpoint, returning the full JSON response dict (non-paginated)."""
        return self._get(self.base_url + path, params=params)

    @staticmethod
    def _next_link(payload: Dict[str, Any]) -> Optional[str]:
        for link in payload.get("links", []) or []:
            if link.get("rel") == "next":
                return link.get("href")
        return None

    def get_all(
        self, path: str, params: Optional[Dict[str, Any]] = None
    ) -> List[Dict[str, Any]]:
        """Fetch every page of a listing endpoint, merging all ``dados`` records.

        The first request uses ``base_url + path`` with ``params``. Subsequent
        pages follow the absolute ``next`` link returned by the API.
        """
        url: Optional[str] = self.base_url + path
        records: List[Dict[str, Any]] = []
        first = True
        while url:
            payload = self._get(url, params=params if first else None)
            records.extend(payload.get("dados", []) or [])
            url = self._next_link(payload)
            first = False
            if url and self.page_delay:
                time.sleep(self.page_delay)
        return records


class SenadoClient:
    """Minimal client for the Senado Federal open-data API.

    The Senado API returns XML by default but honors ``Accept: application/json``
    for every endpoint we use, so this requests JSON. Unlike Câmara it returns whole
    payloads (no ``links``/``next`` pagination), so a single ``get`` is enough; the
    verbose JSON envelope is unwrapped by the caller (see ``common.senado_json``).

    Same retry/backoff behaviour as ``CamaraClient``: retry transient errors (5xx,
    timeouts, connection drops) with exponential backoff; client errors raise at once.
    """

    def __init__(
        self,
        base_url: str = SENADO_BASE_URL,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        page_delay: float = 0.25,
        timeout: float = 30.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.base_url = base_url.rstrip("/")
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.page_delay = page_delay
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update(
            {"Accept": "application/json", "User-Agent": user_agent}
        )

    def get(self, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        """GET ``base_url + path`` as JSON, retrying transient errors with backoff."""
        url = self.base_url + path
        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, params=params, timeout=self.timeout)
                if response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()
                return response.json()
            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status is not None and status < 500:
                    raise  # client error — not worth retrying
                last_exc = exc

            if attempt < self.max_retries:
                if self.backoff_base:
                    time.sleep(self.backoff_base * (2 ** attempt))

        assert last_exc is not None
        raise last_exc


class TseDownloader:
    """Streaming downloader for large TSE bulk files (ZIPs, CSV archives).

    Unlike ``CamaraClient``/``SenadoClient`` which are designed for paginated
    JSON API calls, this streams binary content to a temp file and renames
    atomically.  Retry behaviour mirrors the existing clients.
    """

    def __init__(
        self,
        session: Optional[requests.Session] = None,
        max_retries: int = 3,
        backoff_base: float = 0.5,
        chunk_size: int = 65536,
        timeout: float = 120.0,
        user_agent: str = DEFAULT_USER_AGENT,
    ) -> None:
        self.max_retries = max_retries
        self.backoff_base = backoff_base
        self.chunk_size = chunk_size
        self.timeout = timeout
        self.session = session or requests.Session()
        self.session.headers.update({"User-Agent": user_agent})

    def download(self, url: str, dest_path: Path) -> None:
        """Stream ``url`` to ``dest_path`` via a temp file (atomic rename on success).

        Retries on 5xx, timeouts, and connection errors with exponential backoff.
        Raises immediately on 4xx (not retryable).
        Raises ``ValueError`` on Content-Length mismatch; removes the temp file.
        """
        dest_path = Path(dest_path)
        dest_path.parent.mkdir(parents=True, exist_ok=True)
        tmp_path = dest_path.with_name(dest_path.name + ".tmp")

        last_exc: Optional[Exception] = None
        for attempt in range(self.max_retries + 1):
            try:
                response = self.session.get(url, stream=True, timeout=self.timeout)
                if response.status_code >= 500:
                    response.raise_for_status()
                response.raise_for_status()

                content_length = response.headers.get("Content-Length")
                expected = int(content_length) if content_length else None

                written = 0
                with open(tmp_path, "wb") as fh:
                    for chunk in response.iter_content(chunk_size=self.chunk_size):
                        fh.write(chunk)
                        written += len(chunk)

                if expected is not None and written != expected:
                    tmp_path.unlink(missing_ok=True)
                    raise ValueError(
                        f"Content-length mismatch downloading {url}: "
                        f"expected {expected}, got {written}"
                    )

                os.replace(tmp_path, dest_path)
                return

            except (requests.ConnectionError, requests.Timeout) as exc:
                last_exc = exc
            except requests.HTTPError as exc:
                status = exc.response.status_code if exc.response is not None else None
                if status is not None and status < 500:
                    raise
                last_exc = exc

            tmp_path.unlink(missing_ok=True)
            if attempt < self.max_retries and self.backoff_base:
                time.sleep(self.backoff_base * (2 ** attempt))

        assert last_exc is not None
        raise last_exc
