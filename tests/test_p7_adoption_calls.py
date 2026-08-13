"""Every frozen P7 operation must complete through its typed registry adapter."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm


def _request(
    operation_id: str,
    input_mode: str,
    bindings: dict[str, object] | None = None,
    options: dict[str, object] | None = None,
) -> dict[str, object]:
    return {
        "operation_id": operation_id,
        "input_mode": input_mode,
        "column_bindings": bindings or {},
        "options": options or {},
    }


def _glm_frame() -> dict[str, pd.DataFrame]:
    rng = np.random.default_rng(20260808)
    x = rng.normal(size=180)
    zero_probability = 1.0 / (1.0 + np.exp(0.9 + 0.8 * x))
    mean = np.exp(0.35 + 0.25 * x)
    structural_zero = rng.random(x.size) < zero_probability
    zip_y = np.where(structural_zero, 0, rng.poisson(mean)).astype(float)
    zinb_mean = rng.gamma(shape=2.0, scale=0.7 * mean)
    zinb_y = np.where(structural_zero, 0, rng.poisson(zinb_mean)).astype(float)
    positive = rng.random(x.size) < (1.0 / (1.0 + np.exp(0.6 + 0.6 * x)))
    hurdle_counts = rng.poisson(np.exp(0.2 + 0.2 * x))
    while np.any(positive & (hurdle_counts == 0)):
        redraw = positive & (hurdle_counts == 0)
        hurdle_counts[redraw] = rng.poisson(np.exp(0.2 + 0.2 * x[redraw]))
    hurdle_y = np.where(positive, hurdle_counts, 0).astype(float)
    hurdle_nb_counts = rng.poisson(rng.gamma(shape=2.0, scale=0.7 * mean))
    while np.any(positive & (hurdle_nb_counts == 0)):
        redraw = positive & (hurdle_nb_counts == 0)
        hurdle_nb_counts[redraw] = rng.poisson(
            rng.gamma(shape=2.0, scale=0.7 * mean[redraw])
        )
    hurdle_nb_y = np.where(positive, hurdle_nb_counts, 0).astype(float)
    beta_mean = 1.0 / (1.0 + np.exp(-0.2 - 0.5 * x))
    beta_y = rng.beta(beta_mean * 18.0, (1.0 - beta_mean) * 18.0)
    return {
        "glm.zero_inflated_poisson": pd.DataFrame({"y": zip_y, "x": x}),
        "glm.zero_inflated_negative_binomial": pd.DataFrame({"y": zinb_y, "x": x}),
        "glm.hurdle_poisson": pd.DataFrame({"y": hurdle_y, "x": x}),
        "glm.hurdle_negative_binomial": pd.DataFrame({"y": hurdle_nb_y, "x": x}),
        "glm.beta": pd.DataFrame({"y": beta_y, "x": x}),
    }


def _matching_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "unit": ["t1", "t2", "t3", "c1", "c2", "c3"],
            "treated": [1, 1, 1, 0, 0, 0],
            "outcome": [10.0, 12.0, 14.0, 8.0, 10.0, 12.0],
            "x": [-1.0, 0.0, 1.0, -1.1, 0.1, 1.2],
            "z": [0.0, 1.0, 2.0, 0.0, 1.0, 2.0],
        }
    )


def _matching_options() -> dict[str, object]:
    return {
        "propensity_policy": {
            "model": "logit",
            "solver": "newton",
            "max_iter": 200,
            "tolerance": 1e-10,
            "min_probability": 1e-6,
            "max_probability": 1.0 - 1e-6,
        },
        "matching_geometry_policy": "standardized_covariate_euclidean_v1",
        "support_distance_policy": "absolute_logit_difference",
        "ratio": 1,
        "caliper": 0.75,
        "replacement": False,
        "tie_policy": "stable_first",
        "common_support_policy": "reject_disjoint_no_trim_v1",
        "unmatched_policy": "reject",
        "balance_threshold": 0.1,
        "missing_policy": "reject",
    }


def _diagnostics_case() -> tuple[pd.DataFrame, dict[str, object]]:
    x1 = np.linspace(-2.5, 2.5, 30)
    x2 = np.sin(np.linspace(-1.7, 2.1, 30)) + np.linspace(-0.2, 0.2, 30)
    design = np.column_stack((np.ones(30), x1, x2))
    response = 1.25 + 0.8 * x1 - 0.35 * x2 + 0.04 * x1**2 + 0.18 * np.cos(x1 * 2.0)
    fitted = sm.OLS(response, design).fit()
    metadata = {
        "model_type": "ols",
        "parameter_count": int(fitted.df_model + 1),
        "residual_df": int(fitted.df_resid),
        "residual_variance": float(fitted.mse_resid),
        "covariance": "unadjusted",
        "parameter_names": ["const", "x1", "x2"],
    }
    frame = pd.DataFrame({"response": response, "x1": x1, "x2": x2})
    return frame, {
        "intercept": True,
        "intercept_column": "const",
        "model_metadata": metadata,
    }


def _efa_frame() -> pd.DataFrame:
    rng = np.random.default_rng(20260807)
    factor_1 = rng.normal(size=120)
    factor_2 = rng.normal(size=120)
    noise = rng.normal(scale=0.25, size=(120, 6))
    return pd.DataFrame(
        {
            "v1": factor_1 + noise[:, 0],
            "v2": 0.9 * factor_1 + noise[:, 1],
            "v3": 0.8 * factor_1 + noise[:, 2],
            "v4": factor_2 + noise[:, 3],
            "v5": 0.9 * factor_2 + noise[:, 4],
            "v6": 0.8 * factor_2 + noise[:, 5],
        }
    )


def _repeated_frame() -> pd.DataFrame:
    values = {
        "s1": [10.0, 11.0, 12.5],
        "s2": [11.0, 13.0, 14.0],
        "s3": [9.0, 10.5, 11.0],
        "s4": [12.0, 13.5, 15.0],
    }
    return pd.DataFrame(
        [
            {"response": value, "subject": subject, "within": level}
            for subject, subject_values in values.items()
            for level, value in zip(("pre", "mid", "post"), subject_values)
        ]
    )


def _mixed_frame() -> pd.DataFrame:
    values = {
        "A1": ("A", [10.0, 12.0]),
        "A2": ("A", [11.0, 13.0]),
        "A3": ("A", [9.0, 10.0]),
        "B1": ("B", [20.0, 24.0]),
        "B2": ("B", [21.0, 25.0]),
        "B3": ("B", [19.0, 22.0]),
    }
    return pd.DataFrame(
        [
            {
                "response": value,
                "subject": subject,
                "within": level,
                "between": between,
            }
            for subject, (between, subject_values) in values.items()
            for level, value in zip(("pre", "post"), subject_values)
        ]
    )


def _power_options(design: str, solve_for: str) -> dict[str, object]:
    return {"design": design, "solve_for": solve_for}


def _spatial_frame() -> tuple[pd.DataFrame, dict[str, object]]:
    weights = np.array(
        [
            [0.0, 1.0, 0.0, 0.0],
            [1.0, 0.0, 1.0, 0.0],
            [0.0, 1.0, 0.0, 1.0],
            [0.0, 0.0, 1.0, 0.0],
        ]
    )
    frame = pd.DataFrame({"values": [1.0, 2.0, 4.0, 8.0]})
    for index in range(4):
        frame[f"w{index}"] = weights[:, index]
    return frame, {
        "weight_policy": {
            "normalization": "none",
            "symmetry_policy": "require_symmetric",
            "row_sum_policy": "require_positive",
            "zero_diagonal_policy": "require_zero",
            "islands_policy": "reject",
            "negative_weight_policy": "reject",
        },
        "permutation_policy": {
            "n_permutations": 19,
            "seed": 17,
            "tail": "two-sided",
            "plus_one": True,
        },
    }


def _synthetic_control_case() -> tuple[pd.DataFrame, dict[str, object]]:
    fixture = json.loads(
        (Path(__file__).parent / "fixtures" / "synthetic_control" / "oracle_cases.json").read_text()
    )
    frame = pd.DataFrame(
        np.asarray(fixture["outcomes"]).T,
        columns=list(fixture["units"]),
    )
    options = {
        "treated_unit": "treated",
        "donor_pool": ["d1", "d2", "d3"],
        "periods": fixture["periods"],
        "pre_periods": [0, 1, 2],
        "post_periods": [3, 4, 5],
        "solver_policy": {
            "solver": "scipy_slsqp",
            "max_iter": 500,
            "tolerance": 1e-10,
            "constraint_tolerance": 1e-8,
        },
        "tolerance_policy": {
            "weight_sum": 1e-8,
            "constraint": 1e-8,
            "finite": 0.0,
        },
    }
    return frame, options


def _time_series_frame() -> pd.DataFrame:
    rng = np.random.default_rng(20260808)
    time = np.arange(1.0, 121.0)
    innovations = rng.normal(scale=0.15, size=(120, 2))
    first = np.zeros(120)
    second = np.zeros(120)
    for index in range(1, 120):
        first[index] = 0.72 * first[index - 1] + innovations[index, 0]
        second[index] = 0.35 * second[index - 1] + 0.15 * first[index - 1] + innovations[index, 1]
    return pd.DataFrame({"time": time, "value": first, "other": second})


def _cases() -> dict[str, tuple[pd.DataFrame | None, dict[str, object]]]:
    cases: dict[str, tuple[pd.DataFrame | None, dict[str, object]]] = {}
    category = pd.DataFrame(
        {
            "row": ["a"] * 12 + ["b"] * 12,
            "column": ["x"] * 10 + ["y"] * 2 + ["x"] * 3 + ["y"] * 9,
        }
    )
    cases["categorical.cramers_v"] = (
        category,
        _request(
            "categorical.cramers_v",
            "typed",
            {"row": "row", "column": "column"},
            {"correction": False},
        ),
    )
    cases["categorical.mcnemar"] = (
        category,
        _request(
            "categorical.mcnemar",
            "typed",
            {"row": "row", "column": "column"},
            {"correction": False, "exact": False},
        ),
    )

    for operation_id, frame in _glm_frame().items():
        cases[operation_id] = (
            frame,
            _request(operation_id, "frame", {"outcome": "y", "predictors": ["x"]}, {"maxiter": 500}),
        )

    rng = np.random.default_rng(20260808)
    n = 240
    x = rng.normal(size=n)
    z1 = rng.normal(size=n)
    z2 = rng.normal(size=n)
    endogenous = 0.85 * z1 + 0.35 * z2 + 0.45 * x + rng.normal(scale=0.65, size=n)
    y = 1.25 + 0.70 * x + 1.80 * endogenous + 0.50 * rng.normal(size=n)
    iv = pd.DataFrame({"y": y, "const": 1.0, "x": x, "endog": endogenous, "z1": z1, "z2": z2})
    for operation_id in ("iv.gmm", "iv.weak_instruments"):
        cases[operation_id] = (
            iv,
            _request(
                operation_id,
                "typed",
                {"outcome": "y", "exog": ["const", "x"], "endog": ["endog"], "instruments": ["z1", "z2"]},
                {"estimator": "two_step"} if operation_id == "iv.gmm" else {},
            ),
        )

    matching = _matching_frame()
    for operation_id in ("matching.att", "matching.balance"):
        if operation_id == "matching.att":
            options = _matching_options()
        else:
            options = {
                "balance_threshold": 0.1,
                "missing_policy": "reject",
            }
            options["matched_pairs"] = [
                {"treated_position": 0, "control_position": 3, "control_unit": "c1"},
                {"treated_position": 1, "control_position": 4, "control_unit": "c2"},
                {"treated_position": 2, "control_position": 5, "control_unit": "c3"},
            ]
        cases[operation_id] = (
            matching,
            _request(
                operation_id,
                "frame",
                (
                    {"treatment": "treated", "outcome": "outcome", "id": "unit", "covariates": ["x", "z"]}
                    if operation_id == "matching.att"
                    else {"treatment": "treated", "id": "unit", "covariates": ["x", "z"]}
                ),
                options,
            ),
        )

    studies = pd.DataFrame(
        {"study": ["study-a", "study-b", "study-c"], "effect": [0.2, 0.8, 1.1], "variance": [0.04, 0.09, 0.16]}
    )
    cases["meta.combine"] = (
        studies,
        _request(
            "meta.combine",
            "typed",
            {"study_id": "study", "effect": "effect", "variance": "variance"},
            {"effect_measure": "direct", "method": "fixed_effect", "alpha": 0.05},
        ),
    )
    cases["meta.effect_size"] = (
        studies,
        _request(
            "meta.effect_size",
            "typed",
            {"study_id": "study", "effect": "effect", "variance": "variance"},
            {"effect_measure": "direct", "alpha": 0.05},
        ),
    )

    missing = pd.DataFrame({"a": [1.0, np.nan, 3.0, 4.0], "b": [2.0, 2.0, np.nan, 4.0]})
    cases["missingness.profile"] = (missing, _request("missingness.profile", "frame"))
    cases["missing_data.rubin_pool"] = (
        missing,
        _request(
            "missing_data.rubin_pool",
            "frame",
            options={
                "model_results": [
                    {"coefficients": {"Intercept": {"estimate": 1.0, "std_error": 0.2}}},
                    {"coefficients": {"Intercept": {"estimate": 1.8, "std_error": 0.2}}},
                ]
            },
        ),
    )

    diagnostics, diagnostic_options = _diagnostics_case()
    diagnostic_bindings = {"design": ["x1", "x2"]}
    for operation_id in (
        "diagnostics.vif",
        "diagnostics.breusch_pagan",
        "diagnostics.white",
        "diagnostics.breusch_godfrey",
        "diagnostics.reset",
        "diagnostics.influence",
    ):
        bindings = dict(diagnostic_bindings)
        options = dict(diagnostic_options)
        if operation_id != "diagnostics.vif":
            bindings["response"] = "response"
        if operation_id == "diagnostics.breusch_godfrey":
            options.update({"lag": 2, "time_order": "declared_monotonic"})
        if operation_id == "diagnostics.reset":
            options["reset_powers"] = [2, 3]
        cases[operation_id] = (diagnostics, _request(operation_id, "typed", bindings, options))

    groups = pd.DataFrame(
        [
            {"group": group, "value": value}
            for group, values in {
                "control": [1.0, 1.2, 0.9, 1.1, 1.0, 1.1],
                "treatment_a": [2.0, 2.1, 1.9, 2.2, 2.0],
                "treatment_b": [3.0, 3.5, 2.7, 3.1],
            }.items()
            for value in values
        ]
    )
    for operation_id in ("multiple_comparisons.games_howell", "multiple_comparisons.scheffe"):
        cases[operation_id] = (groups, _request(operation_id, "typed", {"group": "group", "value": "value"}, {"alpha": 0.05}))

    pca = pd.DataFrame(
        {
            "small": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0],
            "large": [100.0, 101.0, 99.0, 102.0, 98.0, 103.0],
            "middle": [2.0, 4.0, 1.0, 5.0, 3.0, 6.0],
        }
    )
    cases["multivariate.pca"] = (
        pca,
        _request("multivariate.pca", "frame", {"columns": ["small", "large", "middle"]}, {"matrix": "correlation", "component_selection": "all", "include_scores": False, "max_score_rows": 100}),
    )
    cases["multivariate.efa"] = (
        _efa_frame(),
        _request("multivariate.efa", "frame", {"columns": ["v1", "v2", "v3", "v4", "v5", "v6"]}, {"n_factors": 2, "extraction": "principal_axis", "rotation": "none", "kmo_threshold": 0.6, "bartlett_alpha": 0.05}),
    )
    reliability = pd.DataFrame({"item_1": [1.0, 2.0, 3.0, 4.0, 5.0], "item_2": [2.0, 3.0, 4.0, 5.0, 6.0], "item_3": [1.0, 3.0, 5.0, 7.0, 9.0]})
    cases["multivariate.cronbach_alpha"] = (reliability, _request("multivariate.cronbach_alpha", "frame", {"columns": ["item_1", "item_2", "item_3"]}))
    cases["multivariate.clustering"] = (
        pca,
        _request("multivariate.clustering", "frame", {"columns": ["small", "large", "middle"]}, {"algorithm": "kmeans", "standardization": "zscore_sample", "selection": "fixed", "n_clusters": 2, "candidate_ks": None, "random_state": 17, "linkage": "ward", "metric": "euclidean", "max_iter": 300, "tol": 0.0001, "include_assignments": False, "max_assignment_rows": 500}),
    )
    correspondence_rows = []
    for row_label, column_counts in {"r1": {"c1": 9, "c2": 3}, "r2": {"c1": 2, "c2": 6, "c3": 1}, "r3": {"c1": 4, "c2": 3, "c3": 3}}.items():
        for column_label, count in column_counts.items():
            correspondence_rows.extend({"row": row_label, "column": column_label} for _ in range(count))
    cases["multivariate.correspondence"] = (pd.DataFrame(correspondence_rows), _request("multivariate.correspondence", "frame", {"row": "row", "column": "column"}, {"n_dimensions": 2}))
    cases["multivariate.mca"] = (
        pd.DataFrame({"a": ["x", "x", "y", "y", "x", "y", "x", "y"], "b": ["u", "v", "u", "v", "u", "v", "u", "v"]}),
        _request("multivariate.mca", "frame", {"columns": ["a", "b"]}, {"n_dimensions": 1}),
    )
    rng = np.random.default_rng(7)
    discriminant = pd.DataFrame({"f1": np.r_[rng.normal(0, 1, 30), rng.normal(3, 1, 30)], "f2": np.r_[rng.normal(0, 1, 30), rng.normal(3, 1, 30)], "target": ["a"] * 30 + ["b"] * 30})
    cases["multivariate.discriminant"] = (
        discriminant,
        _request("multivariate.discriminant", "frame", {"features": ["f1", "f2"], "target": "target"}, {"method": "lda", "prior_policy": "empirical", "regularization": 0.0, "evaluation": "none", "test_size": None, "random_state": None, "include_predictions": False, "max_prediction_rows": 500}),
    )
    manova = pd.DataFrame({"response one": [6.2, 5.8, 7.1, 6.7, 8.4, 8.9, 9.1, 8.6, 10.2, 9.7, 10.8, 11.1], "response two": [2.4, 2.9, 3.1, 2.7, 4.2, 4.6, 4.1, 4.8, 5.7, 5.2, 5.9, 6.3], "group name": ["zeta", "alpha", "alpha", "zeta", "beta", "beta", "alpha", "zeta", "beta", "alpha", "zeta", "beta"]})
    cases["multivariate.manova"] = (
        manova,
        _request("multivariate.manova", "frame", {"responses": ["response one", "response two"], "factors": ["group name"]}, {"interaction_terms": [], "intercept": True, "missing_policy": "complete_case_v1", "max_retained_positions": 500}),
    )

    nonparametric = pd.DataFrame({"x": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "y": [1.2, 2.1, 2.8, 4.2, 4.9, 6.1], "group": ["a", "a", "a", "b", "b", "b"], "value": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "v1": [1.0, 2.0, 3.0, 4.0, 5.0, 6.0], "v2": [1.1, 1.9, 3.2, 3.8, 5.2, 5.9], "v3": [0.9, 2.2, 2.8, 4.1, 4.8, 6.2]})
    for operation_id in ("nonparametric.mann_whitney", "nonparametric.wilcoxon_signed_rank", "nonparametric.spearman", "nonparametric.kendall"):
        cases[operation_id] = (nonparametric, _request(operation_id, "typed", {"x": "x", "y": "y"}))
    cases["nonparametric.kruskal_wallis"] = (nonparametric, _request("nonparametric.kruskal_wallis", "typed", {"group": "group", "value": "value"}))
    cases["nonparametric.friedman"] = (nonparametric, _request("nonparametric.friedman", "typed", {"columns": ["v1", "v2", "v3"]}))
    cases["nonparametric.robust_summary"] = (nonparametric, _request("nonparametric.robust_summary", "typed", {"values": "value"}))

    for design in ("independent_t", "one_way_anova", "two_proportion_z"):
        for solve_for in ("power", "sample_size", "effect_size", "alpha"):
            cases[f"power_analysis.solve:{design}:{solve_for}"] = (None, _request("power_analysis.solve", "typed", options=_power_options(design, solve_for)))
    cases["power_analysis.solve"] = cases.pop("power_analysis.solve:independent_t:power")
    cases["power_analysis.sensitivity_grid"] = (
        None,
        _request("power_analysis.sensitivity_grid", "typed", options={"design": "independent_t", "solve_for": "power", "axes": {"effect_size": [0.4, 0.5]}}),
    )

    cases["repeated_measures_anova.repeated_only"] = (_repeated_frame(), _request("repeated_measures_anova.repeated_only", "frame", {"response": "response", "subject": "subject", "within": "within"}, {"correction": "none"}))
    cases["repeated_measures_anova.mixed_design"] = (_mixed_frame(), _request("repeated_measures_anova.mixed_design", "frame", {"response": "response", "subject": "subject", "within": "within", "between": "between"}, {"correction": "none"}))

    resampling = pd.DataFrame({"values": np.arange(1.0, 11.0), "left": np.arange(1.0, 11.0), "right": np.arange(1.5, 11.5)})
    cases["resampling.bootstrap"] = (resampling, _request("resampling.bootstrap", "typed", {"values": "values"}, {"statistic_id": "mean", "n_resamples": 199, "seed": 17, "confidence_level": 0.95, "interval_method": "percentile"}))
    cases["resampling.permutation"] = (resampling, _request("resampling.permutation", "typed", {"left": "left", "right": "right"}, {"statistic_id": "difference_in_means", "n_resamples": 199, "seed": 17, "alternative": "two-sided"}))

    roc = pd.DataFrame({"truth": [0, 1, 0, 1, 1, 0, 1, 0], "scores": [0.1, 0.85, 0.25, 0.55, 0.75, 0.15, 0.65, 0.35]})
    cases["roc.curve"] = (roc, _request("roc.curve", "frame", {"truth": "truth", "scores": "scores"}, {"positive_label": 1, "score_semantics": "probability", "threshold_policy": "unique_scores"}))
    cases["roc.calibration"] = (roc, _request("roc.calibration", "frame", {"truth": "truth", "scores": "scores"}, {"positive_label": 1, "score_semantics": "probability", "calibration_method": "equal_width", "n_bins": 4}))

    spatial, spatial_options = _spatial_frame()
    for operation_id in ("spatial.moran_i", "spatial.geary_c", "spatial.getis_ord_g"):
        cases[operation_id] = (spatial, _request(operation_id, "typed", {"values": "values", "weights": ["w0", "w1", "w2", "w3"]}, spatial_options))

    survival = pd.DataFrame({"duration": [1.0, 2.0, 4.0, 5.0, 1.0, 3.0, 4.0, 6.0], "event": [1, 0, 1, 0, 1, 1, 0, 0], "group": ["A", "A", "A", "A", "B", "B", "B", "B"]})
    survival_options = {
        "survival.kaplan_meier": {"ci_method": "log_log", "confidence_level": 0.95, "tau": 4.0},
        "survival.log_rank": {"tie_policy": "hypergeometric"},
        "survival.rmst": {"tau": 4.0},
    }
    for operation_id in ("survival.kaplan_meier", "survival.log_rank", "survival.rmst"):
        cases[operation_id] = (survival, _request(operation_id, "frame", {"duration": "duration", "event": "event", "group": "group"}, survival_options[operation_id]))

    synthetic, synthetic_options = _synthetic_control_case()
    cases["synthetic_control.fit"] = (synthetic, _request("synthetic_control.fit", "typed", {"outcomes": ["treated", "d1", "d2", "d3"]}, synthetic_options))
    cases["synthetic_control.placebo"] = (synthetic, _request("synthetic_control.placebo", "typed", {"outcomes": ["treated", "d1", "d2", "d3"]}, {**synthetic_options, "placebo_policy": {"unit_policy": "explicit", "placebo_units": ["d1", "d2"], "max_placebos": 2, "donor_policy": "exclude_original_treated", "failure_policy": "reject"}}))

    time_series = _time_series_frame()
    time_options = {"time_order": "declared_monotonic"}
    cases["time_series.acf"] = (time_series, _request("time_series.acf", "frame", {"time": "time", "value": "value"}, {**time_options, "nlags": 8}))
    cases["time_series.pacf"] = (time_series, _request("time_series.pacf", "frame", {"time": "time", "value": "value"}, {**time_options, "nlags": 8, "method": "ywm"}))
    cases["time_series.adf"] = (time_series, _request("time_series.adf", "frame", {"time": "time", "value": "value"}, {**time_options, "regression": "c", "autolag": "aic", "max_lag": 4}))
    cases["time_series.kpss"] = (time_series, _request("time_series.kpss", "frame", {"time": "time", "value": "value"}, {**time_options, "regression": "c", "nlags": "auto"}))
    cases["time_series.arima"] = (time_series, _request("time_series.arima", "frame", {"time": "time", "value": "value"}, {**time_options, "order": [1, 0, 0], "trend": "c", "forecast_horizon": 1}))
    cases["time_series.var"] = (
        time_series,
        _request(
            "time_series.var",
            "frame",
            {"time": "time", "values": ["value", "other"]},
            {
                **time_options,
                "lags": 1,
                "trend": "c",
                "forecast_horizon": 1,
                "confidence_level": 0.95,
                "stability_policy": "report_only",
            },
        ),
    )
    cases["time_series.irf"] = (
        time_series,
        _request(
            "time_series.irf",
            "frame",
            {"time": "time", "values": ["value", "other"]},
            {
                **time_options,
                "lags": 1,
                "trend": "c",
                "horizon": 5,
                "orthogonalized": True,
                "confidence_level": 0.95,
                "ci_method": "asymptotic_normal",
                "stability_policy": "report_only",
            },
        ),
    )
    cases["time_series.cointegration"] = (time_series, _request("time_series.cointegration", "frame", {"time": "time", "values": ["value", "other"]}, {**time_options, "method": "engle_granger", "confidence_level": 0.95, "max_lag": 1, "trend": "c", "det_order": 0, "k_ar_diff": 1}))
    cases["time_series.vecm"] = (time_series, _request("time_series.vecm", "frame", {"time": "time", "values": ["value", "other"]}, {**time_options, "det_order": 0, "k_ar_diff": 1, "deterministic": "co", "forecast_horizon": 1, "confidence_level": 0.95}))
    cases["time_series.granger"] = (time_series, _request("time_series.granger", "frame", {"time": "time", "cause": "value", "effect": "other"}, {**time_options, "max_lag": 1, "test": "ssr_ftest"}))

    return cases


def test_every_registered_p7_operation_completes_through_its_adapter() -> None:
    """This is the live-call guard: the denominator comes from the registry."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    cases = _cases()
    operation_ids = set(p7_pack_registry.operation_ids())
    assert {key for key in cases if ":" not in key} == operation_ids
    failures: list[str] = []
    for operation_id in sorted(operation_ids):
        frame, request = cases[operation_id]
        operation = p7_pack_registry.get(operation_id)
        try:
            operation.validate(request)
            result = operation.execute(frame, request)
            operation.validate_result(result)
            assert result["operation_id"] == operation_id
            assert result.get("status") in {None, "completed"}
        except Exception as exc:  # report all missing calls in one red test
            failures.append(f"{operation_id}: {type(exc).__name__}: {exc}")
    assert not failures, "P7 adapter calls failed:\n" + "\n".join(failures)


def test_vif_completes_from_a_design_frame_without_a_fake_model_payload() -> None:
    """The design-only VIF path must not require a fabricated response model."""

    from workbench.agent.p7_pack_registry import p7_pack_registry

    operation = p7_pack_registry.get("diagnostics.vif")
    request = _request(
        "diagnostics.vif",
        "typed",
        {"design": ["x1", "x2"]},
    )
    frame = pd.DataFrame(
        {
            "x1": np.linspace(-2.0, 2.0, 30),
            "x2": np.cos(np.linspace(-1.5, 1.5, 30)),
        }
    )

    operation.validate(request)
    result = operation.execute(frame, request)
    operation.validate_result(result)

    assert result["operation_id"] == "diagnostics.vif"
    assert result["status"] == "completed"
    assert set(result["result"]["vif"]) == {"x1", "x2"}


@pytest.mark.parametrize("design", ["independent_t", "one_way_anova", "two_proportion_z"])
@pytest.mark.parametrize("solve_for", ["power", "sample_size", "effect_size", "alpha"])
def test_power_adapter_completes_every_declared_design_target(design: str, solve_for: str) -> None:
    from workbench.agent.p7_pack_registry import p7_pack_registry

    operation = p7_pack_registry.get("power_analysis.solve")
    request = _request("power_analysis.solve", "typed", options=_power_options(design, solve_for))
    operation.validate(request)
    result = operation.execute(None, request)
    operation.validate_result(result)
    assert result["operation_id"] == "power_analysis.solve"
    assert result["payload"]["design"] == design
    assert result["payload"]["solve_for"] == solve_for
