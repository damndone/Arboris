"""v1.8.10 step 1a: every fitted model leaves an inference kernel behind.

Post-estimation (Wald, LR, lincom, margins) has to read the coefficient
covariance instead of refitting, so each run persists the parameter vector,
its covariance, the reference distribution and the log-likelihood -- or an
explicit record of why one of those is not available.
"""

from __future__ import annotations

import math
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import statsmodels.formula.api as smf

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import (
    INFERENCE_KERNEL_CONTRACT,
    MAX_FULL_VCOV_PARAMS,
    InferenceKernelError,
    build_inference_kernel,
    kernel_relative_path,
    resolve_inference_kernel,
    unavailable_inference_kernel,
    validate_inference_kernel,
)
from workbench.orchestrator import run_workflow
from workbench.projects import create_project
from workbench.services.results_service import read_model_results


def _cross(n: int = 300, seed: int = 7) -> pd.DataFrame:
    rng = np.random.default_rng(seed)
    x1 = rng.normal(size=n)
    x2 = rng.normal(size=n)
    eta = 0.5 * x1 - 0.3 * x2
    frame = pd.DataFrame({
        "x1": x1,
        "x2": x2,
        "g": rng.choice(["a", "b", "c"], size=n),
        "y": 1 + eta + rng.normal(size=n),
        "yb": (rng.random(n) < 1 / (1 + np.exp(-eta))).astype(int),
        "yc": rng.poisson(np.exp(0.3 + eta)),
        "z": x1 + rng.normal(size=n),
    })
    frame["yo"] = pd.cut(
        eta + rng.logistic(size=n), [-np.inf, -0.5, 0.5, np.inf], labels=["low", "mid", "high"]
    ).astype(str)
    frame["xe"] = 0.6 * frame["z"] + rng.normal(size=n)
    frame["yiv"] = 1 + 0.5 * frame["xe"] + 0.3 * frame["x2"] + rng.normal(size=n)
    return frame


def _staggered() -> pd.DataFrame:
    rng = np.random.default_rng(11)
    rows = []
    for i in range(40):
        cohort = [0, 2019, 2020, 2021][i % 4]
        fe = float(rng.normal())
        x1 = float(rng.normal())
        for year in range(2017, 2023):
            treated = 1 if (cohort and year >= cohort) else 0
            xt = float(rng.normal())
            rows.append({
                "id": f"u{i:02d}", "year": year, "first_treat": cohort, "x1": x1, "xt": xt,
                "treat": 1 if cohort else 0, "post": 1 if year >= 2020 else 0,
                "y": fe + 0.1 * (year - 2017) + 0.3 * x1 + 0.2 * xt + 2.0 * treated + 0.05 * rng.normal(),
            })
    return pd.DataFrame(rows)


def _survival() -> pd.DataFrame:
    return pd.DataFrame({
        "duration": [1, 2, 3, 4, 5, 6, 7, 8] * 8,
        "event": [1, 1, 0, 1, 0, 1, 0, 1] * 8,
        "group": [0, 0, 1, 1, 0, 1, 0, 1] * 8,
        "x": [float(i % 5) for i in range(64)],
    })


def _run(tmp_path: Path, frame: pd.DataFrame, *, model_type: str, **kwargs) -> Path:
    tmp_path.mkdir(parents=True, exist_ok=True)
    source = tmp_path / f"{model_type}.csv"
    frame.to_csv(source, index=False)
    project = create_project(tmp_path, model_type)
    result = run_workflow(project.root, [source], mode="auto", model_type=model_type, **kwargs)
    assert result["status"] == "completed", result
    return project.root / "runs" / result["run_id"]


def _kernel(run_root: Path, model_id: str) -> dict:
    kernel = read_json(run_root / kernel_relative_path(model_id))
    validate_inference_kernel(kernel)
    return kernel


def test_ols_kernel_matches_an_independent_statsmodels_fit(tmp_path: Path) -> None:
    frame = _cross()
    run_root = _run(tmp_path, frame, model_type="ols", y="y", x=["x1", "x2"])
    kernel = _kernel(run_root, "ols_1")

    reference = smf.ols("y ~ x1 + x2", frame).fit(cov_type="HC1")
    assert kernel["contract"] == INFERENCE_KERNEL_CONTRACT
    assert kernel["param_names"] == list(reference.params.index)
    np.testing.assert_allclose(kernel["params"], reference.params.to_numpy(), rtol=0, atol=1e-10)
    np.testing.assert_allclose(
        np.asarray(kernel["vcov"]), reference.cov_params().to_numpy(), rtol=1e-9, atol=1e-14
    )
    assert kernel["nobs"] == 300
    assert kernel["vcov_scope"] == "full"
    assert set(kernel["interfaces"]) == {"coef_vcov", "loglik"}
    assert math.isclose(kernel["loglik"], reference.llf, rel_tol=1e-12)
    assert kernel["df_resid"] == pytest.approx(297)


FAMILY_CASES = [
    ("ols", "ols_1", "cross", {"y": "y", "x": ["x1", "x2"]}),
    ("logit", "logit_1", "cross", {"y": "yb", "x": ["x1", "x2"]}),
    ("probit", "probit_1", "cross", {"y": "yb", "x": ["x1", "x2"]}),
    ("poisson", "poisson_1", "cross", {"y": "yc", "x": ["x1", "x2"]}),
    ("negative_binomial", "negative_binomial_1", "cross", {"y": "yc", "x": ["x1", "x2"]}),
    ("iv_2sls", "iv_2sls_1", "cross", {"y": "yiv", "x": ["x2"], "iv_endog": ["xe"], "iv_instruments": ["z"]}),
    ("ordinal_logit", "ordinal_logit_1", "cross", {"y": "yo", "x": ["x1", "x2"]}),
    ("multinomial_logit", "multinomial_logit_1", "cross", {"y": "g", "x": ["x1", "x2"]}),
    ("quantile_regression", "quantile_regression_1", "cross", {"y": "y", "x": ["x1", "x2"]}),
    ("survival_cox", "survival_cox_1", "survival", {
        "y": "duration", "x": ["x"], "model_options": {"event_column": "event"},
    }),
    ("cs_did", "cs_did_1", "staggered", {
        "y": "y", "x": ["x1"], "entity_col": "id", "time_col": "year", "did_mode": "cohort",
        "did_cohort_col": "first_treat", "cs_control_group": "never", "cs_est_method": "dr",
        "cs_base_period": "varying",
    }),
    ("panel_ols", "panel_ols_1", "staggered", {"y": "y", "x": ["xt"], "entity_col": "id", "time_col": "year"}),
    ("did", "did_1", "staggered", {
        "y": "y", "x": [], "entity_col": "id", "time_col": "year", "did_mode": "two_by_two",
        "did_treat_col": "treat", "did_post_col": "post",
    }),
    ("sa_did", "sa_did_1", "staggered", {
        "y": "y", "x": [], "entity_col": "id", "time_col": "year", "did_mode": "cohort",
        "did_cohort_col": "first_treat",
    }),
]
FRAMES = {"cross": _cross, "survival": _survival, "staggered": _staggered}


@pytest.mark.parametrize(("model_type", "model_id", "frame_name", "kwargs"), FAMILY_CASES)
def test_kernel_covariance_agrees_with_every_reported_standard_error(
    tmp_path: Path, model_type: str, model_id: str, frame_name: str, kwargs: dict
) -> None:
    run_root = _run(tmp_path, FRAMES[frame_name](), model_type=model_type, **kwargs)
    kernel = _kernel(run_root, model_id)
    packet = read_json(run_root / "model_results" / f"{model_id}.json")

    assert "coef_vcov" in kernel["interfaces"], kernel["unavailable"]
    names = kernel["param_names"]
    variances = np.diag(np.asarray(kernel["vcov"], dtype=float))
    checked = 0
    for term, row in packet["coefficients"].items():
        standard_error = row.get("std_error") if isinstance(row, dict) else None
        if standard_error is None or not math.isfinite(standard_error):
            continue
        assert term in names, f"{term} missing from kernel names {names}"
        assert math.sqrt(variances[names.index(term)]) == pytest.approx(standard_error, rel=1e-8)
        checked += 1
    assert checked > 0
    assert kernel["nobs"] == packet["nobs"]


def _assert_diagonal_matches_packet(kernel: dict, packet: dict) -> None:
    names = kernel["vcov_param_names"]
    variances = np.diag(np.asarray(kernel["vcov"], dtype=float))
    for term, row in packet["coefficients"].items():
        assert math.sqrt(variances[names.index(term)]) == pytest.approx(row["std_error"], rel=1e-8), term


def test_survey_design_kernel_carries_the_design_variance_not_the_naive_one(tmp_path: Path) -> None:
    """Otherwise a joint test would quietly use the variance the run replaced."""
    source = tmp_path / "svy.csv"
    source.write_text((Path(__file__).parent / "fixtures" / "survey" / "design.csv").read_text())
    project = create_project(tmp_path, "svy")
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="ols", y="y", x=["x1", "x2"],
        sampling_weight="weight", survey_strata_col="stratum", survey_psu_col="psu",
    )
    assert outcome["status"] == "completed", outcome
    run_root = project.root / "runs" / outcome["run_id"]
    kernel = _kernel(run_root, "ols_1")
    packet = read_json(run_root / "model_results" / "ols_1.json")

    _assert_diagonal_matches_packet(kernel, packet)
    assert kernel["covariance_estimator"].startswith("survey_design_")
    assert kernel["reference_distribution"] == "t"
    assert kernel["df_resid"] == packet["survey_design"]["residual_degf"]
    assert "loglik" not in kernel["interfaces"]
    assert "design-based" in kernel["unavailable"]["loglik"]
    assert kernel["weights"] == "sampling"


def test_clustered_ols_kernel_matches_the_reported_cluster_standard_errors(tmp_path: Path) -> None:
    run_root = _run(
        tmp_path, _staggered(), model_type="ols", y="y", x=["x1"],
        entity_col="id", time_col="year", covariance="clustered",
    )
    kernel = _kernel(run_root, "ols_1")
    packet = read_json(run_root / "model_results" / "ols_1.json")
    _assert_diagonal_matches_packet(kernel, packet)
    assert kernel["covariance_estimator"] == "cluster"


def test_instrumental_variables_declare_no_likelihood(tmp_path: Path) -> None:
    run_root = _run(
        tmp_path, _cross(), model_type="iv_2sls", y="yiv", x=["x2"], iv_endog=["xe"], iv_instruments=["z"]
    )
    kernel = _kernel(run_root, "iv_2sls_1")
    assert "loglik" not in kernel["interfaces"]
    assert kernel["loglik"] is None
    assert kernel["unavailable"]["loglik"]


def test_kernel_files_are_not_read_as_model_results(tmp_path: Path) -> None:
    run_root = _run(tmp_path, _cross(), model_type="ols", y="y", x=["x1", "x2"])
    assert (run_root / kernel_relative_path("ols_1")).is_file()
    results = read_model_results(run_root)
    assert [result.get("model_id") for result in results] == ["ols_1"]


def test_resolve_prefers_a_recorded_kernel_then_the_fitted_object_then_says_why_not() -> None:
    recorded = build_inference_kernel(
        model_id="m_1", model_type="custom", param_names=["a"], params=[1.0], vcov=[[0.25]],
        reference_distribution="z", df_resid=None, loglik=None, nobs=10, covariance_estimator="nonrobust",
    )
    assert resolve_inference_kernel(
        model_id="m_1", model_type="custom", primary={"nobs": 10}, fitted=None, recorded=recorded
    ) == recorded

    missing = resolve_inference_kernel(
        model_id="m_1", model_type="custom", primary={"nobs": 10}, fitted=object(), recorded=None
    )
    validate_inference_kernel(missing)
    assert missing["interfaces"] == []
    assert missing["unavailable"]["coef_vcov"]


def test_unavailable_kernel_states_a_reason() -> None:
    kernel = unavailable_inference_kernel(
        model_id="x_1", model_type="x", nobs=5, reason="The runtime exposes no covariance."
    )
    validate_inference_kernel(kernel)
    assert kernel["vcov"] is None and kernel["vcov_scope"] == "unavailable"
    with pytest.raises(InferenceKernelError):
        unavailable_inference_kernel(model_id="x_1", model_type="x", nobs=5, reason="")


def test_large_models_keep_only_the_focal_covariance() -> None:
    k = MAX_FULL_VCOV_PARAMS + 1
    names = [f"b{i}" for i in range(k)]
    params = [0.0] * k
    vcov = np.eye(k).tolist()

    focal = build_inference_kernel(
        model_id="big_1", model_type="ols", param_names=names, params=params, vcov=vcov,
        reference_distribution="t", df_resid=1000.0, loglik=-1.0, nobs=2000,
        covariance_estimator="nonrobust", focal_param_names=["b0", "b3"],
    )
    assert focal["vcov_scope"] == "focal"
    assert focal["vcov_param_names"] == ["b0", "b3"]
    assert np.asarray(focal["vcov"]).shape == (2, 2)
    assert "coef_vcov" in focal["interfaces"]

    none = build_inference_kernel(
        model_id="big_1", model_type="ols", param_names=names, params=params, vcov=vcov,
        reference_distribution="t", df_resid=1000.0, loglik=-1.0, nobs=2000,
        covariance_estimator="nonrobust",
    )
    assert none["vcov_scope"] == "unavailable" and none["vcov"] is None
    assert "coef_vcov" not in none["interfaces"]
    assert str(k) in none["unavailable"]["coef_vcov"]


@pytest.mark.parametrize(
    "vcov",
    [
        [[1.0, 0.0]],
        [[1.0, 0.5], [0.4, 1.0]],
        [[1.0, 0.0], [0.0, float("nan")]],
        [[-1.0, 0.0], [0.0, 1.0]],
    ],
)
def test_invalid_covariance_is_rejected(vcov: list) -> None:
    with pytest.raises(InferenceKernelError):
        build_inference_kernel(
            model_id="m_1", model_type="ols", param_names=["a", "b"], params=[1.0, 2.0], vcov=vcov,
            reference_distribution="t", df_resid=10.0, loglik=None, nobs=12, covariance_estimator="HC1",
        )


def test_duplicate_parameter_names_are_rejected() -> None:
    with pytest.raises(InferenceKernelError):
        build_inference_kernel(
            model_id="m_1", model_type="ols", param_names=["a", "a"], params=[1.0, 2.0],
            vcov=[[1.0, 0.0], [0.0, 1.0]], reference_distribution="t", df_resid=10.0, loglik=None,
            nobs=12, covariance_estimator="HC1",
        )


class _FakeFit:
    def __init__(self, cov, *, raises: bool = False) -> None:
        self.params = pd.Series([1.0, 2.0], index=["a", "b"])
        self._cov = cov
        self._raises = raises
        self.nobs = 40
        self.use_t = True
        self.df_resid = 38.0
        self.llf = -10.0

    def cov_params(self):
        if self._raises:
            raise np.linalg.LinAlgError("singular")
        return self._cov


def test_an_unusable_covariance_is_explained_instead_of_failing_the_run() -> None:
    from workbench.contracts.model.inference_kernel import kernel_from_fitted

    kernel = kernel_from_fitted(
        _FakeFit(np.array([[1.0, 0.0], [0.0, np.nan]])), model_id="m_1", model_type="logit", nobs=40
    )
    validate_inference_kernel(kernel)
    assert kernel["interfaces"] == []
    assert "could not be used" in kernel["unavailable"]["coef_vcov"]

    failed = kernel_from_fitted(_FakeFit(None, raises=True), model_id="m_1", model_type="logit", nobs=40)
    validate_inference_kernel(failed)
    assert "failed to produce" in failed["unavailable"]["coef_vcov"]


def test_rounding_noise_below_zero_is_not_a_negative_variance() -> None:
    kernel = build_inference_kernel(
        model_id="m_1", model_type="ols", param_names=["a", "b"], params=[1.0, 2.0],
        vcov=[[1.0, 0.0], [0.0, -1e-20]], reference_distribution="t", df_resid=10.0, loglik=None,
        nobs=12, covariance_estimator="nonrobust",
    )
    assert "coef_vcov" in kernel["interfaces"]


def test_a_full_size_kernel_stays_within_the_two_megabyte_budget(tmp_path: Path) -> None:
    from workbench.artifacts import initialize_artifact_index
    from workbench.orchestrator import _write_inference_kernel

    k = MAX_FULL_VCOV_PARAMS
    rng = np.random.default_rng(0)
    a = rng.normal(size=(k, k))
    kernel = build_inference_kernel(
        model_id="big_1", model_type="ols", param_names=[f"b{i}" for i in range(k)],
        params=rng.normal(size=k).tolist(), vcov=(a @ a.T / k).tolist(), reference_distribution="t",
        df_resid=1000.0, loglik=-1.0, nobs=2000, covariance_estimator="nonrobust",
    )
    initialize_artifact_index(tmp_path)
    _write_inference_kernel(tmp_path, kernel, inputs=["big_1"])
    path = tmp_path / kernel_relative_path("big_1")
    assert path.stat().st_size <= 2_000_000
    assert read_json(path) == kernel


def test_a_family_without_a_kernel_interface_still_records_why(tmp_path: Path) -> None:
    source = tmp_path / "an.csv"
    source.write_text((Path(__file__).parent / "fixtures" / "anova" / "anova.csv").read_text())
    project = create_project(tmp_path, "an")
    outcome = run_workflow(
        project.root, [source], mode="auto", model_type="anova", y="score",
        x=["factor_a", "factor_b", "covariate"],
        model_options={"sums_of_squares": 3, "categorical": ["factor_a", "factor_b"]},
    )
    assert outcome["status"] == "completed", outcome
    kernels = list((project.root / "runs" / outcome["run_id"] / "model_results" / "inference_kernels").glob("*.json"))
    assert kernels, "the run left no inference kernel record"
    for path in kernels:
        kernel = read_json(path)
        validate_inference_kernel(kernel)
        for interface in ("coef_vcov", "loglik"):
            assert interface in kernel["interfaces"] or kernel["unavailable"][interface]


def test_the_sample_fingerprint_identifies_the_rows_a_model_used(tmp_path: Path) -> None:
    """A likelihood-ratio test needs it to refuse models fitted to different rows."""
    frame = _cross()
    same_a = _kernel(_run(tmp_path / "a", frame, model_type="logit", y="yb", x=["x1"]), "logit_1")
    same_b = _kernel(_run(tmp_path / "b", frame, model_type="logit", y="yb", x=["x1", "x2"]), "logit_1")
    assert same_a["estimation_sample_fingerprint"].startswith("rows-sha256:")
    assert same_a["estimation_sample_fingerprint"] == same_b["estimation_sample_fingerprint"]

    gappy = frame.copy()
    gappy.loc[gappy.index[:20], "x2"] = np.nan  # listwise deletion drops 20 rows
    fewer = _kernel(_run(tmp_path / "c", gappy, model_type="logit", y="yb", x=["x1", "x2"]), "logit_1")
    assert fewer["nobs"] == 280
    assert fewer["estimation_sample_fingerprint"] != same_a["estimation_sample_fingerprint"]


@pytest.mark.parametrize(
    ("weight_kwargs", "expected"),
    # Sampling weights come with a design; the survey test above covers them.
    [({}, "none"), ({"analysis_weight": "w"}, "analysis"), ({"frequency_weight": "w"}, "frequency")],
)
def test_the_kernel_says_how_the_sample_was_weighted(tmp_path: Path, weight_kwargs, expected) -> None:
    """A likelihood-ratio test is not valid under probability weights; the
    kernel is all post-estimation reads, so it has to carry the fact."""
    frame = _cross()
    frame["w"] = 1 + (np.arange(len(frame)) % 3)
    run_root = _run(tmp_path, frame, model_type="ols", y="y", x=["x1", "x2"], **weight_kwargs)
    assert _kernel(run_root, "ols_1")["weights"] == expected
