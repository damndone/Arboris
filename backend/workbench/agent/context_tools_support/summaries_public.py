"""Summaries: bounded read-only context projection. (public)."""

from __future__ import annotations

from pathlib import Path
from collections.abc import Mapping
import re
from typing import Any
from ..context_compiler import (
    read_completion_artifact,
    read_context_artifact_index,
    resolve_registered_artifact,
)
from ..bounds import _bounded_label, _public_stat_number
from .summaries_public_values import (
    _PublicResultBudget,
    _bounded_public_result_value,
    _bounded_test_by_group,
)


def _public_iv_ar_result(payload: dict[str, Any]) -> dict[str, Any]:
    """Keep set topology and certificate scope ahead of the large stored proof."""
    result = payload["result"]
    region = result.get("anderson_rubin_95")
    region = region if isinstance(region, dict) else {}
    certificate = region.get("global_certification")
    certificate = certificate if isinstance(certificate, dict) else {}
    computation = region.get("computation")
    computation = computation if isinstance(computation, dict) else {}
    source = payload.get("source")
    source = source if isinstance(source, dict) else {}
    components = region.get("components")
    component_keys = {"lower", "upper", "lower_closed", "upper_closed", "lower_root", "upper_root"}
    selected = (components[:16] if isinstance(components, list) else [])
    bounded_components = [{key: value for key, value in component.items()
        if key in component_keys and (value is None or type(value) in {bool, int, float})}
        for component in selected if isinstance(component, dict)]
    detail_omitted = (len(bounded_components) != len(selected)
        or any(not isinstance(c, dict) or set(c) != set(b) for c, b in zip(selected, bounded_components)))
    projected_region = _bounded_public_result_value({key: region[key] for key in
        ("kind", "method", "reference_distribution", "inference_scope", "coverage_certified",
         "critical_value", "critical_binary64_ratio", "lower", "upper", "reason") if key in region})
    projected_region.update(
        components=bounded_components,
        components_omitted=max(0, len(components)-len(selected)) if isinstance(components, list) else 0,
        component_details_omitted=detail_omitted or not isinstance(components, list),
        global_certification=_bounded_public_result_value({key: certificate[key] for key in
            ("status", "arithmetic", "algorithm", "input_topology_certified") if key in certificate}),
        computation=_bounded_public_result_value({key: computation[key] for key in
            ("path", "certification_target", "engine") if key in computation}))
    # This compact view is still bounded; it never reads or validates a new source.
    public = _bounded_public_result_value({key: result[key] for key in
        ("contract", "model_id", "model_run_id", "model_sha256", "completion_sha256",
         "point_estimation_fingerprint", "analysis_sample_fingerprint", "covariance", "confidence_level",
         "scientific_validity") if key in result})
    public["source"] = _bounded_public_result_value({key: source[key] for key in
        ("run_id", "node_ref", "artifact_id", "sha256", "model_run_id", "model_artifact_id",
         "workflow_id", "workflow_step_id", "workflow_step_fingerprint") if key in source})
    public["anderson_rubin_95"] = projected_region
    public["interpretation_limits"] = {
        "set": "A certified whole_line rejects no real candidate at this test level under its assumptions. "
               "The set shape does not supply or imply a first-stage F or Wald statistic.",
        "certification": "global_certification concerns mathematical inversion. coverage_certified and "
                         "scientific_validity concern different sampling/design/causal assumptions; their "
                         "absence of certification does not undo a certified mathematical set.",
        "proof": "Bounded summary only; the full original proof remains in the registered artifact named by "
                 "the outer evidence_ref and its SHA. This summary does not independently recompute it.",
        "reader": "Use the exact receipt reference with inspect_operation_artifact for an Agent operation; "
                  "use inspect_notebook_workflow_results for a Notebook receipt. inspect_analysis_completion "
                  "checks the bound original producer evidence, not arbitrary free-text interpretation."}
    return public


def _public_operation_artifact_result(
    artifact_type: str,
    payload: dict[str, Any],
) -> tuple[dict[str, Any] | None, list[str]]:
    """Project a declared result type; unknown types remain deliberately opaque."""

    if artifact_type not in {
        "statistical_exploration",
        "statistical_test",
        "post_estimation",
        "p7_analysis",
        "workflow_capability_result",
    }:
        return None, ["raw_artifact_payloads"]
    result = payload.get("result")
    if not isinstance(result, dict):
        return None, ["raw_artifact_payloads"]
    if artifact_type == "workflow_capability_result":
        from ...native_research import NATIVE_RESEARCH_OPERATIONS

        operation_id = result.get("operation_id")
        if isinstance(operation_id, str) and operation_id in NATIVE_RESEARCH_OPERATIONS:
            secondary = {"coefficients", "predictors", "inputs", "policy", "assumptions"}
            core = {key: value for key, value in result.items() if key not in secondary}
            # Older saved results can still carry these exact observation
            # labels inside aggregate sections. They are local-only now.
            for field, private in (("split", {"train_last_time", "test_first_time"}), ("holdout", {"origin_time"})):
                if isinstance(core.get(field), dict):
                    core[field] = {key: value for key, value in core[field].items() if key not in private}
            public = _bounded_public_result_value(
                core, budget=_PublicResultBudget(remaining_items=192), max_depth=5,
            )
            public.update(_bounded_public_result_value(
                {key: result[key] for key in ("assumptions", "policy") if key in result},
            ))
            if isinstance(result.get("inputs"), dict):
                public["inputs"] = _bounded_public_result_value({
                    key: value for key, value in result["inputs"].items() if not isinstance(value, list)
                })
            if isinstance(result.get("coefficients"), dict):
                coefficients = result["coefficients"]
                public["coefficients"] = _bounded_public_result_value(dict(list(coefficients.items())[:12]))
                public["coefficient_count"] = len(coefficients)
            return public, ["raw_artifact_payloads", "local_detail"]
    if artifact_type == "post_estimation" and result.get("contract") == "iv-ar.evidence.v1":
        return _public_iv_ar_result(payload), ["raw_artifact_payloads", "raw_rows", "full_ar_certificate"]
    source = _dataset_source(artifact_type, payload)
    if artifact_type == "workflow_capability_result" and isinstance(result.get("result"), dict):
        # {operation_id, family, source_columns, result: {...}}: the inner
        # result holds the statistics; lifting it keeps them inside the
        # projection's nesting limit.
        result = {
            "operation_id": result.get("operation_id"),
            "source_columns": result.get("source_columns"),
            **result["result"],
        }
    if (
        artifact_type == "statistical_exploration"
        and result.get("operation") == "tabulate"
        and isinstance(result.get("rows"), list)
    ):
        # A frequency table is an aggregate. Its entries are stored under
        # `rows` for the UI table, a key the projection withholds as raw data.
        result = {**{key: value for key, value in result.items() if key != "rows"}, "frequencies": result["rows"]}
    if artifact_type == "statistical_test" and isinstance(result.get("by_group"), Mapping):
        return ({**source, **_public_test_by_group(result)},
                ["raw_artifact_payloads", "raw_rows", "test_effect_details"])
    budget, max_depth = None, 4
    if artifact_type == "workflow_capability_result":
        # Test effect summaries can contain distinct estimands with their own
        # intervals. Keep the bounded fields paired with their method labels.
        max_depth = 5
        if result.get("operation_id") == "test.proportions":
            from ...statistical_test_proportions import ROLE_PARAMETERS

            max_depth = 6  # The two groups each have events, trials and a rate.
            request = payload.get("request")
            options = request.get("options") if isinstance(request, dict) else None
            if isinstance(options, dict):
                result = {**result, "column_roles": {
                    key: options[key] for key in ROLE_PARAMETERS if isinstance(options.get(key), str)
                }}
    if artifact_type == "statistical_exploration":
        # Grouped statistics sit at groups[i].variables[name].percentiles --
        # one level deeper than any other result. Lifting each group's
        # variables into the group, and allowing one more level, keeps every
        # group's numbers; before, the Agent saw only "[omitted: nesting
        # limit]" and could not answer "mean wage by sex".
        if isinstance(result.get("groups"), list):
            groups = result["groups"]
            if result.get("operation") == "tabulate":
                # Each group's frequency table is the same aggregate as the ungrouped one above; left
                # under `rows` it was withheld, and QRData 374 saw "state: distinct 1" in the
                # California group but not which state it was.
                groups = [{**{key: value for key, value in group.items() if key != "rows"}, "frequencies": group["rows"]}
                          if isinstance(group, dict) and isinstance(group.get("rows"), list) else group
                          for group in groups]
            result = {**result, "groups": [_lift_group_variables(group) for group in groups]}
        budget, max_depth = _PublicResultBudget(remaining_items=320), 5
    public = _bounded_public_result_value(result, budget=budget, max_depth=max_depth)
    public.update(source)
    return public, ["raw_artifact_payloads", "raw_rows"]


def _dataset_source(artifact_type: str, payload: dict[str, Any]) -> dict[str, Any]:
    """Show the producer's immediate data pin, which may already be a subset."""
    if artifact_type == "statistical_exploration":
        source = {"artifact_id": payload.get("source_artifact_id"), "sha256": payload.get("source_sha256")}
    elif artifact_type in {"statistical_test", "p7_analysis", "workflow_capability_result"}:
        source = payload.get("source")
    else:
        return {}
    if not isinstance(source, dict):
        return {}
    pin = {key: source[key] for key in ("run_id", "node_ref", "artifact_id", "sha256")
           if isinstance(source.get(key), str) and 0 < len(source[key]) <= 300}
    if "artifact_id" not in pin or not re.fullmatch(r"[0-9a-f]{64}", pin.get("sha256", "")):
        return {}
    return {"dataset_source": pin}


_BY_GROUP_TEST_FIELDS = (
    "test_id", "test_type", "group", "nobs", "statistic", "degrees_of_freedom", "p_value",
    "p_value_holm_across_groups", "p_value_bh_across_groups",
)


_MAX_BY_GROUP_TEST_ROWS = 60


def _public_test_by_group(result: Mapping[str, Any]) -> dict[str, Any]:
    """Every group's row of every test, compactly: a generic budget dropped whole groups."""
    rows = [row for row in result.get("results") or () if isinstance(row, Mapping)]
    kept = rows[:_MAX_BY_GROUP_TEST_ROWS]
    return {
        "test_type": result.get("test_type"),
        "by_group": _bounded_test_by_group(result["by_group"]),
        "results": [
            {key: (_public_stat_number(row[key]) if isinstance(row[key], (int, float)) and not isinstance(row[key], bool)
                   else _bounded_label(row[key]))
             for key in _BY_GROUP_TEST_FIELDS if row.get(key) is not None}
            for row in kept
        ],
        "result_count": len(rows),
        "results_omitted": max(len(rows) - len(kept), 0),
    }


def _lift_group_variables(group: Any) -> Any:
    if not isinstance(group, dict) or not isinstance(group.get("variables"), dict):
        return group
    lifted = {key: value for key, value in group.items() if key not in {"variables", "filters"}}
    for name, statistics in group["variables"].items():
        lifted[name if name not in lifted else f"variable:{name}"] = statistics
    return lifted


def _node_public_result_evidence(
    project_root: Path,
    *,
    owner_run_id: str,
    op_node_id: str,
) -> list[dict[str, Any]]:
    """Read statistical results whose declared input is the selected data node.

    This is deliberately a relation check, not a run-wide artifact dump.  A
    UI-created statistical exploration records the selected data artifact in
    its artifact-index inputs; only those descendants become Agent evidence.
    """

    run_root = project_root / "runs" / owner_run_id
    if op_node_id.startswith("native-result:"):
        from ...native_research import native_result_operation

        artifact_id = op_node_id.removeprefix("native-result:")
        if native_result_operation(artifact_id) is None:
            return []
        artifact = read_completion_artifact(run_root, artifact_id)
        if artifact is None or artifact.payload is None:
            return []
        public, _ = _public_operation_artifact_result(artifact.artifact_type, artifact.payload)
        return [{"artifact_id": artifact_id, "artifact_type": artifact.artifact_type,
                 "sha256": artifact.sha256, "result": public}] if public is not None else []

    try:
        from ...data_operations import resolve_data_column_cast_context

        source = resolve_data_column_cast_context(
            project_root,
            source_run_id=owner_run_id,
            source_node_id=op_node_id,
        )
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return []
    source_artifact_id = source.get("source_artifact_id")
    if not isinstance(source_artifact_id, str) or not source_artifact_id:
        return []
    try:
        index = read_context_artifact_index(run_root)
    except (FileNotFoundError, OSError, ValueError):
        return []
    entries = index.get("artifacts") if isinstance(index, dict) else None
    if not isinstance(entries, list):
        return []
    evidence: list[dict[str, Any]] = []
    for entry in entries:
        if len(evidence) >= 8 or not isinstance(entry, dict):
            break
        artifact_id = entry.get("artifact_id")
        artifact_type = entry.get("artifact_type")
        inputs = entry.get("inputs")
        if (
            not isinstance(artifact_id, str)
            or not isinstance(artifact_type, str)
            or not isinstance(inputs, list)
            or source_artifact_id not in inputs
        ):
            continue
        artifact = resolve_registered_artifact(run_root, artifact_id)
        if artifact is None:
            continue
        resolved_type, sha256, payload = artifact
        public_result, _omitted = _public_operation_artifact_result(resolved_type, payload)
        if public_result is None:
            continue
        evidence.append(
            {
                "artifact_id": artifact_id,
                "artifact_type": artifact_type,
                "sha256": sha256,
                "result": public_result,
            }
        )
    return evidence
