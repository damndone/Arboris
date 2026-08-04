from __future__ import annotations

import pandas as pd
import pytest

from workbench.artifacts import read_json
from workbench.econometrics.runner import run_ols
from workbench.engine.stages.estimation import _validate_model_family_weights
from workbench.orchestrator import run_workflow
from workbench.projects import create_project


def _frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "y": [1.0, 2.0, 10.0, 11.0, 12.0, 13.0],
            "x": [0.0, 1.0, 0.0, 1.0, 2.0, 3.0],
            "freq": [1.0, 1.0, 1.0, 8.0, 8.0, 8.0],
            "analysis": [1.0, 1.0, 1.0, 8.0, 8.0, 8.0],
        }
    )


def test_ols_frequency_weight_is_executed_and_changes_estimate() -> None:
    frame = _frame()
    plain, _ = run_ols(frame, y="y", x=["x"], robust=False, model_id="plain")
    weighted, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        model_id="weighted",
        weights={"kind": "frequency", "column": "freq"},
    )

    assert weighted["weights"] == {"kind": "frequency", "column": "freq", "executed": True}
    assert weighted["coefficients"]["x"]["estimate"] != plain["coefficients"]["x"]["estimate"]


def test_ols_all_one_frequency_weight_keeps_unweighted_result() -> None:
    frame = _frame().assign(freq=1.0)
    plain, _ = run_ols(frame, y="y", x=["x"], robust=False, model_id="plain")
    weighted, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        model_id="weighted",
        weights={"kind": "frequency", "column": "freq"},
    )

    assert weighted["coefficients"]["Intercept"]["estimate"] == plain["coefficients"]["Intercept"]["estimate"]
    assert weighted["coefficients"]["x"]["estimate"] == plain["coefficients"]["x"]["estimate"]
    for term in ("Intercept", "x"):
        for field in ("estimate", "std_error", "p_value", "ci_lower", "ci_upper"):
            assert weighted["coefficients"][term][field] == plain["coefficients"][term][field]
    for field in (
        "nobs",
        "r_squared",
        "r_squared_adj",
        "fitted_values",
        "residuals",
        "analysis_sample",
        "covariance_evidence",
        "inference_config",
    ):
        assert weighted[field] == plain[field]


def test_ols_analysis_weight_is_executed_and_changes_estimate() -> None:
    frame = _frame()
    plain, _ = run_ols(frame, y="y", x=["x"], robust=False, model_id="plain")
    weighted, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        model_id="analysis-weighted",
        weights={"kind": "analysis", "column": "analysis"},
    )

    assert weighted["weights"] == {"kind": "analysis", "column": "analysis", "executed": True}
    assert weighted["coefficients"]["x"]["estimate"] != plain["coefficients"]["x"]["estimate"]


def test_ols_analysis_weight_reuses_existing_cluster_covariance_channel() -> None:
    frame = _frame().assign(cluster=["a", "a", "b", "b", "c", "c"])

    weighted, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        model_id="clustered-analysis-weighted",
        cluster_col="cluster",
        covariance="clustered",
        weights={"kind": "analysis", "column": "analysis"},
    )

    assert weighted["weights"] == {"kind": "analysis", "column": "analysis", "executed": True}
    assert weighted["covariance_evidence"]["cluster_variable"] == "cluster"
    assert weighted["covariance_evidence"]["cluster_count"] == 3


def test_weight_admission_reads_declared_model_family_contract() -> None:
    assert _validate_model_family_weights(
        "ols", frequency_weight="freq", analysis_weight="", sampling_weight=""
    ) is None
    with pytest.raises(ValueError, match="MODEL_WEIGHT_UNSUPPORTED"):
        _validate_model_family_weights(
            "logit", frequency_weight="freq", analysis_weight="", sampling_weight=""
        )


def test_undeclared_logit_weight_fails_before_result_artifact(tmp_path) -> None:
    source = tmp_path / "binary.csv"
    pd.DataFrame(
        {
            "y": [index % 2 for index in range(36)],
            "x": [float(index) for index in range(36)],
            "freq": [1.0 if index < 18 else 2.0 for index in range(36)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "undeclared-weight")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="logit",
        y="y",
        x=["x"],
        frequency_weight="freq",
    )

    assert outcome["status"] == "failed"
    run_root = project.root / "runs" / outcome["run_id"]
    errors = read_json(run_root / "errors.json")
    assert errors["issues"][-1]["code"] == "MODEL_WEIGHT_UNSUPPORTED"
    assert not (run_root / "model_results" / "logit_1.json").exists()


def test_ols_sampling_weight_fails_closed_with_cluster_channel_next_step() -> None:
    with pytest.raises(ValueError) as error:
        run_ols(
            _frame(),
            y="y",
            x=["x"],
            robust=False,
            model_id="sampling",
            weights={"kind": "sampling", "column": "freq"},
        )

    assert str(error.value) == (
        "OLS_SAMPLING_WEIGHT_UNSUPPORTED: sampling_weight requires a declared "
        "strata/PSU design; declare strata/PSU through the existing "
        "entity_col + covariance=clustered channel"
    )


def test_workflow_sampling_weight_fails_without_result_and_names_cluster_channel(tmp_path) -> None:
    source = tmp_path / "sampling.csv"
    pd.DataFrame(
        {
            "y": [1.0 + 2.0 * index + (5.0 if index % 3 == 0 else 0.0) for index in range(36)],
            "x": [float(index) for index in range(36)],
            "sample": [1.0 if index < 18 else 2.0 for index in range(36)],
        }
    ).to_csv(source, index=False)
    project = create_project(tmp_path, "sampling-weight")

    outcome = run_workflow(
        project.root,
        [source],
        mode="auto",
        model_type="ols",
        y="y",
        x=["x"],
        sampling_weight="sample",
    )

    assert outcome["status"] in {"failed", "blocked"}
    run_root = project.root / "runs" / outcome["run_id"]
    errors = read_json(run_root / "errors.json")
    issue = errors["issues"][-1]
    assert issue["code"] == "OLS_SAMPLING_WEIGHT_UNSUPPORTED"
    assert "entity_col + covariance=clustered channel" in issue["message"]
    assert not (run_root / "model_results" / "ols_1.json").exists()


def test_ols_frequency_weight_matches_row_expansion_oracle() -> None:
    """A frequency weight means "this row occurred w times".

    The only correct reference is the dataset with each row physically
    repeated w times: coefficients, standard errors, nobs and residual
    degrees of freedom must all agree with that expansion.
    """
    frame = _frame()
    expanded = frame.loc[frame.index.repeat(frame["freq"].astype(int))].reset_index(drop=True)

    oracle, _ = run_ols(expanded, y="y", x=["x"], robust=False, model_id="oracle")
    weighted, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        model_id="weighted",
        weights={"kind": "frequency", "column": "freq"},
    )

    assert weighted["nobs"] == oracle["nobs"] == 27
    for term in ("Intercept", "x"):
        for field in ("estimate", "std_error", "p_value", "ci_lower", "ci_upper"):
            assert weighted["coefficients"][term][field] == pytest.approx(
                oracle["coefficients"][term][field], rel=1e-9, abs=1e-12
            ), f"{term}.{field} diverged from the row-expansion oracle"


def test_ols_frequency_weight_matches_row_expansion_oracle_under_robust_covariance() -> None:
    frame = _frame()
    expanded = frame.loc[frame.index.repeat(frame["freq"].astype(int))].reset_index(drop=True)

    oracle, _ = run_ols(expanded, y="y", x=["x"], robust=True, model_id="oracle")
    weighted, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=True,
        model_id="weighted",
        weights={"kind": "frequency", "column": "freq"},
    )

    for term in ("Intercept", "x"):
        assert weighted["coefficients"][term]["std_error"] == pytest.approx(
            oracle["coefficients"][term]["std_error"], rel=1e-9, abs=1e-12
        )


def test_ols_frequency_weight_rejects_non_integer_counts() -> None:
    frame = _frame()
    frame.loc[0, "freq"] = 2.5

    with pytest.raises(ValueError, match="OLS_FREQUENCY_WEIGHT_NOT_INTEGER"):
        run_ols(
            frame,
            y="y",
            x=["x"],
            robust=False,
            model_id="fractional",
            weights={"kind": "frequency", "column": "freq"},
        )


def test_ols_analysis_weight_keeps_weighted_least_squares_semantics() -> None:
    """analysis_weight must stay WLS: nobs is the row count, not the weight sum."""
    frame = _frame()
    weighted, _ = run_ols(
        frame,
        y="y",
        x=["x"],
        robust=False,
        model_id="analysis",
        weights={"kind": "analysis", "column": "analysis"},
    )

    assert weighted["nobs"] == len(frame)
