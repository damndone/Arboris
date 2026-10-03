"""v1.8.10 step 5: Rubin pooling with Barnard-Rubin df, against mice::pool.

The five completed datasets are R's (tests/fixtures/multiple_imputation), so
the comparison isolates what Workbench owns: each dataset is fitted by the real
pipeline, its inference kernel read back, and the kernels pooled. Every
(family, covariance) pair offered for pooling must name an oracle case.
"""

from __future__ import annotations

import json
import math
from pathlib import Path

import pytest

from workbench.artifacts import read_json
from workbench.combinators import MI_VALIDATED, MultipleImputationRefusal, pool_kernels, require_poolable
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "multiple_imputation"
ORACLE = json.loads((FIXTURES / "oracle.json").read_text())
M = ORACLE["meta"]["m"]

# oracle case -> (model_type, outcome, run arguments)
CASES = {
    "ols": ("ols", "y", {"covariance": "unadjusted"}),
    "ols_robust": ("ols", "y", {}),
    "ols_cluster": ("ols", "y", {"covariance": "clustered", "entity_col": "g"}),
    "logit": ("logit", "yb", {}),
}


@pytest.fixture(scope="module")
def kernels(tmp_path_factory):
    root = tmp_path_factory.mktemp("mi-pool")
    cache: dict[str, list[dict]] = {}

    def fitted(case: str) -> list[dict]:
        if case not in cache:
            model_type, y, extra = CASES[case]
            cache[case] = []
            for index in range(1, M + 1):
                project = create_project(root, f"{case}-{index}")
                run_workflow(
                    project.root, [FIXTURES / f"imputed_{index}.csv"], mode="auto",
                    model_type=model_type, y=y, x=["x1", "x2", "x3"], **extra,
                )
                run_root = next((project.root / "runs").iterdir())
                cache[case].append(read_json(run_root / kernel_relative_path(f"{model_type}_1")))
        return cache[case]

    return fitted


def test_every_validated_pair_names_an_existing_oracle_case() -> None:
    named = {case for cases in MI_VALIDATED.values() for case in cases}
    assert named <= set(ORACLE["cases"]), sorted(named - set(ORACLE["cases"]))
    assert named <= set(CASES)


@pytest.mark.parametrize("case", sorted(CASES))
def test_pooled_results_match_mice_pool(kernels, case: str) -> None:
    fitted = kernels(case)
    require_poolable(fitted[0]["model_type"], fitted[0])
    pooled = pool_kernels(fitted)
    expected = ORACLE["cases"][case]
    tolerance = float(ORACLE["tolerances"]["default"])
    dfcom = expected["dfcom"]
    assert pooled["dfcom"] == (None if dfcom == "Inf" else pytest.approx(dfcom))
    assert set(pooled["terms"]) == set(expected["terms"])
    for term, reference in expected["terms"].items():
        ours = pooled["terms"][term]
        for ours_key, ref_key in (
            ("estimate", "estimate"), ("within_variance", "ubar"), ("between_variance", "b"),
            ("total_variance", "t"), ("std_error", "std_error"), ("df", "df"), ("riv", "riv"),
            ("lambda", "lambda"), ("fmi", "fmi"), ("statistic", "statistic"), ("p_value", "p_value"),
            ("ci_lower", "ci_lower"), ("ci_upper", "ci_upper"),
        ):
            # An interval endpoint can sit near zero, where a relative tolerance
            # magnifies the optimiser's last digits; measure it on the scale of
            # its standard error instead.
            absolute = tolerance * reference["std_error"] if ref_key.startswith("ci_") else 1e-12
            assert ours[ours_key] == pytest.approx(reference[ref_key], rel=tolerance, abs=absolute), (
                f"{case} {term} {ours_key}"
            )


def test_an_unvalidated_covariance_is_refused_and_told_what_is_offered(kernels) -> None:
    kernel = dict(kernels("ols")[0], covariance_estimator="HC3")
    with pytest.raises(MultipleImputationRefusal) as caught:
        require_poolable("ols", kernel)
    assert caught.value.code == "NOT_YET_VALIDATED"
    assert "ols with covariance unadjusted, robust or clustered" in caught.value.message


def test_a_family_without_a_covariance_matrix_is_refused() -> None:
    kernel = {"interfaces": [], "vcov_scope": "unavailable",
              "unavailable": {"coef_vcov": "the runtime does not expose one"}}
    with pytest.raises(MultipleImputationRefusal) as caught:
        require_poolable("quantile_regression", kernel)
    assert caught.value.code == "NO_INFERENCE_KERNEL"
    assert "does not expose one" in caught.value.message


def test_imputations_fitted_differently_are_not_pooled(kernels) -> None:
    fitted = [dict(kernel) for kernel in kernels("ols")]
    fitted[2]["covariance_estimator"] = "HC1"
    with pytest.raises(MultipleImputationRefusal) as caught:
        pool_kernels(fitted)
    assert caught.value.code == "IMPUTATIONS_DISAGREE" and "imputation 3" in caught.value.message


def test_one_imputation_is_not_pooled(kernels) -> None:
    with pytest.raises(MultipleImputationRefusal) as caught:
        pool_kernels(kernels("ols")[:1])
    assert caught.value.code == "IMPUTATION_COUNT"


def test_identical_imputations_reduce_to_the_complete_data_fit(kernels) -> None:
    """No between-imputation variance: lambda = 0 and Barnard-Rubin df is
    (dfcom + 1) / (dfcom + 3) * dfcom, slightly below dfcom."""
    one = kernels("ols")[0]
    pooled = pool_kernels([one] * 3)
    dfcom = float(one["df_resid"])
    for j, term in enumerate(one["param_names"]):
        entry = pooled["terms"][term]
        assert entry["between_variance"] == 0 and entry["lambda"] == 0
        assert entry["std_error"] == pytest.approx(math.sqrt(one["vcov"][j][j]))
        assert entry["df"] == pytest.approx((dfcom + 1) / (dfcom + 3) * dfcom)


def test_a_weighted_fit_is_not_pooled_until_a_reference_checks_it(kernels) -> None:
    kernel = dict(kernels("ols")[0], weights="frequency")
    with pytest.raises(MultipleImputationRefusal) as caught:
        require_poolable("ols", kernel)
    assert caught.value.code == "NOT_YET_VALIDATED" and "frequency-weighted" in caught.value.message
