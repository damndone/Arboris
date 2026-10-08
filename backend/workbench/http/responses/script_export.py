"""Reproducible analysis-script export."""

from __future__ import annotations

from typing_extensions import TypedDict


class ScriptExportTarget(TypedDict):
    target: str
    label: str


class ScriptExportTargets(TypedDict):
    targets: list[ScriptExportTarget]


class ScriptCoverage(TypedDict):
    step_id: str
    operation: str
    status: str
    note: str


class ScriptExportResult(TypedDict):
    run_id: str
    target: str
    language: str
    fully_native: bool
    coverage: list[ScriptCoverage]
    required_packages: list[str]
    lineage_hash: str
    artifact_id: str
    filename: str
    sha256: str
    download_url: str
    bytes: int
