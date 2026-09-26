"""v1.8.9 — Workbench against Stata 18 on Stata's own data.

Every check computes the same thing twice -- in Workbench and in Stata batch
mode -- from the same auto.dta that Stata saved, and compares. Skipped when
Stata is not installed.
"""

from __future__ import annotations

import math
from pathlib import Path

import pandas as pd
import pytest

from tests.stata_oracle import emit, emit_text, requires_stata, run
from tests.test_data_column_cast import _source_project
from workbench.agent.context_compiler import resolve_registered_artifact
from workbench.agent.workflow import WorkflowExecutor, compile_workflow
from workbench.agent.workflow_runtime import build_workflow_step_executor
from workbench.data_operation_registry import get_data_operation
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.services.results_service import read_model_results
from workbench.statistical_exploration import ExplorationSpec, execute_exploration
from workbench.tabular_io import read_statistical, read_statistical_labels

pytestmark = requires_stata

REGRESSORS = ["mpg", "weight", "foreign"]
PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)


@pytest.fixture(scope="module")
def stata(tmp_path_factory) -> tuple[Path, dict]:
    """One Stata session computes every reference number the tests need."""

    workdir = tmp_path_factory.mktemp("stata-oracle")
    body = "\n".join(
        [
            "sysuse auto, clear",
            "save auto.dta, replace",
            f"regress price {' '.join(REGRESSORS)}",
            emit("ols_n", "e(N)"), emit("ols_r2", "e(r2)"),
            *[emit(f"ols_b_{name}", f"_b[{name}]") for name in [*REGRESSORS, "_cons"]],
            *[emit(f"ols_se_{name}", f"_se[{name}]") for name in [*REGRESSORS, "_cons"]],
            f"regress price {' '.join(REGRESSORS)}, vce(robust)",
            *[emit(f"hc1_se_{name}", f"_se[{name}]") for name in [*REGRESSORS, "_cons"]],
            "logit foreign price mpg",
            *[emit(f"logit_b_{name}", f"_b[{name}]") for name in ["price", "mpg", "_cons"]],
            *[emit(f"logit_se_{name}", f"_se[{name}]") for name in ["price", "mpg", "_cons"]],
            emit("logit_ll", "e(ll)"),
            "ttest price, by(foreign) unequal",
            emit("t_t", "r(t)"), emit("t_p", "r(p)"), emit("t_mu1", "r(mu_1)"), emit("t_mu2", "r(mu_2)"),
            emit("t_df", "r(df_t)"),
            "summarize price, detail",
            emit("sd_mean", "r(mean)"), emit("sd_sd", "r(sd)"), emit("sd_skew", "r(skewness)"),
            emit("sd_kurt", "r(kurtosis)"), emit("sd_n", "r(N)"),
            *[emit(f"sd_p{p}", f"r(p{p})") for p in PERCENTILES],
            *[f"count if rep78 == {value}\n" + emit(f"tab_rep78_{value}", "r(N)") for value in range(1, 6)],
            "count if missing(rep78)",
            emit("tab_rep78_missing", "r(N)"),
            "recode mpg (min/19 = 1) (20/29 = 2) (30/max = 3), generate(mpg_group)",
            "export delimited make mpg mpg_group using recoded.csv, replace",
            emit_text("label_price", ": variable label price"),
            emit_text("label_foreign_1", ": label (foreign) 1"),
        ]
    )
    return workdir, run(workdir, body)


def _close(workbench: float, reference: float, rel: float = 1e-6) -> bool:
    return math.isclose(workbench, reference, rel_tol=rel, abs_tol=1e-9)


def _model(tmp_path: Path, auto: Path, **kwargs) -> dict:
    project = create_project(tmp_path, "p")
    outcome = run_workflow(project.root, [auto], mode="auto", **kwargs)
    assert outcome["status"] == "completed", outcome
    [result] = [
        item for item in read_model_results(project.root / "runs" / outcome["run_id"])
        if not str(item.get("model_id", "")).startswith("diagnostics")
    ]
    return result


def _coefficient(result: dict, term: str) -> dict:
    term = "Intercept" if term == "_cons" else term
    return result["coefficients"][term]


def test_ols_matches_regress(stata, tmp_path: Path) -> None:
    workdir, reference = stata
    result = _model(tmp_path, workdir / "auto.dta", model_type="ols", y="price", x=REGRESSORS, covariance="unadjusted")
    assert result["nobs"] == reference["ols_n"]
    assert _close(result["r_squared"], reference["ols_r2"])
    for name in [*REGRESSORS, "_cons"]:
        coefficient = _coefficient(result, name)
        assert _close(coefficient["estimate"], reference[f"ols_b_{name}"]), name
        assert _close(coefficient["std_error"], reference[f"ols_se_{name}"]), name


def test_robust_standard_errors_match_vce_robust(stata, tmp_path: Path) -> None:
    workdir, reference = stata
    result = _model(tmp_path, workdir / "auto.dta", model_type="ols", y="price", x=REGRESSORS, covariance="robust")
    for name in [*REGRESSORS, "_cons"]:
        assert _close(_coefficient(result, name)["std_error"], reference[f"hc1_se_{name}"]), name


def test_logit_matches_logit(stata, tmp_path: Path) -> None:
    workdir, reference = stata
    result = _model(tmp_path, workdir / "auto.dta", model_type="logit", y="foreign", x=["price", "mpg"])
    for name in ["price", "mpg", "_cons"]:
        coefficient = _coefficient(result, name)
        assert _close(coefficient["estimate"], reference[f"logit_b_{name}"], rel=1e-5), name
        assert _close(coefficient["std_error"], reference[f"logit_se_{name}"], rel=1e-4), name
    assert _close(result["llf"], reference["logit_ll"], rel=1e-7)


def _step_result(tmp_path: Path, frame: pd.DataFrame, step: dict) -> dict:
    project, run_id, artifact_id = _source_project(tmp_path, frame)
    draft = compile_workflow(
        workflow_id="wf-oracle", target={"run_id": run_id, "node_ref": "stage:source", "artifact_id": artifact_id},
        preconditions={"context_fingerprint": "fp"}, steps=[step], available_columns=list(frame.columns),
    )
    state = WorkflowExecutor(project).execute(draft, build_workflow_step_executor(project, draft))
    assert state.status == "completed"
    [artifact] = state.steps[step["step_id"]].artifact_ids
    _type, _sha, payload = resolve_registered_artifact(project / "runs" / run_id, artifact)
    return payload["result"]


def _auto(stata) -> pd.DataFrame:
    workdir, _ = stata
    return read_statistical(workdir / "auto.dta", "dta")


def test_welch_t_test_matches_ttest_unequal(stata, tmp_path: Path) -> None:
    _, reference = stata
    frame = _auto(stata)[["price", "foreign"]]
    result = _step_result(tmp_path, frame, {
        "step_id": "tt", "operation_id": "test.t_tests",
        "spec": {"input_mode": "frame", "column_bindings": {"columns": ["price", "foreign"]}, "options": {}},
    })
    [test] = result["result"]["results"]
    assert _close(abs(test["statistic"]), abs(reference["t_t"]))
    assert _close(test["p_value"], reference["t_p"], rel=1e-6)
    # Workbench names the group means by value (mean_0, mean_1); Stata by order.
    means = [value for key, value in sorted(test["effect"].items()) if key.startswith("mean_")]
    assert _close(means[0], reference["t_mu1"]) and _close(means[1], reference["t_mu2"])


def test_summarize_detail_matches_stata_percentiles_and_moments(stata) -> None:
    _, reference = stata
    result = execute_exploration(
        _auto(stata),
        ExplorationSpec("summarize_detail", ("price",), options={"quantile_method": "stata_summarize_detail_v1"}),
    )
    price = result["variables"]["price"]
    assert price["obs"] == reference["sd_n"]
    assert _close(price["mean"], reference["sd_mean"]) and _close(price["std_dev"], reference["sd_sd"])
    assert _close(price["skewness"], reference["sd_skew"]) and _close(price["kurtosis"], reference["sd_kurt"])
    for p in PERCENTILES:
        assert _close(price["percentiles"][f"p{p}"], reference[f"sd_p{p}"]), p


def test_tabulate_matches_stata_counts(stata) -> None:
    _, reference = stata
    result = execute_exploration(_auto(stata), ExplorationSpec("tabulate", ("rep78",)))
    counts = {row["value"]: row["count"] for row in result["rows"]}
    for value in range(1, 6):
        assert counts.get(value, counts.get(float(value), 0)) == reference[f"tab_rep78_{value}"], value
    assert result["variables"]["rep78"]["missing"] == reference["tab_rep78_missing"]


def test_recode_matches_stata_recode(stata) -> None:
    workdir, _ = stata
    frame = _auto(stata)
    recoded = get_data_operation("recode").run(frame, {
        "column": "mpg", "output": "mpg_group",
        "rules": [{"from": {"low": -1e9, "high": 19}, "to": 1}, {"from": {"low": 20, "high": 29}, "to": 2},
                  {"from": {"low": 30, "high": 1e9}, "to": 3}],
    })
    stata_recoded = pd.read_csv(workdir / "recoded.csv")
    assert list(recoded["mpg_group"].astype(int)) == list(stata_recoded["mpg_group"].astype(int))


def test_workbench_reads_the_labels_stata_saved(stata) -> None:
    workdir, reference = stata
    labels = read_statistical_labels(workdir / "auto.dta", "dta")
    assert labels["variable_labels"]["price"] == reference["label_price"]
    assert labels["value_labels"]["foreign"]["1"] == reference["label_foreign_1"]


def test_stata_reads_what_workbench_exports(tmp_path: Path) -> None:
    """Unicode labels, value labels and declared missing codes survive the trip."""

    from workbench.services.data_export import export_dataset

    frame = pd.DataFrame({"educ": [12.0, -99.0, 16.0, 9.0], "region": [1, 2, 3, 2], "wage": [10.5, 12.0, 30.25, 8.0]})
    source = tmp_path / "w.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, "p")
    labels = {
        "variable_labels": {"educ": "受教育年限", "wage": "小时工资"},
        "value_labels": {"region": {"1": "北方", "2": "南方", "3": "西部"}},
        "user_missing_values": {"educ": [-99]},
    }
    outcome = run_workflow(project.root, [source], mode="auto", model_type="ols", y="wage", x=["educ"], labels=labels)
    exports = []
    for version in (13, 14, 15):
        # Stata 13 files are not Unicode: only region carries no Chinese label.
        columns = ["region"] if version == 13 else None
        exported = export_dataset(project.root, outcome["run_id"], "stage:raw",
                                  {"format": "dta", "dta_version": version, "columns": columns,
                                   "value_labels": "none" if version == 13 else "labels",
                                   "filename": f"wb{version}"})
        [path] = (project.root / "runs" / outcome["run_id"] / "exports" / "data").rglob(exported["filename"])
        exports.append(path)
    body = "\n".join(
        [
            f'use "{exports[1]}", clear',
            emit_text("label_educ", ": variable label educ"),
            emit_text("label_region_2", ": label (region) 2"),
            "count if missing(educ)", emit("educ_missing", "r(N)"),
            "summarize wage", emit("wage_mean", "r(mean)"),
            f'use "{exports[0]}", clear', "summarize region", emit("v13_mean", "r(mean)"),
            f'use "{exports[2]}", clear', "summarize wage", emit("v15_mean", "r(mean)"),
        ]
    )
    reference = run(tmp_path / "stata", body)
    assert reference["label_educ"] == "受教育年限"
    assert reference["label_region_2"] == "南方"
    assert reference["educ_missing"] == 1  # -99 declared missing -> missing in Stata
    assert _close(reference["wage_mean"], frame["wage"].mean())
    assert _close(reference["v13_mean"], frame["region"].mean()) and _close(reference["v15_mean"], frame["wage"].mean())


def _real_dta_files() -> list[Path]:
    """The user's own Stata files: local only, never committed, skipped when absent."""

    import os

    root = Path(os.environ.get("WORKBENCH_REAL_DTA_DIR", Path.home() / "Downloads"))
    if not root.is_dir():
        return []
    return sorted(path for path in root.rglob("*.dta") if path.stat().st_size < 50_000_000)[:20]


@pytest.mark.parametrize("path", _real_dta_files(), ids=lambda path: path.name)
def test_real_stata_files_summarize_as_in_stata(path: Path, tmp_path: Path) -> None:
    frame = read_statistical(path, "dta")
    numeric = [str(column) for column in frame.columns if pd.api.types.is_numeric_dtype(frame[column])][:40]
    if not numeric:
        pytest.skip("no numeric variables")
    lines = [f'use "{path}", clear']
    for index, column in enumerate(numeric):
        lines += [f"quietly summarize {column}", emit(f"n{index}", "r(N)"), emit(f"m{index}", "r(mean)"), emit(f"s{index}", "r(sd)")]
    reference = run(tmp_path, "\n".join(lines))
    for index, column in enumerate(numeric):
        series = frame[column].dropna().astype(float)
        assert len(series) == reference[f"n{index}"], column
        if len(series):
            assert _close(float(series.mean()), reference[f"m{index}"], rel=1e-9), column
        if len(series) > 1:
            assert _close(float(series.std(ddof=1)), reference[f"s{index}"], rel=1e-7), column
