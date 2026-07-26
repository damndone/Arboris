from __future__ import annotations

import pytest


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
