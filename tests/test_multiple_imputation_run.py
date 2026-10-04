"""v1.8.10 step 5: multiple imputation from request to pooled result.

`test_multiple_imputation_pool.py` checks the pooling against mice::pool on R's
completed datasets. This file checks the run: m datasets are drawn and
recorded, each is fitted by the family's own handler, the pooled packet equals
the pooling of those fits, single-dataset figures are not shown as the pooled
model's, and every unsupported combination is refused with its reason.
"""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from workbench.agent.workflow_contracts import (
    OperationValidationError,
    genesis_run_params,
    validate_model_genesis_spec,
)
from workbench.artifacts import read_json
from workbench.combinators import pool_kernels
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.lineage.incremental import _mice_requested
from workbench.orchestrator import run_workflow
from workbench.postestimation import PostestimationRefusal
from workbench.postestimation.registry import run_operation
from workbench.projects import create_project

DATA = Path(__file__).parent / "fixtures" / "multiple_imputation" / "data.csv"
X = ["x1", "x2", "x3"]


def _run(tmp_path: Path, name: str, *, model_type: str = "ols", y: str = "y", m: int = 5, source: Path = DATA, **extra):
    project = create_project(tmp_path, name)
    result = run_workflow(
        project.root, [source], mode="auto", model_type=model_type, y=y, x=X,
        imputation={"method": "mice", "m": m}, **extra,
    )
    return result, project.root / "runs" / result["run_id"]


@pytest.fixture(scope="module")
def pooled_run(tmp_path_factory):
    return _run(tmp_path_factory.mktemp("mi-run"), "pooled")


def test_m_datasets_are_drawn_recorded_and_all_read_by_the_model(pooled_run) -> None:
    result, run_root = pooled_run
    assert result["status"] == "completed"
    summary = read_json(run_root / "imputation_summary.json")
    datasets = [f"imputed_dataset_{index:04d}" for index in range(1, 6)]
    assert summary["mode"] == "multiple_imputation" and summary["persisted_datasets"] == 5
    assert summary["output_artifacts"] == datasets
    assert summary["pooled_estimates"] is True
    manifest = read_json(run_root / "imputation" / "mice_manifest.json")
    assert [item["artifact_id"] for item in manifest["datasets"]] == datasets
    records = {item["artifact_id"]: item for item in read_json(run_root / "artifacts_index.json")["artifacts"]}
    assert records["ols_1"]["inputs"] == datasets
    assert records["rubin_pool_ols_1"]["inputs"] == datasets
    assert "imputed_dataset" not in records


def test_the_pooled_packet_is_the_pooling_of_fits_on_its_own_datasets(pooled_run, tmp_path) -> None:
    """Refit each persisted dataset as an ordinary run and pool the kernels:
    the stage must agree. With the R comparison this chains the run to mice."""
    _, run_root = pooled_run
    kernels = []
    for index in range(1, 6):
        frame = pd.read_parquet(run_root / "processed" / f"imputed_dataset_{index:04d}.parquet")
        source = tmp_path / f"imputed_{index}.csv"
        frame.to_csv(source, index=False)
        project = create_project(tmp_path, f"refit-{index}")
        run_workflow(project.root, [source], mode="auto", model_type="ols", y="y", x=X)
        refit_root = next((project.root / "runs").iterdir())
        kernels.append(read_json(refit_root / kernel_relative_path("ols_1")))
    expected = pool_kernels(kernels)
    packet = read_json(run_root / "model_results" / "ols_1.json")
    for term, entry in packet["coefficients"].items():
        for field in ("estimate", "std_error", "p_value", "ci_lower", "ci_upper", "df", "fmi", "riv"):
            assert entry[field] == pytest.approx(expected["terms"][term][field], rel=1e-10), (term, field)
    assert packet["multiple_imputation"]["m"] == 5
    assert packet["multiple_imputation"]["covariance_estimator"] == "HC1"
    assert any(entry["fmi"] > 0 for entry in packet["coefficients"].values())


def test_single_dataset_figures_are_not_shown_as_the_pooled_models(pooled_run) -> None:
    _, run_root = pooled_run
    packet = read_json(run_root / "model_results" / "ols_1.json")
    for field in ("r_squared", "r_squared_adj", "fitted_values", "residuals", "df_resid", "analysis_sample"):
        assert field not in packet, field
    assert packet["covariance_evidence"]["df_method"] == "barnard_rubin"
    assert packet["covariance_evidence"]["effective_df"] is None
    diagnostics = read_json(run_root / "model_results" / "diagnostics_ols_1.json")
    assert diagnostics["status"] == "unavailable"
    assert "pools m = 5" in diagnostics["residual_diagnostics_withheld"]
    report = (run_root / "reports" / "report.html").read_text()
    assert "m = 5 imputed datasets" in report and "Barnard–Rubin" in report


def test_a_joint_test_on_the_pooled_result_is_refused_with_the_reason(pooled_run) -> None:
    _, run_root = pooled_run
    kernel = read_json(run_root / kernel_relative_path("ols_1"))
    with pytest.raises(PostestimationRefusal) as caught:
        run_operation("wald", [kernel], {"constraints": [{"terms": {"x1": 1}, "value": 0},
                                                         {"terms": {"x2": 1}, "value": 0}]})
    assert caught.value.code == "INTERFACE_UNAVAILABLE"
    assert "D1" in caught.value.message and "m = 5" in caught.value.message


def test_a_family_not_validated_for_pooling_fails_after_one_fit(tmp_path) -> None:
    result, run_root = _run(tmp_path, "probit", model_type="probit", y="yb")
    assert result["status"] == "failed"
    issue = read_json(run_root / "errors.json")["issues"][-1]
    assert issue["code"] == "MI_NOT_YET_VALIDATED"
    assert "ols with covariance unadjusted, robust or clustered" in issue["message"]
    assert not (run_root / "model_results" / "probit_1.json").exists()


def test_a_sampling_design_is_refused_before_anything_is_imputed(tmp_path) -> None:
    frame = pd.read_csv(DATA)
    frame["w"] = 1.0 + (frame.index % 3)
    frame["stratum"] = frame.index % 4
    source = tmp_path / "survey.csv"
    frame.to_csv(source, index=False)
    result, run_root = _run(tmp_path, "survey", source=source, sampling_weight="w",
                            survey_strata_col="stratum", survey_psu_col="g")
    assert result["status"] == "blocked"
    assert read_json(run_root / "errors.json")["issues"][0]["code"] == "MI_WITH_SURVEY_DESIGN"
    assert not list((run_root / "processed").glob("imputed_dataset*"))


def test_by_group_with_multiple_imputation_is_refused_not_silently_dropped(tmp_path) -> None:
    """v1.8.10 evaluation A03: the run pooled and dropped the grouping without a word."""
    result, run_root = _run(tmp_path, "mi-by", by_group={"column": "g"})
    assert result["status"] == "blocked"
    issue = read_json(run_root / "errors.json")["issues"][0]
    assert issue["code"] == "MI_WITH_BY_GROUP" and "separately" in issue["message"]
    assert not list((run_root / "processed").glob("imputed_dataset*"))
    assert not (run_root / "model_results" / "collections" / "by_group.json").exists()


def test_a_model_column_that_cannot_be_imputed_blocks_the_run(tmp_path) -> None:
    frame = pd.read_csv(DATA)
    frame.loc[frame.index % 2 == 0, "x3"] = np.nan  # 50% missing: above the threshold
    source = tmp_path / "sparse.csv"
    frame.to_csv(source, index=False)
    result, run_root = _run(tmp_path, "sparse", source=source)
    assert result["status"] == "blocked"
    issue = read_json(run_root / "errors.json")["issues"][0]
    assert issue["code"] == "MI_IMPUTATION_FAILED"
    assert "x3 has missing values" in issue["message"]
    assert not list((run_root / "processed").glob("imputed_dataset*"))


def test_single_imputation_keeps_its_one_dataset_and_says_what_it_omits(tmp_path) -> None:
    result, run_root = _run(tmp_path, "single", m=1)
    assert result["status"] == "completed"
    summary = read_json(run_root / "imputation_summary.json")
    assert summary["output_artifact"] == "imputed_dataset" and summary["pooled_estimates"] is False
    assert any("standard errors do not reflect" in warning for warning in summary["warnings"])
    assert "multiple_imputation" not in read_json(run_root / "model_results" / "ols_1.json")


def test_only_single_imputation_is_served_from_the_cache() -> None:
    assert _mice_requested({"imputation": {"method": "mice", "m": 1}}, {})
    assert not _mice_requested({"imputation": {"method": "mice", "m": 5}}, {})
    assert not _mice_requested({}, {"imputation_method": "mice", "imputation_m": 5})


def _genesis(family: str, **extra) -> dict:
    return {"model_family": family, "branches": [{"branch_id": "b1", "outcome": "y", "predictors": X}], **extra}


def test_the_agent_requests_it_on_model_genesis_and_it_travels_with_the_run() -> None:
    validate_model_genesis_spec(_genesis("ols", multiple_imputations=5))
    assert json.loads(genesis_run_params(_genesis("ols", multiple_imputations=5))["imputation"]) == {
        "method": "mice", "m": 5,
    }
    assert "imputation" not in genesis_run_params(_genesis("ols"))


@pytest.mark.parametrize(
    ("spec", "message"),
    [
        (_genesis("probit", multiple_imputations=5), "not offered for probit"),
        (_genesis("ols", multiple_imputations=1), "from 2 to 100"),
        (_genesis("ols", multiple_imputations=5, sampling_weight="w", survey_psu_col="g"), "sampling design"),
    ],
)
def test_the_agent_is_told_at_planning_time_what_is_not_offered(spec, message) -> None:
    with pytest.raises(OperationValidationError, match=message):
        validate_model_genesis_spec(spec)



def test_the_dataset_preparation_step_points_to_model_genesis_for_pooling() -> None:
    from workbench.agent.workflow_capability_registry import workflow_capability_registry

    operation = workflow_capability_registry().require("imputation.mice")
    with pytest.raises(ValueError, match="multiple_imputations on model.genesis"):
        operation.validate({
            "operation_id": operation.operation_id, "input_mode": "frame",
            "column_bindings": {"columns": ["x1", "x2"]}, "options": {"m": 5},
        })


def test_any_figure_that_differs_between_the_fits_is_left_out_and_named(tmp_path) -> None:
    """No list per family: logit's odds ratios and marginal effects come from
    one dataset each, so they are dropped and named, like R² for OLS."""
    result, run_root = _run(tmp_path, "logit", model_type="logit", y="yb")
    assert result["status"] == "completed"
    packet = read_json(run_root / "model_results" / "logit_1.json")
    omitted = packet["multiple_imputation"]["omitted_single_dataset_fields"]
    for field in ("odds_ratios", "marginal_effects", "pseudo_r2", "llf"):
        assert field in omitted and field not in packet
    assert packet["multiple_imputation"]["dfcom"] is None  # z-based fit: large-sample dfcom
    assert all(entry["df"] is not None for entry in packet["coefficients"].values())


def test_every_agent_reading_of_the_result_says_it_is_pooled(pooled_run) -> None:
    """Browser acceptance found the Global Agent reading the project coefficient
    tool, not the result summary, and unable to tell the figures were pooled."""
    from workbench.agent.context_tools import _bounded_persisted_model_facts, _public_requested_model_coefficients
    from workbench.orchestrator import _model_summary

    _, run_root = pooled_run
    packet = read_json(run_root / "model_results" / "ols_1.json")
    project_view = _public_requested_model_coefficients(run_id="r", result=packet, requested_terms=("x1", "x2"))
    summary_view = _bounded_persisted_model_facts([packet], run_root=run_root)[0]
    for view in (project_view, summary_view):
        block = view["multiple_imputation"]
        assert block["m"] == 5 and "D1" in block["post_estimation"]
        assert {"df", "fmi"} <= set(view["coefficients"][0])
        # A pooled result has no R-squared; not even a null field (evaluation A04).
        assert "r_squared" not in view and "r_squared_adj" not in view
    label = _model_summary("ols_robust", packet, robust_se_dp=None, exposure_col=None, fallback_n=0)
    assert label.endswith("pooled from m = 5 imputations)")
