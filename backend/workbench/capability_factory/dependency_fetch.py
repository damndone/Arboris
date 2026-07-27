"""Strict network fetch into an immutable, content-addressed quarantine.

The fetch plane is intentionally separate from dependency assembly and
validation.  It can contact an allowlisted HTTPS origin, but it never imports,
installs, or executes the bytes it receives.  The default transport disables
ambient proxy configuration and redirects are followed only after each target
passes the same origin policy.
"""

from __future__ import annotations

import hashlib
import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Protocol
from urllib.parse import urlsplit
from urllib.error import HTTPError
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener, urljoin

from .contracts import _digest, _sequence, _text


class FetchValidationError(ValueError):
    """Raised when a fetch result violates the immutable fetch policy."""


class FetchWorkerError(FetchValidationError):
    """Raised when a network fetch cannot produce a verified quarantine object."""


def _allowed_origin(url: str, origins: tuple[str, ...]) -> bool:
    parsed = urlsplit(url)
    origin = f"{parsed.scheme}://{parsed.netloc}".rstrip("/")
    return origin in origins


@dataclass(frozen=True, slots=True)
class FetchPolicy:
    allowed_origins: tuple[str, ...]
    max_artifact_bytes: int
    max_redirects: int

    def __post_init__(self) -> None:
        origins = _sequence(self.allowed_origins, "allowed_origins")
        if any(not item.startswith("https://") for item in origins):
            raise FetchValidationError("allowed origins must use https")
        if not isinstance(self.max_artifact_bytes, int) or self.max_artifact_bytes < 1:
            raise FetchValidationError("max_artifact_bytes must be positive")
        if not isinstance(self.max_redirects, int) or self.max_redirects < 0:
            raise FetchValidationError("max_redirects must be non-negative")
        object.__setattr__(self, "allowed_origins", tuple(item.rstrip("/") for item in origins))


@dataclass(frozen=True, slots=True)
class FetchMetadata:
    requested_url: str
    final_url: str
    content_digest: str
    content_length: int
    redirect_chain: tuple[str, ...]

    def __post_init__(self) -> None:
        for field in ("requested_url", "final_url"):
            url = _text(getattr(self, field), field)
            parsed = urlsplit(url)
            if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
                raise FetchValidationError(f"{field} must be an https URL without query or fragment")
            object.__setattr__(self, field, url)
        try:
            object.__setattr__(self, "content_digest", _digest(self.content_digest, "content_digest"))
        except ValueError as error:
            raise FetchValidationError(str(error)) from error
        if not isinstance(self.content_length, int) or self.content_length < 0:
            raise FetchValidationError("content_length must be non-negative")
        redirects = _sequence(self.redirect_chain, "redirect_chain", allow_empty=True)
        object.__setattr__(self, "redirect_chain", redirects)


@dataclass(frozen=True, slots=True)
class FetchValidationResult:
    status: str
    reason_code: str


class FetchResponse(Protocol):
    status: int
    headers: Mapping[str, Any]

    def read(self, size: int = -1) -> bytes: ...


class FetchTransport(Protocol):
    def open(self, url: str) -> FetchResponse: ...


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):  # type: ignore[no-untyped-def]
        return None


class _UrllibFetchTransport:
    """Minimal HTTPS GET transport with no ambient proxy or redirect policy."""

    def __init__(self) -> None:
        self._opener = build_opener(ProxyHandler({}), _NoRedirect())

    def open(self, url: str) -> FetchResponse:
        request = Request(
            url,
            method="GET",
            headers={"Accept": "application/octet-stream"},
        )
        try:
            return self._opener.open(request, timeout=30)
        except HTTPError as error:
            # Redirect responses are useful to the worker because it applies
            # the allowlist itself. Other HTTP errors remain fetch failures.
            if 300 <= error.code < 400:
                return error
            raise FetchWorkerError(f"HTTP fetch failed with status {error.code}") from error


@dataclass(frozen=True, slots=True)
class QuarantinedArtifact:
    artifact_ref: str
    metadata: FetchMetadata
    path: Path

    def __post_init__(self) -> None:
        object.__setattr__(self, "artifact_ref", _digest(self.artifact_ref, "artifact_ref"))
        if self.metadata.content_digest != self.artifact_ref:
            raise FetchWorkerError("quarantine artifact ref does not match fetched content")
        path = Path(self.path)
        if not path.is_absolute() or path.name != f"{self.artifact_ref}.artifact":
            raise FetchWorkerError("quarantine path is not the content-addressed artifact path")
        object.__setattr__(self, "path", path)


class FetchWorker:
    """Fetch locked bytes and atomically persist them in a quarantine root."""

    _CHUNK_SIZE = 64 * 1024

    def __init__(self, *, transport: FetchTransport | None = None) -> None:
        self.transport = transport or _UrllibFetchTransport()

    def fetch(
        self,
        *,
        url: str,
        expected_digest: str,
        policy: FetchPolicy,
        quarantine_root: Path | str,
    ) -> QuarantinedArtifact:
        if not isinstance(policy, FetchPolicy):
            raise FetchWorkerError("policy must be a FetchPolicy")
        try:
            expected = _digest(expected_digest, "expected_digest")
        except ValueError as error:
            raise FetchWorkerError(str(error)) from error
        current = self._validate_url(url, field="requested URL", policy=policy)
        requested = current
        redirect_chain: list[str] = []
        body: bytes | None = None
        while True:
            try:
                response = self.transport.open(current)
            except FetchWorkerError:
                raise
            except Exception as error:
                raise FetchWorkerError("network fetch failed") from error
            try:
                status = self._status(response)
                if 300 <= status < 400:
                    if len(redirect_chain) >= policy.max_redirects:
                        raise FetchWorkerError("redirect limit exceeded")
                    location = self._header(response, "Location")
                    if not location:
                        raise FetchWorkerError("redirect response has no Location")
                    next_url = self._validate_url(
                        urljoin(current, location), field="redirect URL", policy=policy
                    )
                    if next_url in {requested, *redirect_chain}:
                        raise FetchWorkerError("redirect cycle detected")
                    redirect_chain.append(next_url)
                    current = next_url
                    continue
                if not 200 <= status < 300 or status == 206:
                    raise FetchWorkerError(f"HTTP fetch returned unexpected status {status}")
                declared_length = self._content_length(response)
                if declared_length is not None and declared_length > policy.max_artifact_bytes:
                    raise FetchWorkerError("artifact exceeds the policy size limit")
                body = self._read_bounded(response, policy.max_artifact_bytes)
                if declared_length is not None and declared_length != len(body):
                    raise FetchWorkerError("content length does not match the received bytes")
                break
            finally:
                close = getattr(response, "close", None)
                if callable(close):
                    close()

        assert body is not None
        actual = hashlib.sha256(body).hexdigest()
        if actual != expected:
            raise FetchWorkerError("fetched artifact digest does not match the lock")
        metadata = FetchMetadata(
            requested_url=requested,
            final_url=current,
            content_digest=actual,
            content_length=len(body),
            redirect_chain=tuple(redirect_chain),
        )
        validate_fetch_metadata(metadata, expected_digest=expected, policy=policy)
        path = self._write_quarantine(body, expected, quarantine_root)
        return QuarantinedArtifact(artifact_ref=expected, metadata=metadata, path=path)

    @staticmethod
    def _status(response: FetchResponse) -> int:
        value = getattr(response, "status", getattr(response, "code", None))
        if not isinstance(value, int):
            raise FetchWorkerError("fetch response has no valid status")
        return value

    @staticmethod
    def _header(response: FetchResponse, name: str) -> str | None:
        headers = getattr(response, "headers", None)
        if isinstance(headers, Mapping):
            items = headers.items()
        else:
            items_method = getattr(headers, "items", None)
            if not callable(items_method):
                return None
            items = items_method()
        for key, value in items:
            if str(key).lower() == name.lower():
                return str(value)
        return None

    @classmethod
    def _content_length(cls, response: FetchResponse) -> int | None:
        value = cls._header(response, "Content-Length")
        if value is None:
            return None
        if not value.isdigit():
            raise FetchWorkerError("content length is invalid")
        return int(value)

    @classmethod
    def _read_bounded(cls, response: FetchResponse, limit: int) -> bytes:
        chunks: list[bytes] = []
        total = 0
        while True:
            try:
                chunk = response.read(cls._CHUNK_SIZE)
            except Exception as error:
                raise FetchWorkerError("reading fetched artifact failed") from error
            if not isinstance(chunk, bytes):
                raise FetchWorkerError("fetch response returned non-byte content")
            if not chunk:
                break
            total += len(chunk)
            if total > limit:
                raise FetchWorkerError("artifact exceeds the policy size limit")
            chunks.append(chunk)
        return b"".join(chunks)

    @staticmethod
    def _validate_url(url: str, *, field: str, policy: FetchPolicy) -> str:
        text = _text(url, field)
        parsed = urlsplit(text)
        if parsed.scheme != "https" or not parsed.netloc or parsed.query or parsed.fragment:
            raise FetchWorkerError(f"{field} must be an https URL without query or fragment")
        if not _allowed_origin(text, policy.allowed_origins):
            raise FetchWorkerError("fetch URL or redirect is outside the allowlist")
        return text

    @staticmethod
    def _write_quarantine(body: bytes, digest: str, quarantine_root: Path | str) -> Path:
        root = Path(quarantine_root)
        if not root.is_absolute():
            raise FetchWorkerError("quarantine root must be absolute")
        FetchWorker._assert_no_symlink_ancestors(root)
        if root.exists() and root.is_symlink():
            raise FetchWorkerError("quarantine root must not be a symlink")
        root.mkdir(parents=True, exist_ok=True)
        if root.is_symlink() or not root.is_dir():
            raise FetchWorkerError("quarantine root is not a directory")
        destination = root / f"{digest}.artifact"
        if destination.is_symlink():
            raise FetchWorkerError("quarantine destination must not be a symlink")
        if destination.exists():
            if not destination.is_file():
                raise FetchWorkerError("content-addressed quarantine object is not a regular file")
            if destination.stat().st_nlink != 1:
                raise FetchWorkerError("content-addressed quarantine object is a hardlink")
            if hashlib.sha256(destination.read_bytes()).hexdigest() != digest:
                raise FetchWorkerError("content-addressed quarantine object is already bound")
            return destination
        fd, temporary_name = tempfile.mkstemp(prefix=".fetch-", suffix=".tmp", dir=root)
        temporary = Path(temporary_name)
        try:
            with os.fdopen(fd, "wb") as handle:
                handle.write(body)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, destination)
            return destination
        except OSError as error:
            raise FetchWorkerError("quarantine write failed") from error
        finally:
            try:
                temporary.unlink()
            except FileNotFoundError:
                pass

    @staticmethod
    def _assert_no_symlink_ancestors(path: Path) -> None:
        current = path
        while True:
            if current.is_symlink():
                raise FetchWorkerError("quarantine path contains a symlink ancestor")
            if current.parent == current:
                return
            current = current.parent


def validate_fetch_metadata(
    metadata: FetchMetadata,
    *,
    expected_digest: str,
    policy: FetchPolicy,
) -> FetchValidationResult:
    if not isinstance(metadata, FetchMetadata) or not isinstance(policy, FetchPolicy):
        raise FetchValidationError("metadata and policy have invalid types")
    try:
        expected = _digest(expected_digest, "expected_digest")
    except ValueError as error:
        raise FetchValidationError(str(error)) from error
    if metadata.content_digest != expected:
        raise FetchValidationError("fetched artifact digest does not match the lock")
    if len(metadata.redirect_chain) > policy.max_redirects:
        raise FetchValidationError("redirect limit exceeded")
    urls = (metadata.requested_url, *metadata.redirect_chain, metadata.final_url)
    if any(not _allowed_origin(url, policy.allowed_origins) for url in urls):
        raise FetchValidationError("fetch URL or redirect is outside the allowlist")
    if metadata.content_length > policy.max_artifact_bytes:
        raise FetchValidationError("artifact exceeds the policy size limit")
    return FetchValidationResult("accepted", "pinned_artifact_metadata_valid")


__all__ = [
    "FetchTransport",
    "FetchMetadata",
    "FetchPolicy",
    "FetchValidationError",
    "FetchValidationResult",
    "FetchWorker",
    "FetchWorkerError",
    "QuarantinedArtifact",
    "validate_fetch_metadata",
]
