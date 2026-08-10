from __future__ import annotations

from copy import deepcopy
import json
import math

import pytest
from statsmodels.stats.power import FTestAnovaPower, NormalIndPower, TTestIndPower


def _valid_result_kwargs() -> dict[str, object]:
    return _valid_result_kwargs_for_design("independent_t", "power", 0.75)


def _add_evidence_digest(kwargs: dict[str, object]) -> dict[str, object]:
    from workbench.canonical import sha256_canonical
    from workbench.contracts.model.power_analysis import (
        POWER_ANALYSIS_CONTRACT,
        POWER_ANALYSIS_CONTRACT_VERSION,
        POWER_ANALYSIS_COMPLETED,
    )

    payload = {
        "contract": POWER_ANALYSIS_CONTRACT,
        "contract_version": POWER_ANALYSIS_CONTRACT_VERSION,
        "status": kwargs.get("status", "completed"),
        "reason_code": kwargs.get("reason_code", POWER_ANALYSIS_COMPLETED),
        "design": kwargs["design"],
        "solve_for": kwargs["solve_for"],
        "effect_size_type": kwargs["effect_size_type"],
        "design_semantics": kwargs["design_semantics"],
        "inputs": kwargs["inputs"],
        "solved_value": kwargs["solved_value"],
        "provenance": kwargs["provenance"],
    }
    if "sensitivity_grid" in kwargs:
        payload["sensitivity_grid"] = kwargs["sensitivity_grid"]
    updated = dict(kwargs)
    updated["status"] = payload["status"]
    updated["reason_code"] = payload["reason_code"]
    updated["evidence_digest"] = sha256_canonical(payload)
    return updated


def _valid_result_kwargs_for_design(
    design: str, solve_for: str, solved_value: float
) -> dict[str, object]:
    from workbench.contracts.model.power_analysis import PowerAnalysisInput

    if design == "one_way_anova":
        effect_size_type = "cohens_f"
        inputs = {
            "design": design,
            "solve_for": solve_for,
            "effect_size_type": effect_size_type,
            "alpha": 0.05,
            "power": 0.8,
            "sample_size": 90.0,
            "effect_size": 0.25,
            "ratio": None,
            "alternative": None,
            "k_groups": 4,
        }
        sample_semantics = "total_nobs"
        semantics = {
            "family": design,
            "effect_size": effect_size_type,
            "sample_size": sample_semantics,
            "k_groups": 4,
            "rounding_policy": "none",
        }
        solver_class = "FTestAnovaPower"
    else:
        effect_size_type = "cohens_d" if design == "independent_t" else "cohens_h"
        inputs = {
            "design": design,
            "solve_for": solve_for,
            "effect_size_type": effect_size_type,
            "alpha": 0.05,
            "power": 0.8,
            "sample_size": 40.0,
            "effect_size": 0.5,
            "ratio": 1.5,
            "alternative": "two-sided",
            "k_groups": None,
        }
        sample_semantics = "nobs1_per_group"
        semantics = {
            "family": design,
            "effect_size": effect_size_type,
            "sample_size": sample_semantics,
            "ratio": "nobs2_over_nobs1",
            "alternative": "two-sided",
            "rounding_policy": "none",
        }
        solver_class = "TTestIndPower" if design == "independent_t" else "NormalIndPower"

    inputs[solve_for] = None
    inputs = PowerAnalysisInput(**inputs).to_dict()
    return _add_evidence_digest({
        "design": design,
        "solve_for": solve_for,
        "effect_size_type": effect_size_type,
        "design_semantics": semantics,
        "inputs": inputs,
        "solved_value": solved_value,
        "provenance": {
            "library": "statsmodels",
            "version": "0.14.6",
            "solver_class": solver_class,
        },
    })


def test_power_analysis_contract_is_versioned_and_json_safe() -> None:
    from workbench.contracts.model.power_analysis import (
        POWER_ANALYSIS_CONTRACT,
        POWER_ANALYSIS_CONTRACT_VERSION,
        PowerAnalysisInput,
        PowerAnalysisResult,
    )

    request = PowerAnalysisInput(
        design="independent_t",
        solve_for="power",
        effect_size_type="cohens_d",
        alpha=0.05,
        power=None,
        sample_size=40.0,
        effect_size=0.5,
        ratio=1.5,
        alternative="two-sided",
        k_groups=None,
    )
    assert request.to_dict() == {
        "design": "independent_t",
        "solve_for": "power",
        "effect_size_type": "cohens_d",
        "alpha": 0.05,
        "power": None,
        "sample_size": 40.0,
        "effect_size": 0.5,
        "ratio": 1.5,
        "alternative": "two-sided",
        "k_groups": None,
    }

    result = PowerAnalysisResult(**_valid_result_kwargs()).to_dict()
    assert result["contract"] == POWER_ANALYSIS_CONTRACT
    assert result["contract_version"] == POWER_ANALYSIS_CONTRACT_VERSION == "1.0"
    assert json.loads(json.dumps(result, allow_nan=False)) == result


def test_power_analysis_result_requires_closed_status_and_consistent_reason_code() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import (
        POWER_ANALYSIS_COMPLETED,
        POWER_ANALYSIS_FAILED,
        POWER_ANALYSIS_REASON_CODES,
        POWER_ANALYSIS_REJECTED,
        POWER_ANALYSIS_STATUSES,
        PowerAnalysisResult,
    )

    assert POWER_ANALYSIS_STATUSES == frozenset({"completed", "rejected", "failed"})
    assert POWER_ANALYSIS_REASON_CODES == frozenset(
        {POWER_ANALYSIS_COMPLETED, POWER_ANALYSIS_REJECTED, POWER_ANALYSIS_FAILED}
    )
    invalid_pairs = [
        ("completed", "POWER_ANALYSIS_ARBITRARY"),
        ("completed", POWER_ANALYSIS_REJECTED),
        ("rejected", POWER_ANALYSIS_COMPLETED),
        ("failed", POWER_ANALYSIS_COMPLETED),
        ("unsupported", POWER_ANALYSIS_COMPLETED),
    ]
    for status, reason_code in invalid_pairs:
        kwargs = _valid_result_kwargs()
        kwargs["status"] = status
        kwargs["reason_code"] = reason_code
        kwargs = _add_evidence_digest(kwargs)
        with pytest.raises(ContractError):
            PowerAnalysisResult(**kwargs)


def test_power_analysis_result_requires_and_verifies_evidence_digest() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    result = PowerAnalysisResult(**_valid_result_kwargs()).to_dict()
    assert isinstance(result["evidence_digest"], str)
    assert len(result["evidence_digest"]) == 64
    assert PowerAnalysisResult.from_dict(result).to_dict() == result

    missing_digest = dict(result)
    del missing_digest["evidence_digest"]
    with pytest.raises(ContractError):
        PowerAnalysisResult.from_dict(missing_digest)

    tampered = dict(result)
    tampered["solved_value"] = 0.76
    with pytest.raises(ContractError):
        PowerAnalysisResult.from_dict(tampered)

    tampered_inputs = dict(result)
    tampered_inputs["inputs"] = dict(result["inputs"])
    tampered_inputs["inputs"]["effect_size"] = 0.6
    with pytest.raises(ContractError):
        PowerAnalysisResult.from_dict(tampered_inputs)

    constructed = PowerAnalysisResult(**_valid_result_kwargs())
    object.__setattr__(constructed, "evidence_digest", "0" * 64)
    with pytest.raises(ContractError):
        constructed.to_dict()


@pytest.mark.parametrize(
    "field_name",
    ["alpha", "power", "sample_size", "effect_size", "ratio"],
)
@pytest.mark.parametrize("non_finite", [math.nan, math.inf, -math.inf])
def test_power_analysis_input_rejects_non_finite_numbers_and_cannot_serialize_them(
    field_name: str, non_finite: float
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisInput

    values: dict[str, object] = {
        "design": "independent_t",
        "solve_for": "power",
        "effect_size_type": "cohens_d",
        "alpha": 0.05,
        "power": None,
        "sample_size": 40.0,
        "effect_size": 0.5,
        "ratio": 1.5,
        "alternative": "two-sided",
        "k_groups": None,
    }
    values[field_name] = non_finite

    with pytest.raises(ContractError):
        PowerAnalysisInput(**values)


@pytest.mark.parametrize(
    "field_name",
    ["alpha", "power", "sample_size", "effect_size", "ratio"],
)
def test_power_analysis_input_to_dict_rejects_non_finite_state(
    field_name: str,
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisInput

    request = PowerAnalysisInput(
        design="independent_t",
        solve_for="power",
        effect_size_type="cohens_d",
        alpha=0.05,
        power=None,
        sample_size=40.0,
        effect_size=0.5,
        ratio=1.5,
        alternative="two-sided",
        k_groups=None,
    )
    object.__setattr__(request, field_name, math.nan)

    with pytest.raises(ContractError):
        request.to_dict()


@pytest.mark.parametrize(
    "field_name",
    ["alpha", "power", "sample_size", "effect_size", "ratio"],
)
def test_power_analysis_input_rejects_huge_integer_without_overflow(
    field_name: str,
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisInput

    values: dict[str, object] = {
        "design": "independent_t",
        "solve_for": "power",
        "effect_size_type": "cohens_d",
        "alpha": 0.05,
        "power": None,
        "sample_size": 40.0,
        "effect_size": 0.5,
        "ratio": 1.5,
        "alternative": "two-sided",
        "k_groups": None,
    }
    values[field_name] = 10**400

    with pytest.raises(ContractError):
        PowerAnalysisInput(**values)


@pytest.mark.parametrize(
    ("field_name", "solve_for"),
    [
        ("alpha", "power"),
        ("power", "alpha"),
        ("sample_size", "power"),
        ("effect_size", "power"),
        ("ratio", "power"),
    ],
)
def test_solve_power_rejects_huge_integer_without_raw_overflow(
    field_name: str, solve_for: str
) -> None:
    from workbench.engine.packs.power_analysis import PowerAnalysisError, solve_power

    values: dict[str, object] = {
        "design": "independent_t",
        "solve_for": solve_for,
        "effect_size_type": "cohens_d",
        "alpha": 0.05,
        "power": 0.8,
        "sample_size": 40.0,
        "effect_size": 0.5,
        "ratio": 1.5,
        "alternative": "two-sided",
    }
    values[solve_for] = None
    values[field_name] = 10**400

    with pytest.raises(PowerAnalysisError):
        solve_power(**values)


def test_solve_power_grid_rejects_huge_integer_without_raw_overflow() -> None:
    from workbench.engine.packs.power_analysis import PowerAnalysisError, solve_power

    with pytest.raises(PowerAnalysisError):
        solve_power(
            design="independent_t",
            solve_for="power",
            effect_size_type="cohens_d",
            alpha=0.05,
            power=None,
            sample_size=40.0,
            effect_size=0.5,
            ratio=1.5,
            alternative="two-sided",
            sensitivity_grid={"effect_size": [10**400]},
        )


@pytest.mark.parametrize(
    ("design", "solve_for", "solved_value"),
    [
        ("independent_t", "power", 0.0),
        ("independent_t", "power", 1.0),
        ("independent_t", "alpha", 1.0),
        ("independent_t", "sample_size", 1.999),
        ("one_way_anova", "sample_size", 4.0),
        ("independent_t", "effect_size", 0.0),
        ("one_way_anova", "effect_size", -0.1),
    ],
)
def test_power_analysis_result_rejects_out_of_range_completed_solution(
    design: str, solve_for: str, solved_value: float
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    kwargs = _valid_result_kwargs_for_design(design, solve_for, solved_value)

    with pytest.raises(ContractError):
        PowerAnalysisResult(**kwargs)


@pytest.mark.parametrize(
    "design",
    ["independent_t", "two_proportion_z", "one_way_anova"],
)
def test_power_analysis_input_enforces_design_sample_size_minimum(
    design: str,
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisInput

    if design == "one_way_anova":
        values = {
            "design": design,
            "solve_for": "power",
            "effect_size_type": "cohens_f",
            "alpha": 0.05,
            "power": None,
            "sample_size": 4.0,
            "effect_size": 0.25,
            "ratio": None,
            "alternative": None,
            "k_groups": 4,
        }
    else:
        values = {
            "design": design,
            "solve_for": "power",
            "effect_size_type": "cohens_d" if design == "independent_t" else "cohens_h",
            "alpha": 0.05,
            "power": None,
            "sample_size": 1.999,
            "effect_size": 0.5,
            "ratio": 1.5,
            "alternative": "two-sided",
            "k_groups": None,
        }

    with pytest.raises(ContractError):
        PowerAnalysisInput(**values)


def test_power_analysis_input_rejects_huge_anova_group_count_without_overflow() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisInput

    with pytest.raises(ContractError):
        PowerAnalysisInput(
            design="one_way_anova",
            solve_for="power",
            effect_size_type="cohens_f",
            alpha=0.05,
            power=None,
            sample_size=90.0,
            effect_size=0.25,
            ratio=None,
            alternative=None,
            k_groups=10**400,
        )


@pytest.mark.parametrize(
    "sensitivity_grid",
    [
        {},
        {"axes": {}, "scenarios": []},
        {"axes": {"effect_size": []}, "scenarios": []},
        {"axes": {"effect_size": list(range(21))}, "scenarios": []},
        {"axes": {"unknown": [0.4]}, "scenarios": []},
        {"axes": {"effect_size": [10**400]}, "scenarios": []},
        {
            "axes": {"effect_size": [0.4]},
            "scenarios": [{"inputs": {}, "solved_value": 0.75}],
        },
    ],
)
def test_power_analysis_result_rejects_malformed_or_unbounded_sensitivity_grid(
    sensitivity_grid: object,
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    kwargs = _valid_result_kwargs()
    kwargs["sensitivity_grid"] = sensitivity_grid

    with pytest.raises(ContractError):
        PowerAnalysisResult(**kwargs)


def _valid_direct_grid_result() -> dict[str, object]:
    from workbench.engine.packs.power_analysis import solve_power

    return solve_power(
        design="independent_t",
        solve_for="power",
        effect_size_type="cohens_d",
        alpha=0.05,
        power=None,
        sample_size=40.0,
        effect_size=0.5,
        ratio=1.5,
        alternative="two-sided",
        sensitivity_grid={
            "alpha": [0.01, 0.05],
            "effect_size": [0.4, 0.5],
        },
    )


def test_power_analysis_result_rejects_duplicate_and_missing_grid_combinations() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    result = _valid_direct_grid_result()
    grid = deepcopy(result["sensitivity_grid"])
    scenarios = grid["scenarios"]
    scenarios[-1] = deepcopy(scenarios[0])
    result["sensitivity_grid"] = grid

    with pytest.raises(ContractError):
        PowerAnalysisResult.from_dict(result)


def test_power_analysis_result_rejects_non_axis_input_drift_from_base_request() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    result = _valid_direct_grid_result()
    grid = deepcopy(result["sensitivity_grid"])
    grid["scenarios"][0]["inputs"]["ratio"] = 2.0
    result["sensitivity_grid"] = grid

    with pytest.raises(ContractError):
        PowerAnalysisResult.from_dict(result)


def test_power_analysis_result_digest_covers_grid_scenario_evidence() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    result = _valid_direct_grid_result()
    tampered = deepcopy(result)
    tampered["sensitivity_grid"]["scenarios"][0]["solved_value"] += 0.001

    with pytest.raises(ContractError):
        PowerAnalysisResult.from_dict(tampered)


def test_power_analysis_result_rejects_extra_grid_scenario_fields() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    result = _valid_direct_grid_result()
    tampered = deepcopy(result)
    tampered["sensitivity_grid"]["scenarios"][0]["unexpected"] = "drift"

    with pytest.raises(ContractError):
        PowerAnalysisResult.from_dict(tampered)


@pytest.mark.parametrize(
    ("field_name", "value"),
    [
        ("design", "unsupported_design"),
        ("solve_for", "unsupported_target"),
        ("effect_size_type", "cohens_f"),
    ],
)
def test_power_analysis_result_rejects_unsupported_identity_and_effect_mismatch(
    field_name: str, value: str
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    kwargs = _valid_result_kwargs()
    kwargs[field_name] = value
    kwargs["inputs"] = dict(kwargs["inputs"])
    kwargs["inputs"][field_name] = value

    with pytest.raises(ContractError):
        PowerAnalysisResult(**kwargs)


@pytest.mark.parametrize(
    "design_semantics",
    [
        {},
        {"family": "independent_t"},
        {
            "family": "one_way_anova",
            "effect_size": "cohens_d",
            "sample_size": "nobs1_per_group",
            "rounding_policy": "none",
        },
        "not-a-mapping",
    ],
)
def test_power_analysis_result_rejects_empty_or_invalid_design_semantics(
    design_semantics: object,
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    kwargs = _valid_result_kwargs()
    kwargs["design_semantics"] = design_semantics

    with pytest.raises(ContractError):
        PowerAnalysisResult(**kwargs)


@pytest.mark.parametrize(
    "provenance",
    [
        {},
        {"library": "statsmodels", "version": "0.14.6"},
        {
            "library": "other-library",
            "version": "0.14.6",
            "solver_class": "TTestIndPower",
        },
        {
            "library": "statsmodels",
            "version": "",
            "solver_class": "TTestIndPower",
        },
    ],
)
def test_power_analysis_result_rejects_empty_or_invalid_provenance(
    provenance: object,
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    kwargs = _valid_result_kwargs()
    kwargs["provenance"] = provenance

    with pytest.raises(ContractError):
        PowerAnalysisResult(**kwargs)


@pytest.mark.parametrize(
    "input_patch",
    [
        {"power": 0.8},
        {"alpha": None, "power": None},
    ],
)
def test_power_analysis_result_rejects_inputs_whose_unknown_does_not_match_target(
    input_patch: dict[str, object],
) -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.power_analysis import PowerAnalysisResult

    kwargs = _valid_result_kwargs()
    inputs = dict(kwargs["inputs"])
    inputs.update(input_patch)
    kwargs["inputs"] = inputs

    with pytest.raises(ContractError):
        PowerAnalysisResult(**kwargs)


def test_independent_t_solves_power_with_explicit_ratio_and_alternative() -> None:
    from workbench.contracts.model.power_analysis import POWER_ANALYSIS_COMPLETED
    from workbench.engine.packs.power_analysis import solve_power

    result = solve_power(
        design="independent_t",
        solve_for="power",
        effect_size_type="cohens_d",
        alpha=0.05,
        power=None,
        sample_size=40,
        effect_size=0.5,
        ratio=1.5,
        alternative="larger",
    )
    expected = TTestIndPower().power(
        effect_size=0.5,
        nobs1=40,
        alpha=0.05,
        ratio=1.5,
        alternative="larger",
    )

    assert result["status"] == "completed"
    assert result["reason_code"] == POWER_ANALYSIS_COMPLETED
    assert result["design"] == "independent_t"
    assert result["solve_for"] == "power"
    assert result["effect_size_type"] == "cohens_d"
    assert result["design_semantics"] == {
        "family": "independent_t",
        "effect_size": "cohens_d",
        "sample_size": "nobs1_per_group",
        "ratio": "nobs2_over_nobs1",
        "alternative": "larger",
        "rounding_policy": "none",
    }
    assert result["inputs"]["power"] is None
    assert result["solved_value"] == pytest.approx(expected)
    assert result["provenance"]["solver_class"] == "TTestIndPower"


def test_independent_t_solves_sample_size_and_alpha_without_rounding() -> None:
    from workbench.engine.packs.power_analysis import solve_power

    sample_size = solve_power(
        design="independent_t",
        solve_for="sample_size",
        effect_size_type="cohens_d",
        alpha=0.05,
        power=0.8,
        effect_size=0.5,
        ratio=1.0,
        alternative="two-sided",
    )
    expected_nobs1 = TTestIndPower().solve_power(
        effect_size=0.5,
        nobs1=None,
        alpha=0.05,
        power=0.8,
        ratio=1.0,
        alternative="two-sided",
    )
    assert sample_size["solved_value"] == pytest.approx(expected_nobs1)
    assert sample_size["design_semantics"]["sample_size"] == "nobs1_per_group"

    alpha = solve_power(
        design="independent_t",
        solve_for="alpha",
        effect_size_type="cohens_d",
        alpha=None,
        power=0.8,
        sample_size=40,
        effect_size=0.5,
        ratio=1.0,
        alternative="two-sided",
    )
    expected_alpha = TTestIndPower().solve_power(
        effect_size=0.5,
        nobs1=40,
        alpha=None,
        power=0.8,
        ratio=1.0,
        alternative="two-sided",
    )
    assert alpha["solved_value"] == pytest.approx(expected_alpha)


def test_one_way_anova_solves_total_sample_size_with_explicit_group_count() -> None:
    from workbench.engine.packs.power_analysis import solve_power

    result = solve_power(
        design="one_way_anova",
        solve_for="sample_size",
        effect_size_type="cohens_f",
        alpha=0.05,
        power=0.8,
        sample_size=None,
        effect_size=0.25,
        ratio=None,
        alternative=None,
        k_groups=4,
    )
    expected = FTestAnovaPower().solve_power(
        effect_size=0.25,
        nobs=None,
        alpha=0.05,
        power=0.8,
        k_groups=4,
    )
    assert result["solved_value"] == pytest.approx(expected)
    assert result["design_semantics"] == {
        "family": "one_way_anova",
        "effect_size": "cohens_f",
        "sample_size": "total_nobs",
        "k_groups": 4,
        "rounding_policy": "none",
    }


def test_two_proportion_z_solves_effect_size_with_explicit_allocation() -> None:
    from workbench.engine.packs.power_analysis import solve_power

    result = solve_power(
        design="two_proportion_z",
        solve_for="effect_size",
        effect_size_type="cohens_h",
        alpha=0.05,
        power=0.8,
        sample_size=50,
        effect_size=None,
        ratio=2.0,
        alternative="two-sided",
    )
    expected = NormalIndPower().solve_power(
        effect_size=None,
        nobs1=50,
        alpha=0.05,
        power=0.8,
        ratio=2.0,
        alternative="two-sided",
    )
    assert result["solved_value"] == pytest.approx(expected)
    assert result["design_semantics"]["sample_size"] == "nobs1_per_group"
    assert result["design_semantics"]["effect_size"] == "cohens_h"


def test_power_analysis_rejects_wrong_effect_labels_and_implicit_design_options() -> None:
    from workbench.engine.packs.power_analysis import PowerAnalysisError, solve_power

    common = {
        "solve_for": "power",
        "alpha": 0.05,
        "power": None,
        "sample_size": 40,
        "effect_size": 0.5,
    }
    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_EFFECT_SIZE_LABEL"):
        solve_power(
            design="independent_t",
            effect_size_type="cohens_f",
            ratio=1.0,
            alternative="two-sided",
            **common,
        )
    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_REQUIRED_PARAMETER"):
        solve_power(
            design="independent_t",
            effect_size_type="cohens_d",
            ratio=None,
            alternative="two-sided",
            **common,
        )
    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_REQUIRED_PARAMETER"):
        solve_power(
            design="one_way_anova",
            effect_size_type="cohens_f",
            ratio=None,
            alternative=None,
            k_groups=None,
            **common,
        )


@pytest.mark.parametrize(
    ("missing", "solve_for"),
    [("alpha", "alpha"), ("power", "power"), ("sample_size", "sample_size"), ("effect_size", "effect_size")],
)
def test_power_analysis_requires_exactly_one_declared_unknown(
    missing: str, solve_for: str
) -> None:
    from workbench.engine.packs.power_analysis import PowerAnalysisError, solve_power

    values = {
        "alpha": 0.05,
        "power": 0.8,
        "sample_size": 40,
        "effect_size": 0.5,
    }
    values[missing] = None
    result = solve_power(
        design="independent_t",
        solve_for=solve_for,
        effect_size_type="cohens_d",
        ratio=1.0,
        alternative="two-sided",
        **values,
    )
    assert result["solve_for"] == solve_for

    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_UNKNOWN_COUNT"):
        solve_power(
            design="independent_t",
            solve_for=solve_for,
            effect_size_type="cohens_d",
            ratio=1.0,
            alternative="two-sided",
            alpha=0.05,
            power=0.8,
            sample_size=40,
            effect_size=0.5,
        )
    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_UNKNOWN_COUNT"):
        solve_power(
            design="independent_t",
            solve_for=solve_for,
            effect_size_type="cohens_d",
            ratio=1.0,
            alternative="two-sided",
            alpha=None,
            power=None,
            sample_size=40,
            effect_size=0.5,
        )


def test_power_analysis_is_deterministic_and_never_emits_non_json_numbers() -> None:
    from workbench.engine.packs.power_analysis import solve_power

    kwargs = {
        "design": "two_proportion_z",
        "solve_for": "power",
        "effect_size_type": "cohens_h",
        "alpha": 0.05,
        "power": None,
        "sample_size": 50,
        "effect_size": 0.4,
        "ratio": 1.25,
        "alternative": "two-sided",
    }
    first = solve_power(**kwargs)
    second = solve_power(**kwargs)
    assert first == second
    assert json.loads(json.dumps(first, allow_nan=False)) == first
    assert math.isfinite(first["solved_value"])


def test_bounded_sensitivity_grid_returns_every_scenario_without_a_winner() -> None:
    from workbench.engine.packs.power_analysis import solve_power, solve_power_grid

    kwargs = {
        "design": "independent_t",
        "solve_for": "power",
        "effect_size_type": "cohens_d",
        "alpha": 0.05,
        "power": None,
        "sample_size": 40,
        "effect_size": 0.5,
        "ratio": 1.0,
        "alternative": "two-sided",
    }
    axes = {"effect_size": [0.4, 0.5], "alpha": [0.01, 0.05]}
    result = solve_power(**kwargs, sensitivity_grid=axes)
    helper_result = solve_power_grid(**kwargs, axes=axes)

    assert result == helper_result
    assert result["sensitivity_grid"]["axes"] == {
        "alpha": [0.01, 0.05],
        "effect_size": [0.4, 0.5],
    }
    scenarios = result["sensitivity_grid"]["scenarios"]
    assert len(scenarios) == 4
    assert {scenario["inputs"]["effect_size"] for scenario in scenarios} == {0.4, 0.5}
    assert {scenario["inputs"]["alpha"] for scenario in scenarios} == {0.01, 0.05}
    assert all("solved_value" in scenario for scenario in scenarios)
    assert "winner" not in result["sensitivity_grid"]


def test_solve_power_grid_rejects_unknown_kwargs_with_stable_power_error() -> None:
    from workbench.engine.packs.power_analysis import PowerAnalysisError, solve_power_grid

    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_UNKNOWN_PARAMETER"):
        solve_power_grid(
            axes={"effect_size": [0.4]},
            design="independent_t",
            solve_for="power",
            effect_size_type="cohens_d",
            alpha=0.05,
            power=None,
            sample_size=40,
            effect_size=0.5,
            ratio=1.0,
            alternative="two-sided",
            typo_parameter=0.1,
        )


def test_sensitivity_grid_rejects_unbounded_nonfinite_and_target_axes() -> None:
    from workbench.engine.packs.power_analysis import PowerAnalysisError, solve_power

    kwargs = {
        "design": "independent_t",
        "solve_for": "power",
        "effect_size_type": "cohens_d",
        "alpha": 0.05,
        "power": None,
        "sample_size": 40,
        "effect_size": 0.5,
        "ratio": 1.0,
        "alternative": "two-sided",
    }
    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_GRID_BOUNDS"):
        solve_power(**kwargs, sensitivity_grid={"effect_size": list(range(21))})
    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_GRID_FINITE"):
        solve_power(**kwargs, sensitivity_grid={"effect_size": [0.5, math.inf]})
    with pytest.raises(PowerAnalysisError, match="POWER_ANALYSIS_GRID_TARGET"):
        solve_power(**kwargs, sensitivity_grid={"power": [0.7, 0.8]})
