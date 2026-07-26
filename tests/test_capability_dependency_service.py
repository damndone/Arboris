from __future__ import annotations

import hashlib
import io
import zipfile


def _wheel() -> bytes:
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("safe_library/__init__.py", b"VALUE = 1\n")
        archive.writestr(
            "safe_library-1.2.3.dist-info/METADATA",
            b"Metadata-Version: 2.3\nName: safe-library\nVersion: 1.2.3\n",
        )
        archive.writestr("safe_library-1.2.3.dist-info/WHEEL", b"Wheel-Version: 1.0\n")
    return buffer.getvalue()


def _inputs():
    from workbench.capability_factory import dependency_contract as contracts
    from workbench.capability_factory import dependency_resolver as resolver

    raw = _wheel()
    digest = hashlib.sha256(raw).hexdigest()
    requirement = contracts.DependencyRequirement(
        distribution="safe-library",
        version="1.2.3",
        artifact_digest=digest,
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
        artifacts=(
            resolver.ArtifactCandidate(
                distribution="safe-library",
                version="1.2.3",
                artifact_digest=digest,
                url="https://packages.example.test/files/safe.whl",
                python_tag="py3",
                platform_tag="macosx_14_0_arm64",
            ),
        ),
    )
    return (requirement,), snapshot, policy, {digest: raw}


def test_dependency_service_stops_at_quarantine_and_keeps_admission_explicit():
    from workbench.capability_factory.dependency_service import DependencyService

    requirements, snapshot, policy, artifacts = _inputs()
    prepared = DependencyService().prepare_quarantine(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        artifacts=artifacts,
    )

    assert prepared.lock.content_digest
    assert prepared.bundle.lock_ref == prepared.lock.content_digest
    assert prepared.bundle.status == "quarantined"
    assert prepared.admission.status == "quarantined"
    assert prepared.admission.validity_ref == prepared.bundle.bundle_ref


def test_dependency_service_does_not_admit_when_static_assembly_fails():
    import pytest

    from workbench.capability_factory.dependency_service import (
        DependencyPreparationError,
        DependencyService,
    )

    requirements, snapshot, policy, _artifacts = _inputs()
    with pytest.raises(DependencyPreparationError):
        DependencyService().prepare_quarantine(
            requirements=requirements,
            snapshot=snapshot,
            policy=policy,
            artifacts={},
        )
