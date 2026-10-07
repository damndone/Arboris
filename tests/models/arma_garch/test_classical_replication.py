"""Classical full-sample results and strictly prefix-only rolling refits."""

from __future__ import annotations

import json
from pathlib import Path
import subprocess

import numpy as np
import pandas as pd
import pytest

from workbench.contracts.model.arma_garch import (
    ArmaGarchAnalysisContract, ArmaGarchContractError,
)
from workbench.engine.packs.arma_garch.input import prepare_arma_garch_input
from workbench.engine.packs.arma_garch.split import freeze_train_validation_split
from workbench.engine.packs.arma_garch.arma import search_arma_candidates
from workbench.engine.packs.arma_garch.transforms import TRANSFORMED_VALUE_COLUMN


def _options(mode="classical_replication", *, tail=4, refit=1):
    return {
        "dataset_ref": "dataset:classic",
        "time_column": "when", "value_column": "value",
        "time_index_semantics": "business_or_trading_observations",
        "transform": "level", "transform_confirmed": True,
        "selection_mode": "manual",
        "arma": {"p": 0, "q": 0, "constant_mode": "exclude"},
        "variance": {"model": "constant_variance"},
        "estimation_strategy": "sequential",
        "validation": {"evaluation_mode": mode, "validation_n": tail, "refit_every": refit},
    }


def _source(n=120):
    return pd.DataFrame({
        "when": pd.bdate_range("2025-01-01", periods=n),
        "value": np.random.default_rng(181103).normal(size=n),
    })


class _Recorder:
    def record_stage(self, *args, **kwargs):
        pass

    def record_edge(self, *args, **kwargs):
        pass


def _run(tmp_path, source, mode="classical_replication", *, p=0):
    from workbench.engine.context import DataHandle, ModelingContext, RunEnv
    from workbench.engine.packs.arma_garch.runner import fit_from_context

    tmp_path.mkdir(parents=True)
    (tmp_path / "artifacts_index.json").write_text('{"artifacts": []}')
    ctx = ModelingContext(
        data=DataHandle.of(source.copy(), artifact_id="cleaned_dataset", provenance=("source.csv",)),
        y_col="value", x_cols=[], y_type="continuous",
        requested_model_type="time_series.arma_garch",
    )
    options = _options(mode)
    options["arma"]["p"] = p
    ctx.artifacts.update({"_model_options": options, "_frames": {"source.csv": source}})
    _, result, _ = fit_from_context(ctx, RunEnv(run_root=tmp_path, run_id=tmp_path.name, recorder=_Recorder()))
    artifacts = {
        path.stem: json.loads(path.read_text())["payload"]
        for path in (tmp_path / "artifacts" / "time_series").glob("ts.*.json")
    }
    return result, artifacts


def test_classic_contract_rejects_skipped_refits_and_unknown_scope():
    with pytest.raises(ArmaGarchContractError, match="refit_every must be 1"):
        ArmaGarchAnalysisContract.from_dict(_options(refit=2))
    with pytest.raises(ArmaGarchContractError):
        ArmaGarchAnalysisContract.from_dict(_options("unknown"))
    default = _options()
    default["validation"].pop("evaluation_mode")
    assert ArmaGarchAnalysisContract.from_dict(default).validation.evaluation_mode == "train_validation"


@pytest.mark.parametrize("mode, expected_n", [("train_validation", 116), ("classical_replication", 120)])
def test_estimation_scope_is_frozen_distinct_from_tail_membership(mode, expected_n):
    contract = ArmaGarchAnalysisContract.from_dict(_options(mode))
    prepared = prepare_arma_garch_input(_source(), contract)
    split = freeze_train_validation_split(prepared.transformed_view, contract)
    assert split.n_train == 116
    assert len(split.estimation_view) == expected_n
    assert len(split.estimation_row_ids) == expected_n
    assert set(split.training_row_ids).isdisjoint(split.validation_row_ids)
    exposed = split.estimation_view
    exposed.loc[0, TRANSFORMED_VALUE_COLUMN] = 999999
    assert split.estimation_view.loc[0, TRANSFORMED_VALUE_COLUMN] != 999999
    search = search_arma_candidates(split, contract)
    assert search.candidates[0].nobs == expected_n


def test_classic_workflow_aligns_all_full_sample_outputs_and_agent_evidence(tmp_path):
    from workbench.agent.recipes.arma_garch import build_arma_garch_public_result_view
    from workbench.engine.packs.arma_garch.deliverables import build_arma_garch_deliverables

    source = _source()
    before = source.copy()
    result, artifacts = _run(tmp_path / "classic", source)
    assert result["nobs"] == 120
    sample = artifacts["ts.report"]["sample"]
    assert sample["estimation_n"] == 120
    assert sample["training_n"] == 116
    assert sample["evaluation_mode"] == "classical_replication"
    assert sample["validation_data_role"] == "retrospective_tail_evaluation"
    assert artifacts["ts.arma_selection"]["candidate_selection_used_validation"] is True
    assert artifacts["ts.volatility_selection"]["candidate_selection_used_validation"] is True
    assert "in_sample_fit" in artifacts["ts.final_model"]
    assert "validation_fit" not in artifacts["ts.final_model"]
    assert len(artifacts["ts.conditional_series"]["variance"]) == 120
    for name in ("conditional_variance", "conditional_volatility",
                 "standardized_residual_series", "in_sample_interval_comparison"):
        rows = artifacts[f"ts.chart.{name}"]["rows"]
        assert len(rows) == 120
        assert rows[-1]["row_id"] == artifacts["ts.analysis_view_manifest"]["row_ids"][-1]
    assert all(row["fit_method"] == "refit" for row in artifacts["ts.rolling_forecasts"]["rows"])
    assert artifacts["ts.rolling_forecasts"]["frozen_spec"]["evaluation_mode"] == "classical_replication"
    assert any("retrospective" in item for item in artifacts["ts.report"]["warnings"])
    view = build_arma_garch_public_result_view(artifacts)
    assert view["sample"] == sample
    assert view["model_result"]["fit_scope"] == "full_sample"
    assert view["model_result"]["in_sample_fit"]["resolved_strategy"] == "sequential_arma_garch"
    delivery = build_arma_garch_deliverables(tmp_path / "classic")["report"]
    assert any(row["field"] == "Evaluation mode" and row["value"] == "classical_replication"
               for row in delivery["overview"])
    pd.testing.assert_frame_equal(source, before)


@pytest.mark.parametrize("p", [0, 1])
def test_future_tail_changes_full_fit_but_never_first_origin_forecast(tmp_path, p):
    source = _source()
    changed = source.copy()
    changed.loc[116:, "value"] += 8.0
    _, original = _run(tmp_path / "original", source, p=p)
    _, perturbed = _run(tmp_path / "perturbed", changed, p=p)
    assert original["ts.parameters"] != perturbed["ts.parameters"]
    first = original["ts.rolling_forecasts"]["rows"][0]
    changed_first = perturbed["ts.rolling_forecasts"]["rows"][0]
    assert first["conditional_mean"] == changed_first["conditional_mean"]
    assert first["conditional_variance"] == changed_first["conditional_variance"]
    assert first["upper_bound"] == changed_first["upper_bound"]


def test_full_fit_and_each_rolling_origin_match_live_r(tmp_path):
    source = _source()
    _, artifacts = _run(tmp_path / "oracle-run", source)
    data = tmp_path / "values.csv"
    source[["value"]].to_csv(data, index=False)
    script = tmp_path / "oracle.R"
    script.write_text("""
args <- commandArgs(trailingOnly=TRUE)
x <- read.csv(args[1])$value
emit <- function(k,v) cat(k, format(v,digits=17,scientific=TRUE),sep="\t",fill=TRUE)
full <- arima(x,order=c(0,0,0),include.mean=FALSE,method="ML")
emit("variance",full$sigma2)
emit("ll",as.numeric(logLik(full)))
emit("aic",AIC(full))
for (lag in c(5,10,20)) {
  lb <- Box.test(residuals(full),lag=lag,type="Ljung-Box",fitdf=0)
  emit(paste0("q",lag),as.numeric(lb$statistic)); emit(paste0("p",lag),lb$p.value)
}
means <- variances <- lowers <- uppers <- numeric()
for (i in (length(x)-3):length(x)) {
  fit <- arima(x[seq_len(i-1)],order=c(0,0,0),include.mean=FALSE,method="ML")
  pr <- predict(fit,n.ahead=1)
  mu <- as.numeric(pr$pred); variance <- as.numeric(pr$se)^2
  emit(paste0("mu",i),mu); emit(paste0("var",i),variance)
  emit(paste0("lo",i),mu+qnorm(.025)*sqrt(variance))
  emit(paste0("hi",i),mu+qnorm(.975)*sqrt(variance))
  means <- c(means,mu); variances <- c(variances,variance)
}
observed <- tail(x,4)
emit("mae",mean(abs(observed-means))); emit("rmse",sqrt(mean((observed-means)^2)))
emit("width",mean(2*qnorm(.975)*sqrt(variances)))
""")
    completed = subprocess.run(["Rscript", "--vanilla", str(script), str(data)],
                               check=True, text=True, capture_output=True, timeout=30)
    oracle = dict((key, float(value)) for key, value in
                  (line.split() for line in completed.stdout.splitlines()))
    differences = {}
    fit = artifacts["ts.final_model"]["in_sample_fit"]
    assert fit["variance_stage"]["parameters"]["sigma2"] == pytest.approx(oracle["variance"], abs=1e-10)
    candidate = artifacts["ts.arma_candidates"]["candidates"][0]
    assert candidate["log_likelihood"] == pytest.approx(oracle["ll"], abs=1e-7)
    assert candidate["aic"] == pytest.approx(oracle["aic"], abs=2e-7)
    differences["full_variance"] = abs(fit["variance_stage"]["parameters"]["sigma2"] - oracle["variance"])
    differences["full_ll"] = abs(candidate["log_likelihood"] - oracle["ll"])
    differences["full_aic"] = abs(candidate["aic"] - oracle["aic"])
    for row in artifacts["ts.final_diagnostics"]["ljung_box"]:
        assert row["statistic"] == pytest.approx(oracle[f'q{row["lag"]}'], abs=1e-10)
        assert row["p_value"] == pytest.approx(oracle[f'p{row["lag"]}'], abs=1e-12)
    for index, row in enumerate(artifacts["ts.rolling_forecasts"]["rows"], start=117):
        for field, key in (("conditional_mean","mu"), ("conditional_variance","var"),
                           ("lower_bound","lo"), ("upper_bound","hi")):
            assert row[field] == pytest.approx(oracle[f"{key}{index}"], abs=1e-8)
            differences[f"{field}_{index}"] = abs(row[field] - oracle[f"{key}{index}"])
    metrics = artifacts["ts.forecast_metrics"]
    for field, key in (("mae","mae"), ("rmse","rmse"), ("average_interval_width","width")):
        assert metrics[field] == pytest.approx(oracle[key], abs=1e-8)
        differences[field] = abs(metrics[field] - oracle[key])
    (tmp_path / "r_classical_comparison.json").write_text(json.dumps({
        "oracle": oracle, "differences": differences,
        "largest_absolute_difference": max(differences.values()),
        "specification": "ARMA(0,0), zero mean, constant variance, N=120, tail=4",
    }, indent=2))



def test_classic_ar1_estimation_and_rolling_means_match_r(tmp_path):
    source = _source(160)
    values = source["value"].to_numpy().copy()
    for index in range(1, len(values)):
        values[index] += 0.65 * values[index - 1]
    source["value"] = values
    _, artifacts = _run(tmp_path / "ar1-run", source, p=1)
    data = tmp_path / "ar1.csv"
    source[["value"]].to_csv(data, index=False)
    script = tmp_path / "ar1.R"
    script.write_text("""
x <- read.csv(commandArgs(trailingOnly=TRUE)[1])$value
emit <- function(k,v) cat(k,format(v,digits=17,scientific=TRUE),sep="\t",fill=TRUE)
full <- arima(x,order=c(1,0,0),include.mean=FALSE,method="ML")
emit("ar",coef(full)[1]); emit("ll",as.numeric(logLik(full))); emit("aic",AIC(full))
for (i in (length(x)-3):length(x)) {
  fit <- arima(x[seq_len(i-1)],order=c(1,0,0),include.mean=FALSE,method="ML")
  emit(paste0("mu",i),as.numeric(predict(fit,n.ahead=1)$pred))
}
""")
    output = subprocess.run(["Rscript", "--vanilla", str(script), str(data)],
                            check=True, text=True, capture_output=True, timeout=30).stdout
    oracle = dict((key, float(value)) for key, value in
                  (line.split() for line in output.splitlines()))
    candidate = artifacts["ts.arma_candidates"]["candidates"][0]
    differences = {
        "ar": abs(candidate["parameters"]["ar.L1"] - oracle["ar"]),
        "ll": abs(candidate["log_likelihood"] - oracle["ll"]),
        "aic": abs(candidate["aic"] - oracle["aic"]),
    }
    assert differences["ar"] < 1e-4
    assert differences["ll"] < 1e-6
    assert differences["aic"] < 2e-6
    for index, row in enumerate(artifacts["ts.rolling_forecasts"]["rows"], start=157):
        differences[f"mu{index}"] = abs(row["conditional_mean"] - oracle[f"mu{index}"])
        assert differences[f"mu{index}"] < 1e-4
    (tmp_path / "r_ar1_comparison.json").write_text(json.dumps({
        "oracle": oracle, "differences": differences,
        "specification": "ARMA(1,0), no constant, sequential constant variance, N=160, tail=4",
    }, indent=2))
