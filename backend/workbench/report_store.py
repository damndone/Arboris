"""Durable storage for AI-generated reports.

Browser localStorage remains a convenience cache only.  The authoritative
record is an immutable JSON artifact under the analysed run so it travels with
the project and contains the exact fact snapshot sent to the provider.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from pathlib import Path
from typing import Any

from .artifacts import read_json, register_artifact, write_json

_REPORT_ID = re.compile(r"^rpt_[A-Za-z0-9_-]{3,100}$")


def save_ai_report(run_root: Path, record: Mapping[str, Any]) -> dict[str, Any]:
    report_id = record.get("id")
    if not isinstance(report_id, str) or not _REPORT_ID.fullmatch(report_id):
        raise ValueError("AI report id must use the rpt_<safe-id> format")
    required = ("generatedAt", "instruction", "text", "scope", "facts", "excluded_fact_ids")
    missing = [key for key in required if key not in record]
    if missing:
        raise ValueError(f"AI report is missing required fields: {', '.join(missing)}")
    reports_dir = run_root / "reports"
    reports_dir.mkdir(parents=True, exist_ok=True)
    path = reports_dir / f"ai_report_{report_id}.json"
    payload = {
        "schema_version": "workbench-ai-report/v1",
        "record": dict(record),
    }
    if path.exists():
        existing = read_json(path)
        if existing != payload:
            raise ValueError("AI report id already exists with different content")
    else:
        write_json(path, payload)
        register_artifact(run_root, f"ai_report_{report_id}", path, "ai_report", "reporting", [])
    return payload


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
