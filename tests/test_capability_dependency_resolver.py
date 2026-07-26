from __future__ import annotations

import pytest


def _requirement(contracts):
    return contracts.DependencyRequirement(
        distribution="safe-library",
        version="1.2.3",
        artifact_digest="a" * 64,
        python_tag="py3",
        platform_tag="macosx_14_0_arm64",
        index_origin="https://packages.example.test/simple",
    )


def _policy(resolver):
    return resolver.DependencyResolutionPolicy(
        policy_id="resolver.alpha",
        revision=1,
        allowed_origins=("https://packages.example.test",),
        python_version="3.14.6",
        operating_system="darwin",
        architecture="arm64",
    )


def test_offline_resolver_selects_only_exact_snapshot_artifact():
    from workbench.capability_factory import dependency_contract as contracts
    from workbench.capability_factory import dependency_resolver as resolver

    requirement = _requirement(contracts)
    snapshot = resolver.IndexSnapshot(
        snapshot_ref="b" * 64,
        artifacts=(
            resolver.ArtifactCandidate(
                distribution="safe-library",
                version="1.2.3",
                artifact_digest="a" * 64,
                url="https://packages.example.test/files/safe.whl",
                python_tag="py3",
                platform_tag="macosx_14_0_arm64",
            ),
        ),
    )

    lock = resolver.DependencyResolver().resolve(
        requirements=(requirement,), snapshot=snapshot, policy=_policy(resolver)
    )

    assert lock.requirements == (requirement,)
    assert lock.content_digest


@pytest.mark.parametrize(
    "artifacts",
    [
        (),
        (
            {
                "distribution": "safe-library",
                "version": "1.2.3",
                "artifact_digest": "b" * 64,
                "url": "https://packages.example.test/files/other.whl",
                "python_tag": "py3",
                "platform_tag": "macosx_14_0_arm64",
            },
        ),
        (
            {
                "distribution": "safe-library",
                "version": "1.2.3",
                "artifact_digest": "a" * 64,
                "url": "https://evil.example.test/files/safe.whl",
                "python_tag": "py3",
                "platform_tag": "macosx_14_0_arm64",
            },
        ),
    ],
)
def test_offline_resolver_rejects_missing_hash_mismatch_or_origin_escape(artifacts):
    from workbench.capability_factory import dependency_contract as contracts
    from workbench.capability_factory import dependency_resolver as resolver

    requirement = _requirement(contracts)
    candidates = tuple(
        item if isinstance(item, resolver.ArtifactCandidate) else resolver.ArtifactCandidate(**item)
        for item in artifacts
    )
    snapshot = resolver.IndexSnapshot(snapshot_ref="b" * 64, artifacts=candidates)

    with pytest.raises(resolver.DependencyResolutionError):
        resolver.DependencyResolver().resolve(
            requirements=(requirement,), snapshot=snapshot, policy=_policy(resolver)
        )
