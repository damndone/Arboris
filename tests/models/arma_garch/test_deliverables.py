"""Deliverable projections, exercised against the pack's real artifact schema.

Every fixture below mirrors the shape of a persisted ``ts.*`` payload from an
actual VIX run.  An earlier revision invented flat ``origin``/``actual``/
``forecast`` keys that the exporter also guessed, so implementation and test
agreed with each other while both disagreed with the artifacts, and the shipped
workbook silently carried two of eighteen forecast columns.
"""

from __future__ import annotations

import json
from pathlib import Path

# One rolling origin, keyed exactly as ``ts.rolling_forecasts.payload.rows[]``.
ROLLING_ROW = {
    "forecast_origin": {"row_id": "source-row:0000002589", "time": "2025-11-14T00:00:00+00:00"},
    "target": {"row_id": "source-row:0000002590", "time": "2025-11-17T00:00:00+00:00"},
    "observed_value": 12.097176035207458,
    "conditional_mean": -0.7044666459818231,
    "conditional_variance": 56.334301359308775,
    "conditional_volatility": 7.505617986502429,
    "lower_bound": -15.41520758124262,
    "upper_bound": 14.006274289278975,
    "lower_quantile": -13.050109613592554,
    "interval_covered": True,
    "quantile_exception": False,
    "model_scale": "log_return_pct",
    "original_scale": {"transform": "log_return_pct"},
    "fit_status": "ok",
    "fit_method": "refit",
    "warning": None,
    "predictive_interval": "plugin_conditional",
    "parameter_uncertainty_included": False,
}

# ``ts.volatility_candidates`` groups candidates under the mean candidate they
# were fitted against; the candidates live one level below ``searches``.
VOLATILITY_SEARCHES = {
    "searches": [
        {
            "mean_candidate_id": "arma-p1-q1-n",
            "selected_candidate_id": "variance-garch-p1-q1-normal",
            "shortlist_candidate_ids": ["variance-garch-p1-q1-normal"],
            "selection_status": "provisional_pre_validation",
            "common_hold_back": 1,
            "blocking_diagnostic": None,
            "candidates": [
                {
                    "candidate_id": "variance-garch-p1-q1-normal",
                    "variance_model": "garch",
                    "p": 1,
                    "q": 1,
                    "distribution": "normal",
                    "estimation_strategy": "sequential",
                    "joint_likelihood": False,
                    "mean_binding_status": "bound",
                    "converged": True,
                    "nobs": 2520,
                    "effective_sample": 2520,
                    "hold_back": 1,
                    "log_likelihood": -8610.390375470011,
                    "parameter_count": 3,
                    "aic": 17226.780750940023,
                    "aicc": 17226.790289890738,
                    "bic": 17244.27679348154,
                    "elapsed_seconds": 0.42,
                }
            ],
        }
    ]
}

FINAL_DIAGNOSTICS = {
    "adf": {"status": "ok", "statistic": -20.993055819285008, "p_value": 0.0, "used_lag": 7, "nobs": 2513},
    "ljung_box": [
        {"lag": 5, "statistic": 2.347722834109214, "p_value": 0.5034401753978699},
        {"lag": 10, "statistic": 5.957147203709429, "p_value": 0.6520321748833993},
        {"lag": 20, "statistic": 11.234978317647728, "p_value": 0.8841203912701809},
    ],
    "arch_lm": {
        "status": "ok",
        "lag": 10,
        "statistic": 3.386864895071169,
        "p_value": 0.9708008697619382,
        "f_statistic": 0.3379274529129465,
        "f_p_value": 0.9709415005788429,
    },
    "normality": {
        "status": "ok",
        "statistic": 6454.495164932475,
        "p_value": 0.0,
        "skew": 1.5682927476742836,
        "kurtosis": 10.18562550885693,
        "shapiro_wilk": {"status": "ok", "statistic": 0.908678961220391, "p_value": 1.86e-36},
        "shapiro_francia": {"status": "ok", "statistic": 0.9076191545025534, "p_value": 8.64e-34},
    },
    "residual_exceedance": {"threshold": 1.96, "count": 131, "rate": 0.05198412698412699, "n": 2520},
    "warnings": [],
}


def _write_artifact(run_root: Path, artifact_id: str, payload: object) -> None:
    path = run_root / "artifacts" / f"{artifact_id}.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"payload": payload}), encoding="utf-8")
    index_path = run_root / "artifacts_index.json"
    index = json.loads(index_path.read_text(encoding="utf-8")) if index_path.exists() else {"artifacts": []}
    index["artifacts"].append({"artifact_id": artifact_id, "path": str(path.relative_to(run_root))})
    index_path.write_text(json.dumps(index), encoding="utf-8")


def _minimal_run(tmp_path: Path) -> Path:
    """A run root carrying only the contract every projection needs."""
    run_root = tmp_path / "run"
    run_root.mkdir()
    _write_artifact(run_root, "ts.analysis_contract", {
        "dataset_ref": "upload:VIXCLS.csv",
        "time_column": "observation_date",
        "value_column": "VIXCLS",
        "transform": "log_return_pct",
        "estimation_strategy": "sequential",
        "arma": {"p": 1, "q": 1, "constant_mode": "exclude"},
        "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
    })
    return run_root


def test_arma_garch_deliverables_are_human_readable_and_nonempty(tmp_path: Path) -> None:
    """A time-series run must export its native evidence, never an empty coefficients sheet."""
    from workbench.engine.packs.arma_garch.deliverables import build_arma_garch_deliverables

    run_root = tmp_path / "run"
    run_root.mkdir()
    _write_artifact(run_root, "ts.analysis_contract", {
        "dataset_ref": "upload:VIXCLS.csv", "time_column": "observation_date",
        "value_column": "VIXCLS", "transform": "log_return_pct", "selection_mode": "manual",
        "estimation_strategy": "sequential", "innovation_distribution": "normal",
        "arma": {"p": 1, "q": 1, "constant_mode": "exclude"},
        "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
        "validation": {"validation_n": 20, "method": "expanding_window_one_step"},
    })
    _write_artifact(run_root, "ts.data_audit", {"time_index": {"original_row_count": 2610}, "data_quality": {"finite_value_count": 2541}})
    _write_artifact(run_root, "ts.arma_selection", {
        "final_selected_candidate_id": "arma-p1-q1-n",
        "final_selection_basis": "frozen_training_gates_aicc_bic_parsimony",
        "validation_data_role": "independent_evaluation_after_selection",
    })
    _write_artifact(run_root, "ts.volatility_selection", {
        "final_selected_candidate_id": "variance-garch-p1-q1-normal",
        "final_selection_basis": "frozen_training_gates_aicc_bic_parsimony",
    })
    _write_artifact(run_root, "ts.parameters", {
        "mean_candidate": {"ar.L1": 0.9208, "ma.L1": -0.9743, "sigma2": 62.223},
        "selected_variance_candidate": {"omega": 14.185, "alpha[1]": 0.1969, "beta[1]": 0.5784},
    })
    _write_artifact(run_root, "ts.forecast_metrics", {
        "validation_n": 20, "successful_forecast_n": 20, "mae": 6.4236,
        "rmse": 7.4409, "interval_coverage": 1.0, "average_interval_width": 30.1852,
    })
    _write_artifact(run_root, "ts.next_forecast", {
        "forecast_origin": {"time": "2025-12-12T00:00:00+00:00"},
        "conditional_mean": 0.6146, "conditional_variance": 48.4046,
        "conditional_volatility": 6.9573, "lower_bound": -13.0216, "upper_bound": 14.2507,
        "model_scale": "log_return_pct",
    })
    _write_artifact(run_root, "ts.final_diagnostics", FINAL_DIAGNOSTICS)
    _write_artifact(run_root, "ts.arma_candidates", {"candidates": [
        {"candidate_id": "arma-p1-q1-n", "p": 1, "q": 1, "constant": False, "converged": True,
         "log_likelihood": -8784.113651942433, "parameter_count": 3,
         "aic": 17574.22730388487, "bic": 17591.72453666643, "elapsed_seconds": 1.7},
    ]})
    _write_artifact(run_root, "ts.volatility_candidates", VOLATILITY_SEARCHES)
    _write_artifact(run_root, "ts.rolling_forecasts", {"rows": [ROLLING_ROW]})

    deliverables = build_arma_garch_deliverables(run_root)

    assert deliverables["report"]["title"] == "ARMA–GARCH Volatility Report"
    assert "ARMA(1,1)" in deliverables["report"]["model_label"]
    assert "GARCH(1,1)" in deliverables["report"]["model_label"]
    assert deliverables["report"]["metrics"]["rmse"] == 7.4409
    assert next(row for row in deliverables["tables"]["Overview"] if row["field"] == "Analysis observations")["value"] == 2541
    assert deliverables["report"]["limitations"]
    assert set(deliverables["tables"]) >= {
        "Overview", "ARMA candidates", "Volatility candidates", "Parameters",
        "Diagnostics", "Rolling forecasts", "Next forecast", "Acceptance",
    }
    assert all(rows for rows in deliverables["tables"].values())
    assert deliverables["tables"]["Parameters"][0]["component"] == "mean"


def test_rolling_forecast_sheet_can_be_reconciled_against_reported_metrics(tmp_path: Path) -> None:
    """Interval bounds alone cannot justify an RMSE or a coverage rate."""
    from workbench.engine.packs.arma_garch.deliverables import build_arma_garch_deliverables

    run_root = _minimal_run(tmp_path)
    _write_artifact(run_root, "ts.rolling_forecasts", {"rows": [ROLLING_ROW]})

    row = build_arma_garch_deliverables(run_root)["tables"]["Rolling forecasts"][0]

    # Identity of the origin and target, so a reader knows which date each row is.
    assert row["origin_time"] == "2025-11-14T00:00:00+00:00"
    assert row["target_time"] == "2025-11-17T00:00:00+00:00"
    assert row["origin_row_id"] == "source-row:0000002589"
    # The evaluated quantities behind RMSE and interval coverage.
    assert row["observed_value"] == ROLLING_ROW["observed_value"]
    assert row["conditional_mean"] == ROLLING_ROW["conditional_mean"]
    assert row["interval_covered"] is True
    assert row["quantile_exception"] is False
    assert row["fit_status"] == "ok"


def test_volatility_sheet_lists_candidates_not_search_metadata(tmp_path: Path) -> None:
    """Candidates live under ``searches[].candidates[]``; a one-level flatten lost them all."""
    from workbench.engine.packs.arma_garch.deliverables import build_arma_garch_deliverables

    run_root = _minimal_run(tmp_path)
    _write_artifact(run_root, "ts.volatility_candidates", VOLATILITY_SEARCHES)

    rows = build_arma_garch_deliverables(run_root)["tables"]["Volatility candidates"]

    assert len(rows) == 1
    row = rows[0]
    assert row["candidate_id"] == "variance-garch-p1-q1-normal"
    assert row["mean_candidate_id"] == "arma-p1-q1-n"
    assert row["selected"] is True
    assert row["shortlisted"] is True
    # The sequential-estimation disclosure must survive into the deliverable.
    assert row["joint_likelihood"] is False
    # Variance-equation-only information criteria: k counts omega/alpha/beta only.
    assert row["parameter_count"] == 3
    assert row["aic"] == 17226.780750940023


def test_diagnostics_sheet_carries_the_evidence_behind_acceptance_warnings(tmp_path: Path) -> None:
    """Ljung--Box and Jarque--Bera drive the warnings, so they must be exported."""
    from workbench.engine.packs.arma_garch.deliverables import build_arma_garch_deliverables

    run_root = _minimal_run(tmp_path)
    _write_artifact(run_root, "ts.final_diagnostics", FINAL_DIAGNOSTICS)

    rows = build_arma_garch_deliverables(run_root)["tables"]["Diagnostics"]
    tests = [str(row["test"]) for row in rows]

    assert any(name.startswith("ADF") for name in tests)
    assert sum(name.startswith("Ljung–Box") for name in tests) == 3
    assert any(name.startswith("ARCH-LM") for name in tests)
    assert any(name.startswith("Jarque–Bera") for name in tests)
    assert any(name.startswith("Shapiro–Wilk") for name in tests)
    assert any(name.startswith("Shapiro–Francia") for name in tests)
    assert any(name.startswith("Residual exceedance") for name in tests)

    jarque_bera = next(row for row in rows if str(row["test"]).startswith("Jarque–Bera"))
    assert jarque_bera["p_value"] == 0.0
    assert "skew=" in jarque_bera["detail"]


def test_unavailable_ljung_box_lag_is_not_reported_as_ok(tmp_path: Path) -> None:
    """The producer emits None for a non-finite statistic; status must follow the data."""
    from workbench.engine.packs.arma_garch.deliverables import build_arma_garch_deliverables

    run_root = _minimal_run(tmp_path)
    _write_artifact(run_root, "ts.final_diagnostics", {
        "ljung_box": [
            {"lag": 5, "statistic": None, "p_value": None},
            {"lag": 10, "statistic": 5.957147203709429, "p_value": 0.6520321748833993},
        ],
    })

    rows = build_arma_garch_deliverables(run_root)["tables"]["Diagnostics"]

    assert rows[0]["status"] == "unavailable"
    assert rows[0]["statistic"] == "—"
    assert rows[1]["status"] == "ok"


def test_deliverables_never_embed_nondeterministic_columns(tmp_path: Path) -> None:
    """Wall-clock timings would make an otherwise reproducible export drift."""
    from workbench.engine.packs.arma_garch.deliverables import build_arma_garch_deliverables

    run_root = _minimal_run(tmp_path)
    _write_artifact(run_root, "ts.volatility_candidates", VOLATILITY_SEARCHES)
    _write_artifact(run_root, "ts.arma_candidates", {"candidates": [
        {"candidate_id": "arma-p1-q1-n", "aic": 17574.2, "elapsed_seconds": 1.7},
    ]})

    tables = build_arma_garch_deliverables(run_root)["tables"]

    for name, rows in tables.items():
        for row in rows:
            assert "elapsed_seconds" not in row, f"{name} leaked a wall-clock timing"
            assert "convergence_details" not in row, f"{name} leaked a convergence blob"


def test_arma_garch_report_and_exports_render_the_native_evidence(tmp_path: Path) -> None:
    from openpyxl import load_workbook

    from workbench.engine.packs.arma_garch.deliverables import build_arma_garch_deliverables
    from workbench.exports import export_pdf, export_xlsx
    from workbench.reporting import render_html_report

    # Reuse the small, registered-artifact fixture above via the public builder
    # setup rather than creating a special report-only representation.
    run_root = tmp_path / "run"
    run_root.mkdir()
    _write_artifact(run_root, "ts.analysis_contract", {
        "dataset_ref": "upload:VIXCLS.csv", "time_column": "observation_date", "value_column": "VIXCLS",
        "transform": "log_return_pct", "arma": {"p": 1, "q": 1, "constant_mode": "exclude"},
        "variance": {"model": "garch", "garch_p": 1, "garch_q": 1},
    })
    _write_artifact(run_root, "ts.arma_selection", {"final_selected_candidate_id": "arma-p1-q1-n"})
    _write_artifact(run_root, "ts.volatility_selection", {"selected_candidate_id": "variance-garch-p1-q1-normal"})
    _write_artifact(run_root, "ts.parameters", {"mean_candidate": {"ar.L1": 0.9208}, "selected_variance_candidate": {"omega": 14.185}})
    _write_artifact(run_root, "ts.forecast_metrics", {"validation_n": 20, "rmse": 7.4409})
    _write_artifact(run_root, "ts.next_forecast", {"conditional_mean": 0.6146, "conditional_volatility": 6.9573})
    _write_artifact(run_root, "ts.final_diagnostics", FINAL_DIAGNOSTICS)
    _write_artifact(run_root, "ts.arma_candidates", {"candidates": [{"candidate_id": "arma-p1-q1-n", "aic": 17711.38}]})
    _write_artifact(run_root, "ts.volatility_candidates", VOLATILITY_SEARCHES)
    _write_artifact(run_root, "ts.rolling_forecasts", {"rows": [ROLLING_ROW]})

    deliverables = build_arma_garch_deliverables(run_root)
    html_path = render_html_report(deliverables["report"], run_root)
    pdf_path = export_pdf(deliverables["report"], run_root)
    xlsx_path = export_xlsx(deliverables["tables"], run_root)

    html = html_path.read_text(encoding="utf-8")
    assert 'id="time-series-overview"' in html
    assert "ARMA(1,1)" in html
    assert "7.4409" in html
    # The residual diagnostics a reader needs must reach the rendered surfaces,
    # not just the typed artifacts.
    assert "Ljung–Box" in html
    assert "Jarque–Bera" in html
    assert pdf_path.stat().st_size > 4_000
    workbook = load_workbook(xlsx_path, read_only=True, data_only=True)
    assert "Parameters" in workbook.sheetnames
    assert workbook["Parameters"].max_row > 1
    rolling = workbook["Rolling forecasts"]
    header = [cell.value for cell in next(rolling.iter_rows(min_row=1, max_row=1))]
    assert {"origin_time", "target_time", "observed_value", "conditional_mean"} <= set(header)
