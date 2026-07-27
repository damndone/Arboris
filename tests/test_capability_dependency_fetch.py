from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


class _Response:
    def __init__(self, status: int, *, body: bytes = b"", headers: dict[str, str] | None = None) -> None:
        self.status = status
        self.headers = headers or {}
        self._body = body

    def read(self, _size: int = -1) -> bytes:
        body, self._body = self._body, b""
        return body


class _Transport:
    def __init__(self, responses: dict[str, _Response]) -> None:
        self.responses = responses
        self.calls: list[str] = []

    def open(self, url: str) -> _Response:
        self.calls.append(url)
        return self.responses[url]


def test_fetch_metadata_accepts_pinned_artifact_without_following_redirects():
    from workbench.capability_factory.dependency_fetch import (
        FetchPolicy,
        FetchMetadata,
        validate_fetch_metadata,
    )

    policy = FetchPolicy(
        allowed_origins=("https://packages.example.test",),
        max_artifact_bytes=1024,
        max_redirects=1,
    )
    metadata = FetchMetadata(
        requested_url="https://packages.example.test/files/safe.whl",
        final_url="https://packages.example.test/files/safe.whl",
        content_digest="a" * 64,
        content_length=128,
        redirect_chain=(),
    )

    result = validate_fetch_metadata(metadata, expected_digest="a" * 64, policy=policy)

    assert result.status == "accepted"


@pytest.mark.parametrize(
    "mutator",
    [
        lambda item: item.__class__(
            requested_url=item.requested_url,
            final_url=item.final_url,
            content_digest="b" * 64,
            content_length=item.content_length,
            redirect_chain=item.redirect_chain,
        ),
        lambda item: item.__class__(
            requested_url=item.requested_url,
            final_url="https://evil.example.test/file.whl",
            content_digest=item.content_digest,
            content_length=item.content_length,
            redirect_chain=("https://evil.example.test/file.whl",),
        ),
        lambda item: item.__class__(
            requested_url=item.requested_url,
            final_url=item.final_url,
            content_digest=item.content_digest,
            content_length=2048,
            redirect_chain=item.redirect_chain,
        ),
    ],
)
def test_fetch_metadata_rejects_hash_redirect_and_size_violations(mutator):
    from workbench.capability_factory.dependency_fetch import (
        FetchPolicy,
        FetchMetadata,
        FetchValidationError,
        validate_fetch_metadata,
    )

    policy = FetchPolicy(
        allowed_origins=("https://packages.example.test",),
        max_artifact_bytes=1024,
        max_redirects=1,
    )
    metadata = FetchMetadata(
        requested_url="https://packages.example.test/files/safe.whl",
        final_url="https://packages.example.test/files/safe.whl",
        content_digest="a" * 64,
        content_length=128,
        redirect_chain=(),
    )
    with pytest.raises(FetchValidationError):
        validate_fetch_metadata(mutator(metadata), expected_digest="a" * 64, policy=policy)


def test_fetch_worker_follows_only_allowlisted_redirects_and_writes_content_addressed_quarantine(tmp_path: Path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker

    body = b"immutable wheel bytes"
    digest = hashlib.sha256(body).hexdigest()
    start = "https://packages.example.test/files/start.whl"
    final = "https://packages.example.test/files/final.whl"
    transport = _Transport(
        {
            start: _Response(302, headers={"Location": final}),
            final: _Response(200, body=body, headers={"Content-Length": str(len(body))}),
        }
    )
    receipt = FetchWorker(transport=transport).fetch(
        url=start,
        expected_digest=digest,
        policy=FetchPolicy(
            allowed_origins=("https://packages.example.test",),
            max_artifact_bytes=1024,
            max_redirects=1,
        ),
        quarantine_root=tmp_path / "quarantine",
    )

    assert transport.calls == [start, final]
    assert receipt.metadata.redirect_chain == (final,)
    assert receipt.artifact_ref == digest
    assert receipt.path.read_bytes() == body
    assert receipt.path == tmp_path / "quarantine" / f"{digest}.artifact"


def test_fetch_worker_rejects_redirect_escape_before_following_it(tmp_path: Path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker, FetchWorkerError

    start = "https://packages.example.test/files/start.whl"
    transport = _Transport(
        {start: _Response(302, headers={"Location": "https://evil.example.test/file.whl"})}
    )

    with pytest.raises(FetchWorkerError, match="allowlist"):
        FetchWorker(transport=transport).fetch(
            url=start,
            expected_digest="a" * 64,
            policy=FetchPolicy(
                allowed_origins=("https://packages.example.test",),
                max_artifact_bytes=1024,
                max_redirects=1,
            ),
            quarantine_root=tmp_path,
        )
    assert transport.calls == [start]


def test_fetch_worker_rejects_digest_and_size_mismatch_without_persisting(tmp_path: Path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker, FetchWorkerError

    url = "https://packages.example.test/files/safe.whl"
    transport = _Transport(
        {url: _Response(200, body=b"not-the-locked-bytes", headers={"Content-Length": "20"})}
    )
    root = tmp_path / "quarantine"
    with pytest.raises(FetchWorkerError, match="digest"):
        FetchWorker(transport=transport).fetch(
            url=url,
            expected_digest="a" * 64,
            policy=FetchPolicy(
                allowed_origins=("https://packages.example.test",),
                max_artifact_bytes=1024,
                max_redirects=0,
            ),
            quarantine_root=root,
        )
    assert not list(root.glob("*.artifact"))


def test_fetch_worker_rejects_a_preexisting_hardlink_destination(tmp_path: Path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker, FetchWorkerError

    body = b"immutable wheel bytes"
    digest = hashlib.sha256(body).hexdigest()
    root = tmp_path / "quarantine"
    root.mkdir()
    outside = tmp_path / "outside.artifact"
    outside.write_bytes(body)
    destination = root / f"{digest}.artifact"
    destination.hardlink_to(outside)

    with pytest.raises(FetchWorkerError, match="hardlink"):
        FetchWorker(
            transport=_Transport(
                {
                    "https://packages.example.test/files/safe.whl": _Response(
                        200, body=body, headers={"Content-Length": str(len(body))}
                    )
                }
            )
        ).fetch(
            url="https://packages.example.test/files/safe.whl",
            expected_digest=digest,
            policy=FetchPolicy(
                allowed_origins=("https://packages.example.test",),
                max_artifact_bytes=1024,
                max_redirects=0,
            ),
            quarantine_root=root,
        )


def test_fetch_worker_rejects_a_symlinked_quarantine_ancestor(tmp_path: Path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker, FetchWorkerError

    body = b"immutable wheel bytes"
    digest = hashlib.sha256(body).hexdigest()
    real_root = tmp_path / "real"
    real_root.mkdir()
    linked_parent = tmp_path / "linked"
    linked_parent.symlink_to(real_root, target_is_directory=True)

    with pytest.raises(FetchWorkerError, match="symlink"):
        FetchWorker(
            transport=_Transport(
                {
                    "https://packages.example.test/files/safe.whl": _Response(
                        200, body=body, headers={"Content-Length": str(len(body))}
                    )
                }
            )
        ).fetch(
            url="https://packages.example.test/files/safe.whl",
            expected_digest=digest,
            policy=FetchPolicy(
                allowed_origins=("https://packages.example.test",),
                max_artifact_bytes=1024,
                max_redirects=0,
            ),
            quarantine_root=linked_parent / "quarantine",
        )
