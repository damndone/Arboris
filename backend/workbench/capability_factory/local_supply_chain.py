"""Pinned local scanner-worker bridge for the experimental Capability Factory.

This module deliberately trusts no Agent-provided executable, command, policy,
or scan result.  Application bootstrap supplies an explicit worker command and
the exact digest of its executable; the Agent can later request a scan through
the already-wired service but cannot replace its trust root.
"""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import os
from pathlib import Path
import subprocess
from typing import Any, Mapping

from ..custom_capability.canonical import canonical_json_bytes, domain_digest
from .dependency_service import (
    DependencyPreparation,
    DependencyPreparationError,
    DependencyService,
    QuarantineBuild,
    SupplyChainAttestation,
    SupplyChainReport,
    SupplyChainVerification,
)


_SCANNER_SCHEMA_VERSION = "workbench.local_supply_chain_scanner/v1"
_MAX_COMMAND_ITEMS = 32
_MAX_COMMAND_ITEM_CHARS = 16_384
_MAX_SCANNER_OUTPUT_BYTES = 1_048_576


class LocalSupplyChainScannerError(DependencyPreparationError):
    """Raised when the pinned local scanner cannot prove a bound result."""


def _digest(value: Any, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LocalSupplyChainScannerError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _text(value: Any, field: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\x00" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise LocalSupplyChainScannerError(f"{field} is invalid")
    return value


def _file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _parse_scanner_response(raw: bytes) -> Mapping[str, Any]:
    if len(raw) > _MAX_SCANNER_OUTPUT_BYTES:
        raise LocalSupplyChainScannerError("scanner response exceeds the output budget")

    def reject_duplicate_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
        result: dict[str, Any] = {}
        for key, value in pairs:
            if key in result:
                raise LocalSupplyChainScannerError("scanner response has duplicate JSON keys")
            result[key] = value
        return result

    def reject_non_finite(value: str) -> None:
        raise LocalSupplyChainScannerError(f"scanner response has non-finite JSON constant {value}")

    try:
        value = json.loads(
            raw.decode("utf-8"),
            object_pairs_hook=reject_duplicate_keys,
            parse_constant=reject_non_finite,
        )
        canonical_json_bytes(value)
    except (UnicodeDecodeError, json.JSONDecodeError, ValueError) as error:
        if isinstance(error, LocalSupplyChainScannerError):
            raise
        raise LocalSupplyChainScannerError("scanner response is not valid bounded JSON") from error
    if not isinstance(value, Mapping):
        raise LocalSupplyChainScannerError("scanner response must be an object")
    return value


@dataclass(frozen=True, slots=True)
class LocalSupplyChainScannerConfiguration:
    """Administrator-owned worker identity and policy for one local profile."""

    scanner_id: str
    command: tuple[str, ...]
    executable_sha256: str
    policy_ref: str
    timeout_seconds: int = 60

    def __post_init__(self) -> None:
        scanner_id = _text(self.scanner_id, "scanner_id")
        if not isinstance(self.command, tuple) or not 1 <= len(self.command) <= _MAX_COMMAND_ITEMS:
            raise LocalSupplyChainScannerError("scanner command is invalid")
        command = tuple(
            _text(value, "scanner command item", maximum=_MAX_COMMAND_ITEM_CHARS)
            for value in self.command
        )
        executable = Path(command[0])
        if not executable.is_absolute() or executable.is_symlink() or not executable.is_file():
            raise LocalSupplyChainScannerError("scanner executable must be an absolute regular file")
        if not os.access(executable, os.X_OK):
            raise LocalSupplyChainScannerError("scanner executable is not executable")
        if not isinstance(self.timeout_seconds, int) or not 1 <= self.timeout_seconds <= 600:
            raise LocalSupplyChainScannerError("scanner timeout_seconds is invalid")
        object.__setattr__(self, "scanner_id", scanner_id)
        object.__setattr__(self, "command", command)
        object.__setattr__(self, "executable_sha256", _digest(self.executable_sha256, "executable_sha256"))
        object.__setattr__(self, "policy_ref", _digest(self.policy_ref, "policy_ref"))

    @property
    def authority_ref(self) -> str:
        return domain_digest(
            "workbench.capability_factory.local_scanner_authority/v1",
            {
                "scanner_id": self.scanner_id,
                "command": list(self.command),
                "executable_sha256": self.executable_sha256,
                "policy_ref": self.policy_ref,
                "schema_version": _SCANNER_SCHEMA_VERSION,
            },
        )


class LocalSupplyChainScanner:
    """Invoke one pinned worker and translate its exact reports into CF2 facts."""

    def __init__(self, configuration: LocalSupplyChainScannerConfiguration) -> None:
        if not isinstance(configuration, LocalSupplyChainScannerConfiguration):
            raise TypeError("configuration must be a LocalSupplyChainScannerConfiguration")
        self.configuration = configuration
        self._issued_verifications: dict[str, SupplyChainVerification] = {}

    def scan_and_validate(
        self,
        *,
        service: DependencyService,
        preparation: DependencyPreparation,
    ) -> DependencyPreparation:
        """Run the configured worker, persist its reports, and advance CF2 once.

        This operation is intentionally server-side.  It takes only an already
        sealed quarantine build; it cannot resolve, fetch, install, or execute
        dependency code.
        """

        if not isinstance(service, DependencyService):
            raise TypeError("service must be a DependencyService")
        if service.supply_chain_verifier is not self:
            raise LocalSupplyChainScannerError(
                "the dependency service is not wired to this local scanner"
            )
        if not isinstance(preparation, DependencyPreparation) or preparation.quarantine_build is None:
            raise LocalSupplyChainScannerError("scanner requires a sealed quarantine build")
        build = preparation.quarantine_build
        response = self._run(build)
        reports = self._reports_from_response(response=response, build=build)
        for report in reports.values():
            service.store.put_supply_chain_report(report)
        if any(report.status != "passed" for report in reports.values()):
            raise LocalSupplyChainScannerError("local scanner blocked the dependency bundle")
        attestation = SupplyChainAttestation(
            bundle_ref=preparation.bundle.bundle_ref,
            tree_manifest_ref=build.tree_manifest_ref,
            sbom_ref=build.sbom_ref,
            license_status="passed",
            vulnerability_status="passed",
            license_report_ref=reports["license"].content_digest,
            vulnerability_report_ref=reports["vulnerability"].content_digest,
            authority_ref=self.configuration.authority_ref,
        )
        verification = SupplyChainVerification(
            authority_ref=self.configuration.authority_ref,
            decision_ref=domain_digest(
                "workbench.capability_factory.local_scanner_decision/v1",
                {
                    "attestation_ref": attestation.content_digest,
                    "authority_ref": self.configuration.authority_ref,
                    "license_report_ref": reports["license"].content_digest,
                    "vulnerability_report_ref": reports["vulnerability"].content_digest,
                },
            ),
            status="passed",
            attestation_ref=attestation.content_digest,
            build_ref=build.content_digest,
        )
        self._issued_verifications[attestation.content_digest] = verification
        try:
            return service.mark_validated(preparation, attestation=attestation)
        except Exception:
            self._issued_verifications.pop(attestation.content_digest, None)
            raise

    def verify(
        self,
        *,
        attestation: SupplyChainAttestation,
        build: QuarantineBuild,
    ) -> SupplyChainVerification:
        if not isinstance(attestation, SupplyChainAttestation) or not isinstance(build, QuarantineBuild):
            raise LocalSupplyChainScannerError("scanner verification input is invalid")
        if attestation.authority_ref != self.configuration.authority_ref:
            raise LocalSupplyChainScannerError("supply-chain attestation is from another scanner")
        verification = self._issued_verifications.get(attestation.content_digest)
        if verification is None or verification.build_ref != build.content_digest:
            raise LocalSupplyChainScannerError(
                "local scanner did not issue a current verification for this attestation"
            )
        return verification

    def _run(self, build: QuarantineBuild) -> Mapping[str, Any]:
        executable = Path(self.configuration.command[0])
        if _file_sha256(executable) != self.configuration.executable_sha256:
            raise LocalSupplyChainScannerError("configured scanner executable digest changed")
        request = canonical_json_bytes(
            {
                "schema_version": _SCANNER_SCHEMA_VERSION,
                "policy_ref": self.configuration.policy_ref,
                "build": {
                    "content_digest": build.content_digest,
                    "bundle_ref": build.bundle_ref,
                    "tree_manifest_ref": build.tree_manifest_ref,
                    "sbom_ref": build.sbom_ref,
                    "root": str(build.root),
                },
            }
        )
        try:
            completed = subprocess.run(
                self.configuration.command,
                input=request,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                cwd=build.root,
                env={"PATH": os.defpath, "LANG": "C", "LC_ALL": "C", "PYTHONNOUSERSITE": "1"},
                close_fds=True,
                start_new_session=True,
                check=False,
                timeout=self.configuration.timeout_seconds,
            )
        except (OSError, subprocess.TimeoutExpired) as error:
            raise LocalSupplyChainScannerError("configured scanner worker is unavailable") from error
        if completed.returncode != 0:
            raise LocalSupplyChainScannerError("configured scanner worker failed")
        return _parse_scanner_response(completed.stdout)

    def _reports_from_response(
        self,
        *,
        response: Mapping[str, Any],
        build: QuarantineBuild,
    ) -> dict[str, SupplyChainReport]:
        if set(response) != {"schema_version", "build_ref", "sbom_ref", "policy_ref", "reports"}:
            raise LocalSupplyChainScannerError("scanner response fields are invalid")
        if (
            response["schema_version"] != _SCANNER_SCHEMA_VERSION
            or response["build_ref"] != build.content_digest
            or response["sbom_ref"] != build.sbom_ref
            or response["policy_ref"] != self.configuration.policy_ref
        ):
            raise LocalSupplyChainScannerError("scanner response is bound to another build or policy")
        raw_reports = response["reports"]
        if not isinstance(raw_reports, Mapping) or set(raw_reports) != {"license", "vulnerability"}:
            raise LocalSupplyChainScannerError("scanner response reports are invalid")
        reports: dict[str, SupplyChainReport] = {}
        for kind in ("license", "vulnerability"):
            item = raw_reports[kind]
            if not isinstance(item, Mapping) or set(item) != {"status", "evidence_ref"}:
                raise LocalSupplyChainScannerError(f"scanner {kind} report is invalid")
            if item["status"] not in {"passed", "blocked"}:
                raise LocalSupplyChainScannerError(f"scanner {kind} status is invalid")
            reports[kind] = SupplyChainReport(
                report_kind=kind,
                build_ref=build.content_digest,
                sbom_ref=build.sbom_ref,
                authority_ref=self.configuration.authority_ref,
                status=item["status"],
                evidence_ref=_digest(item["evidence_ref"], f"scanner {kind} evidence_ref"),
            )
        return reports


__all__ = [
    "LocalSupplyChainScanner",
    "LocalSupplyChainScannerConfiguration",
    "LocalSupplyChainScannerError",
]
