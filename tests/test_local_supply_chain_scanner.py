from __future__ import annotations

import hashlib
import sys
from pathlib import Path

import pytest


_FIXTURE_SCANNER = r'''
import hashlib
import json
import sys

request = json.loads(sys.stdin.read())
build = request["build"]
response = {
    "schema_version": "workbench.local_supply_chain_scanner/v1",
    "build_ref": build["content_digest"],
    "sbom_ref": build["sbom_ref"],
    "policy_ref": request["policy_ref"],
    "reports": {
        "license": {
            "status": "passed",
            "evidence_ref": hashlib.sha256(b"fixture-license-evidence").hexdigest(),
        },
        "vulnerability": {
            "status": "passed",
            "evidence_ref": hashlib.sha256(b"fixture-vulnerability-evidence").hexdigest(),
        },
    },
}
sys.stdout.write(json.dumps(response))
'''


def _prepared_dependency(tmp_path: Path, scanner):
    from test_capability_dependency_service import _FetchTransport, _authorized_fetch, _inputs
    from workbench.capability_factory.dependency_fetch import FetchPolicy, FetchWorker
    from workbench.capability_factory.dependency_service import DependencyService
    from workbench.capability_factory.dependency_store import DependencyStore

    requirements, snapshot, policy, artifacts = _inputs()
    service = DependencyService(
        fetcher=FetchWorker(
            transport=_FetchTransport(snapshot.artifacts[0].url, next(iter(artifacts.values())))
        ),
        store=DependencyStore(tmp_path / "store"),
        supply_chain_verifier=scanner,
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
    return service, prepared


def _scanner(tmp_path: Path, *, executable_sha256: str | None = None):
    from workbench.capability_factory.local_supply_chain import (
        LocalSupplyChainScanner,
        LocalSupplyChainScannerConfiguration,
    )
    from workbench.custom_capability.canonical import domain_digest

    executable = Path(sys.executable).resolve()
    worker = tmp_path / "fixture-scanner.py"
    worker.write_text(f"#!{executable}\n{_FIXTURE_SCANNER}", encoding="utf-8")
    worker.chmod(0o700)
    return LocalSupplyChainScanner(
        LocalSupplyChainScannerConfiguration(
            scanner_id="fixture-local-scanner",
            command=(str(worker),),
            executable_sha256=executable_sha256
            or hashlib.sha256(worker.read_bytes()).hexdigest(),
            policy_ref=domain_digest(
                "tests.local_supply_chain.policy/v1", {"allow": ["fixture"]}
            ),
        )
    )


def test_local_scanner_runs_a_pinned_external_worker_and_validates_exact_build(tmp_path):
    scanner = _scanner(tmp_path)
    service, prepared = _prepared_dependency(tmp_path, scanner)

    validated = scanner.scan_and_validate(service=service, preparation=prepared)
    assert validated.admission.status == "validated"
    assert validated.quarantine_build is not None
    attestation = service.store.get_supply_chain_attestation(validated.bundle.bundle_ref)
    assert attestation.authority_ref == scanner.configuration.authority_ref
    assert service.store.get_supply_chain_report(attestation.license_report_ref).status == "passed"
    assert service.store.get_supply_chain_report(attestation.vulnerability_report_ref).status == "passed"

    admitted = service.admit_execution_bundle(validated.bundle.bundle_ref, scope="project")
    assert admitted.status == "admitted"
    service.assert_execution_bundle(validated.bundle.bundle_ref)


def test_local_scanner_fails_closed_when_the_configured_worker_changed(tmp_path):
    from workbench.capability_factory.local_supply_chain import LocalSupplyChainScannerError

    scanner = _scanner(tmp_path, executable_sha256="0" * 64)
    service, prepared = _prepared_dependency(tmp_path, scanner)

    with pytest.raises(LocalSupplyChainScannerError, match="executable digest"):
        scanner.scan_and_validate(service=service, preparation=prepared)
