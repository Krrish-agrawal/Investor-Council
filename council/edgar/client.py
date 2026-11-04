"""EDGAR HTTP client with an on-disk response cache.

* Declares an identifying User-Agent (required; supplied by the user, never defaulted) and keeps
  below the SEC's published ceiling of 10 requests/second.
* Responses are validated *before* they are cached, so an invalid response never becomes a snapshot.
* The cache is the frozen dataset: ``<cache_dir>/CIK##########/<kind>.json`` plus a sidecar
  ``<kind>.meta.json`` recording the source URL, retrieval timestamp (UTC) and SHA-256.
  Cached responses are reused unless ``refresh=True``; a cached file whose hash no longer matches
  its sidecar is refused rather than silently re-downloaded.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import time
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import httpx

from council.edgar.models import COMPANY_FACTS_URL, SUBMISSIONS_URL, normalize_cik
from council.edgar.validate import parse_submissions, validate_companyfacts
from council.errors import (
    ConfigError,
    DataValidationError,
    EdgarCacheError,
    EdgarError,
    EdgarNotFoundError,
)

log = logging.getLogger(__name__)

Kind = Literal["companyfacts", "submissions"]
MAX_RESPONSE_BYTES = 250 * 1024 * 1024
SEC_MAX_RPS = 10.0
_URLS: dict[str, str] = {"companyfacts": COMPANY_FACTS_URL, "submissions": SUBMISSIONS_URL}


@dataclass(frozen=True)
class CacheMeta:
    url: str
    kind: str
    cik: str
    retrieved_at: datetime  # timezone-aware UTC
    sha256: str
    size_bytes: int
    status_code: int

    def to_json(self) -> dict[str, Any]:
        return {
            "url": self.url,
            "kind": self.kind,
            "cik": self.cik,
            "retrieved_at": self.retrieved_at.isoformat(),
            "sha256": self.sha256,
            "size_bytes": self.size_bytes,
            "status_code": self.status_code,
        }

    @staticmethod
    def from_json(data: dict[str, Any]) -> CacheMeta:
        try:
            retrieved = datetime.fromisoformat(data["retrieved_at"])
            if retrieved.tzinfo is None:
                raise ValueError("retrieved_at has no timezone")
            return CacheMeta(
                url=str(data["url"]),
                kind=str(data["kind"]),
                cik=str(data["cik"]),
                retrieved_at=retrieved.astimezone(timezone.utc),
                sha256=str(data["sha256"]),
                size_bytes=int(data["size_bytes"]),
                status_code=int(data["status_code"]),
            )
        except (KeyError, ValueError, TypeError) as exc:
            raise EdgarCacheError(f"invalid cache metadata: {exc}") from exc


@dataclass(frozen=True)
class CachedDocument:
    path: Path
    meta: CacheMeta
    raw: dict[str, Any]
    from_cache: bool


def cache_paths(cache_dir: Path | str, cik: str | int, kind: Kind) -> tuple[Path, Path]:
    """(document path, metadata path) for a cached response."""
    folder = Path(cache_dir) / f"CIK{normalize_cik(cik)}"
    return folder / f"{kind}.json", folder / f"{kind}.meta.json"


def read_cached_document(cache_dir: Path | str, cik: str | int, kind: Kind) -> CachedDocument | None:
    """Read a cached response without any network access. ``None`` if it was never cached.

    Raises :class:`EdgarCacheError` if the cache is incomplete or the file no longer matches the
    SHA-256 recorded when it was retrieved.
    """
    path, meta_path = cache_paths(cache_dir, cik, kind)
    if not path.exists() and not meta_path.exists():
        return None
    if not (path.exists() and meta_path.exists()):
        raise EdgarCacheError(f"Incomplete cache for CIK{normalize_cik(cik)} {kind}: need both {path.name} and {meta_path.name}")
    meta = CacheMeta.from_json(json.loads(meta_path.read_text(encoding="utf-8")))
    content = path.read_bytes()
    if hashlib.sha256(content).hexdigest() != meta.sha256:
        raise EdgarCacheError(
            f"{path} does not match the SHA-256 recorded when it was retrieved. "
            "Refusing to use altered data; re-download with --refresh if that is intended."
        )
    return CachedDocument(path, meta, json.loads(content), from_cache=True)


class _RateLimiter:
    def __init__(
        self,
        max_rps: float,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
    ) -> None:
        if not 0 < max_rps <= SEC_MAX_RPS:
            raise ConfigError(f"max_rps must be in (0, {SEC_MAX_RPS}]")
        self._interval = 1.0 / max_rps
        self._clock = clock
        self._sleep = sleep
        self._next = 0.0

    def wait(self) -> None:
        now = self._clock()
        if now < self._next:
            self._sleep(self._next - now)
            now = self._next
        self._next = now + self._interval


class EdgarClient:
    """Fetch and cache company facts and submissions for a CIK."""

    def __init__(
        self,
        *,
        user_agent: str,
        cache_dir: Path | str,
        max_rps: float = 5.0,
        transport: httpx.BaseTransport | None = None,
        timeout: float = 30.0,
        retries: int = 2,
        clock: Callable[[], float] = time.monotonic,
        sleep: Callable[[float], None] = time.sleep,
        now: Callable[[], datetime] = lambda: datetime.now(timezone.utc),
    ) -> None:
        if not user_agent.strip() or "@" not in user_agent:
            raise ConfigError('A declared User-Agent with a contact email is required, e.g. "Jane Doe jane@example.com".')
        self._cache_dir = Path(cache_dir)
        self._limiter = _RateLimiter(max_rps, clock, sleep)
        self._sleep = sleep
        self._retries = retries
        self._now = now
        self._http = httpx.Client(
            transport=transport,
            timeout=timeout,
            headers={"User-Agent": user_agent, "Accept-Encoding": "gzip, deflate"},
            follow_redirects=False,
        )

    def close(self) -> None:
        self._http.close()

    def __enter__(self) -> EdgarClient:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    # ---- paths -----------------------------------------------------------------------------

    def paths(self, cik: str, kind: Kind) -> tuple[Path, Path]:
        return cache_paths(self._cache_dir, cik, kind)

    # ---- public API --------------------------------------------------------------------------

    def get_company_facts(self, cik: str | int, *, refresh: bool = False) -> CachedDocument:
        return self._get(normalize_cik(cik), "companyfacts", refresh)

    def get_submissions(self, cik: str | int, *, refresh: bool = False) -> CachedDocument:
        return self._get(normalize_cik(cik), "submissions", refresh)

    def load_cached(self, cik: str | int, kind: Kind) -> CachedDocument | None:
        """Read a cached document without touching the network. ``None`` if not cached."""
        return self._read_cache(normalize_cik(cik), kind)

    # ---- internals -----------------------------------------------------------------------------

    def _get(self, cik: str, kind: Kind, refresh: bool) -> CachedDocument:
        if not refresh:
            cached = self._read_cache(cik, kind)
            if cached is not None:
                log.info("Using cached %s for CIK%s (retrieved %s)", kind, cik, cached.meta.retrieved_at.isoformat())
                return cached
        url = _URLS[kind].format(cik=cik)
        content, status = self._download(url, cik)
        try:
            raw = json.loads(content)
        except json.JSONDecodeError as exc:
            raise DataValidationError(f"{url} did not return valid JSON: {exc}") from exc
        self._validate(kind, raw, cik)
        return self._write_cache(cik, kind, url, content, status, raw)

    @staticmethod
    def _validate(kind: Kind, raw: Any, cik: str) -> None:
        if kind == "companyfacts":
            report = validate_companyfacts(raw, expected_cik=cik)
            log.info("Validated company facts for CIK%s: %d entries", cik, report.entries_checked)
        else:
            info = parse_submissions(raw, expected_cik=cik)
            log.info("Validated submissions for CIK%s: %d recent filings", cik, len(info.filings))

    def _download(self, url: str, cik: str) -> tuple[bytes, int]:
        last_error: Exception | None = None
        for attempt in range(self._retries + 1):
            self._limiter.wait()
            try:
                response = self._http.get(url)
            except httpx.TransportError as exc:
                last_error = exc
                log.warning("EDGAR request failed (%s); attempt %d/%d", type(exc).__name__, attempt + 1, self._retries + 1)
                self._sleep(2.0**attempt)
                continue
            status = response.status_code
            if status == 200:
                if len(response.content) > MAX_RESPONSE_BYTES:
                    raise EdgarError(f"{url} returned more than {MAX_RESPONSE_BYTES} bytes; refusing")
                return response.content, status
            if status == 404:
                raise EdgarNotFoundError(f"EDGAR has no document at {url} (is CIK{cik} correct?)")
            if status in (403, 429):
                raise EdgarError(
                    f"EDGAR answered HTTP {status} for {url}. Check that your declared User-Agent "
                    "(COUNCIL_SEC_USER_AGENT) identifies you and that you are within SEC fair-access limits "
                    "(max 10 requests/second); wait before retrying."
                )
            if status >= 500:
                last_error = EdgarError(f"HTTP {status}")
                log.warning("EDGAR server error %s; attempt %d/%d", status, attempt + 1, self._retries + 1)
                self._sleep(2.0**attempt)
                continue
            raise EdgarError(f"Unexpected HTTP {status} from {url}")
        raise EdgarError(f"EDGAR request to {url} failed after {self._retries + 1} attempts: {last_error}")

    def _write_cache(
        self, cik: str, kind: Kind, url: str, content: bytes, status: int, raw: dict[str, Any]
    ) -> CachedDocument:
        path, meta_path = self.paths(cik, kind)
        path.parent.mkdir(parents=True, exist_ok=True)
        meta = CacheMeta(
            url=url,
            kind=kind,
            cik=cik,
            retrieved_at=self._now().astimezone(timezone.utc),
            sha256=hashlib.sha256(content).hexdigest(),
            size_bytes=len(content),
            status_code=status,
        )
        _atomic_write(path, content)
        _atomic_write(meta_path, json.dumps(meta.to_json(), indent=2, sort_keys=True).encode() + b"\n")
        log.info("Cached %s for CIK%s (%d bytes, sha256 %s...)", kind, cik, len(content), meta.sha256[:12])
        return CachedDocument(path, meta, raw, from_cache=False)

    def _read_cache(self, cik: str, kind: Kind) -> CachedDocument | None:
        return read_cached_document(self._cache_dir, cik, kind)


def _atomic_write(path: Path, content: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(content)
    os.replace(tmp, path)
