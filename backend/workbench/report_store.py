"""Durable storage for AI-generated reports.

Browser localStorage remains a convenience cache only.  The authoritative
record is an immutable JSON artifact under the analysed run so it travels with
the project and contains the exact fact snapshot sent to the provider.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifacts import read_json, register_artifact, write_json

_REPORT_ID = re.compile(r"^rpt_[A-Za-z0-9_-]{3,100}$")
_REPORT_REVISION_FIELDS = frozenset(
    {
        "schema_version",
        "revision_id",
        "document_id",
        "revision_number",
        "parent_revision_id",
        "created_at",
        "markdown",
        "source",
    }
)
_REPORT_REVISION_SOURCE_FIELDS = frozenset(
    {
        "source_record_id",
        "source_report_id",
        "source_run_id",
        "context_fingerprints",
        "capability_manifest",
        "scope",
        "facts",
        "figures",
        "excluded_fact_ids",
        "excluded_figure_ids",
    }
)


def save_ai_report(
    run_root: Path,
    record: Mapping[str, Any],
    *,
    validation_status: str | None = None,
) -> dict[str, Any]:
    report_id = record.get("id")
    if not isinstance(report_id, str) or not _REPORT_ID.fullmatch(report_id):
        raise ValueError("AI report id must use the rpt_<safe-id> format")
    required = ("generatedAt", "instruction", "text", "scope", "facts", "excluded_fact_ids")
    missing = [key for key in required if key not in record]
    if missing:
        raise ValueError(f"AI report is missing required fields: {', '.join(missing)}")
    _validate_revision_snapshot(run_root, record)
    stored_record = dict(record)
    # These are server-derived audit fields.  The browser may display them but
    # cannot choose a different hash, artifact list, or validation status.
    stored_record["fact_snapshot_hash"] = _fact_snapshot_hash(stored_record)
    stored_record["artifact_ids"] = _artifact_ids(stored_record)
    stored_record["validation_status"] = validation_status or "exportable"
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"ai_report_{report_id}.json"
    payload = {
        "schema_version": "workbench-ai-report/v1",
        "record": stored_record,
    }
    if path.exists():
        existing = read_json(path)
        if existing != payload:
            raise ValueError("AI report id already exists with different content")
    else:
        write_json(path, payload)
        register_artifact(run_root, f"ai_report_{report_id}", path, "ai_report", "reporting", [])
    return payload


def _validate_revision_snapshot(run_root: Path, record: Mapping[str, Any]) -> None:
    """Keep report prose revisions from becoming a result-mutation channel."""

    revision = record.get("revision")
    if revision is None:
        return
    if not isinstance(revision, Mapping):
        raise ValueError("report revision must be an object")
    unknown_revision_fields = set(revision) - _REPORT_REVISION_FIELDS
    if unknown_revision_fields:
        raise ValueError(
            "report revision has unknown fields: "
            + ", ".join(sorted(unknown_revision_fields))
        )
    for key in ("schema_version", "revision_id", "document_id", "revision_number", "created_at", "markdown", "source"):
        if key not in revision:
            raise ValueError(f"report revision is missing required field: {key}")
    if revision.get("schema_version") != "workbench.report.revision/v1":
        raise ValueError("unsupported report revision schema")
    if not isinstance(revision.get("revision_number"), int) or isinstance(
        revision.get("revision_number"), bool
    ) or revision.get("revision_number") < 1:
        raise ValueError("report revision number must be a positive integer")
    if revision.get("markdown") != record.get("text"):
        raise ValueError("report revision markdown must equal report text")
    source = revision.get("source")
    if not isinstance(source, Mapping):
        raise ValueError("report revision source must be an object")
    unknown_source_fields = set(source) - _REPORT_REVISION_SOURCE_FIELDS
    if unknown_source_fields:
        raise ValueError(
            "report revision source has unknown fields: "
            + ", ".join(sorted(unknown_source_fields))
        )
    scope = record.get("scope")
    if not isinstance(scope, Mapping):
        raise ValueError("report scope must be an object")
    source_record_id = source.get("source_record_id")
    source_report_id = source.get("source_report_id")
    if source_report_id is not None and source_report_id != source_record_id:
        raise ValueError("report revision source identifiers must match")
    if source_record_id != record.get("id"):
        _validate_parent_report_snapshot(run_root, source_record_id, source)
    if source.get("source_run_id") != scope.get("run_id"):
        raise ValueError("report revision source run must equal report scope run")
    if source.get("context_fingerprints", []) != record.get("context_fingerprints", []):
        raise ValueError("report revision context fingerprints cannot be edited")
    if source.get("capability_manifest", []) != record.get("capability_manifest", []):
        raise ValueError("report revision capability manifest cannot be edited")
    if source.get("scope") != scope:
        raise ValueError("report revision scope cannot be edited")
    if source.get("facts") != record.get("facts"):
        raise ValueError("report revision facts cannot be edited")
    if source.get("figures", []) != record.get("figures", []):
        raise ValueError("report revision figures cannot be edited")
    if source.get("excluded_fact_ids", []) != record.get("excluded_fact_ids", []):
        raise ValueError("report revision exclusions cannot be edited")
    if source.get("excluded_figure_ids", []) != record.get("excluded_figure_ids", []):
        raise ValueError("report revision figure exclusions cannot be edited")
    protected = {
        "dataset",
        "data",
        "artifacts",
        "artifact_payload",
        "diagnostics",
        "diagnostic_summary",
        "lineage",
        "model_results",
        "prediction_results",
        "graph",
    }
    if protected.intersection(source) or protected.intersection(revision):
        raise ValueError("report revision cannot contain Workbench result fields")


def _validate_parent_report_snapshot(
    run_root: Path,
    source_record_id: object,
    source: Mapping[str, Any],
) -> None:
    """Allow a new record only when it points at an existing immutable report."""

    if not isinstance(source_record_id, str) or not _REPORT_ID.fullmatch(source_record_id):
        raise ValueError("report revision source report cannot be edited")
    path = run_root / "reports" / f"ai_report_{source_record_id}.json"
    try:
        payload = read_json(path)
    except (OSError, ValueError, TypeError) as exc:
        raise ValueError("report revision source report cannot be edited") from exc
    parent = payload.get("record") if isinstance(payload, Mapping) else None
    if not isinstance(parent, Mapping) or parent.get("id") != source_record_id:
        raise ValueError("report revision source report cannot be edited")
    parent_scope = parent.get("scope")
    if not isinstance(parent_scope, Mapping):
        raise ValueError("report revision source report cannot be edited")
    parent_snapshot = {
        "source_run_id": parent_scope.get("run_id"),
        "context_fingerprints": parent.get("context_fingerprints", []),
        "capability_manifest": parent.get("capability_manifest", []),
        "scope": parent_scope,
        "facts": parent.get("facts"),
        "figures": parent.get("figures", []),
        "excluded_fact_ids": parent.get("excluded_fact_ids", []),
        "excluded_figure_ids": parent.get("excluded_figure_ids", []),
    }
    if any(
        source.get(
            key,
            [] if key in {
                "context_fingerprints",
                "capability_manifest",
                "excluded_fact_ids",
                "excluded_figure_ids",
            } else None,
        )
        != value
        for key, value in parent_snapshot.items()
    ):
        raise ValueError("report revision source snapshot does not match parent report")


def _fact_snapshot_hash(record: Mapping[str, Any]) -> str:
    snapshot = {
        "scope": record.get("scope"),
        "context_fingerprints": record.get("context_fingerprints", []),
        "capability_manifest": record.get("capability_manifest", []),
        "facts": record.get("facts"),
        "figures": record.get("figures", []),
        "excluded_fact_ids": record.get("excluded_fact_ids", []),
        "excluded_figure_ids": record.get("excluded_figure_ids", []),
    }
    try:
        encoded = json.dumps(
            snapshot,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
    except (TypeError, ValueError) as exc:
        raise ValueError("AI report evidence snapshot must be JSON-compatible") from exc
    return f"sha256:{hashlib.sha256(encoded).hexdigest()}"


def _artifact_ids(record: Mapping[str, Any]) -> list[str]:
    figures = record.get("figures", [])
    if not isinstance(figures, list):
        return []
    return sorted(
        {
            item.get("artifact_id")
            for item in figures
            if isinstance(item, Mapping) and isinstance(item.get("artifact_id"), str)
        }
    )


def list_ai_reports(run_root: Path) -> list[dict[str, Any]]:
    reports_dir = run_root / "reports"
    records: list[dict[str, Any]] = []
    for path in reports_dir.glob("ai_report_rpt_*.json") if reports_dir.is_dir() else []:
        try:
            payload = read_json(path)
            record = payload.get("record") if isinstance(payload, Mapping) else None
            if isinstance(record, Mapping) and isinstance(record.get("id"), str):
                records.append(dict(record))
        except (OSError, ValueError):
            continue
    return sorted(records, key=lambda item: str(item.get("generatedAt", "")), reverse=True)
