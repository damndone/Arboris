"""ARMA-GARCH evidence strategy for the existing four-layer ComparePacket."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from .canonical import sha256_canonical
from .compare import (
    COMPARE_PACKET_SCHEMA_VERSION,
    ComparePacket,
    compare_logical_key,
)
from .contracts import ComparisonTarget


ARMA_GARCH_COMPARE_STRATEGY_VERSION = "arma-garch-compare@1"
_REQUIRED_COMPARE_ARTIFACTS = (
    "ts.analysis_contract",
    "ts.report",
    "ts.final_model",
    "ts.parameters",
    "ts.final_diagnostics",
    "ts.forecast_metrics",
    "ts.arma_vs_garch_comparison",
    "ts.artifact_manifest",
)


def _object(value: object) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _artifact(artifacts: Mapping[str, object], artifact_id: str) -> dict[str, Any]:
    value = _object(artifacts.get(artifact_id))
    payload = value.get("payload")
    return _object(payload) if isinstance(payload, Mapping) else value


def _field(before: object, after: object) -> dict[str, object]:
    return {"before": before, "after": after, "changed": before != after}


def _mapping_diff(
    before: Mapping[str, object], after: Mapping[str, object]
) -> dict[str, object]:
    fields = {
        key: _field(before.get(key), after.get(key))
        for key in sorted(set(before) | set(after))
    }
    return {"changed": any(value["changed"] for value in fields.values()), "fields": fields}


def _parameter_snapshot(artifacts: Mapping[str, object]) -> dict[str, object]:
    contract = _artifact(artifacts, "ts.analysis_contract")
    final_model = _artifact(artifacts, "ts.final_model")
    validation_fit = _object(final_model.get("validation_fit"))
    return {
        "transform": contract.get("transform"),
        "time_index_semantics": contract.get("time_index_semantics"),
        "selection_mode": contract.get("selection_mode"),
        "arma": contract.get("arma"),
        "variance": contract.get("variance"),
        "estimation_strategy": contract.get("estimation_strategy"),
        "resolved_strategy": validation_fit.get("resolved_strategy"),
        "innovation_distribution": contract.get("innovation_distribution"),
        "validation": contract.get("validation"),
    }


def _data_snapshot(artifacts: Mapping[str, object]) -> dict[str, object]:
    contract = _artifact(artifacts, "ts.analysis_contract")
    report = _artifact(artifacts, "ts.report")
    reproducibility = _object(report.get("reproducibility"))
    return {
        "dataset_ref": contract.get("dataset_ref"),
        "time_column": contract.get("time_column"),
        "value_column": contract.get("value_column"),
        "sample": _object(report.get("sample")),
        "analysis_view_hash": reproducibility.get("analysis_view_hash"),
        "split_hash": reproducibility.get("split_hash"),
    }


def _acceptance_status(artifacts: Mapping[str, object]) -> str | None:
    report = _artifact(artifacts, "ts.report")
    return _object(report.get("acceptance")).get("overall_status")


def _diagnostic_snapshot(artifacts: Mapping[str, object]) -> dict[str, object]:
    diagnostics = _artifact(artifacts, "ts.final_diagnostics")
    return {
        "normality": _object(diagnostics.get("normality")),
        "arch_lm": _object(diagnostics.get("arch_lm")),
        "warnings": list(diagnostics.get("warnings", []))
        if isinstance(diagnostics.get("warnings"), list)
        else [],
    }


def _trust_conclusion(
    source_artifacts: Mapping[str, object],
    child_artifacts: Mapping[str, object],
    *,
    blocked: bool,
) -> dict[str, object]:
    if blocked:
        return {
            "status": "blocked",
            "classification": None,
            "more_trustworthy": None,
            "reason": "Lineage or required terminal artifacts are incomplete.",
        }
    source_status = _acceptance_status(source_artifacts)
    child_status = _acceptance_status(child_artifacts)
    trusted = {"accepted", "accepted_with_warnings"}
    untrusted = {"rejected", "inconclusive"}
    if child_status in trusted and source_status in untrusted:
        classification = "CHILD_MORE_TRUSTWORTHY"
        more_trustworthy = "child"
        reason = "The child has stronger persisted acceptance evidence on its own frozen validation contract."
    elif source_status in trusted and child_status in untrusted:
        classification = "SOURCE_MORE_TRUSTWORTHY"
        more_trustworthy = "source"
        reason = "The source has stronger persisted acceptance evidence on its own frozen validation contract."
    else:
        classification = "COMPARABLE_WITH_NO_AUTOMATIC_WINNER"
        more_trustworthy = None
        reason = (
            "Both runs remain reviewable; metric changes alone do not establish that one specification is more trustworthy."
        )
    return {
        "status": "complete",
        "classification": classification,
        "more_trustworthy": more_trustworthy,
        "reason": reason,
        "source_acceptance": source_status,
        "child_acceptance": child_status,
    }


def build_arma_garch_compare_packet(
    *,
    source_run_id: str,
    child_run_id: str,
    source_artifacts: Mapping[str, object],
    child_artifacts: Mapping[str, object],
    child_source_run_id: str | None,
) -> ComparePacket:
    """Compare two persisted ARMA-GARCH runs without refitting either model."""

    if not source_run_id or not child_run_id:
        raise ValueError("source_run_id and child_run_id are required")
    findings: list[str] = []
    if child_source_run_id != source_run_id:
        findings.append("SOURCE_CHILD_LINEAGE_MISMATCH")
    for label, artifacts in (("SOURCE", source_artifacts), ("CHILD", child_artifacts)):
        contract = _artifact(artifacts, "ts.analysis_contract")
        manifest = _artifact(artifacts, "ts.artifact_manifest")
        if contract.get("pack_id") != "time_series.arma_garch":
            findings.append(f"{label}_CONTRACT_MISSING")
        if manifest.get("status") != "complete":
            findings.append(f"{label}_ARTIFACT_MANIFEST_INCOMPLETE")
        for artifact_id in _REQUIRED_COMPARE_ARTIFACTS:
            if not _artifact(artifacts, artifact_id):
                findings.append(
                    f"{label}_{artifact_id.removeprefix('ts.').upper().replace('.', '_')}_MISSING"
                )

    source_data = _data_snapshot(source_artifacts)
    child_data = _data_snapshot(child_artifacts)
    for label, snapshot in (("SOURCE", source_data), ("CHILD", child_data)):
        for key in (
            "dataset_ref",
            "time_column",
            "value_column",
            "analysis_view_hash",
            "split_hash",
        ):
            if not isinstance(snapshot.get(key), str) or not snapshot[key]:
                findings.append(f"{label}_{key.upper()}_MISSING")
        if not snapshot.get("sample"):
            findings.append(f"{label}_SAMPLE_MISSING")
    data_diff = {
        key: _field(source_data.get(key), child_data.get(key))
        for key in source_data
    }
    data_diff["changed"] = any(
        value["changed"] for key, value in data_diff.items() if key != "changed"
    )
    for key in (
        "dataset_ref",
        "time_column",
        "value_column",
        "sample",
        "analysis_view_hash",
        "split_hash",
    ):
        if data_diff[key]["changed"]:
            findings.append(f"{key.upper()}_MISMATCH")

    source_parameters = _parameter_snapshot(source_artifacts)
    child_parameters = _parameter_snapshot(child_artifacts)
    parameter_diff = {
        key: _field(source_parameters.get(key), child_parameters.get(key))
        for key in source_parameters
    }
    parameter_diff["changed"] = any(
        value["changed"]
        for key, value in parameter_diff.items()
        if key != "changed"
    )

    source_report = _artifact(source_artifacts, "ts.report")
    child_report = _artifact(child_artifacts, "ts.report")
    result_diff = {
        "model": _mapping_diff(
            _object(_artifact(source_artifacts, "ts.final_model").get("validation_fit")),
            _object(_artifact(child_artifacts, "ts.final_model").get("validation_fit")),
        ),
        "parameters": _mapping_diff(
            _artifact(source_artifacts, "ts.parameters"),
            _artifact(child_artifacts, "ts.parameters"),
        ),
        "forecast_metrics": _mapping_diff(
            _artifact(source_artifacts, "ts.forecast_metrics"),
            _artifact(child_artifacts, "ts.forecast_metrics"),
        ),
        "diagnostics": _mapping_diff(
            _diagnostic_snapshot(source_artifacts),
            _diagnostic_snapshot(child_artifacts),
        ),
        "arma_vs_garch": _mapping_diff(
            _artifact(source_artifacts, "ts.arma_vs_garch_comparison"),
            _artifact(child_artifacts, "ts.arma_vs_garch_comparison"),
        ),
        "acceptance": _field(
            _object(source_report.get("acceptance")),
            _object(child_report.get("acceptance")),
        ),
    }
    target = ComparisonTarget(
        result_id="ts.forecast_metrics",
        role="primary",
        resolution_source="time_series_artifact_contract",
    )
    evidence_hash = sha256_canonical(
        {
            "source": {
                "data": source_data,
                "parameters": source_parameters,
                "metrics": _artifact(source_artifacts, "ts.forecast_metrics"),
            },
            "child": {
                "data": child_data,
                "parameters": child_parameters,
                "metrics": _artifact(child_artifacts, "ts.forecast_metrics"),
            },
        }
    )
    validation_key = f"ts-validation:{evidence_hash}"
    blocked = bool(findings)
    return ComparePacket(
        compare_status="blocked_by_integrity" if blocked else "complete",
        source_run_id=source_run_id,
        child_run_id=child_run_id,
        target=target.to_dict(),
        data_diff=data_diff,
        parameter_diff=parameter_diff,
        result_diff=result_diff,
        conclusion_diff=_trust_conclusion(
            source_artifacts,
            child_artifacts,
            blocked=blocked,
        ),
        validation_status="blocked" if blocked else "complete",
        integrity_findings=tuple(dict.fromkeys(findings)),
        logical_key=compare_logical_key(
            source_run_id=source_run_id,
            child_run_id=child_run_id,
            validation_logical_key=validation_key,
            target_hash=target.target_hash,
            strategy_version=ARMA_GARCH_COMPARE_STRATEGY_VERSION,
            schema_version=COMPARE_PACKET_SCHEMA_VERSION,
        ),
        strategy_version=ARMA_GARCH_COMPARE_STRATEGY_VERSION,
        schema_version=COMPARE_PACKET_SCHEMA_VERSION,
        reason_code=findings[0] if findings else None,
        user_safe_message=(
            "The time-series runs cannot be compared until lineage and terminal artifacts are complete."
            if findings
            else None
        ),
    )


__all__ = [
    "ARMA_GARCH_COMPARE_STRATEGY_VERSION",
    "build_arma_garch_compare_packet",
]
