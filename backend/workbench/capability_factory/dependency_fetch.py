"""Pure validation of network-fetch metadata; no network calls are made."""

from __future__ import annotations

from dataclasses import dataclass
from urllib.parse import urlsplit

from .contracts import _digest, _sequence, _text


class FetchValidationError(ValueError):
    """Raised when a fetch result violates the immutable fetch policy."""


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
    "FetchMetadata",
    "FetchPolicy",
    "FetchValidationError",
    "FetchValidationResult",
    "validate_fetch_metadata",
]
