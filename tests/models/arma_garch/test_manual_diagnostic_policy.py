from __future__ import annotations

import json
from dataclasses import replace
import subprocess

import numpy as np
import pandas as pd
import pytest

from workbench.contracts.model.arma_garch import ArmaGarchAnalysisContract
from workbench.engine.packs.arma_garch.arma import search_arma_candidates
from workbench.engine.packs.arma_garch.diagnostics import build_mean_diagnostics
from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
from workbench.engine.packs.arma_garch.split import freeze_train_validation_split
from workbench.engine.packs.arma_garch.statistics import ljung_box_results


def _source() -> pd.DataFrame:
    innovations = np.random.default_rng(811).normal(size=160)
    values = np.zeros(160)
    for index in range(1, len(values)):
        values[index] = 0.85 * values[index - 1] + innovations[index]
    return pd.DataFrame({"when": pd.bdate_range("2025-01-01", periods=160), "value": values})


def _contract(selection_mode: str = "manual") -> ArmaGarchAnalysisContract:
    return ArmaGarchAnalysisContract.from_dict({
        "dataset_ref": "dataset:manual-diagnostics",
        "time_column": "when",
        "value_column": "value",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "level",
        "transform_confirmed": True,
        "selection_mode": selection_mode,
        "arma": {"p": 0 if selection_mode == "manual" else None,
                 "q": 0 if selection_mode == "manual" else None,
                 "constant_mode": "exclude", "auto_max_p": 0, "auto_max_q": 0},
        "variance": {"model": "constant_variance" if selection_mode == "manual" else "auto"},
        "estimation_strategy": "sequential",
        "validation": {"validation_n": 3},
    })


def test_manual_order_survives_residual_rejection_with_explicit_lag_warning() -> None:
    contract = _contract()
    prepared = prepare_arma_garch_input(_source(), contract)
    split = freeze_train_validation_split(prepared.transformed_view, contract)
    search = search_arma_candidates(split, contract)

    assert search.selected_candidate_id == "arma-p0-q0-n"
    assert search.blocking_diagnostic is None
    candidate = search.candidates[0]
    assert candidate.failure_code is None
    assert any(row["p_value"] < 0.01 for row in candidate.ljung_box_results)
    assert any("Ljung-Box" in warning and "lag 5" in warning for warning in candidate.warnings)


def test_auto_order_keeps_residual_acceptance_gate() -> None:
    contract = _contract("auto")
    prepared = prepare_arma_garch_input(_source(), contract)
    split = freeze_train_validation_split(prepared.transformed_view, contract)
    search = search_arma_candidates(split, contract)

    assert search.selected_candidate_id is None
    assert search.blocking_diagnostic is not None
    assert search.candidates[0].failure_code == "ARMA_RESIDUAL_AUTOCORRELATION"


@pytest.mark.parametrize(("field", "value", "failure_code"), [
    ("converged", False, "ARMA_NOT_CONVERGED"),
    ("finite_parameters", False, "ARMA_NONFINITE_PARAMETERS"),
    ("stationary", False, "ARMA_NONSTATIONARY"),
    ("invertible", False, "ARMA_NONINVERTIBLE"),
])
def test_manual_selection_keeps_structural_fit_failures_blocking(field, value, failure_code) -> None:
    from workbench.engine.packs.arma_garch.arma import (
        ArmaCandidateSpec, fit_arma_candidate, select_arma_candidate,
    )
    candidate = fit_arma_candidate(_source()["value"].to_numpy(),
                                   ArmaCandidateSpec("manual", 0, 0, False), selection_mode="manual")
    failed = replace(candidate, **{field: value, "failure_code": failure_code})
    assert select_arma_candidate((failed,), selection_mode="manual").selected_candidate_id is None


def test_available_ljung_box_statistics_df_and_p_values_match_r(tmp_path) -> None:
    values = np.random.default_rng(18).normal(size=160)
    data_path = tmp_path / "residuals.csv"
    np.savetxt(data_path, values)
    script = '''
        x <- scan(commandArgs(TRUE)[1], quiet=TRUE)
        for (lag in c(3, 5, 10, 20)) {
            result <- Box.test(x, lag=lag, type="Ljung-Box", fitdf=2)
            cat(sprintf("%d,%.17g,%d,%.17g\\n", lag, result$statistic,
                        result$parameter, result$p.value))
        }
    '''
    oracle = subprocess.run(["Rscript", "--vanilla", "-e", script, str(data_path)],
                            check=True, capture_output=True, text=True, timeout=30)
    references = [row.split(",") for row in oracle.stdout.strip().splitlines()]
    rows = ljung_box_results(values, model_df=2, requested_lags=(3, 5, 10, 20))
    for actual, expected in zip(rows, references, strict=True):
        assert actual["lag"] == int(expected[0])
        assert actual["statistic"] == pytest.approx(float(expected[1]), abs=1e-10)
        assert actual["df"] == int(expected[2])
        assert actual["p_value"] == pytest.approx(float(expected[3]), abs=1e-12)


def test_short_lags_remain_visible_with_unavailable_adjusted_reference() -> None:
    rows = ljung_box_results(_source()["value"].to_numpy(), model_df=10)
    assert [row["lag"] for row in rows] == [5, 10, 20]
    for row in rows[:2]:
        assert row["status"] == "unavailable"
        assert row["p_value"] is None
        assert row["df"] is None
        assert row["reason_code"] == "LJUNG_BOX_NONPOSITIVE_DF"
        assert "model_df" in row["reason"]
    assert rows[2]["status"] == "ok"
    assert rows[2]["df"] == 10
    json.dumps(rows, allow_nan=False)


def test_unavailable_lags_are_not_replaced_with_an_unrequested_test() -> None:
    rows = ljung_box_results(_source()["value"].to_numpy(), model_df=10, requested_lags=(5, 10))
    assert [row["lag"] for row in rows] == [5, 10]
    assert all(row["p_value"] is None for row in rows)


def test_diagnostics_carry_lag_specific_unavailable_warning() -> None:
    values = _source()["value"].to_numpy()
    diagnostics = build_mean_diagnostics(values, values, model_df=10)
    assert any("Ljung-Box" in warning and "lag 5" in warning and "unavailable" in warning
               for warning in diagnostics.warnings)


def test_report_projection_preserves_unavailable_reason_and_mean_warning(tmp_path, monkeypatch) -> None:
    from workbench.engine.packs.arma_garch import deliverables

    warning = "Ljung-Box training mean residual autocorrelation at lag 5."
    values = _source()["value"].to_numpy()
    diagnostics = build_mean_diagnostics(values, values, model_df=10).to_dict()
    monkeypatch.setattr(deliverables, "_artifact_payloads", lambda _root: {
        "ts.report": {"warnings": [warning]}, "ts.final_diagnostics": diagnostics,
    })
    report = deliverables.build_arma_garch_deliverables(tmp_path)["report"]
    assert warning in report["limitations"]
    row = next(row for row in report["diagnostics"] if row["test"].endswith("(lag 5)"))
    assert row["status"] == "unavailable"
    assert "model_df 10" in row["detail"]


def test_agent_vocabulary_requires_manual_diagnostic_warnings_to_be_reported() -> None:
    from workbench.agent.recipes.arma_garch_vocabulary import build_arma_garch_option_vocabulary
    vocabulary = build_arma_garch_option_vocabulary()
    selection_field = next(row for row in vocabulary["fields"] if row["path"] == "selection_mode")
    assert "warnings" in selection_field["description"]
    assert any("diagnostic warnings" in rule for rule in vocabulary["prohibited_claims"])


def test_manual_workflow_persists_warning_in_report_and_agent_view(tmp_path) -> None:
    from workbench.agent.recipes.arma_garch import build_arma_garch_public_result_view
    from workbench.orchestrator import run_workflow
    from workbench.projects import create_project

    source_path = tmp_path / "series.csv"
    _source().to_csv(source_path, index=False)
    project = create_project(tmp_path, "manual-warning")
    outcome = run_workflow(project.root, [source_path], mode="auto", y="value", x=[],
                           model_type="time_series.arma_garch", model_options=_contract().to_dict())
    assert outcome["status"] == "completed"
    run_root = project.root / "runs" / outcome["run_id"]
    index = json.loads((run_root / "artifacts_index.json").read_text())
    artifacts = {item["artifact_id"]: json.loads((run_root / item["path"]).read_text())["payload"]
                 for item in index["artifacts"] if item["artifact_id"].startswith("ts.")}
    report = artifacts["ts.report"]
    assert any("Ljung-Box" in warning and "lag 5" in warning for warning in report["warnings"])
    assert report["acceptance"]["dimensions"]["mean_adequacy"]["status"] == "accepted_with_warnings"
    view = build_arma_garch_public_result_view(artifacts)
    assert view["warnings"] == report["warnings"]
