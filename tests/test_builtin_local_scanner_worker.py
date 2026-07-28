from __future__ import annotations

from pathlib import Path


def _request(root: Path, *, license_allowlist: list[str] | None = None) -> dict[str, object]:
    return {
        "schema_version": "workbench.local_supply_chain_scanner/v2",
        "policy_ref": "a" * 64,
        "license_allowlist": license_allowlist or ["MIT"],
        "build": {
            "content_digest": "b" * 64,
            "bundle_ref": "c" * 64,
            "tree_manifest_ref": "d" * 64,
            "sbom_ref": "e" * 64,
            "root": str(root),
        },
        "requirements": [
            {
                "distribution": "safe-library",
                "version": "1.2.3",
                "artifact_digest": "f" * 64,
            }
        ],
    }


def _metadata(root: Path, *, license_text: str = "MIT") -> None:
    metadata = root / "safe_library-1.2.3.dist-info" / "METADATA"
    metadata.parent.mkdir(parents=True)
    metadata.write_text(
        "Metadata-Version: 2.3\n"
        "Name: safe-library\n"
        "Version: 1.2.3\n"
        f"License: {license_text}\n",
        encoding="utf-8",
    )


def test_builtin_worker_scans_metadata_without_importing_the_package(tmp_path):
    from workbench.capability_factory.local_scanner_worker import scan_request

    _metadata(tmp_path)
    observed_queries: list[dict[str, object]] = []

    def query_osv(payload: dict[str, object]) -> dict[str, object]:
        observed_queries.append(payload)
        return {"results": [{}]}

    response = scan_request(_request(tmp_path), query_osv=query_osv)

    assert response["schema_version"] == "workbench.local_supply_chain_scanner/v2"
    assert response["reports"]["license"]["status"] == "passed"
    assert response["reports"]["vulnerability"]["status"] == "passed"
    assert len(observed_queries) == 1
    assert observed_queries[0]["queries"] == [
        {"package": {"ecosystem": "PyPI", "name": "safe-library"}, "version": "1.2.3"}
    ]
    assert isinstance(response["advisory_snapshot_ref"], str)
    assert len(response["advisory_snapshot_ref"]) == 64


def test_builtin_worker_blocks_disallowed_license_and_known_vulnerability(tmp_path):
    from workbench.capability_factory.local_scanner_worker import scan_request

    _metadata(tmp_path, license_text="GPL-3.0-only")
    response = scan_request(
        _request(tmp_path),
        query_osv=lambda _payload: {"results": [{"vulns": [{"id": "OSV-1"}]}]},
    )

    assert response["reports"]["license"]["status"] == "blocked"
    assert response["reports"]["vulnerability"]["status"] == "blocked"
