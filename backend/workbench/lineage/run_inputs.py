"""run_inputs.json — the minimal immutable contract for reproducing/rerunning a run.

Written OUTSIDE the engine (api layer), so golden (which runs the engine) never drifts.
The form bag is a generic dict (form-param name -> value): a new estimator's params land
here automatically. Secrets are redacted on the way in."""
from __future__ import annotations

from collections.abc import Mapping
from pathlib import Path
from typing import Any

from ..artifacts import read_json, write_json

RUN_INPUT_SCHEMA_VERSION = 1
RUN_INPUTS_FILENAME = "run_inputs.json"

# Substrings that mark a form key as secret-bearing. Today the form bag has none;
# this guards future inputs (external connections, API keys).
_SECRET_MARKERS = ("password", "secret", "token", "api_key", "apikey", "credential")


def redact_form(form: dict[str, Any]) -> dict[str, Any]:
    return _redact_value(form)


def _redact_value(value: Any) -> Any:
    if isinstance(value, Mapping):
        out: dict[str, Any] = {}
        for key, item in value.items():
            lowered = str(key).lower()
            if any(marker in lowered for marker in _SECRET_MARKERS):
                out[key] = "***"
            else:
                out[key] = _redact_value(item)
        return out
    if isinstance(value, list):
        return [_redact_value(item) for item in value]
    if isinstance(value, tuple):
        return [_redact_value(item) for item in value]
    return value


def _optional_payload(value: Any) -> Any:
    return _redact_value(value)


def write_run_inputs(
    run_root: Path,
    *,
    form: dict[str, Any],
    upload: dict[str, Any],
    rerun_of: str | None,
    from_node: str | None,
    rerun_reason: str,
    override_hash: str | None,
    dag_hash: str,
    rerun_from: dict[str, Any] | None = None,
    source_lineage: dict[str, Any] | None = None,
    workbench_context: dict[str, Any] | None = None,
    contract_summary: dict[str, Any] | None = None,
    executable_payload: dict[str, Any] | None = None,
    rerun_inputs: dict[str, Any] | None = None,
    confirmed_payload: dict[str, Any] | None = None,
    executed_payload: dict[str, Any] | None = None,
    contract_metadata: dict[str, Any] | None = None,
) -> None:
    payload = {
        "run_input_schema_version": RUN_INPUT_SCHEMA_VERSION,
        "form": redact_form(form),
        "upload": {"sha256": upload["sha256"], "filename": upload.get("filename")},
        "rerun_of": rerun_of,
        "from_node": from_node,
        "rerun_reason": rerun_reason,
        "override_hash": override_hash,
        "dag_hash": dag_hash,
    }
    if rerun_from is not None:
        payload["rerun_from"] = _optional_payload(rerun_from)
    if source_lineage is not None:
        payload["source_lineage"] = _optional_payload(source_lineage)
    if workbench_context is not None:
        payload["workbench_context"] = _optional_payload(workbench_context)
    optional = {
        "contract_summary": contract_summary,
        "executable_payload": executable_payload,
        "rerun_inputs": rerun_inputs,
        "confirmed_payload": confirmed_payload,
        "executed_payload": executed_payload,
        "contract_metadata": contract_metadata,
    }
    for key, value in optional.items():
        if value is not None:
            payload[key] = _optional_payload(value)
    write_json(run_root / RUN_INPUTS_FILENAME, payload)


def update_run_inputs_metadata(run_root: Path, **metadata: Any) -> dict[str, Any]:
    """Add terminal contract evidence without changing immutable executable inputs."""
    payload = read_run_inputs(run_root)
    for key, value in metadata.items():
        if value is not None:
            payload[key] = _optional_payload(value)
    write_json(run_root / RUN_INPUTS_FILENAME, payload)
    return payload


def read_run_inputs(run_root: Path) -> dict[str, Any]:
    return read_json(run_root / RUN_INPUTS_FILENAME)
