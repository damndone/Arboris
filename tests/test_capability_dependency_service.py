from __future__ import annotations

import hashlib
import io
import zipfile

import pytest


class _FetchResponse:
    def __init__(self, body: bytes) -> None:
        self.status = 200
        self.headers = {"Content-Length": str(len(body))}
        self.body = body

    def read(self, _size: int = -1) -> bytes:
        body, self.body = self.body, b""
        return body


class _FetchTransport:
    def __init__(self, url: str, body: bytes) -> None:
        self.url = url
        self.body = body
        self.calls: list[str] = []

    def open(self, url: str) -> _FetchResponse:
        self.calls.append(url)
        assert url == self.url
        return _FetchResponse(self.body)


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


def _authorized_fetch(tmp_path, requirements, snapshot, policy):
    from workbench.agent.dependency_control import DependencyAcquisitionControl
    from workbench.capability_factory.dependency_resolver import DependencyResolver

    lock = DependencyResolver().resolve(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
    )
    control = DependencyAcquisitionControl()
    proposal = control.create_proposal(
        lock=lock,
        index_snapshot_ref=snapshot.snapshot_ref,
        proposal_id="proposal.fetch_service",
    )
    revision = control.persist_proposal(
        proposal,
        root=tmp_path,
        session_id="session-fetch",
        chain_id="chain-fetch",
        active_head_run_id="run-fetch",
    )
    return control.authorize_persisted_proposal(
        proposal,
        root=tmp_path,
        revision=revision.revision,
        fingerprint=revision.fingerprint,
        actor_type="human_ui",
        current_context_fingerprint=proposal.content_digest,
        current_active_head_run_id="run-fetch",
    )


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


def test_dependency_service_can_fetch_locked_artifacts_before_offline_assembly(tmp_path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker
    from workbench.capability_factory.dependency_service import DependencyService

    requirements, snapshot, policy, artifacts = _inputs()
    url = snapshot.artifacts[0].url
    transport = _FetchTransport(url, next(iter(artifacts.values())))
    receipt = _authorized_fetch(tmp_path, requirements, snapshot, policy)
    prepared = DependencyService(fetcher=FetchWorker(transport=transport)).fetch_and_prepare(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        fetch_policy=FetchPolicy(
            allowed_origins=("https://packages.example.test",),
            max_artifact_bytes=1024 * 1024,
            max_redirects=0,
        ),
        quarantine_root=tmp_path / "quarantine",
        authorization_receipt=receipt,
        authorization_root=tmp_path,
    )

    assert transport.calls == [url]
    assert prepared.bundle.status == "quarantined"
    assert prepared.quarantine_build is not None
    assert prepared.quarantine_build.root.is_dir()
    assert prepared.quarantine_build.root.stat().st_mode & 0o222 == 0
    assert prepared.quarantine_build.license_status == "not_assessed"
    assert prepared.quarantine_build.vulnerability_status == "not_assessed"
    assert (prepared.quarantine_build.root / "safe_library" / "__init__.py").read_bytes() == b"VALUE = 1\n"


def test_authorized_fetch_replay_reuses_the_same_quarantine_bundle(tmp_path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker
    from workbench.capability_factory.dependency_service import DependencyService

    requirements, snapshot, policy, artifacts = _inputs()
    transport = _FetchTransport(snapshot.artifacts[0].url, next(iter(artifacts.values())))
    service = DependencyService(fetcher=FetchWorker(transport=transport))
    receipt = _authorized_fetch(tmp_path, requirements, snapshot, policy)
    kwargs = {
        "requirements": requirements,
        "snapshot": snapshot,
        "policy": policy,
        "fetch_policy": FetchPolicy(
            allowed_origins=("https://packages.example.test",),
            max_artifact_bytes=1024 * 1024,
            max_redirects=0,
        ),
        "quarantine_root": tmp_path / "quarantine",
        "authorization_receipt": receipt,
        "authorization_root": tmp_path,
    }

    first = service.fetch_and_prepare(**kwargs)
    second = service.fetch_and_prepare(**kwargs)

    assert first.bundle == second.bundle
    assert first.quarantine_build is not None
    assert second.quarantine_build is not None
    assert first.quarantine_build.tree_manifest_ref == second.quarantine_build.tree_manifest_ref
    assert transport.calls == [snapshot.artifacts[0].url, snapshot.artifacts[0].url]


def test_dependency_service_requires_external_supply_chain_attestation_before_validation(tmp_path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker
    from workbench.capability_factory.dependency_service import (
        DependencyPreparationError,
        DependencyService,
        SupplyChainAttestation,
        SupplyChainVerification,
    )
    from workbench.capability_factory.dependency_store import DependencyStore

    requirements, snapshot, policy, artifacts = _inputs()
    transport = _FetchTransport(snapshot.artifacts[0].url, next(iter(artifacts.values())))
    receipt = _authorized_fetch(tmp_path, requirements, snapshot, policy)
    class _PassingVerifier:
        def verify(self, *, attestation, build):
            return SupplyChainVerification(
                authority_ref=attestation.authority_ref,
                decision_ref="5" * 64,
                status="passed",
                attestation_ref=attestation.content_digest,
                build_ref=build.content_digest,
            )

    service = DependencyService(
        fetcher=FetchWorker(transport=transport),
        store=DependencyStore(tmp_path / "store"),
        supply_chain_verifier=_PassingVerifier(),
    )
    prepared = service.fetch_and_prepare(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        fetch_policy=FetchPolicy(
            allowed_origins=("https://packages.example.test",),
            max_artifact_bytes=1024 * 1024,
            max_redirects=0,
        ),
        quarantine_root=tmp_path / "quarantine",
        authorization_receipt=receipt,
        authorization_root=tmp_path,
    )
    assert prepared.quarantine_build is not None
    not_assessed = SupplyChainAttestation(
        bundle_ref=prepared.bundle.bundle_ref,
        tree_manifest_ref=prepared.quarantine_build.tree_manifest_ref,
        sbom_ref=prepared.quarantine_build.sbom_ref,
        license_status="not_assessed",
        vulnerability_status="not_assessed",
        authority_ref="1" * 64,
    )
    with pytest.raises(DependencyPreparationError, match="supply-chain"):
        service.mark_validated(prepared, attestation=not_assessed)

    passed = SupplyChainAttestation(
        bundle_ref=prepared.bundle.bundle_ref,
        tree_manifest_ref=prepared.quarantine_build.tree_manifest_ref,
        sbom_ref=prepared.quarantine_build.sbom_ref,
        license_status="passed",
        vulnerability_status="passed",
        license_report_ref="2" * 64,
        vulnerability_report_ref="3" * 64,
        authority_ref="4" * 64,
    )
    with pytest.raises(DependencyPreparationError, match="verifier is unavailable"):
        DependencyService().mark_validated(prepared, attestation=passed)
    validated = service.mark_validated(prepared, attestation=passed)
    assert validated.admission.status == "validated"
    assert validated.admission.validity_ref == passed.content_digest
    assert service.store.get_supply_chain_attestation(prepared.bundle.bundle_ref) == passed
    assert DependencyStore(tmp_path / "store", create=False).get_supply_chain_attestation(
        prepared.bundle.bundle_ref
    ) == passed
    assert service.store.get_supply_chain_verification(passed.content_digest).status == "passed"
    assert DependencyStore(tmp_path / "store", create=False).get_supply_chain_verification(
        passed.content_digest
    ).attestation_ref == passed.content_digest


def test_offline_builder_rejects_a_dangling_symlink_root(tmp_path):
    from workbench.capability_factory.dependency_service import DependencyService, OfflineRuntimeBuilder, DependencyPreparationError

    requirements, snapshot, policy, artifacts = _inputs()
    prepared = DependencyService().prepare_quarantine(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        artifacts=artifacts,
    )
    root = tmp_path / "tree"
    root.symlink_to(tmp_path / "missing-tree", target_is_directory=True)
    with pytest.raises(DependencyPreparationError, match="symlink"):
        OfflineRuntimeBuilder().build(
            lock=prepared.lock,
            bundle=prepared.bundle,
            artifacts=artifacts,
            root=root,
        )


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
