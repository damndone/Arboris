"""Turn check results into the run's issues and a persisted artifact."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from ..artifacts import read_json, register_artifact, write_json
from ..contracts.model.inference_kernel import kernel_relative_path
from ..domain import GuardrailIssue, Severity
from .context import build_context
from .registry import run_checks

CHECKS_SCHEMA = "workbench.checks/v1"
_SEVERITY = {"fails": Severity.WARNING, "caution": Severity.CAUTION, "needs_reason": Severity.CAUTION}


def check_issues(results: Sequence[Mapping[str, Any]], model_id: str) -> list[dict[str, Any]]:
    issues = []
    for result in results:
        severity = _SEVERITY.get(str(result.get("status")))
        if severity is None:
            continue
        code = "CHECK_" + str(result["check_id"]).upper().replace(".", "_")
        issues.append(GuardrailIssue(
            severity, code, f"Model {model_id}: {result['summary']}",
            {"model_id": model_id, "check_id": result["check_id"], "status": result["status"],
             "evidence": result.get("evidence"), "remedy": result.get("remedy")},
        ).to_dict())
    return issues


def run_model_checks(
    run_root: Path, *, model_id: str, model_type: str, fitted: Any, nobs: int | None, inputs: Sequence[str],
    facts: Mapping[str, Any] | None = None,
) -> list[dict[str, Any]]:
    """Run the library on one fitted model and persist `checks_<model_id>`."""
    kernel_path = run_root / kernel_relative_path(model_id)
    kernel = read_json(kernel_path) if kernel_path.is_file() else None
    context = build_context(model_id=model_id, model_type=model_type, fitted=fitted, kernel=kernel, nobs=nobs, facts=facts)
    results = run_checks(context)
    withheld = next((item for item in results if item.get("suppresses_inference")), None)
    if withheld is not None:
        suppress_inference(run_root, model_id, check_id=str(withheld["check_id"]), reason=str(withheld["summary"]))
    path = run_root / "model_results" / f"checks_{model_id}.json"
    write_json(path, {"schema_version": CHECKS_SCHEMA, "model_id": model_id, "model_type": model_type,
                      "traits": sorted(context.traits), "checks": results})
    register_artifact(run_root, f"checks_{model_id}", path, "model_checks", "checks", list(inputs))
    return results


_INFERENCE_FIELDS = ("std_error", "p_value", "ci_lower", "ci_upper", "t_value", "z_value", "statistic", "p_value_display")


def suppress_inference(run_root: Path, model_id: str, *, check_id: str, reason: str) -> None:
    """Withhold standard errors, tests and intervals the fit cannot support.

    Point estimates stay; everything computed from the covariance is removed
    from the packet, and the kernel stops offering its covariance, so no
    post-estimation can be run on it either.
    """
    from ..contracts.model.inference_kernel import validate_inference_kernel

    packet_path = run_root / "model_results" / f"{model_id}.json"
    if packet_path.is_file():
        packet = read_json(packet_path)
        for row in (packet.get("coefficients") or {}).values():
            if isinstance(row, dict):
                for field in _INFERENCE_FIELDS:
                    if field in row:
                        row[field] = None
        packet["inference_suppressed"] = {"check_id": check_id, "reason": reason}
        write_json(packet_path, packet)
    kernel_path = run_root / kernel_relative_path(model_id)
    if kernel_path.is_file():
        kernel = read_json(kernel_path)
        kernel["vcov"] = None
        kernel["vcov_param_names"] = None
        kernel["vcov_scope"] = "unavailable"
        kernel["interfaces"] = [item for item in kernel.get("interfaces", []) if item != "coef_vcov"]
        kernel["unavailable"] = {**kernel.get("unavailable", {}), "coef_vcov": reason}
        validate_inference_kernel(kernel)
        write_json(kernel_path, kernel)
