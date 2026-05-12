"""Artifact manifest assembly + report gating contract.

Owns: `_artifact_manifest`, `_file_artifact`. These were previously private
helpers in diagnostic_preview.py and remain private; only the in-package
__init__ re-exports them through the public surface as needed.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any


def build_artifact_manifest(run_root: Path, model_results: list[dict[str, Any]]) -> dict[str, Any]:
    return {
        "report_html": _file_artifact(run_root / "reports" / "report.html", "report_html", "report.html"),
        "diagnostic_summary_json": {
            **_file_artifact(run_root / "diagnostic_summary.json", "diagnostic_summary", "diagnostic_summary.json"),
            "schema_valid": (run_root / "diagnostic_summary.json").is_file(),
        },
        "primary_model_results": {
            "expected": True,
            "available": bool(model_results),
            "readable": bool(model_results),
            "model_id": model_results[0].get("model_id") if model_results else None,
        },
        "secondary_model_results": {
            "expected": len(model_results) > 1,
            "available_count": max(len(model_results) - 1, 0),
        },
        "errors_json": {
            **_file_artifact(run_root / "errors.json", "errors_json", "errors.json"),
            "legacy_debug_only": True,
        },
    }


def _file_artifact(path: Path, artifact_id: str, filename: str) -> dict[str, Any]:
    available = path.is_file()
    return {
        "expected": True,
        "available": available,
        "readable": available,
        "artifact_id": artifact_id,
        "filename": filename,
    }
