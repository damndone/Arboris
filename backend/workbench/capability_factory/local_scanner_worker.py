"""Sealed-tree local scanner worker for the experimental Capability Factory.

This file deliberately has no Workbench imports: a provisioned copy can run as
the pinned external worker.  It reads distribution metadata only, never imports
from the quarantined tree, and queries the fixed OSV batch endpoint for known
Python-package vulnerabilities.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from email.parser import BytesParser
import hashlib
import json
import os
from pathlib import Path
import stat
import sys
from typing import Any, Callable, Mapping
from urllib.request import Request, urlopen


SCHEMA_VERSION = "workbench.local_supply_chain_scanner/v2"
_OSV_QUERY_BATCH_URL = "https://api.osv.dev/v1/querybatch"
_MAX_METADATA_BYTES = 65_536
_MAX_TREE_ENTRIES = 20_000
_MAX_PACKAGES = 512
_MAX_OSV_RESPONSE_BYTES = 4 * 1024 * 1024


class LocalScannerWorkerError(ValueError):
    """The worker cannot produce a safe, bound report."""


def _canonical_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        allow_nan=False,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return hashlib.sha256(_canonical_json_bytes(value)).hexdigest()


def _digest(value: object, field: str) -> str:
    if (
        not isinstance(value, str)
        or len(value) != 64
        or any(character not in "0123456789abcdef" for character in value)
    ):
        raise LocalScannerWorkerError(f"{field} must be a lowercase SHA-256 digest")
    return value


def _text(value: object, field: str, *, maximum: int = 256) -> str:
    if (
        not isinstance(value, str)
        or not value
        or len(value) > maximum
        or "\x00" in value
        or any(ord(character) < 0x20 for character in value)
    ):
        raise LocalScannerWorkerError(f"{field} is invalid")
    return value


def _distribution(value: object) -> str:
    return _text(value, "distribution").lower().replace("_", "-").replace(".", "-")


def _license_label(value: object) -> str | None:
    if not isinstance(value, str) or not value.strip():
        return None
    normalized = " ".join(value.split()).lower()
    aliases = {
        "mit license": "MIT",
        "mit": "MIT",
        "apache software license": "Apache-2.0",
        "apache license 2.0": "Apache-2.0",
        "apache-2.0": "Apache-2.0",
        "isc license": "ISC",
        "isc": "ISC",
    }
    return aliases.get(normalized, value.strip())


def _request_parts(request: Mapping[str, Any]) -> tuple[Path, list[dict[str, str]], set[str]]:
    if set(request) != {
        "schema_version",
        "policy_ref",
        "license_allowlist",
        "build",
        "requirements",
    }:
        raise LocalScannerWorkerError("scanner request fields are invalid")
    if request["schema_version"] != SCHEMA_VERSION:
        raise LocalScannerWorkerError("scanner request schema is unsupported")
    _digest(request["policy_ref"], "policy_ref")
    raw_build = request["build"]
    if not isinstance(raw_build, Mapping) or set(raw_build) != {
        "content_digest",
        "bundle_ref",
        "tree_manifest_ref",
        "sbom_ref",
        "root",
    }:
        raise LocalScannerWorkerError("scanner build binding is invalid")
    for field in ("content_digest", "bundle_ref", "tree_manifest_ref", "sbom_ref"):
        _digest(raw_build[field], f"build.{field}")
    root = Path(_text(raw_build["root"], "build.root", maximum=8_192))
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise LocalScannerWorkerError("scanner build root is not a sealed directory")
    raw_allowlist = request["license_allowlist"]
    if not isinstance(raw_allowlist, list) or len(raw_allowlist) > 128:
        raise LocalScannerWorkerError("scanner license policy is invalid")
    allowlist = {
        _license_label(_text(item, "license policy entry", maximum=128))
        for item in raw_allowlist
    }
    if None in allowlist:
        raise LocalScannerWorkerError("scanner license policy is invalid")
    raw_requirements = request["requirements"]
    if not isinstance(raw_requirements, list) or not 1 <= len(raw_requirements) <= _MAX_PACKAGES:
        raise LocalScannerWorkerError("scanner requirements are invalid")
    requirements: list[dict[str, str]] = []
    for item in raw_requirements:
        if not isinstance(item, Mapping) or set(item) != {
            "distribution",
            "version",
            "artifact_digest",
        }:
            raise LocalScannerWorkerError("scanner requirement is invalid")
        requirements.append(
            {
                "distribution": _distribution(item["distribution"]),
                "version": _text(item["version"], "requirement.version"),
                "artifact_digest": _digest(item["artifact_digest"], "requirement.artifact_digest"),
            }
        )
    if len({(item["distribution"], item["version"]) for item in requirements}) != len(requirements):
        raise LocalScannerWorkerError("scanner requirements contain duplicates")
    return root, sorted(requirements, key=lambda item: (item["distribution"], item["version"])), allowlist


def _read_metadata(path: Path) -> tuple[str, str, str | None]:
    try:
        descriptor = os.open(path, os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0))
        with os.fdopen(descriptor, "rb", closefd=True) as handle:
            content = handle.read(_MAX_METADATA_BYTES + 1)
    except OSError as error:
        raise LocalScannerWorkerError("scanner could not safely read package metadata") from error
    if len(content) > _MAX_METADATA_BYTES:
        raise LocalScannerWorkerError("package metadata exceeds scanner budget")
    try:
        message = BytesParser().parsebytes(content)
        distribution = _distribution(message["Name"])
        version = _text(message["Version"], "metadata.version")
    except (TypeError, ValueError, LocalScannerWorkerError) as error:
        raise LocalScannerWorkerError("package metadata is missing name or version") from error
    license_value = _license_label(message["License"])
    if license_value is None:
        for classifier in message.get_all("Classifier", []):
            if isinstance(classifier, str) and classifier.startswith("License ::"):
                license_value = _license_label(classifier.rsplit("::", 1)[-1])
                if license_value is not None:
                    break
    return distribution, version, license_value


def _package_metadata(root: Path) -> list[dict[str, str | None]]:
    packages: list[dict[str, str | None]] = []
    entries_seen = 0
    for current, directories, files in os.walk(root, followlinks=False):
        current_path = Path(current)
        for name in directories:
            candidate = current_path / name
            if candidate.is_symlink():
                raise LocalScannerWorkerError("scanner rejects symlinks in the sealed build tree")
        entries_seen += len(directories) + len(files)
        if entries_seen > _MAX_TREE_ENTRIES:
            raise LocalScannerWorkerError("sealed build tree exceeds scanner entry budget")
        if not current_path.name.endswith(".dist-info") or "METADATA" not in files:
            continue
        metadata_path = current_path / "METADATA"
        if metadata_path.is_symlink() or not stat.S_ISREG(metadata_path.stat().st_mode):
            raise LocalScannerWorkerError("scanner metadata is not a regular file")
        distribution, version, license_value = _read_metadata(metadata_path)
        packages.append(
            {"distribution": distribution, "version": version, "license": license_value}
        )
        if len(packages) > _MAX_PACKAGES:
            raise LocalScannerWorkerError("sealed build tree has too many packages")
    if not packages:
        raise LocalScannerWorkerError("sealed build tree has no package metadata")
    if len({(item["distribution"], item["version"]) for item in packages}) != len(packages):
        raise LocalScannerWorkerError("sealed build tree has duplicate package metadata")
    return sorted(packages, key=lambda item: (str(item["distribution"]), str(item["version"])))


def _query_osv(payload: dict[str, object]) -> dict[str, object]:
    request = Request(
        _OSV_QUERY_BATCH_URL,
        data=_canonical_json_bytes(payload),
        method="POST",
        headers={"Content-Type": "application/json", "Accept": "application/json"},
    )
    try:
        with urlopen(request, timeout=20) as response:  # nosec B310: fixed HTTPS URL
            raw = response.read(_MAX_OSV_RESPONSE_BYTES + 1)
    except OSError as error:
        raise LocalScannerWorkerError("OSV vulnerability service is unavailable") from error
    if len(raw) > _MAX_OSV_RESPONSE_BYTES:
        raise LocalScannerWorkerError("OSV vulnerability response exceeds scanner budget")
    try:
        parsed = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as error:
        raise LocalScannerWorkerError("OSV vulnerability response is invalid") from error
    if not isinstance(parsed, dict):
        raise LocalScannerWorkerError("OSV vulnerability response is invalid")
    return parsed


def scan_request(
    request: Mapping[str, Any],
    *,
    query_osv: Callable[[dict[str, object]], dict[str, object]] = _query_osv,
) -> dict[str, object]:
    """Return bounded reports for one sealed build without importing its code."""

    root, requirements, allowlist = _request_parts(request)
    packages = _package_metadata(root)
    expected = {(item["distribution"], item["version"]) for item in requirements}
    observed = {(str(item["distribution"]), str(item["version"])) for item in packages}
    if observed != expected:
        raise LocalScannerWorkerError("sealed metadata does not match the resolved dependency lock")
    osv_payload: dict[str, object] = {
        "queries": [
            {
                "package": {"ecosystem": "PyPI", "name": item["distribution"]},
                "version": item["version"],
            }
            for item in requirements
        ]
    }
    osv_response = query_osv(osv_payload)
    results = osv_response.get("results") if isinstance(osv_response, dict) else None
    if not isinstance(results, list) or len(results) != len(requirements):
        raise LocalScannerWorkerError("OSV vulnerability response is not bound to all packages")
    has_vulnerability = any(
        isinstance(result, Mapping)
        and isinstance(result.get("vulns", []), list)
        and bool(result.get("vulns"))
        for result in results
    )
    license_passed = bool(allowlist) and all(
        isinstance(item["license"], str) and item["license"] in allowlist for item in packages
    )
    issued_at = datetime.now(timezone.utc).replace(microsecond=0)
    return {
        "schema_version": SCHEMA_VERSION,
        "build_ref": request["build"]["content_digest"],
        "sbom_ref": request["build"]["sbom_ref"],
        "policy_ref": request["policy_ref"],
        "issued_at": issued_at.isoformat().replace("+00:00", "Z"),
        "valid_until": (issued_at + timedelta(hours=1)).isoformat().replace("+00:00", "Z"),
        "advisory_snapshot_ref": _sha256({"provider": "osv", "response": osv_response}),
        "reports": {
            "license": {
                "status": "passed" if license_passed else "blocked",
                "evidence_ref": _sha256({"allowlist": sorted(allowlist), "packages": packages}),
            },
            "vulnerability": {
                "status": "blocked" if has_vulnerability else "passed",
                "evidence_ref": _sha256({"provider": "osv", "response": osv_response}),
            },
        },
    }


def provision_worker(destination: str | Path) -> tuple[Path, str]:
    """Create an immutable, executable worker copy for administrator bootstrap."""

    target = Path(destination)
    if not target.is_absolute() or target.is_symlink() or not target.parent.is_dir():
        raise LocalScannerWorkerError("worker destination must have a real existing parent directory")
    source = Path(__file__).read_bytes()
    content = f"#!{Path(sys.executable).resolve()}\n".encode("utf-8") + source
    digest = hashlib.sha256(content).hexdigest()
    try:
        descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o700)
        with os.fdopen(descriptor, "wb", closefd=True) as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
    except FileExistsError:
        if not target.is_file() or target.is_symlink() or hashlib.sha256(target.read_bytes()).hexdigest() != digest:
            raise LocalScannerWorkerError("worker destination already has different content")
    except OSError as error:
        raise LocalScannerWorkerError("worker could not be provisioned") from error
    return target, digest


def main() -> int:
    try:
        request = json.loads(sys.stdin.buffer.read().decode("utf-8"))
        if not isinstance(request, Mapping):
            raise LocalScannerWorkerError("scanner request must be an object")
        sys.stdout.write(json.dumps(scan_request(request), separators=(",", ":"), sort_keys=True))
        return 0
    except (LocalScannerWorkerError, UnicodeDecodeError, json.JSONDecodeError):
        return 2


if __name__ == "__main__":
    raise SystemExit(main())


__all__ = ["LocalScannerWorkerError", "SCHEMA_VERSION", "provision_worker", "scan_request"]
