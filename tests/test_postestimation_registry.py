"""v1.8.10 step 2b: an operation is offered for a family only with oracle data.

Every (family, operation) pair in `VALIDATED` names the oracle cases that
validate it; each case is run here against the real pipeline's kernel. Remove a
case from the oracle and this file fails, naming it, until the pair is removed
from the table too.
"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from workbench.artifacts import read_json
from workbench.contracts.model.inference_kernel import kernel_relative_path
from workbench.orchestrator import run_workflow
from workbench.postestimation import PostestimationRefusal
from workbench.postestimation.registry import OPERATIONS, VALIDATED, run_operation
from workbench.projects import create_project

FIXTURES = Path(__file__).parent / "fixtures" / "postestimation"
ORACLE = json.loads((FIXTURES / "oracle.json").read_text())

# oracle family key -> (model_type, outcome, run arguments, parameter prefix)
FAMILIES = {
    "ols": ("ols", "y", {"covariance": "unadjusted"}, ""),
    "ols_robust": ("ols", "y", {}, ""),
    "logit": ("logit", "yb", {}, ""),
    "probit": ("probit", "yb", {}, ""),
    "poisson": ("poisson", "yc", {}, ""),
    "negative_binomial": ("negative_binomial", "ynb", {}, ""),
    "ordinal_logit": ("ordinal_logit", "yo", {"model_options": {"outcome_order": ["low", "mid", "high"]}}, ""),
    "multinomial_logit": ("multinomial_logit", "ym", {"model_options": {"base_category": "a"}}, "b:"),
}

ALL_CASES = sorted({case for cases in VALIDATED.values() for case in cases})


def _missing_cases(oracle: dict) -> list[str]:
    missing = []
    for case in ALL_CASES:
        family, result = case.split(".", 1)
        if result not in oracle["families"].get(family, {}):
            missing.append(case)
    return missing


def _tolerance(family: str) -> float:
    declared = ORACLE["tolerances"].get(family)
    return float(declared["rel"]) if isinstance(declared, dict) else float(ORACLE["tolerances"]["default"])


def _request(case: str, prefix: str) -> tuple[str, dict]:
    result = case.split(".", 1)[1]
    x1, x2 = f"{prefix}x1", f"{prefix}x2"
    if result == "wald_joint":
        return "wald", {"constraints": [{"terms": {x1: 1}, "value": 0}, {"terms": {x2: 1}, "value": 0}]}
    if result == "wald_shifted":
        return "wald", {"constraints": [{"terms": {x1: 1, x2: -1}, "value": 1}]}
    if result == "lincom":
        return "lincom", {"terms": {x1: 1, x2: 2}, "constant": -0.5}
    if result == "nlcom":
        return "nlcom", {"expression": f"b[{x1!r}] / b[{x2!r}]"}
    if result == "lr_drop_x2_x3":
        return "lr", {}
    raise AssertionError(f"no request is defined for oracle result {result}")


@pytest.fixture(scope="module")
def fit(tmp_path_factory):
    root = tmp_path_factory.mktemp("postestimation-registry")
    cache: dict[tuple[str, tuple[str, ...]], dict] = {}

    def kernel(family: str, x: tuple[str, ...] = ("x1", "x2", "x3")) -> dict:
        key = (family, x)
        if key not in cache:
            model_type, y, extra, _ = FAMILIES[family]
            project = create_project(root, f"{family}-{len(x)}")
            outcome = run_workflow(
                project.root, [FIXTURES / "data.csv"], mode="auto", model_type=model_type, y=y,
                x=list(x), **extra,
            )
            assert outcome["status"] == "completed", outcome
            run_root = project.root / "runs" / outcome["run_id"]
            cache[key] = read_json(run_root / kernel_relative_path(f"{model_type}_1"))
        return cache[key]

    return kernel


def test_every_validated_pair_has_its_oracle_cases() -> None:
    assert _missing_cases(ORACLE) == []


def test_removing_an_oracle_case_is_caught_and_named() -> None:
    doctored = json.loads(json.dumps(ORACLE))
    del doctored["families"]["probit"]["lr_drop_x2_x3"]
    assert _missing_cases(doctored) == ["probit.lr_drop_x2_x3"]


@pytest.mark.parametrize("case", ALL_CASES)
def test_each_validated_case_agrees_with_the_reference(fit, case) -> None:
    family = case.split(".", 1)[0]
    prefix = FAMILIES[family][3]
    operation, spec = _request(case, prefix)
    kernels = [fit(family)] if OPERATIONS[operation].kernels == 1 else [fit(family), fit(family, ("x1",))]
    result = run_operation(operation, kernels, spec)
    expected = ORACLE["families"][family][case.split(".", 1)[1]]
    rel = _tolerance(family)
    for key in ("statistic", "estimate", "std_error"):
        if key in expected:
            assert result[key] == pytest.approx(expected[key], rel=rel), key
    for key in ("df_num", "df_den", "df"):
        if key in expected and key in result:
            assert result[key] == expected[key], key
    if "p_value" in expected:
        assert result["p_value"] == pytest.approx(expected["p_value"], rel=max(rel * 10, 1e-5))


def test_a_pair_without_oracle_data_is_refused_with_the_reason(fit) -> None:
    with pytest.raises(PostestimationRefusal) as caught:
        run_operation("nlcom", [fit("ordinal_logit")], {"expression": "x1 / x2"})
    refusal = caught.value
    assert refusal.code == "NOT_YET_VALIDATED"
    assert "not the model's ability" in refusal.message
    assert "wald, lincom are available" in refusal.message


def test_every_operation_is_validated_for_at_least_one_family() -> None:
    assert {operation for _, operation in VALIDATED} == set(OPERATIONS)
