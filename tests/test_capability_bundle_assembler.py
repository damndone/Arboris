from __future__ import annotations

import hashlib
import io
import zipfile

import pytest


def _wheel(*, unsafe: str | None = None):
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("safe_library/__init__.py", b"VALUE = 1\n")
        archive.writestr(
            "safe_library-1.2.3.dist-info/METADATA",
            b"Metadata-Version: 2.3\nName: safe-library\nVersion: 1.2.3\n",
        )
        archive.writestr("safe_library-1.2.3.dist-info/WHEEL", b"Wheel-Version: 1.0\n")
        if unsafe:
            archive.writestr(unsafe, b"import os\n")
    return buffer.getvalue()


def _lock(contracts, resolver, raw):
    requirement = contracts.DependencyRequirement(
        distribution="safe-library",
        version="1.2.3",
        artifact_digest=hashlib.sha256(raw).hexdigest(),
        python_tag="py3",
        platform_tag="macosx_14_0_arm64",
        index_origin="https://packages.example.test/simple",
    )
    policy = resolver.DependencyResolutionPolicy(
        policy_id="resolver.alpha",
        revision=1,
        allowed_origins=("https://packages.example.test",),
        python_version="3.14.6",
        operating_system="darwin",
        architecture="arm64",
    )
    snapshot = resolver.IndexSnapshot(
        snapshot_ref="a" * 64,
        artifacts=(resolver.ArtifactCandidate(
            distribution="safe-library",
            version="1.2.3",
            artifact_digest=requirement.artifact_digest,
            url="https://packages.example.test/files/safe.whl",
            python_tag="py3",
            platform_tag="macosx_14_0_arm64",
        ),),
    )
    return resolver.DependencyResolver().resolve(
        requirements=(requirement,), snapshot=snapshot, policy=policy
    )


def test_assembler_creates_quarantine_candidate_from_static_wheel_reports():
    from workbench.capability_factory import dependency_contract as contracts
    from workbench.capability_factory import dependency_resolver as resolver
    from workbench.capability_factory import bundle_assembler as assembler

    raw = _wheel()
    lock = _lock(contracts, resolver, raw)
    bundle = assembler.BundleAssembler().assemble(
        lock=lock,
        artifacts={lock.requirements[0].artifact_digest: raw},
    )

    assert bundle.status == "quarantined"
    assert bundle.lock_ref == lock.content_digest
    assert bundle.bundle_ref
    assert bundle.manifest_digest


@pytest.mark.parametrize("artifacts", [{}, {"a" * 64: _wheel(unsafe="safe_library/unsafe.pth")}])
def test_assembler_rejects_missing_or_unsafe_artifacts(artifacts):
    from workbench.capability_factory import dependency_contract as contracts
    from workbench.capability_factory import dependency_resolver as resolver
    from workbench.capability_factory import bundle_assembler as assembler

    raw = _wheel()
    lock = _lock(contracts, resolver, raw)
    if artifacts and "a" * 64 in artifacts:
        artifacts = {lock.requirements[0].artifact_digest: next(iter(artifacts.values()))}
    with pytest.raises(assembler.BundleAssemblyError):
        assembler.BundleAssembler().assemble(lock=lock, artifacts=artifacts)
