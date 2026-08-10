from __future__ import annotations

import json
import shutil
import subprocess

import numpy as np
import pytest
from scipy.stats import chi2_contingency
from statsmodels.stats.contingency_tables import mcnemar


def test_categorical_result_contract_is_collected_and_json_safe() -> None:
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.categorical import (
        CATEGORICAL_CONTRACT,
        CATEGORICAL_CONTRACT_VERSION,
        CategoricalResultEnvelope,
    )

    cramers_payload = {
        "chi_square": 1.25,
        "degrees_of_freedom": 1,
        "p_value": 0.25,
        "sample_size": 20,
        "cramers_v": 0.25,
        "expected_counts": [[5.0, 5.0], [5.0, 5.0]],
        "expected_count_diagnostics": {
            "cells_below_5": 0,
            "cells_total": 4,
            "fraction_below_5": 0.0,
            "maximum": 5.0,
            "minimum": 5.0,
        },
        "method": "pearson_chi_square",
        "correction": False,
        "correction_policy": "uncorrected",
    }
    mcnemar_payload = {
        "discordant_counts": {"b": 5, "c": 2},
        "statistic": 1.2857142857142858,
        "p_value": 0.2568392579578533,
        "method": "chi_square_asymptotic",
        "exact": False,
        "correction": False,
        "correction_policy": "uncorrected",
        "paired_effect": {
            "discordant_total": 7,
            "discordance_rate": 0.28,
            "directional_discordance": 3 / 7,
        },
    }

    for operation_id, payload in (
        ("categorical.cramers_v", cramers_payload),
        ("categorical.mcnemar", mcnemar_payload),
    ):
        envelope = CategoricalResultEnvelope(
            operation_id=operation_id,
            result=payload,
        )
        value = envelope.to_dict()
        assert set(value) == {
            "contract",
            "contract_version",
            "operation_id",
            "result",
        }
        assert value["contract"] == CATEGORICAL_CONTRACT
        assert value["contract_version"] == CATEGORICAL_CONTRACT_VERSION
        assert CategoricalResultEnvelope.from_dict(value) == envelope
        assert json.loads(json.dumps(value, allow_nan=False)) == value

        additive = {**value, "result": {**value["result"], "future_field": True}}
        assert CategoricalResultEnvelope.from_dict(additive).to_dict() == additive

    missing_cramers_field = {**cramers_payload}
    del missing_cramers_field["cramers_v"]
    with pytest.raises(ContractError, match="missing categorical.cramers_v result field"):
        CategoricalResultEnvelope(
            operation_id="categorical.cramers_v",
            result=missing_cramers_field,
        )

    with pytest.raises(ContractError, match="unknown categorical result field"):
        CategoricalResultEnvelope.from_dict(
            {
                "contract": CATEGORICAL_CONTRACT,
                "contract_version": CATEGORICAL_CONTRACT_VERSION,
                "operation_id": "categorical.cramers_v",
                "result": cramers_payload,
                "extra": True,
            }
        )

    with pytest.raises(ContractError, match="finite"):
        CategoricalResultEnvelope(
            operation_id="categorical.cramers_v",
            result={"chi_square": float("nan")},
        )


def test_cramers_v_reports_scipy_statistics_and_expected_count_diagnostics() -> None:
    from workbench.engine.packs.categorical import fit_cramers_v

    table = [[10, 5], [2, 8]]
    result = fit_cramers_v(table, correction=False)
    payload = result["result"]
    expected = chi2_contingency(table, correction=False)

    assert result["contract"] == "categorical_count.result"
    assert result["contract_version"] == "1.0"
    assert result["operation_id"] == "categorical.cramers_v"
    assert payload["chi_square"] == pytest.approx(expected.statistic)
    assert payload["degrees_of_freedom"] == expected.dof
    assert payload["p_value"] == pytest.approx(expected.pvalue)
    assert payload["sample_size"] == 25
    assert payload["cramers_v"] == pytest.approx(
        np.sqrt(expected.statistic / 25)
    )
    np.testing.assert_allclose(
        payload["expected_counts"], expected.expected_freq.tolist()
    )
    assert payload["expected_count_diagnostics"] == {
        "cells_below_5": 1,
        "cells_total": 4,
        "fraction_below_5": 0.25,
        "maximum": pytest.approx(float(expected.expected_freq.max())),
        "minimum": pytest.approx(float(expected.expected_freq.min())),
    }
    assert payload["method"] == "pearson_chi_square"
    assert payload["correction_policy"] == "uncorrected"


def test_cramers_v_keeps_yates_correction_explicit_and_rejects_non_2x2_request() -> None:
    from workbench.engine.packs.categorical import fit_cramers_v
    from workbench.engine.packs.categorical import CategoricalPackError

    table = [[10, 5], [2, 8]]
    corrected = fit_cramers_v(table, correction=True)
    uncorrected = fit_cramers_v(table, correction=False)
    scipy_corrected = chi2_contingency(table, correction=True)

    assert corrected["result"]["chi_square"] == pytest.approx(
        scipy_corrected.statistic
    )
    assert corrected["result"]["correction_policy"] == "yates_2x2"
    assert corrected["result"]["chi_square"] != uncorrected["result"]["chi_square"]

    with pytest.raises(CategoricalPackError, match="CATEGORICAL_UNSUPPORTED_CORRECTION"):
        fit_cramers_v([[10, 5, 3], [2, 8, 4]], correction=True)


@pytest.mark.parametrize(
    ("exact", "correction", "method", "statsmodels_exact", "statsmodels_correction"),
    [
        (True, False, "exact_binomial", True, False),
        (False, False, "chi_square_asymptotic", False, False),
        (False, True, "chi_square_asymptotic", False, True),
    ],
)
def test_mcnemar_preserves_explicit_method_and_correction_policy(
    exact: bool,
    correction: bool,
    method: str,
    statsmodels_exact: bool,
    statsmodels_correction: bool,
) -> None:
    from workbench.engine.packs.categorical import fit_mcnemar

    table = [[10, 5], [2, 8]]
    result = fit_mcnemar(table, exact=exact, correction=correction)
    payload = result["result"]
    expected = mcnemar(
        table,
        exact=statsmodels_exact,
        correction=statsmodels_correction,
    )

    assert result["operation_id"] == "categorical.mcnemar"
    assert payload["discordant_counts"] == {"b": 5, "c": 2}
    assert payload["statistic"] == pytest.approx(float(expected.statistic))
    assert payload["p_value"] == pytest.approx(float(expected.pvalue))
    assert payload["method"] == method
    assert payload["exact"] is exact
    assert payload["correction"] is correction
    assert payload["correction_policy"] == (
        "not_applicable_exact" if exact else ("yates_continuity" if correction else "uncorrected")
    )
    assert 0.0 <= payload["paired_effect"]["discordance_rate"] <= 1.0
    assert -1.0 <= payload["paired_effect"]["directional_discordance"] <= 1.0


def test_mcnemar_rejects_exact_continuity_correction_that_statsmodels_does_not_apply() -> None:
    from workbench.engine.packs.categorical import CategoricalPackError, fit_mcnemar

    with pytest.raises(CategoricalPackError, match="CATEGORICAL_UNSUPPORTED_CORRECTION"):
        fit_mcnemar([[10, 5], [2, 8]], exact=True, correction=True)


def test_categorical_results_are_deterministic_and_strictly_json_safe() -> None:
    from workbench.engine.packs.categorical import fit_cramers_v, fit_mcnemar

    cramers_first = fit_cramers_v([[10, 5], [2, 8]], correction=False)
    cramers_second = fit_cramers_v([[10, 5], [2, 8]], correction=False)
    mcnemar_first = fit_mcnemar([[10, 5], [2, 8]], exact=False, correction=True)
    mcnemar_second = fit_mcnemar([[10, 5], [2, 8]], exact=False, correction=True)

    assert cramers_first == cramers_second
    assert mcnemar_first == mcnemar_second
    for result in (cramers_first, mcnemar_first):
        assert json.loads(json.dumps(result, allow_nan=False)) == result


@pytest.mark.parametrize(
    "table",
    [
        [[1.0, 2], [3, 4]],
        [[1, -1], [3, 4]],
        [[1, float("nan")], [3, 4]],
        [[1, float("inf")], [3, 4]],
        [[True, 2], [3, 4]],
        [[1, 2], [3]],
        [[1, 2]],
        [[1] * 65, [1] * 65],
    ],
)
def test_cramers_v_rejects_non_integer_unsafe_ragged_or_unbounded_tables(table) -> None:
    from workbench.engine.packs.categorical import CategoricalPackError, fit_cramers_v

    with pytest.raises(CategoricalPackError, match="CATEGORICAL_"):
        fit_cramers_v(table, correction=False)


def test_count_table_validation_does_not_coerce_dataframes_or_integer_floats() -> None:
    import pandas as pd

    from workbench.engine.packs.categorical import CategoricalPackError, fit_cramers_v

    with pytest.raises(CategoricalPackError, match="CATEGORICAL_BAD_TABLE"):
        fit_cramers_v(pd.DataFrame([[1, 2], [3, 4]]), correction=False)
    with pytest.raises(CategoricalPackError, match="CATEGORICAL_NON_INTEGER_COUNT"):
        fit_cramers_v(np.array([[1.0, 2.0], [3.0, 4.0]]), correction=False)


def test_count_not_exact_in_float64_is_rejected_before_backend_conversion() -> None:
    from workbench.engine.packs.categorical import CategoricalPackError, fit_cramers_v
    from workbench.engine.packs.categorical import fit_mcnemar

    not_exact_in_float64 = 2**53 + 1

    with pytest.raises(CategoricalPackError, match="CATEGORICAL_COUNT_NOT_EXACT"):
        fit_cramers_v(
            [[not_exact_in_float64, 1], [1, 1]],
            correction=False,
        )
    with pytest.raises(CategoricalPackError, match="CATEGORICAL_COUNT_NOT_EXACT"):
        fit_mcnemar(
            [[1, not_exact_in_float64], [1, 1]],
            exact=True,
            correction=False,
        )


def test_mcnemar_preserves_exact_integer_discordant_counts() -> None:
    from workbench.engine.packs.categorical import fit_mcnemar

    exactly_representable = 2**53
    result = fit_mcnemar(
        [[0, exactly_representable], [exactly_representable, 0]],
        exact=True,
        correction=False,
    )

    assert result["result"]["discordant_counts"] == {
        "b": exactly_representable,
        "c": exactly_representable,
    }


def test_mcnemar_requires_2x2_and_rejects_no_discordance() -> None:
    from workbench.engine.packs.categorical import CategoricalPackError, fit_mcnemar

    with pytest.raises(CategoricalPackError, match="CATEGORICAL_INVALID_DIMENSIONS"):
        fit_mcnemar([[10, 5, 1], [2, 8, 4]], exact=True, correction=False)
    with pytest.raises(CategoricalPackError, match="CATEGORICAL_NO_DISCORDANCE"):
        fit_mcnemar([[10, 0], [0, 8]], exact=False, correction=False)


def test_categorical_results_match_independent_base_r_oracle() -> None:
    rscript = shutil.which("Rscript")
    if rscript is None:
        pytest.skip("Rscript unavailable; external categorical oracle is not installed")

    from workbench.engine.packs.categorical import fit_cramers_v, fit_mcnemar

    script = r"""
table <- matrix(c(30, 5, 2, 8, 25, 4, 3, 7, 20), nrow=3, byrow=TRUE)
chi <- suppressWarnings(chisq.test(table, correct=FALSE))
cramers_v <- sqrt(unname(chi$statistic) / (sum(table) * min(nrow(table) - 1, ncol(table) - 1)))
paired <- matrix(c(30, 5, 2, 40), nrow=2, byrow=TRUE)
mcnemar <- suppressWarnings(mcnemar.test(paired, correct=FALSE))
cat(sprintf("%.17g,%.17g,%.17g,%.17g\n", unname(chi$statistic), unname(chi$parameter), chi$p.value, cramers_v))
cat(sprintf("%.17g,%.17g\n", unname(mcnemar$statistic), mcnemar$p.value))
"""
    completed = subprocess.run(
        [rscript, "--vanilla", "-e", script],
        check=True,
        capture_output=True,
        text=True,
        timeout=10,
    )
    lines = [line.strip() for line in completed.stdout.splitlines() if line.strip()]
    assert len(lines) == 2
    cramers_oracle = np.fromstring(lines[0], sep=",")
    mcnemar_oracle = np.fromstring(lines[1], sep=",")

    cramers = fit_cramers_v(
        [[30, 5, 2], [8, 25, 4], [3, 7, 20]],
        correction=False,
    )["result"]
    mcnemar = fit_mcnemar([[30, 5], [2, 40]], exact=False, correction=False)["result"]

    assert cramers["chi_square"] == pytest.approx(cramers_oracle[0], rel=1e-12, abs=1e-12)
    assert cramers["degrees_of_freedom"] == int(cramers_oracle[1])
    assert cramers["p_value"] == pytest.approx(cramers_oracle[2], rel=1e-12, abs=1e-12)
    assert cramers["cramers_v"] == pytest.approx(cramers_oracle[3], rel=1e-12, abs=1e-12)
    assert mcnemar["statistic"] == pytest.approx(mcnemar_oracle[0], rel=1e-12, abs=1e-12)
    assert mcnemar["p_value"] == pytest.approx(mcnemar_oracle[1], rel=1e-12, abs=1e-12)
