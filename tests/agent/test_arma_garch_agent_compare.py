from __future__ import annotations

from workbench.agent.recipes.arma_garch import (
    build_arma_garch_public_result_view,
    normalize_arma_garch_recommended_action,
)
from workbench.agent.operations import OperationRegistry
from workbench.analysis_loop.time_series_compare import (
    build_arma_garch_compare_packet,
)


def _contract(*, distribution: str = "normal") -> dict[str, object]:
    return {
        "pack_id": "time_series.arma_garch",
        "contract_version": "1.0",
        "dataset_ref": "upload:series.csv",
        "time_column": "date",
        "value_column": "value",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "level",
        "transform_confirmed": True,
        "analysis_goal": "balanced",
        "selection_mode": "auto",
        "arma": {
            "p": None,
            "q": None,
            "constant_mode": "auto",
            "auto_max_p": 3,
            "auto_max_q": 3,
            "auto_max_total_order": 4,
        },
        "variance": {
            "model": "auto",
            "arch_p": None,
            "garch_p": None,
            "garch_q": None,
            "auto_arch_max_p": 10,
            "include_garch_1_1": True,
        },
        "estimation_strategy": "auto",
        "innovation_distribution": distribution,
        "validation": {
            "method": "expanding_window_one_step",
            "validation_n": 20,
            "refit_every": 1,
            "selection_repeated_during_validation": False,
        },
        "forecast": {"horizon": 1, "interval_level": 0.95, "lower_quantile": 0.05},
        "random_seed": 0,
    }


def _artifacts(*, distribution: str = "normal", rmse: float = 1.2) -> dict[str, object]:
    contract = _contract(distribution=distribution)
    return {
        "ts.analysis_contract": contract,
        "ts.report": {
            "answer": "Selected arma_1_1 with GARCH(1,1).",
            "sample": {"source_n": 120, "effective_n": 119, "training_n": 99, "validation_n": 20},
            "acceptance": {"overall_status": "accepted_with_warnings"},
            "warnings": ["NORMALITY_REJECTED"],
            "reproducibility": {
                "contract_hash": "contract-hash",
                "analysis_view_hash": "view-hash",
                "split_hash": "split-hash",
            },
        },
        "ts.arma_candidates": {
            "candidates": [
                {
                    "candidate_id": f"arma_{index}",
                    "p": index % 3,
                    "q": index % 2,
                    "aicc": float(index),
                    "bic": float(index + 1),
                    "parameter_count": index + 1,
                    "converged": True,
                    "failure_code": None,
                    "parameters": {"ar.L1": 0.5},
                    "residuals": [99.0],
                }
                for index in range(10)
            ]
        },
        "ts.volatility_candidates": {
            "searches": [{"candidates": [{"candidate_id": "garch_1_1", "display_name": "GARCH(1,1)", "aicc": 10.0, "bic": 11.0, "converged": True, "failure_code": None}]}]
        },
        "ts.final_model": {
            "validation_fit": {"resolved_strategy": "sequential", "joint_likelihood": False},
            "acceptance": {"overall_status": "accepted_with_warnings"},
        },
        "ts.parameters": {"mean_candidate": {"ar.L1": 0.5}, "selected_variance_candidate": {"omega": 0.1, "alpha[1]": 0.1, "beta[1]": 0.8}},
        "ts.final_diagnostics": {"normality": {"status": "ok", "p_value": 0.001}, "arch_lm": {"status": "ok", "p_value": 0.2}, "qq_data": [{"observed": 99.0}]},
        "ts.forecast_metrics": {"validation_n": 20, "successful_forecast_n": 20, "rmse": rmse, "pinball_loss": 0.2, "interval_coverage": 0.9},
        "ts.arma_vs_garch_comparison": {"comparison_validation_n": 20, "arma_garch": {"rmse": rmse}, "arma_only": {"rmse": 1.3}},
        "ts.artifact_manifest": {"status": "complete", "artifact_count_before_manifest": 30},
        "ts.conditional_series": {"volatility": [99.0] * 120},
    }


def test_agent_view_is_bounded_and_does_not_expose_raw_series() -> None:
    view = build_arma_garch_public_result_view(_artifacts())

    assert view["available"] is True
    assert view["candidate_counts"] == {"mean": 10, "volatility": 1}
    assert len(view["mean_candidates"]) == 8
    assert view["candidate_rows_omitted"] == {"mean": 2, "volatility": 0}
    assert "residuals" not in view["mean_candidates"][0]
    assert view["conditional_series"] == {"available": True, "observation_count": 120}
    assert "qq_data" not in view["diagnostics"]


def test_agent_view_exposes_terminal_diagnostic_recovery_without_report() -> None:
    artifacts = {
        "ts.analysis_contract": _contract(),
        "ts.artifact_manifest": {
            "status": "blocked",
            "terminal_code": "LOG_REQUIRES_POSITIVE_VALUES",
            "complete": False,
            "diagnostic": {
                "severity": "blocking",
                "code": "LOG_REQUIRES_POSITIVE_VALUES",
                "message": "Log transforms require positive values.",
                "evidence": {"nonpositive_count": 2},
                "impact": "The confirmed transform cannot run.",
                "recommended_actions": [
                    {
                        "operation": "model.rerun",
                        "patch": {"transform": "level", "transform_confirmed": True},
                    }
                ],
            },
        },
    }

    view = build_arma_garch_public_result_view(artifacts)

    assert view["available"] is True
    assert view["terminal_code"] == "LOG_REQUIRES_POSITIVE_VALUES"
    assert view["recommended_actions"][0]["changes"] == {
        "model_options": {"transform": "level", "transform_confirmed": True}
    }


def test_recommended_action_becomes_existing_one_level_model_options_patch() -> None:
    action = normalize_arma_garch_recommended_action(
        contract=_contract(),
        action={
            "operation": "model.rerun",
            "patch": {"arma": {"q": 0}, "estimation_strategy": "joint"},
        },
    )

    assert action["operation"] == "model.rerun"
    assert action["required_confirmation"] is True
    changes = action["changes"]
    assert set(changes) == {"model_options"}
    assert changes["model_options"]["estimation_strategy"] == "joint"
    assert changes["model_options"]["arma"] == {
        **_contract()["arma"],
        "p": 0,
        "q": 0,
    }
    assert changes["model_options"]["selection_mode"] == "manual"
    assert changes["model_options"]["variance"]["model"] == "garch"
    OperationRegistry().require("model.rerun", "v1").validate(
        target={
            "run_id": "run-source",
            "node_ref": "model:arma_garch_1",
            "node_hash": "node-hash",
            "forest_node_key": "forest-key",
        },
        preconditions={
            "context_version": "v1",
            "context_fingerprint": "context-hash",
            "active_head_run_id": "run-source",
            "owner_resolution": "exact",
        },
        changes=changes,
    )


def test_graph_fork_recommendation_uses_existing_reason_only_contract() -> None:
    action = normalize_arma_garch_recommended_action(
        contract=_contract(),
        action={
            "operation": "graph.fork",
            "purpose": "review_and_confirm_alternative_transform",
            "reason": "Review an eligible transform.",
        },
    )

    assert action["changes"] == {"reason": "Review an eligible transform."}
    assert action["required_confirmation"] is True
    OperationRegistry().require("graph.fork", "v1").validate(
        target={
            "run_id": "run-source",
            "node_ref": "model:arma_garch_1",
            "node_hash": "node-hash",
            "forest_node_key": "forest-key",
            "source_session_entry_id": "entry-1",
        },
        preconditions={
            "context_version": "v1",
            "context_fingerprint": "context-hash",
            "active_head_run_id": "run-source",
            "owner_resolution": "exact",
        },
        changes=action["changes"],
    )


def test_time_series_compare_reuses_four_layer_compare_packet() -> None:
    packet = build_arma_garch_compare_packet(
        source_run_id="run-source",
        child_run_id="run-child",
        source_artifacts=_artifacts(rmse=1.2),
        child_artifacts=_artifacts(distribution="student_t", rmse=1.0),
        child_source_run_id="run-source",
    )

    payload = packet.to_dict()
    assert packet.compare_status == "complete"
    assert payload["data_diff"]["sample"]["changed"] is False
    assert payload["parameter_diff"]["innovation_distribution"] == {
        "before": "normal",
        "after": "student_t",
        "changed": True,
    }
    assert payload["result_diff"]["forecast_metrics"]["fields"]["rmse"]["changed"] is True
    assert payload["conclusion_diff"]["classification"] == "COMPARABLE_WITH_NO_AUTOMATIC_WINNER"


def test_time_series_compare_fails_closed_on_lineage_mismatch() -> None:
    packet = build_arma_garch_compare_packet(
        source_run_id="run-source",
        child_run_id="run-child",
        source_artifacts=_artifacts(),
        child_artifacts=_artifacts(),
        child_source_run_id="another-source",
    )

    assert packet.compare_status == "blocked_by_integrity"
    assert "SOURCE_CHILD_LINEAGE_MISMATCH" in packet.integrity_findings
    assert packet.conclusion_diff["classification"] is None


def test_time_series_compare_fails_closed_when_manifest_claims_missing_metrics() -> None:
    child = _artifacts()
    child.pop("ts.forecast_metrics")

    packet = build_arma_garch_compare_packet(
        source_run_id="run-source",
        child_run_id="run-child",
        source_artifacts=_artifacts(),
        child_artifacts=child,
        child_source_run_id="run-source",
    )

    assert packet.compare_status == "blocked_by_integrity"
    assert "CHILD_FORECAST_METRICS_MISSING" in packet.integrity_findings
    assert packet.conclusion_diff["more_trustworthy"] is None


def test_time_series_compare_does_not_rank_runs_on_changed_samples() -> None:
    child = _artifacts(rmse=0.8)
    child["ts.report"]["sample"]["validation_n"] = 10

    packet = build_arma_garch_compare_packet(
        source_run_id="run-source",
        child_run_id="run-child",
        source_artifacts=_artifacts(),
        child_artifacts=child,
        child_source_run_id="run-source",
    )

    assert packet.compare_status == "blocked_by_integrity"
    assert "SAMPLE_MISMATCH" in packet.integrity_findings
    assert packet.conclusion_diff["classification"] is None
