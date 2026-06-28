"""run_inputs.json — the minimal immutable contract for reproducing/rerunning a run.

Written OUTSIDE the engine (api layer), so golden (which runs the engine) never drifts.
The form bag is a generic dict (form-param name -> value): a new estimator's params land
here automatically. Secrets are redacted on the way in."""
from __future__ import annotations

from pathlib import Path
from typing import Any

from ..artifacts import read_json, write_json

RUN_INPUT_SCHEMA_VERSION = 1
RUN_INPUTS_FILENAME = "run_inputs.json"

# Substrings that mark a form key as secret-bearing. Today the form bag has none;
# this guards future inputs (external connections, API keys).
_SECRET_MARKERS = ("password", "secret", "token", "api_key", "apikey", "credential")


def redact_form(form: dict[str, Any]) -> dict[str, Any]:
    out: dict[str, Any] = {}
    for key, value in form.items():
        lowered = key.lower()
        if any(marker in lowered for marker in _SECRET_MARKERS):
            out[key] = "***"
        else:
            out[key] = value
    return out


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
        payload["rerun_from"] = rerun_from
    write_json(run_root / RUN_INPUTS_FILENAME, payload)


def read_run_inputs(run_root: Path) -> dict[str, Any]:
    return read_json(run_root / RUN_INPUTS_FILENAME)
