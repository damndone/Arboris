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

FIXTURES = Path(__file__).parents[1] / "fixtures" / "eval_v1810" / "a01"

# oracle case -> (model_type, outcome, run arguments)
CASES = {
    "ols": ("ols", "y", {"covariance": "unadjusted"}),
    "ols_robust": ("ols", "y", {}),
    "logit": ("logit", "yb", {}),
}


@pytest.fixture(scope="module")
def kernels(tmp_path_factory):
    root = tmp_path_factory.mktemp("mi-pool")
    cache: dict[str, list[dict]] = {}

    def fitted(case: str, m: int) -> list[dict]:
        key = (case, m)
        if key not in cache:
            model_type, y, extra = CASES[case]
            cache[key] = []
            for index in range(1, m + 1):
                project = create_project(root, f"{case}-{m}-{index}")
                run_workflow(
                    project.root, [FIXTURES / f"m{m}" / f"imputed_{index}.csv"], mode="auto",
                    model_type=model_type, y=y, x=["x1", "x2", "x3"], **extra,
                )
                run_root = next((project.root / "runs").iterdir())
                cache[key].append(read_json(run_root / kernel_relative_path(f"{model_type}_1")))
        return cache[key]

    return fitted


@pytest.mark.parametrize("m", [2, 20])
@pytest.mark.parametrize("case", sorted(CASES))
def test_pooled_results_match_mice_pool(kernels, case: str, m: int) -> None:
    fitted = kernels(case, m)
    require_poolable(fitted[0]["model_type"], fitted[0])
    pooled = pool_kernels(fitted)
    expected = json.loads((FIXTURES / f"m{m}" / "oracle.json").read_text())["cases"][case]
    print("case/data/formula", case, m, str(FIXTURES / f"m{m}"), CASES[case], ["x1", "x2", "x3"])
    print("kernel settings", {key: fitted[0].get(key) for key in (
        "covariance_estimator", "df_method", "reference_distribution", "df_resid", "nobs")})
    print("first three pooled coefficients and standard errors", [
        (term, pooled["terms"][term]["estimate"], reference["estimate"],
         pooled["terms"][term]["std_error"], reference["std_error"])
        for term, reference in list(expected["terms"].items())[:3]])
    tolerance = 1e-7
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
