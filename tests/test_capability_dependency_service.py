from __future__ import annotations

import hashlib
import io
import base64
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


def _wheel(*, include_record: bool = True) -> bytes:
    entries = {
        "safe_library/__init__.py": b"VALUE = 1\n",
        "safe_library-1.2.3.dist-info/METADATA": (
            b"Metadata-Version: 2.3\nName: safe-library\nVersion: 1.2.3\n"
        ),
        "safe_library-1.2.3.dist-info/WHEEL": b"Wheel-Version: 1.0\n",
    }
    if include_record:
        rows = []
        for name, payload in entries.items():
            encoded = base64.urlsafe_b64encode(hashlib.sha256(payload).digest()).rstrip(b"=")
            rows.append(f"{name},sha256={encoded.decode('ascii')},{len(payload)}")
        rows.append("safe_library-1.2.3.dist-info/RECORD,,")
        entries["safe_library-1.2.3.dist-info/RECORD"] = ("\n".join(rows) + "\n").encode()
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, payload in entries.items():
            archive.writestr(name, payload)
    return buffer.getvalue()


def _inputs(*, include_record: bool = True):
    from workbench.capability_factory import dependency_contract as contracts
    from workbench.capability_factory import dependency_resolver as resolver

    raw = _wheel(include_record=include_record)
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
    assert prepared.quarantine_build.lock_ref == prepared.lock.content_digest
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
        SupplyChainReport,
        SupplyChainVerification,
    )
    from workbench.capability_factory.dependency_store import DependencyStore
    from workbench.custom_capability.canonical import domain_digest

    requirements, snapshot, policy, artifacts = _inputs()
    transport = _FetchTransport(snapshot.artifacts[0].url, next(iter(artifacts.values())))
    receipt = _authorized_fetch(tmp_path, requirements, snapshot, policy)
    class _PassingVerifier:
        def verify(self, *, attestation, build):
            return SupplyChainVerification(
                authority_ref=attestation.authority_ref,
                decision_ref=domain_digest(
                    "tests.supply_chain.decision/v1", {"build_ref": build.content_digest}
                ),
                status="passed",
                attestation_ref=attestation.content_digest,
                build_ref=build.content_digest,
                issued_at="2020-01-01T00:00:00Z",
                valid_until="2099-01-01T00:00:00Z",
                advisory_snapshot_ref=domain_digest(
                    "tests.supply_chain.advisory_snapshot/v1", {"name": "fixture"}
                ),
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
        authority_ref=domain_digest("tests.supply_chain.authority/v1", {"name": "test"}),
    )
    with pytest.raises(DependencyPreparationError, match="supply-chain"):
        service.mark_validated(prepared, attestation=not_assessed)

    authority_ref = domain_digest("tests.supply_chain.authority/v1", {"name": "test"})
    license_report = SupplyChainReport(
        report_kind="license",
        build_ref=prepared.quarantine_build.content_digest,
        sbom_ref=prepared.quarantine_build.sbom_ref,
        authority_ref=authority_ref,
        status="passed",
        evidence_ref=domain_digest(
            "tests.supply_chain.license_evidence/v1",
            {"sbom_ref": prepared.quarantine_build.sbom_ref},
        ),
    )
    vulnerability_report = SupplyChainReport(
        report_kind="vulnerability",
        build_ref=prepared.quarantine_build.content_digest,
        sbom_ref=prepared.quarantine_build.sbom_ref,
        authority_ref=authority_ref,
        status="passed",
        evidence_ref=domain_digest(
            "tests.supply_chain.vulnerability_evidence/v1",
            {"sbom_ref": prepared.quarantine_build.sbom_ref},
        ),
    )
    passed = SupplyChainAttestation(
        bundle_ref=prepared.bundle.bundle_ref,
        tree_manifest_ref=prepared.quarantine_build.tree_manifest_ref,
        sbom_ref=prepared.quarantine_build.sbom_ref,
        license_status="passed",
        vulnerability_status="passed",
        license_report_ref=license_report.content_digest,
        vulnerability_report_ref=vulnerability_report.content_digest,
        authority_ref=authority_ref,
    )
    service.store.put_supply_chain_report(license_report)
    service.store.put_supply_chain_report(vulnerability_report)
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
    reloaded = DependencyService(
        store=DependencyStore(tmp_path / "store", create=False),
    )
    reloaded.admit_execution_bundle(prepared.bundle.bundle_ref, scope="project")
    reloaded.assert_execution_bundle(prepared.bundle.bundle_ref)
    reloaded.admission.revoke(
        bundle_ref=prepared.bundle.bundle_ref,
        validity_ref=domain_digest(
            "tests.supply_chain.revoke/v1", {"bundle_ref": prepared.bundle.bundle_ref}
        ),
    )
    reloaded.store.append_admission(reloaded.admission.history(prepared.bundle.bundle_ref)[-1])
    with pytest.raises(DependencyPreparationError, match="scoped admission"):
        reloaded.assert_execution_bundle(prepared.bundle.bundle_ref)


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


def test_offline_builder_rejects_a_wheel_without_record_manifest(tmp_path):
    from workbench.capability_factory.dependency_service import (
        DependencyPreparationError,
        DependencyService,
        OfflineRuntimeBuilder,
    )

    requirements, snapshot, policy, artifacts = _inputs(include_record=False)
    prepared = DependencyService().prepare_quarantine(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        artifacts=artifacts,
    )

    with pytest.raises(DependencyPreparationError, match="RECORD"):
        OfflineRuntimeBuilder().build(
            lock=prepared.lock,
            bundle=prepared.bundle,
            artifacts=artifacts,
            root=tmp_path / "tree",
        )


def test_offline_builder_recomputes_manifest_from_disk(monkeypatch, tmp_path):
    import os

    from workbench.capability_factory import dependency_service as service_module
    from workbench.capability_factory.dependency_service import (
        DependencyPreparationError,
        DependencyService,
        OfflineRuntimeBuilder,
    )

    requirements, snapshot, policy, artifacts = _inputs()
    prepared = DependencyService().prepare_quarantine(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        artifacts=artifacts,
    )
    original_chmod = os.chmod

    def tampering_chmod(path, mode):
        original_chmod(path, mode)
        if path.name == "__init__.py":
            original_chmod(path, 0o644)
            path.write_bytes(b"TAMPERED\n")
            original_chmod(path, mode)

    monkeypatch.setattr(service_module.os, "chmod", tampering_chmod)
    with pytest.raises(DependencyPreparationError, match="manifest"):
        OfflineRuntimeBuilder().build(
            lock=prepared.lock,
            bundle=prepared.bundle,
            artifacts=artifacts,
            root=tmp_path / "tree",
        )


def test_quarantine_build_is_persisted_without_the_runtime_root(tmp_path):
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker
    from workbench.capability_factory.dependency_service import DependencyService
    from workbench.capability_factory.dependency_store import DependencyStore

    requirements, snapshot, policy, artifacts = _inputs()
    store = DependencyStore(tmp_path / "store")
    service = DependencyService(
        fetcher=FetchWorker(
            transport=_FetchTransport(snapshot.artifacts[0].url, next(iter(artifacts.values())))
        ),
        store=store,
    )
    receipt = _authorized_fetch(tmp_path, requirements, snapshot, policy)
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
    restored = DependencyStore(tmp_path / "store", create=False).get_quarantine_build(
        prepared.bundle.bundle_ref,
        root=prepared.quarantine_build.root,
    )
    assert restored == prepared.quarantine_build
    record = next((tmp_path / "store" / "quarantine-builds").glob("*.jsonl")).read_text()
    assert str(tmp_path / "quarantine") not in record


def test_supply_chain_attestation_rejects_obvious_placeholder_references():
    from workbench.capability_factory.dependency_service import (
        SupplyChainAttestation,
        SupplyChainAttestationError,
    )

    with pytest.raises(SupplyChainAttestationError, match="placeholder"):
        SupplyChainAttestation(
            bundle_ref="a" * 64,
            tree_manifest_ref="b" * 64,
            sbom_ref="c" * 64,
            license_status="passed",
            vulnerability_status="passed",
            authority_ref="1" * 64,
            license_report_ref="2" * 64,
            vulnerability_report_ref="3" * 64,
        )


def test_dependency_store_refuses_to_write_through_a_symlink_directory(tmp_path):
    from workbench.capability_factory.dependency_service import DependencyService
    from workbench.capability_factory.dependency_store import DependencyStore, DependencyStoreError

    requirements, snapshot, policy, artifacts = _inputs()
    prepared = DependencyService().prepare_quarantine(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        artifacts=artifacts,
    )
    root = tmp_path / "store"
    root.mkdir()
    outside = tmp_path / "outside"
    outside.mkdir()
    (root / "bundles").symlink_to(outside, target_is_directory=True)

    with pytest.raises(DependencyStoreError):
        DependencyStore(root).put_bundle(prepared.bundle)
    assert not list(outside.iterdir())


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


def test_dependency_store_rejects_a_truncated_jsonl_tail(tmp_path):
    from workbench.capability_factory.dependency_service import DependencyService
    from workbench.capability_factory.dependency_store import DependencyStore, DependencyStoreError

    requirements, snapshot, policy, artifacts = _inputs()
    prepared = DependencyService(store=DependencyStore(tmp_path)).prepare_quarantine(
        requirements=requirements,
        snapshot=snapshot,
        policy=policy,
        artifacts=artifacts,
    )
    path = tmp_path / "locks" / f"{prepared.lock.content_digest}.jsonl"
    path.write_bytes(path.read_bytes() + b'{"truncated":')

    with pytest.raises(DependencyStoreError, match="corrupt|invalid JSONL"):
        DependencyStore(tmp_path, create=False).get_lock(prepared.lock.content_digest)
