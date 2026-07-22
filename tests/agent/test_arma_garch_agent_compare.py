from __future__ import annotations

from pathlib import Path

from workbench.agent.recipes.arma_garch import (
    build_arma_garch_public_result_view,
    normalize_arma_garch_recommended_action,
)
from workbench.agent.operations import OperationRegistry
from workbench.analysis_loop.time_series_compare import (
    build_arma_garch_compare_packet,
    read_time_series_artifacts,
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
        "ts.train_validation_split": {
            "analysis_view_hash": "view-hash",
            "split_index": 99,
            "split_timestamp": "2025-01-01",
            "training_row_ids": [f"row-{index}" for index in range(99)],
            "validation_row_ids": [f"row-{index}" for index in range(99, 119)],
            "validation_n": 20,
            "n_train": 99,
            "method": "expanding_window_one_step",
            "refit_every": 1,
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


def test_unrelated_project_peers_use_sample_membership_not_contract_bound_split_hash() -> None:
    source = _artifacts()
    peer = _artifacts(rmse=0.8)
    peer["ts.report"]["reproducibility"]["split_hash"] = "different-contract-split-hash"

    packet = build_arma_garch_compare_packet(
        source_run_id="run-source",
        child_run_id="run-peer",
        source_artifacts=source,
        child_artifacts=peer,
        child_source_run_id=None,
        relation="unrelated",
    )

    assert packet.compare_status == "complete"
    assert "SOURCE_CHILD_LINEAGE_MISMATCH" not in packet.integrity_findings
    assert "SPLIT_HASH_MISMATCH" not in packet.integrity_findings


def test_time_series_compare_separates_sample_identity_from_split_contract() -> None:
    source = _artifacts()
    child = _artifacts(rmse=0.8)
    child["ts.report"]["reproducibility"]["split_hash"] = "different-contract-split-hash"

    packet = build_arma_garch_compare_packet(
        source_run_id="run-source",
        child_run_id="run-child",
        source_artifacts=source,
        child_artifacts=child,
        child_source_run_id="run-source",
    )

    payload = packet.to_dict()
    assert payload["data_diff"]["changed"] is False
    assert payload["data_diff"]["split_contract_changed"] is True
    assert "SPLIT_HASH_MISMATCH" not in packet.integrity_findings


def _seed_time_series_run(project_root: Path, *, origins: int) -> None:
    """A completed ARMA-GARCH run sized like a real one."""

    import json as _json

    run_root = project_root / "runs" / "run-a"
    (run_root / "artifacts" / "time_series").mkdir(parents=True)
    (run_root / "run_manifest.json").write_text(
        _json.dumps(
            {
                "status": "completed",
                "started_at": "2026-07-21T00:00:00+00:00",
                "model_routing": {
                    "requested_model_type": "time_series.arma_garch",
                    "effective_model_type": "time_series.arma_garch",
                },
            }
        ),
        encoding="utf-8",
    )
    (run_root / "run_inputs.json").write_text(
        _json.dumps({"rerun_of": None, "form": {}}), encoding="utf-8"
    )
    (run_root / "node_index.json").write_text(
        _json.dumps({"model:arma_garch_1": {"node_hash": "a" * 64}}), encoding="utf-8"
    )
    (run_root / "graph.json").write_text(
        _json.dumps(
            {
                "schema_version": 3,
                "run_id": "run-a",
                "nodes": {
                    "model:arma_garch_1": {
                        "id": "model:arma_garch_1",
                        "kind": "model",
                        "display_label": "ARMA-GARCH",
                        "created_at": "2026-07-21T00:00:00+00:00",
                        "parent_stage_id": None,
                        "branch_id": "main",
                        "stage": "model",
                    }
                },
                "edges": {},
                "branches": {},
            }
        ),
        encoding="utf-8",
    )
    artifacts = dict(_artifacts())
    comparison = dict(artifacts["ts.arma_vs_garch_comparison"])
    row_ids = [f"source-row:{index:010d}" for index in range(origins)]
    for field in (
        "locked_forecast_origin_row_ids",
        "locked_target_row_ids",
        "comparison_forecast_origin_row_ids",
        "comparison_target_row_ids",
    ):
        comparison[field] = list(row_ids)
    artifacts["ts.arma_vs_garch_comparison"] = comparison
    for artifact_id, payload in artifacts.items():
        (run_root / "artifacts" / "time_series" / f"{artifact_id}.json").write_text(
            _json.dumps(
                {
                    "artifact_id": artifact_id,
                    "metadata": {
                        "run_id": "run-a",
                        "source_run_id": None,
                        "node_id": "model:arma_garch_1",
                    },
                    "payload": payload,
                }
            ),
            encoding="utf-8",
        )


def test_persisted_compare_reader_keeps_the_frozen_split_membership(tmp_path: Path) -> None:
    project_root = tmp_path / "project"
    _seed_time_series_run(project_root, origins=20)

    artifacts, _metadata = read_time_series_artifacts(
        project_root / "runs" / "run-a"
    )

    assert artifacts["ts.train_validation_split"]["training_row_ids"] == [
        f"row-{index}" for index in range(99)
    ]

def test_the_public_view_stays_within_the_agent_tool_budget() -> None:
    """Found by a live DeepSeek turn, not by the deterministic suite.

    On a real 250-origin run the comparison artifact carries four provenance
    row-id lists totalling ~25,000 characters -- three times the whole tool
    budget -- so `inspect_time_series_summary` returned
    `tool_output_budget_exceeded` and the Agent got no summary at all. The
    synthetic fixtures were small enough to hide it. The ids stay in the
    artifact; the view reports how many there were.
    """

    import json

    from workbench.agent.recipes.arma_garch import build_arma_garch_public_result_view

    artifacts = dict(_artifacts())
    comparison = dict(artifacts["ts.arma_vs_garch_comparison"])
    row_ids = [f"source-row:{index:010d}" for index in range(250)]
    for field in (
        "locked_forecast_origin_row_ids",
        "locked_target_row_ids",
        "comparison_forecast_origin_row_ids",
        "comparison_target_row_ids",
    ):
        comparison[field] = list(row_ids)
    artifacts["ts.arma_vs_garch_comparison"] = comparison

    view = build_arma_garch_public_result_view(artifacts)
    serialized = json.dumps(view, ensure_ascii=False, sort_keys=True)

    assert len(serialized) <= 12288, (
        f"public view is {len(serialized)} chars against the 12288 tool budget"
    )
    # The count survives even though the ids do not: the reader still learns
    # the comparison ran over 250 locked common origins.
    assert view["arma_vs_garch"]["locked_common_origins"] == 250
    assert "comparison_row_ids" in view["omitted_sections"]
    for field in ("locked_target_row_ids", "comparison_target_row_ids"):
        assert field not in view["arma_vs_garch"]


def test_wide_candidate_tables_cannot_push_the_view_over_budget() -> None:
    """The third route to the same failure, found by a live DeepSeek turn.

    The candidate tables were bounded by a fixed row count, which cannot bound
    a variable-width payload. On an automatic bounded search the mean and
    volatility tables carried enough per-row detail -- including a library
    DeprecationWarning repeated verbatim on every candidate -- to put the whole
    summary at 14,388 characters, and the Agent again received nothing instead
    of a shortened table.
    """

    import json

    from workbench.agent.recipes.arma_garch import build_arma_garch_public_result_view

    artifacts = dict(_artifacts())
    noise = "x" * 400
    mean_candidates = [
        {
            "candidate_id": f"arma-p{p}-q{q}-n",
            "p": p,
            "q": q,
            "constant": False,
            "nobs": 2521,
            "converged": True,
            "stationary": True,
            "invertible": True,
            "parameter_count": p + q + 1,
            "aic": 17574.227303884865,
            "aicc": 17574.23683904577,
            "bic": 17591.72453666643,
            "failure_code": "ARMA_RESIDUAL_AUTOCORRELATION",
            "warnings": [noise],
        }
        for p in range(5)
        for q in range(5)
    ]
    artifacts["ts.arma_candidates"] = {"candidates": mean_candidates}
    artifacts["ts.volatility_candidates"] = {
        "searches": [
            {
                "mean_candidate_id": "arma-p1-q1-n",
                "candidates": [
                    {
                        "candidate_id": f"variance-arch-p{order}-normal",
                        "variance_model": "arch",
                        "p": order,
                        "converged": True,
                        "parameter_count": order + 1,
                        "aic": 17226.780750940023,
                        "aicc": 17226.790289890738,
                        "bic": 17244.27679348154,
                        "warnings": [noise],
                    }
                    for order in range(1, 11)
                ],
            }
        ]
    }

    view = build_arma_garch_public_result_view(artifacts)
    serialized = json.dumps(view, ensure_ascii=False, sort_keys=True)

    assert len(serialized) <= 12288, (
        f"public view is {len(serialized)} chars against the 12288 tool budget"
    )
    # Shortened, not emptied: the reader still gets candidates to reason about,
    # and is told how many were left in the artifact.
    assert view["mean_candidates"], "the table was emptied rather than shortened"
    assert view["volatility_candidates"]
    assert view["candidate_counts"] == {"mean": 25, "volatility": 10}
    assert view["candidate_rows_omitted"]["mean"] > 0


def test_library_upkeep_warnings_never_reach_a_candidate_record() -> None:
    """statsmodels emits a NumPy DeprecationWarning on every ARIMA fit.

    Captured verbatim it was repeated on each candidate, and it reads to a user
    as though the model had a problem. Convergence and numerical warnings are
    real findings and must survive.
    """

    import warnings

    from workbench.engine.packs.arma_garch.statistics import modelling_warnings

    with warnings.catch_warnings(record=True) as caught:
        warnings.simplefilter("always")
        warnings.warn("Setting the shape on a NumPy array", DeprecationWarning)
        warnings.warn("pandas will change", FutureWarning)
        warnings.warn("Maximum Likelihood optimization failed to converge", UserWarning)
        warnings.warn("Maximum Likelihood optimization failed to converge", UserWarning)
        warnings.warn("overflow encountered in exp", RuntimeWarning)

    assert modelling_warnings(caught) == [
        "Maximum Likelihood optimization failed to converge",
        "overflow encountered in exp",
    ]


def test_the_inspect_tool_response_fits_its_budget_not_just_the_view(
    tmp_path: Path,
) -> None:
    """The mistake that let this reach a live turn twice.

    Measuring `build_arma_garch_public_result_view` is not the same as
    measuring what `inspect_time_series_summary` returns: the tool wraps the
    view in a canonical envelope with lineage, node, and omitted-section
    fields. The first fix brought the view under budget and the tool response
    was still over, so the Agent still got nothing.
    """

    import json

    from workbench.agent.context_tools import (
        InspectTimeSeriesSummaryRequest,
        NodeOperationContextProvider,
    )
    from workbench.agent.operations import OperationRegistry

    project_root = tmp_path / "project"
    _seed_time_series_run(project_root, origins=250)
    provider = NodeOperationContextProvider(project_root)

    payload = provider.inspect_time_series_summary(
        InspectTimeSeriesSummaryRequest(
            request_id="r1",
            owner_run_id="run-a",
            op_node_id="model:arma_garch_1",
            active_head_run_id="run-a",
        )
    )
    serialized = json.dumps(payload, ensure_ascii=False, sort_keys=True)

    budget = next(
        definition.max_output_budget
        for definition in provider.tool_definitions(
            chain_id="chain-a",
            session_id="chain-session",
            operation_registry=OperationRegistry(),
        )
        if definition.tool_id == "inspect_time_series_summary"
    )
    assert budget is not None
    assert len(serialized) <= budget, (
        f"tool response is {len(serialized)} chars against a {budget} budget; "
        "the Agent would receive tool_output_budget_exceeded instead of a summary"
    )
