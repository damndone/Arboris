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


def test_dependency_store_rebuilds_lock_bundle_and_admission_across_instances(tmp_path):
    from workbench.capability_factory.dependency_service import DependencyService
    from workbench.capability_factory.dependency_store import DependencyStore

    requirements, snapshot, policy, artifacts = _inputs()
    prepared = DependencyService(store=DependencyStore(tmp_path)).prepare_quarantine(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        artifacts=artifacts,
    )
    reopened = DependencyStore(tmp_path, create=False)

    assert reopened.get_lock(prepared.lock.content_digest) == prepared.lock
    assert reopened.get_bundle(prepared.bundle.bundle_ref) == prepared.bundle
    assert reopened.admission_history(prepared.bundle.bundle_ref) == (prepared.admission,)


def test_dependency_store_rejects_tampered_persisted_lock(tmp_path):
    import json

    import pytest

    from workbench.capability_factory.dependency_service import DependencyService
    from workbench.capability_factory.dependency_store import (
        DependencyStore,
        DependencyStoreError,
    )

    requirements, snapshot, policy, artifacts = _inputs()
    prepared = DependencyService(store=DependencyStore(tmp_path)).prepare_quarantine(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        artifacts=artifacts,
    )
    path = tmp_path / "locks" / f"{prepared.lock.content_digest}.jsonl"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["lock"]["lock_id"] = "tampered"
    path.write_text(json.dumps(record) + "\n", encoding="utf-8")

    with pytest.raises(DependencyStoreError):
        DependencyStore(tmp_path, create=False).get_lock(prepared.lock.content_digest)
