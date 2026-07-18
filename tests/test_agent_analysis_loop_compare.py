from __future__ import annotations

import math

import pytest

from workbench.analysis_loop.contracts import ComparisonTarget
from workbench.analysis_loop.compare import (
    ComparePacket,
    ConclusionClassification,
    build_compare_packet,
    classify_primary_target,
    compare_logical_key,
)
from workbench.analysis_loop.validation import ValidationCheck, ValidationPacket


def _result(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "result_id": "coef:treatment",
        "estimate": 1.0,
        "std_error": 0.1,
        "p_value": 0.01,
        "confidence_interval": [0.8, 1.2],
        "confidence_level": 0.95,
    }
    value.update(overrides)
    return value


def _validation(*, status: str = "complete", overall_status: str = "passed") -> ValidationPacket:
    return ValidationPacket(
        status=status,
        overall_status=overall_status,
        terminal=status != "pending",
        checks=(
            ValidationCheck(
                check_id="execution.integrity",
                status="pass" if overall_status == "passed" else "warning",
                severity="info" if overall_status == "passed" else "warning",
                expected=True,
                observed=True,
            ),
        ),
        logical_key="validation:source-child",
        child_run_id="run-child",
        source_run_id="run-source",
        plan_hash="plan-hash",
        executed_payload_hash="payload-hash",
        artifact_manifest_hash="artifact-hash",
        validation_policy_version="validation_policy_v1",
        schema_version="validation_packet_v1",
    )


def _run(**overrides: object) -> dict[str, object]:
    value: dict[str, object] = {
        "run_id": "run-source",
        "source_run_id": None,
        "inference_config": {"covariance": "unadjusted"},
        "fingerprints": {
            "dataset_snapshot": "dataset-1",
            "analysis_sample": "sample-1",
            "point_estimation": "point-1",
            "coefficient_schema": "schema-1",
        },
        "results": {
            "coef:treatment": _result(),
            "coef:control": _result(result_id="coef:control", estimate=0.2),
        },
    }
    value.update(overrides)
    return value


def test_classify_no_material_change() -> None:
    result = classify_primary_target(_result(), _result())

    assert isinstance(result, ConclusionClassification)
    assert result.status == "complete"
    assert result.classification == "NO_MATERIAL_CHANGE"


def test_classify_uncertainty_increase_and_decrease_are_exclusive() -> None:
    increased = classify_primary_target(
        _result(), _result(std_error=0.2, confidence_interval=[0.6, 1.4])
    )
    decreased = classify_primary_target(
        _result(), _result(std_error=0.05, confidence_interval=[0.9, 1.1])
    )

    assert increased.classification == "UNCERTAINTY_INCREASED"
    assert decreased.classification == "UNCERTAINTY_DECREASED"
    assert increased.classification != decreased.classification


@pytest.mark.parametrize(
    ("source_p", "child_p", "expected"),
    [
        (0.01, 0.2, "SIGNIFICANCE_LOST"),
        (0.2, 0.01, "SIGNIFICANCE_GAINED"),
        (0.05, 0.01, "SIGNIFICANCE_GAINED"),
        (0.01, 0.05, "SIGNIFICANCE_LOST"),
    ],
)
def test_classify_significance_uses_strict_alpha_boundary(
    source_p: float, child_p: float, expected: str
) -> None:
    result = classify_primary_target(
        _result(p_value=source_p), _result(p_value=child_p)
    )

    assert result.classification == expected


def test_unknown_nonfinite_evidence_blocks_semantic_classification() -> None:
    result = classify_primary_target(_result(), _result(p_value=math.nan))

    assert result.status == "blocked"
    assert result.classification is None
    assert result.reason_code == "TARGET_EVIDENCE_UNKNOWN"


def test_confidence_level_mismatch_blocks_classification() -> None:
    result = classify_primary_target(
        _result(), _result(confidence_level=0.9)
    )

    assert result.status == "blocked"
    assert result.reason_code == "CONFIDENCE_LEVEL_MISMATCH"


def test_material_estimate_change_does_not_get_an_uncertainty_label() -> None:
    result = classify_primary_target(_result(), _result(estimate=1.2))

    assert result.status == "blocked"
    assert result.classification is None
    assert result.reason_code == "EFFECT_ESTIMATE_MATERIALLY_CHANGED"


def test_target_resolution_is_exact_and_does_not_use_display_labels() -> None:
    result = classify_primary_target(
        {"result_id": "coef:other", "label": "Treatment", "estimate": 1.0, "p_value": 0.01, "confidence_interval": [0.8, 1.2], "confidence_level": 0.95},
        _result(),
        target_result_id="coef:treatment",
    )

    assert result.status == "blocked"
    assert result.reason_code == "PRIMARY_TARGET_MISSING"


def test_build_compare_packet_separates_four_layers_and_classifies_primary_target() -> None:
    source = _run()
    child = _run(
        run_id="run-child",
        source_run_id="run-source",
        inference_config={"covariance": "clustered", "entity_col": "firm_id"},
        results={
            "coef:treatment": _result(
                std_error=0.2,
                confidence_interval=[0.6, 1.4],
            ),
            "coef:control": _result(result_id="coef:control", estimate=0.2),
        },
    )
    packet = build_compare_packet(
        source=source,
        child=child,
        validation=_validation(),
        target=ComparisonTarget(
            result_id="coef:treatment",
            role="primary",
            resolution_source="explicit_primary_metadata",
        ),
    )

    assert isinstance(packet, ComparePacket)
    assert packet.compare_status == "complete"
    assert packet.data_diff["dataset_snapshot"]["changed"] is False
    assert packet.parameter_diff["inference_config"]["changed"] is True
    assert packet.result_diff["coef:treatment"]["changed"] is True
    assert packet.conclusion_diff["classification"] == "UNCERTAINTY_INCREASED"


def test_compare_packet_blocks_when_validation_is_not_integrity_complete() -> None:
    packet = build_compare_packet(
        source=_run(),
        child=_run(run_id="run-child", source_run_id="run-source"),
        validation=_validation(status="blocked", overall_status="failed"),
        target="coef:treatment",
    )

    assert packet.compare_status == "blocked_by_integrity"
    assert packet.conclusion_diff["classification"] is None
    assert "VALIDATION_NOT_COMPLETE" in packet.integrity_findings


def test_compare_packet_allows_partial_only_when_secondary_result_is_missing() -> None:
    child = _run(
        run_id="run-child",
        source_run_id="run-source",
        results={"coef:treatment": _result()},
    )
    packet = build_compare_packet(
        source=_run(),
        child=child,
        validation=_validation(),
        target="coef:treatment",
    )

    assert packet.compare_status == "partial"
    assert packet.conclusion_diff["classification"] == "NO_MATERIAL_CHANGE"
    assert packet.result_diff["coef:control"]["status"] == "missing_in_child"


def test_compare_packet_does_not_fuzzy_match_missing_primary_target() -> None:
    packet = build_compare_packet(
        source=_run(),
        child=_run(run_id="run-child", source_run_id="run-source"),
        validation=_validation(),
        target="coef:missing",
    )

    assert packet.compare_status == "not_comparable"
    assert packet.conclusion_diff["classification"] is None
    assert "PRIMARY_TARGET_MISSING" in packet.integrity_findings


def test_compare_packet_blocks_when_analysis_fingerprint_changes() -> None:
    packet = build_compare_packet(
        source=_run(),
        child=_run(
            run_id="run-child",
            source_run_id="run-source",
            fingerprints={
                "dataset_snapshot": "dataset-1",
                "analysis_sample": "sample-changed",
                "point_estimation": "point-1",
                "coefficient_schema": "schema-1",
            },
        ),
        validation=_validation(),
        target="coef:treatment",
    )

    assert packet.compare_status == "blocked_by_integrity"
    assert "ANALYSIS_SAMPLE_FINGERPRINT_MISMATCH" in packet.integrity_findings


def test_compare_logical_key_changes_with_strategy_and_packet_round_trip_is_immutable() -> None:
    first = build_compare_packet(
        source=_run(),
        child=_run(run_id="run-child", source_run_id="run-source"),
        validation=_validation(),
        target="coef:treatment",
        strategy_version="ols_clustered_v1",
    )
    second_key = compare_logical_key(
        source_run_id="run-source",
        child_run_id="run-child",
        validation_logical_key="validation:source-child",
        target_hash=first.target["target_hash"],
        strategy_version="ols_clustered_v2",
        schema_version=first.schema_version,
    )

    assert second_key != first.logical_key
    assert ComparePacket.from_dict(first.to_dict()) == first
    with pytest.raises(TypeError):
        first.data_diff["mutate"] = True  # type: ignore[index]
