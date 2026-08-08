from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pandas as pd
import pytest


def _fixture() -> tuple[list[int], list[float]]:
    return (
        [0, 1, 0, 1, 1, 0],
        [0.1, 0.8, 0.8, 0.4, 0.4, 0.2],
    )


def test_roc_contract_is_versioned_closed_and_json_safe() -> None:
    from workbench.contracts.model.roc_diagnostics import (
        ROC_DIAGNOSTICS_CONTRACT,
        ROC_DIAGNOSTICS_CONTRACT_VERSION,
        ROC_DIAGNOSTICS_OPERATION_IDS,
        RocDiagnosticsResultEnvelope,
    )

    y_true, scores = _fixture()
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    value = run_roc_curve(
        y_true,
        scores,
        positive_label=1,
        score_semantics="score",
        threshold_policy="unique_scores",
    )
    assert ROC_DIAGNOSTICS_OPERATION_IDS == frozenset(
        {"roc.curve", "roc.calibration"}
    )
    assert value["contract"] == ROC_DIAGNOSTICS_CONTRACT
    assert value["contract_version"] == ROC_DIAGNOSTICS_CONTRACT_VERSION == "1.0"
    assert set(value) == {
        "contract",
        "contract_version",
        "operation_id",
        "status",
        "reason_code",
        "result",
        "provenance",
    }
    assert value["operation_id"] == "roc.curve"
    assert value["provenance"]["runtime"] == "score_only"
    assert RocDiagnosticsResultEnvelope.from_dict(value).to_dict() == value
    assert json.loads(json.dumps(value, allow_nan=False)) == value

    envelope_without_optional_metadata = RocDiagnosticsResultEnvelope(
        operation_id="roc.curve",
        result=value["result"],
    ).to_dict()
    assert envelope_without_optional_metadata["provenance"] == {}


def test_calibration_contract_requires_explicit_probability_and_bin_policy() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.roc_diagnostics import RocDiagnosticsInput

    with pytest.raises(ContractError, match="score_semantics"):
        RocDiagnosticsInput(
            operation_id="roc.calibration",
            positive_label=1,
            score_semantics="score",
            calibration_method="equal_width",
            n_bins=4,
        )
    with pytest.raises(ContractError, match="calibration_method"):
        RocDiagnosticsInput(
            operation_id="roc.calibration",
            positive_label=1,
            score_semantics="probability",
            calibration_method=None,
            n_bins=4,
        )
    with pytest.raises(ContractError, match="n_bins"):
        RocDiagnosticsInput(
            operation_id="roc.calibration",
            positive_label=1,
            score_semantics="probability",
            calibration_method="equal_width",
            n_bins=None,
        )


def test_closed_operation_dispatcher_exposes_only_declared_operations() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_diagnostics
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    curve = run_roc_diagnostics(
        "roc.curve",
        [0, 1, 0, 1],
        [0.1, 0.8, 0.2, 0.7],
        positive_label=1,
    )
    assert curve["operation_id"] == "roc.curve"
    calibration = run_roc_diagnostics(
        "roc.calibration",
        [0, 1, 0, 1],
        [0.1, 0.8, 0.2, 0.7],
        positive_label=1,
        score_semantics="probability",
        calibration_method="equal_width",
        n_bins=2,
    )
    assert calibration["operation_id"] == "roc.calibration"
    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_UNKNOWN_OPERATION"):
        run_roc_diagnostics("roc.other", [0, 1], [0.1, 0.9], positive_label=1)
    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_UNKNOWN_OPERATION"):
        run_roc_diagnostics([], [0, 1], [0.1, 0.9], positive_label=1)


def test_quantile_grid_exposes_exact_and_sampled_auc_semantics() -> None:
    from workbench.contracts.model.roc_diagnostics import RocDiagnosticsResultEnvelope
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    y_true = [0, 1, 0, 1, 0, 1, 0, 1]
    scores = [0.266963, 0.22731, 0.237374, 0.681692, 0.537764, 0.436227, 0.936738, 0.577069]
    value = run_roc_curve(
        y_true,
        scores,
        positive_label=1,
        threshold_policy="quantile_grid",
        quantile_grid_size=3,
        max_thresholds=10,
    )
    payload = value["result"]
    sampled_roc = sum(
        (right["fpr"] - left["fpr"]) * (left["tpr"] + right["tpr"]) / 2.0
        for left, right in zip(payload["roc_points"], payload["roc_points"][1:])
    )

    assert payload["exact_auc"] == pytest.approx(0.5)
    assert payload["auc"] == payload["exact_auc"]
    assert payload["auc_semantics"] == "exact_rank"
    assert payload["sampled_roc_auc"] == pytest.approx(sampled_roc)
    assert payload["sampled_roc_auc"] == pytest.approx(0.4375)
    assert payload["sampled_roc_auc"] != pytest.approx(payload["exact_auc"])
    assert payload["sampled_roc_auc_semantics"] == "grid_based_trapezoid"
    assert payload["sampled_pr_auc"] == payload["pr_auc"]
    assert payload["sampled_pr_auc_semantics"] == "grid_based_stepwise"
    assert value["provenance"]["metric_semantics"] == (
        "exact_rank_auc_and_grid_based_sampled_areas"
    )
    assert RocDiagnosticsResultEnvelope.from_dict(value).to_dict() == value


@pytest.mark.parametrize("reader", ["construct", "persisted"])
def test_persisted_envelope_rejects_non_score_only_metric_semantics(reader) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.roc_diagnostics import RocDiagnosticsResultEnvelope
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    value = run_roc_curve(
        [0, 1, 0, 1],
        [0.1, 0.8, 0.2, 0.7],
        positive_label=1,
    )
    forged_provenance = {
        **value["provenance"],
        "metric_semantics": "model_training_metrics",
    }

    with pytest.raises(ContractError, match="metric_semantics"):
        if reader == "construct":
            RocDiagnosticsResultEnvelope(
                operation_id=value["operation_id"],
                result=value["result"],
                provenance=forged_provenance,
            )
        else:
            forged = {**value, "provenance": forged_provenance}
            RocDiagnosticsResultEnvelope.from_dict(forged)


@pytest.mark.parametrize("reader", ["construct", "persisted"])
@pytest.mark.parametrize(
    ("field", "alias"),
    [("auc", "exact_auc"), ("pr_auc", "sampled_pr_auc")],
)
def test_curve_envelope_rejects_inconsistent_auc_aliases(reader, field, alias) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.roc_diagnostics import RocDiagnosticsResultEnvelope
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    value = run_roc_curve(
        [0, 1, 0, 1, 1, 0],
        [0.1, 0.8, 0.8, 0.4, 0.4, 0.2],
        positive_label=1,
    )
    forged_result = {
        **value["result"],
        field: value["result"][alias] + 0.01,
    }

    with pytest.raises(ContractError, match=field):
        if reader == "construct":
            RocDiagnosticsResultEnvelope(
                operation_id="roc.curve",
                result=forged_result,
                provenance=value["provenance"],
            )
        else:
            forged = {**value, "result": forged_result}
            RocDiagnosticsResultEnvelope.from_dict(forged)


def test_provenance_rejects_reserved_field_conflicts() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    for key, value in (
        ("pack", "forged_pack"),
        ("runtime", "model_training"),
        ("implementation", "r"),
        ("contract_version", "9.9"),
        ("metric_semantics", "model_training_metrics"),
    ):
        with pytest.raises(
            RocDiagnosticsPackError,
            match="ROC_DIAGNOSTICS_PROVENANCE_CONFLICT",
        ):
            run_roc_curve(
                [0, 1, 0, 1],
                [0.1, 0.8, 0.2, 0.7],
                positive_label=1,
                provenance={key: value},
            )

    result = run_roc_curve(
        [0, 1, 0, 1],
        [0.1, 0.8, 0.2, 0.7],
        positive_label=1,
        provenance={"runtime": "score_only", "source": "fixed_fixture"},
    )
    assert result["provenance"]["runtime"] == "score_only"
    assert result["provenance"]["source"] == "fixed_fixture"

    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.roc_diagnostics import RocDiagnosticsResultEnvelope

    with pytest.raises(ContractError, match="provenance field runtime is reserved"):
        RocDiagnosticsResultEnvelope(
            operation_id="roc.curve",
            result=result["result"],
            provenance={"runtime": "model_training"},
        )


def test_rejected_and_failed_envelopes_round_trip_minimal_errors() -> None:
    from workbench.contracts.model.roc_diagnostics import (
        ROC_DIAGNOSTICS_FAILED,
        ROC_DIAGNOSTICS_REJECTED,
        RocDiagnosticsResultEnvelope,
        make_error_envelope,
    )
    from workbench.engine.packs.roc_diagnostics import run_roc_diagnostics

    rejected = make_error_envelope(
        operation_id="roc.curve",
        status="rejected",
        reason_code=ROC_DIAGNOSTICS_REJECTED,
        error_code="ROC_DIAGNOSTICS_EMPTY_CLASS",
        message="both target classes must be non-empty",
    )
    failed = make_error_envelope(
        operation_id="roc.calibration",
        status="failed",
        reason_code=ROC_DIAGNOSTICS_FAILED,
        error_code="ROC_DIAGNOSTICS_INTERNAL_ERROR",
        message="ROC diagnostics execution failed",
        details={"retryable": False},
    )
    for value, status, reason in (
        (rejected, "rejected", ROC_DIAGNOSTICS_REJECTED),
        (failed, "failed", ROC_DIAGNOSTICS_FAILED),
    ):
        assert value["status"] == status
        assert value["reason_code"] == reason
        assert RocDiagnosticsResultEnvelope.from_dict(value).to_dict() == value
        assert json.loads(json.dumps(value, allow_nan=False)) == value

    dispatcher_rejection = run_roc_diagnostics(
        "roc.curve",
        [0, 0, 0, 0],
        [0.1, 0.2, 0.3, 0.4],
        positive_label=1,
    )
    assert dispatcher_rejection["status"] == "rejected"
    assert dispatcher_rejection["reason_code"] == ROC_DIAGNOSTICS_REJECTED
    assert dispatcher_rejection["result"]["error_code"] == "ROC_DIAGNOSTICS_EMPTY_CLASS"


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        (
            {
                "constraint_policy": {
                    "metric": ["sensitivity"],
                    "operator": ">=",
                    "value": 0.8,
                }
            },
            "ROC_DIAGNOSTICS_INVALID_POLICY",
        ),
        (
            {
                "constraint_policy": {
                    "metric": "sensitivity",
                    "operator": [">="],
                    "value": 0.8,
                }
            },
            "ROC_DIAGNOSTICS_INVALID_POLICY",
        ),
        (
            {"constraint_policy": ["metric", "operator", "value"]},
            "ROC_DIAGNOSTICS_INVALID_POLICY",
        ),
        (
            {
                "cost_policy": {
                    "false_positive_cost": [1.0],
                    "false_negative_cost": 1.0,
                }
            },
            "ROC_DIAGNOSTICS_INVALID_OPTION",
        ),
    ],
)
def test_invalid_policy_types_raise_stable_pack_errors(kwargs, reason) -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    with pytest.raises(RocDiagnosticsPackError, match=reason):
        run_roc_curve(
            [0, 1, 0, 1],
            [0.1, 0.8, 0.2, 0.7],
            positive_label=1,
            **kwargs,
        )


def test_roc_fixed_fixture_has_deterministic_tie_aware_auc_curves_and_metrics() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    y_true, scores = _fixture()
    result = run_roc_curve(
        y_true,
        scores,
        positive_label=1,
        threshold_policy="unique_scores",
        score_semantics="score",
    )
    payload = result["result"]

    assert payload["positive_label"] == 1
    assert payload["negative_label"] == 0
    assert payload["tie_policy"] == "average_rank_half_credit"
    assert payload["auc_method"] == "rank_wilcoxon_average_ties"
    assert payload["auc"] == pytest.approx(13 / 18)
    assert payload["pr_auc_method"] == "stepwise_recall_precision"
    assert payload["pr_auc"] == pytest.approx((1 / 3) * (1 / 2) + (2 / 3) * (3 / 4))

    points = payload["threshold_evidence"]
    assert [point["threshold"] for point in points] == [None, 0.8, 0.4, 0.2, 0.1, None]
    assert [point["threshold_role"] for point in points] == [
        "above_max",
        "score",
        "score",
        "score",
        "score",
        "below_min",
    ]
    assert points[1]["confusion_counts"] == {"tp": 1, "fp": 1, "tn": 2, "fn": 2}
    assert points[2]["confusion_counts"] == {"tp": 3, "fp": 1, "tn": 2, "fn": 0}
    assert points[2]["sensitivity"] == pytest.approx(1.0)
    assert points[2]["specificity"] == pytest.approx(2 / 3)
    assert points[2]["ppv"] == pytest.approx(3 / 4)
    assert points[2]["npv"] == pytest.approx(1.0)
    assert points[2]["f1"] == pytest.approx(6 / 7)
    assert payload["decision_evidence"]["mode"] == "evidence_only"
    assert payload["decision_evidence"]["policy"] is None
    assert "best_threshold" not in payload["decision_evidence"]


def test_all_ties_have_half_auc_and_label_flip_is_symmetric() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    y_true = ["negative", "positive", "negative", "positive"]
    scores = [5.0, 5.0, 5.0, 5.0]
    positive = run_roc_curve(
        y_true, scores, positive_label="positive", threshold_policy="unique_scores"
    )["result"]
    flipped = run_roc_curve(
        y_true, scores, positive_label="negative", threshold_policy="unique_scores"
    )["result"]
    assert positive["auc"] == pytest.approx(0.5)
    assert flipped["auc"] == pytest.approx(1.0 - positive["auc"])


def test_threshold_policy_is_bounded_and_quantile_grid_is_explicit() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_OUTPUT_TOO_LARGE"):
        run_roc_curve(
            [0, 1, 0, 1],
            [0.1, 0.2, 0.3, 0.4],
            positive_label=1,
            threshold_policy="unique_scores",
            max_thresholds=4,
        )

    result = run_roc_curve(
        [0, 1, 0, 1, 0, 1],
        [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
        positive_label=1,
        threshold_policy="quantile_grid",
        quantile_grid_size=3,
        max_thresholds=10,
    )
    policy = result["result"]["threshold_policy"]
    assert policy == {
        "name": "quantile_grid",
        "quantile_grid_size": 3,
        "max_thresholds": 10,
    }
    assert len(result["result"]["threshold_evidence"]) <= 5


@pytest.mark.parametrize(
    ("kwargs", "reason"),
    [
        ({"positive_label": 1}, "ROC_DIAGNOSTICS_EMPTY_CLASS"),
        ({"positive_label": 2}, "ROC_DIAGNOSTICS_EMPTY_CLASS"),
        ({"positive_label": 1, "threshold_policy": "unknown"}, "ROC_DIAGNOSTICS_UNKNOWN_POLICY"),
        ({"positive_label": 1, "score_semantics": "probability"}, "ROC_DIAGNOSTICS_INVALID_PROBABILITY"),
    ],
)
def test_roc_rejects_invalid_target_policies_and_probabilities(kwargs, reason) -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    y_true = [0, 1, 0, 1]
    scores = [0.1, 0.8, 0.2, 1.1]
    if reason == "ROC_DIAGNOSTICS_EMPTY_CLASS":
        y_true = [0, 0, 0, 0]
        scores = [0.1, 0.2, 0.3, 0.4]
    if reason == "ROC_DIAGNOSTICS_UNKNOWN_POLICY":
        kwargs = {**kwargs, "threshold_policy": "unknown"}
    with pytest.raises(RocDiagnosticsPackError, match=reason):
        run_roc_curve(y_true, scores, **kwargs)


def test_missing_values_are_rejected_unless_explicit_drop_policy_records_count() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_MISSING_VALUE"):
        run_roc_curve([0, 1, None, 1], [0.1, 0.8, 0.3, 0.7], positive_label=1)

    result = run_roc_curve(
        [0, 1, None, 1],
        [0.1, 0.8, 0.3, 0.7],
        positive_label=1,
        missing_policy="drop_explicit",
    )
    assert result["result"]["missing_metadata"] == {
        "missing_policy": "drop_explicit",
        "n_input": 4,
        "n_used": 3,
        "dropped_count": 1,
    }


def test_iterable_inputs_preserve_input_count_metadata() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    result = run_roc_curve(
        iter([0, 1, 0, 1]),
        iter([0.1, 0.8, 0.2, 0.7]),
        positive_label=1,
    )
    assert result["result"]["missing_metadata"] == {
        "missing_policy": "reject",
        "n_input": 4,
        "n_used": 4,
        "dropped_count": 0,
    }


def test_pandas_missing_marker_is_dropped_only_under_explicit_policy() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_MISSING_VALUE"):
        run_roc_curve([0, pd.NA, 1, 0], [0.1, 0.4, 0.8, 0.2], positive_label=1)
    result = run_roc_curve(
        [0, pd.NA, 1, 0],
        [0.1, 0.4, 0.8, 0.2],
        positive_label=1,
        missing_policy="drop_explicit",
    )
    assert result["result"]["missing_metadata"]["dropped_count"] == 1


def test_probability_metrics_and_calibration_are_explicit_and_bounded() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_calibration, run_roc_curve

    y_true = [0, 1, 0, 1, 1, 0]
    probabilities = [0.05, 0.85, 0.25, 0.55, 0.75, 0.15]
    curve = run_roc_curve(
        y_true,
        probabilities,
        positive_label=1,
        score_semantics="probability",
    )["result"]
    assert curve["brier_score"] == pytest.approx(
        np.mean((np.asarray(probabilities) - np.asarray(y_true)) ** 2)
    )
    assert curve["log_loss"] is not None

    calibration = run_roc_calibration(
        y_true,
        probabilities,
        positive_label=1,
        score_semantics="probability",
        calibration_method="equal_width",
        n_bins=4,
    )["result"]
    assert calibration["calibration_method"] == "equal_width"
    assert len(calibration["bins"]) == 4
    assert sum(item["count"] for item in calibration["bins"]) == 6
    assert 0.0 <= calibration["brier_score"] <= 1.0

    quantile = run_roc_calibration(
        y_true,
        probabilities,
        positive_label=1,
        score_semantics="probability",
        calibration_method="quantile",
        n_bins=3,
    )["result"]
    assert quantile["calibration_method"] == "quantile"
    assert sum(item["count"] for item in quantile["bins"]) == 6


def test_probability_only_operations_reject_arbitrary_scores_and_bin_bounds() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_calibration
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_INVALID_SCORE_SEMANTICS"):
        run_roc_calibration(
            [0, 1, 0, 1],
            [2.0, 3.0, 4.0, 5.0],
            positive_label=1,
            score_semantics="score",
        )

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_INVALID_SCORE_SEMANTICS"):
        run_roc_calibration(
            [0, 1, 0, 1],
            [0.2, 0.8, 0.3, 0.7],
            positive_label=1,
        )

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_UNKNOWN_POLICY"):
        run_roc_calibration(
            [0, 1, 0, 1],
            [0.2, 0.8, 0.3, 0.7],
            positive_label=1,
            score_semantics="probability",
        )

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_OUTPUT_TOO_LARGE"):
        run_roc_calibration(
            [0, 1, 0, 1],
            [0.1, 0.2, 0.8, 0.9],
            positive_label=1,
            score_semantics="probability",
            calibration_method="equal_width",
            n_bins=51,
            max_bins=50,
        )


def test_quantile_budget_and_nonfinite_inputs_fail_closed() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve
    from workbench.engine.packs.roc_diagnostics.errors import RocDiagnosticsPackError

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_OUTPUT_TOO_LARGE"):
        run_roc_curve(
            [0, 1, 0, 1],
            [0.1, 0.2, 0.3, 0.4],
            positive_label=1,
            threshold_policy="quantile_grid",
            quantile_grid_size=10,
            max_thresholds=5,
        )

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_NON_FINITE_INPUT"):
        run_roc_curve([0, 1, 0, 1], [0.1, np.inf, 0.3, 0.4], positive_label=1)

    with pytest.raises(RocDiagnosticsPackError, match="ROC_DIAGNOSTICS_INVALID_SCORE_SEMANTICS"):
        run_roc_curve(
            [0, 1, 0, 1],
            [0.1, 0.2, 0.3, 0.4],
            positive_label=1,
            score_semantics="logit",
        )


def test_quantile_calibration_keeps_one_bin_when_all_probabilities_tie() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_calibration

    result = run_roc_calibration(
        [0, 1, 0, 1],
        [0.5, 0.5, 0.5, 0.5],
        positive_label=1,
        score_semantics="probability",
        calibration_method="quantile",
        n_bins=4,
    )["result"]
    assert len(result["bins"]) == 1
    assert result["bins"][0]["count"] == 4


def test_constraint_and_cost_policies_return_candidates_without_selection_claim() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    result = run_roc_curve(
        [0, 1, 0, 1, 1, 0],
        [0.1, 0.8, 0.8, 0.4, 0.4, 0.2],
        positive_label=1,
        constraint_policy={"metric": "sensitivity", "operator": ">=", "value": 1.0},
        cost_policy={"false_positive_cost": 2.0, "false_negative_cost": 1.0},
    )
    evidence = result["result"]["decision_evidence"]
    assert evidence["mode"] == "evidence_only"
    assert evidence["policy"]["constraint"]["metric"] == "sensitivity"
    assert evidence["policy"]["cost"]["false_positive_cost"] == 2.0
    assert evidence["candidates"]
    assert "best_threshold" not in evidence
    assert "causal_claim" not in evidence


def test_threshold_counts_are_monotone_as_threshold_moves_downward() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    result = run_roc_curve(
        [0, 1, 0, 1, 1, 0],
        [0.1, 0.8, 0.8, 0.4, 0.4, 0.2],
        positive_label=1,
    )["result"]
    counts = [point["confusion_counts"] for point in result["threshold_evidence"]]
    assert all(left["tp"] <= right["tp"] for left, right in zip(counts, counts[1:]))
    assert all(left["fp"] <= right["fp"] for left, right in zip(counts, counts[1:]))
    assert all(left["fn"] >= right["fn"] for left, right in zip(counts, counts[1:]))
    assert all(left["tn"] >= right["tn"] for left, right in zip(counts, counts[1:]))


def test_curve_and_classification_metrics_stay_within_probability_bounds() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    result = run_roc_curve(
        [0, 1, 0, 1, 1, 0],
        [0.1, 0.8, 0.8, 0.4, 0.4, 0.2],
        positive_label=1,
        score_semantics="probability",
    )["result"]
    assert 0.0 <= result["auc"] <= 1.0
    assert 0.0 <= result["pr_auc"] <= 1.0
    for point in result["threshold_evidence"]:
        for metric in (
            "sensitivity",
            "specificity",
            "ppv",
            "npv",
            "f1",
            "fpr",
            "tpr",
            "precision",
            "recall",
        ):
            if point[metric] is not None:
                assert 0.0 <= point[metric] <= 1.0


def test_non_tied_label_flip_complements_rank_auc() -> None:
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    y_true = ["n", "p", "n", "p"]
    scores = [0.1, 0.9, 0.4, 0.6]
    positive = run_roc_curve(y_true, scores, positive_label="p")["result"]["auc"]
    flipped = run_roc_curve(y_true, scores, positive_label="n")["result"]["auc"]
    assert positive + flipped == pytest.approx(1.0)


def test_base_r_oracle_checks_rank_auc_threshold_table_and_probability_metrics() -> None:
    if shutil.which("Rscript") is None:
        pytest.skip("Rscript is required for the independent Oracle")
    from workbench.engine.packs.roc_diagnostics import run_roc_curve

    y_true, probabilities = _fixture()
    result = run_roc_curve(
        y_true,
        probabilities,
        positive_label=1,
        score_semantics="probability",
    )["result"]
    # jsonlite is not part of the runtime contract; use base R output tokens.
    r_code = r'''
y <- c(0, 1, 0, 1, 1, 0)
s <- c(0.1, 0.8, 0.8, 0.4, 0.4, 0.2)
pos <- y == 1
r <- rank(s, ties.method = "average")
auc <- (sum(r[pos]) - sum(seq_len(sum(pos)))) / (sum(pos) * sum(!pos))
u <- sort(unique(s), decreasing = TRUE)
tp <- vapply(u, function(t) sum(pos & s >= t), integer(1))
fp <- vapply(u, function(t) sum(!pos & s >= t), integer(1))
fpr <- c(0, fp / sum(!pos), 1)
tpr <- c(0, tp / sum(pos), 1)
trapezoid <- sum(diff(fpr) * (head(tpr, -1) + tail(tpr, -1)) / 2)
brier <- mean((s - y)^2)
ll <- -mean(ifelse(y == 1, log(s), log(1 - s)))
cat(auc, trapezoid, paste(u, collapse=","), paste(tp, collapse=","), paste(fp, collapse=","), brier, ll, sep="|")
'''
    oracle = subprocess.run(
        ["Rscript", "--vanilla", "-e", r_code],
        check=True,
        capture_output=True,
        text=True,
    ).stdout.strip().split("|")
    assert float(oracle[0]) == pytest.approx(result["exact_auc"])
    assert float(oracle[0]) == pytest.approx(result["auc"])
    assert float(oracle[1]) == pytest.approx(result["sampled_roc_auc"])
    assert [float(value) for value in oracle[2].split(",")] == pytest.approx(
        [0.8, 0.4, 0.2, 0.1]
    )
    assert [int(value) for value in oracle[3].split(",")] == [1, 3, 3, 3]
    assert [int(value) for value in oracle[4].split(",")] == [1, 1, 2, 3]
    assert float(oracle[5]) == pytest.approx(result["brier_score"])
    assert float(oracle[6]) == pytest.approx(result["log_loss"])
