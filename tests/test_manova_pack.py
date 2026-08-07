from __future__ import annotations

import inspect
import json
from pathlib import Path

import numpy as np
import pandas as pd
import pytest


def _one_factor_frame() -> pd.DataFrame:
    return pd.DataFrame(
        {
            "response one": [
                6.2,
                5.8,
                7.1,
                6.7,
                8.4,
                8.9,
                9.1,
                8.6,
                10.2,
                9.7,
                10.8,
                11.1,
            ],
            "response two": [
                2.4,
                2.9,
                3.1,
                2.7,
                4.2,
                4.6,
                4.1,
                4.8,
                5.7,
                5.2,
                5.9,
                6.3,
            ],
            "group name": [
                "zeta",
                "alpha",
                "alpha",
                "zeta",
                "beta",
                "beta",
                "alpha",
                "zeta",
                "beta",
                "alpha",
                "zeta",
                "beta",
            ],
        }
    )


def _factor_covariate_frame() -> pd.DataFrame:
    rng = np.random.default_rng(42)
    group = np.repeat(["zeta", "alpha", "beta"], 20)
    arm = np.tile(np.repeat(["late", "early"], 10), 3)
    x = rng.normal(size=len(group))
    return pd.DataFrame(
        {
            "response one": 4.0 + 0.8 * (group == "beta") + 0.2 * x + rng.normal(0, 0.3, len(group)),
            "response two": 2.0 + 0.6 * (arm == "late") - 0.3 * x + rng.normal(0, 0.3, len(group)),
            "group name": group,
            "arm name": arm,
            "dose value": x,
        }
    )


def _fit_one_factor(frame: pd.DataFrame) -> dict[str, object]:
    from workbench.engine.packs.multivariate import fit_manova

    return fit_manova(
        frame,
        ["response one", "response two"],
        factor_columns=["group name"],
        covariate_columns=[],
        interaction_terms=[],
        intercept=True,
        missing_policy="complete_case_v1",
    )


def test_multivariate_result_envelope_rejects_string_columns_during_from_dict():
    from workbench.contracts.common.envelope import ContractError
    from workbench.contracts.model.multivariate import MultivariateResultEnvelope

    value = MultivariateResultEnvelope(
        operation_id="multivariate.manova",
        status="completed",
        reason_code="ANALYSIS_COMPLETED",
        n_observations=2,
        columns=("x", "y"),
        result={},
    ).to_dict()
    value["columns"] = "xy"

    with pytest.raises(ContractError, match="columns must be an array of strings"):
        MultivariateResultEnvelope.from_dict(value)


def test_one_factor_manova_returns_envelope_design_and_all_four_statistics():
    result = _fit_one_factor(_one_factor_frame())
    payload = result["result"]

    assert result["operation_id"] == "multivariate.manova"
    assert result["status"] == "completed"
    assert result["reason_code"] == "ANALYSIS_COMPLETED"
    assert result["n_observations"] == 12
    assert result["columns"] == ["response one", "response two", "group name"]
    assert payload["model_specification"] == {
        "response_columns": ["response one", "response two"],
        "factor_columns": ["group name"],
        "covariate_columns": [],
        "interaction_terms": [],
        "intercept": True,
        "missing_policy": "complete_case_v1",
        "formula": 'Q("response one") + Q("response two") ~ 1 + C(Q("group name"))',
    }
    assert payload["design"] == {
        "n_rows": 12,
        "n_columns": 3,
        "rank": 3,
        "residual_degrees_of_freedom": 9,
    }
    assert payload["retained_positions"] == list(range(12))

    group_tests = payload["term_tests"]["C(group name)"]
    assert set(group_tests) == {
        "wilks_lambda",
        "pillai_trace",
        "hotelling_lawley_trace",
        "roy_greatest_root",
    }
    for statistic in group_tests.values():
        assert set(statistic) == {
            "statistic",
            "numerator_df",
            "denominator_df",
            "f",
            "p_value",
        }
        assert statistic["numerator_df"] > 0
        assert statistic["denominator_df"] > 0
        assert np.isfinite(
            [
                statistic["statistic"],
                statistic["numerator_df"],
                statistic["denominator_df"],
                statistic["f"],
                statistic["p_value"],
            ]
        ).all()


def test_manova_preserves_explicit_factor_covariate_interaction_policy():
    from workbench.engine.packs.multivariate import fit_manova

    result = fit_manova(
        _factor_covariate_frame(),
        ["response one", "response two"],
        factor_columns=["group name", "arm name"],
        covariate_columns=["dose value"],
        interaction_terms=[("group name", "arm name")],
        intercept=False,
        missing_policy="complete_case_v1",
    )
    specification = result["result"]["model_specification"]

    assert specification["factor_columns"] == ["group name", "arm name"]
    assert specification["covariate_columns"] == ["dose value"]
    assert specification["interaction_terms"] == [["group name", "arm name"]]
    assert specification["intercept"] is False
    assert specification["formula"].startswith('Q("response one") + Q("response two") ~ 0 + ')
    assert 'C(Q("group name")):C(Q("arm name"))' in specification["formula"]
    assert 'Q("dose value")' in specification["formula"]
    assert set(result["result"]["term_tests"]) == {
        "C(group name)",
        "C(arm name)",
        "C(group name):C(arm name)",
        "dose value",
    }


def test_manova_complete_case_policy_and_repeated_calls_are_deterministic():
    frame = _one_factor_frame().copy()
    frame.loc[1, "response one"] = np.nan
    frame.loc[8, "group name"] = None

    first = _fit_one_factor(frame)
    second = _fit_one_factor(frame)

    assert first == second
    assert first["n_observations"] == 10
    assert first["result"]["retained_positions"] == [0, 2, 3, 4, 5, 6, 7, 9, 10, 11]
    assert first["result"]["model_specification"]["missing_policy"] == "complete_case_v1"


def test_manova_bounds_retained_positions_and_reports_truncation_metadata():
    from workbench.engine.packs.multivariate import (
        MANOVA_MAX_RETAINED_POSITIONS,
        fit_manova,
    )

    maximum = 5
    assert maximum <= MANOVA_MAX_RETAINED_POSITIONS
    result = fit_manova(
        _one_factor_frame(),
        ["response one", "response two"],
        factor_columns=["group name"],
        covariate_columns=[],
        interaction_terms=[],
        intercept=True,
        missing_policy="complete_case_v1",
        max_retained_positions=maximum,
    )

    assert result["reason_code"] == "MULTIVARIATE_OUTPUT_TOO_LARGE"
    payload = result["result"]
    assert payload["retained_positions"] == [0, 1, 2, 3, 4]
    assert payload["retained_positions_count"] == 12
    assert payload["retained_positions_limit"] == maximum
    assert payload["retained_positions_truncated"] is True
    assert len(payload["retained_positions"]) <= maximum


def test_manova_matches_independent_statsmodels_one_factor_oracle():
    from statsmodels.multivariate.manova import MANOVA
    from workbench.engine.packs.multivariate import fit_manova

    frame = _one_factor_frame()
    result = fit_manova(
        frame,
        ["response one", "response two"],
        factor_columns=["group name"],
        covariate_columns=[],
        interaction_terms=[],
        intercept=True,
        missing_policy="complete_case_v1",
    )
    oracle = MANOVA.from_formula(
        'Q("response one") + Q("response two") ~ 1 + C(Q("group name"))',
        data=frame.assign(
            **{
                "group name": pd.Categorical(
                    frame["group name"],
                    categories=["alpha", "beta", "zeta"],
                    ordered=True,
                )
            }
        ),
    ).mv_test().results["C(Q(\"group name\"))"]["stat"]

    statistic_labels = {
        "wilks_lambda": "Wilks' lambda",
        "pillai_trace": "Pillai's trace",
        "hotelling_lawley_trace": "Hotelling-Lawley trace",
        "roy_greatest_root": "Roy's greatest root",
    }
    actual = result["result"]["term_tests"]["C(group name)"]
    for key, label in statistic_labels.items():
        assert actual[key]["statistic"] == pytest.approx(float(oracle.loc[label, "Value"]))
        assert actual[key]["numerator_df"] == pytest.approx(float(oracle.loc[label, "Num DF"]))
        assert actual[key]["denominator_df"] == pytest.approx(float(oracle.loc[label, "Den DF"]))
        assert actual[key]["f"] == pytest.approx(float(oracle.loc[label, "F Value"]))
        assert actual[key]["p_value"] == pytest.approx(float(oracle.loc[label, "Pr > F"]))


def test_manova_output_is_json_safe_and_does_not_expose_raw_rows():
    result = _fit_one_factor(_one_factor_frame())
    encoded = json.dumps(result, allow_nan=False, sort_keys=True)

    assert json.loads(encoded) == result
    assert "rows" not in result["result"]
    assert "data" not in result["result"]
    assert "response one" not in result["result"]


@pytest.mark.parametrize(
    ("frame", "kwargs", "reason"),
    [
        (
            _one_factor_frame().assign(**{"response one": ["bad"] * 12}),
            {},
            "MULTIVARIATE_NON_NUMERIC_COLUMN",
        ),
        (
            _one_factor_frame().assign(**{"response two": [np.inf] + [1.0] * 11}),
            {},
            "MULTIVARIATE_NON_FINITE_VALUE",
        ),
        (
            _one_factor_frame().assign(**{"group name": [["bad"]] + ["alpha"] * 11}),
            {},
            "MULTIVARIATE_INVALID_CATEGORY",
        ),
        (
            _one_factor_frame(),
            {"factor_columns": ["missing factor"]},
            "MULTIVARIATE_MISSING_COLUMN",
        ),
        (
            _one_factor_frame(),
            {"factor_columns": ["group name", "group name"]},
            "MULTIVARIATE_DUPLICATE_COLUMN",
        ),
        (
            _one_factor_frame(),
            {"missing_policy": "drop_anywhere"},
            "MULTIVARIATE_UNSUPPORTED_MISSING_POLICY",
        ),
    ],
)
def test_manova_rejects_invalid_numeric_category_and_column_inputs(frame, kwargs, reason):
    from workbench.engine.packs.multivariate import fit_manova
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    options = {
        "factor_columns": ["group name"],
        "covariate_columns": [],
        "interaction_terms": [],
        "intercept": True,
        "missing_policy": "complete_case_v1",
    }
    options.update(kwargs)
    with pytest.raises(MultivariatePackError, match=reason):
        fit_manova(frame, ["response one", "response two"], **options)


def test_manova_rejects_invalid_interactions_singular_design_and_low_residual_df():
    from workbench.engine.packs.multivariate import fit_manova
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    frame = _factor_covariate_frame()
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_FACTOR_INTERACTION"):
        fit_manova(
            frame,
            ["response one", "response two"],
            factor_columns=["group name"],
            covariate_columns=["dose value"],
            interaction_terms=[("group name", "dose value")],
            intercept=True,
            missing_policy="complete_case_v1",
        )

    singular = _one_factor_frame().assign(
        covariate_a=np.arange(12, dtype=float),
        covariate_b=np.arange(12, dtype=float) * 2.0,
    )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_SINGULAR_DESIGN"):
        fit_manova(
            singular,
            ["response one", "response two"],
            factor_columns=["group name"],
            covariate_columns=["covariate_a", "covariate_b"],
            interaction_terms=[],
            intercept=True,
            missing_policy="complete_case_v1",
        )

    low_df = pd.DataFrame(
        {
            "y1": [1.0, 2.0, 3.0],
            "y2": [2.0, 1.0, 4.0],
            "group": ["a", "a", "b"],
        }
    )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INSUFFICIENT_RESIDUAL_DF"):
        fit_manova(
            low_df,
            ["y1", "y2"],
            factor_columns=["group"],
            covariate_columns=[],
            interaction_terms=[],
            intercept=True,
            missing_policy="complete_case_v1",
        )


def test_manova_rejects_public_term_id_collisions_before_extracting_statistics():
    from workbench.engine.packs.multivariate import fit_manova
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    frame = _factor_covariate_frame().rename(
        columns={"group name": "a", "arm name": "b"}
    )
    frame["a):C(b"] = np.tile(["low", "high"], len(frame) // 2)

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_INVALID_OPTION"):
        fit_manova(
            frame,
            ["response one", "response two"],
            factor_columns=["a", "b", "a):C(b"],
            covariate_columns=[],
            interaction_terms=[("a", "b")],
            intercept=True,
            missing_policy="complete_case_v1",
        )


def test_manova_classifies_full_rank_design_with_degenerate_responses_as_numeric_degeneracy():
    from workbench.engine.packs.multivariate import fit_manova
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    frame = _one_factor_frame()
    frame["response two"] = frame["response one"] * 2.0

    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_NUMERIC_DEGENERACY"):
        fit_manova(
            frame,
            ["response one", "response two"],
            factor_columns=["group name"],
            covariate_columns=[],
            interaction_terms=[],
            intercept=True,
            missing_policy="complete_case_v1",
        )


def _fake_manova_results(overrides: dict[str, float]) -> dict[str, object]:
    values = {
        "Wilks' lambda": 0.5,
        "Pillai's trace": 0.5,
        "Hotelling-Lawley trace": 0.8,
        "Roy's greatest root": 0.7,
    }
    values.update(overrides)
    table = pd.DataFrame(
        [
            {
                "Value": values[label],
                "Num DF": 2.0,
                "Den DF": 9.0,
                "F Value": 1.0,
                "Pr > F": 0.5,
            }
            for label in values
        ],
        index=list(values),
    )
    return {
        "Intercept": {"stat": table, "contrast_L": np.array([[1.0, 0.0]])},
        'C(Q("group name"))': {
            "stat": table,
            "contrast_L": np.array([[0.0, 1.0]]),
        },
    }


@pytest.mark.parametrize(
    ("label", "value"),
    [
        ("Wilks' lambda", 1.1),
        ("Pillai's trace", 1.1),
        ("Hotelling-Lawley trace", -0.1),
        ("Roy's greatest root", 0.9),
    ],
)
def test_manova_rejects_invalid_multivariate_statistic_ranges(monkeypatch, label, value):
    from types import SimpleNamespace

    import workbench.engine.packs.multivariate.manova as manova_module
    from workbench.engine.packs.multivariate import fit_manova
    from workbench.engine.packs.multivariate.common import MultivariatePackError

    results = _fake_manova_results({label: value})

    class FakeModel:
        def mv_test(self):
            return SimpleNamespace(results=results)

    monkeypatch.setattr(
        manova_module.MANOVA,
        "from_formula",
        lambda formula, data: FakeModel(),
    )
    with pytest.raises(MultivariatePackError, match="MULTIVARIATE_NUMERIC_DEGENERACY"):
        fit_manova(
            _one_factor_frame(),
            ["response one", "response two"],
            factor_columns=["group name"],
            covariate_columns=[],
            interaction_terms=[],
            intercept=True,
            missing_policy="complete_case_v1",
        )


def test_manova_has_no_formula_argument_or_agent_registration():
    from workbench.engine.packs.multivariate import fit_manova

    assert "formula" not in inspect.signature(fit_manova).parameters
    assert "frame" in inspect.signature(fit_manova).parameters
    operations_source = Path("backend/workbench/agent/operations.py").read_text()
    orchestrator_source = Path("backend/workbench/agent/orchestrator.py").read_text()
    assert "multivariate.manova" not in operations_source
    assert "multivariate.manova" not in orchestrator_source
