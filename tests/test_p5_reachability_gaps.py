"""P5 red/green tests for the live reachability gap closure."""

from __future__ import annotations

from dataclasses import replace

import pandas as pd
import pytest


P5_GAP_IDS = {
    "model.time_series.arma_garch",
    "model.time_series.ets",
    "model.auto",
    "test.anova",
    "test.chi_square",
    "test.correlations",
    "test.evidence",
    "test.fisher_exact",
    "test.nonparametric",
    "test.rank_correlations",
    "test.t_tests",
    "prediction.prediction_lasso",
    "prediction.prediction_ridge",
    "prediction.prediction_random_forest",
    "imputation.mice",
    "resample.smote",
    "resample.oversample",
    "resample.undersample",
}


def test_all_p5_gaps_are_one_live_composable_workflow_identity() -> None:
    from workbench.agent.capability_contract import capability_inventory
    from workbench.agent.operations import OperationRegistry
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    inventory = {
        item.capability_id: item for item in capability_inventory()
    }
    live_operations = set(OperationRegistry().operation_ids())

    assert P5_GAP_IDS <= live_operations
    assert P5_GAP_IDS <= set(WORKFLOW_STEP_SPEC_CONTRACTS)
    assert P5_GAP_IDS <= set(inventory)
    for capability_id in P5_GAP_IDS:
        item = inventory[capability_id]
        assert item.composable_as == (capability_id,)
        assert item.proposed_by == ()
        assert item.reachability_exempt_reason is None


def test_p5_historical_gaps_remain_closed_in_the_live_inventory() -> None:
    """P5 owns its 18 historical IDs; P2 owns the global reachability snapshot."""

    from workbench.agent.capability_contract import capability_reachability_guard

    report = capability_reachability_guard()

    assert {item.capability_id for item in report.gaps} == set()
    assert P5_GAP_IDS <= {item.capability_id for item in report.reachable}


def test_named_statistical_execution_is_family_scoped_and_automatic_is_preserved() -> None:
    from workbench.statistical_tests import (
        run_named_statistical_test,
        run_statistical_tests,
    )

    frame = pd.DataFrame(
        {
            "x": [1.0, 2.0, 4.0, 8.0],
            "y": [2.0, 4.0, 8.0, 16.0],
            "group": ["a", "b", "a", "b"],
        }
    )

    named = run_named_statistical_test(
        frame,
        family="correlations",
        analysis_columns=["x", "y"],
    )
    assert named["execution_mode"] == "named"
    assert named["correction_scope"] == "named:correlations"
    assert named["results"]
    assert all(row["test_type"] in {"pearson_correlation"} for row in named["results"])

    automatic = run_statistical_tests(frame, analysis_columns=["x", "y", "group"])
    assert set(automatic) == {
        "correlations",
        "rank_correlations",
        "t_tests",
        "anova",
        "nonparametric",
        "chi_square",
        "fisher_exact",
        "evidence",
    }
    assert automatic["correlations"]["execution_mode"] == "automatic_pipeline"


@pytest.mark.parametrize(
    ("family", "columns", "frame", "extra"),
    [
        (
            "rank_correlations",
            ["x", "y"],
            pd.DataFrame({"x": [1.0, 2.0, 4.0, 8.0], "y": [2.0, 3.0, 7.0, 15.0]}),
            {},
        ),
        (
            "t_tests",
            ["y", "group"],
            pd.DataFrame({"y": [1.0, 2.0, 1.5, 5.0, 6.0, 5.5], "group": ["a", "a", "a", "b", "b", "b"]}),
            {},
        ),
        (
            "anova",
            ["y", "group"],
            pd.DataFrame({"y": [1.0, 2.0, 1.5, 5.0, 6.0, 5.5, 9.0, 10.0, 9.5], "group": ["a"] * 3 + ["b"] * 3 + ["c"] * 3}),
            {},
        ),
        (
            "nonparametric",
            ["y", "group"],
            pd.DataFrame({"y": [1.0, 2.0, 1.5, 5.0, 6.0, 5.5], "group": ["a", "a", "a", "b", "b", "b"]}),
            {},
        ),
        (
            "chi_square",
            ["left", "right"],
            pd.DataFrame({"left": ["a"] * 4 + ["b"] * 4, "right": ["x", "x", "y", "y", "x", "y", "y", "y"]}),
            {},
        ),
        (
            "fisher_exact",
            ["left", "right"],
            pd.DataFrame({"left": ["a"] * 4 + ["b"] * 4, "right": ["x", "x", "y", "y", "x", "y", "y", "y"]}),
            {},
        ),
        (
            "evidence",
            ["before", "after"],
            pd.DataFrame({"before": [1.0, 1.2, 0.9, 1.1], "after": [1.2, 1.3, 1.1, 1.4]}),
            {"reference_means": {"before": 0.0}, "paired_columns": [["before", "after"]]},
        ),
    ],
)
def test_each_named_statistical_family_has_its_own_evidence_scope(
    family: str,
    columns: list[str],
    frame: pd.DataFrame,
    extra: dict[str, object],
) -> None:
    from workbench.statistical_tests import run_named_statistical_test

    result = run_named_statistical_test(
        frame,
        family=family,
        analysis_columns=columns,
        **extra,
    )

    assert result["execution_mode"] == "named"
    assert result["correction_scope"] == f"named:{family}"
    assert result["test_type"] == family
    assert isinstance(result["results"], list)


def test_dataset_preparation_steps_publish_source_safe_dataset_bindings() -> None:
    from workbench.agent.workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    for operation_id in (
        "imputation.mice",
        "resample.smote",
        "resample.oversample",
        "resample.undersample",
    ):
        contract = WORKFLOW_STEP_SPEC_CONTRACTS[operation_id]
        assert contract.produces_dataset is True
        assert contract.consumes_input_frame is True
        assert contract.replayable_by_recipe is False


def test_nullable_workflow_field_is_validated_as_nullable_string() -> None:
    from workbench.agent.workflow_contracts import (
        StepSpecContract,
        _validate_declared_field_types,
    )

    contract = StepSpecContract(
        summary="A nullable source field.",
        fields={"value": "Optional source value."},
        field_types={"value": "nullable_string"},
    )
    _validate_declared_field_types("test.nullable", {"value": None}, contract)
    _validate_declared_field_types("test.nullable", {"value": "column"}, contract)
    with pytest.raises(Exception):
        _validate_declared_field_types("test.nullable", {"value": 3}, contract)


def test_closed_schema_honors_explicit_nullable_marker() -> None:
    from workbench.agent.workflow_contracts import _schema_value_matches

    assert _schema_value_matches(None, {"type": "string", "nullable": True})
    assert not _schema_value_matches(None, {"type": "string"})


def test_p5_contract_builders_follow_live_registry_injection(monkeypatch) -> None:
    """Every P5 source projection must discover an injected live entry."""

    import workbench.engine.capabilities as engine_capabilities
    import workbench.statistical_tests as statistical_tests
    from workbench.agent import capability_contract
    from workbench.agent import recipe_contracts
    from workbench.agent.workflow_contracts import (
        data_preparation_workflow_step_contracts,
        prediction_workflow_step_contracts,
        recipe_workflow_step_contracts,
        selector_workflow_step_contracts,
        statistical_workflow_step_contracts,
    )
    from workbench.statistical_tests import TestFamilyContract

    monkeypatch.setitem(
        statistical_tests.TEST_FAMILIES,
        "injected_family",
        TestFamilyContract("injected.json", "Injected statistical family."),
    )
    assert "test.injected_family" in statistical_workflow_step_contracts()

    manifest = engine_capabilities.build_capabilities()
    injected_manifest = {
        **manifest,
        "prediction_models": [
            *manifest["prediction_models"],
            {
                "key": "prediction_injected",
                "description": "Injected prediction model.",
            },
        ],
        "imputation_methods": [
            *manifest["imputation_methods"],
            {
                "key": "imputation_injected",
                "description": "Injected imputation method.",
            },
        ],
        "sampling_methods": [
            *manifest["sampling_methods"],
            {"key": "sampling_injected", "label": "Injected sampler"},
        ],
    }
    monkeypatch.setattr(
        engine_capabilities,
        "build_capabilities",
        lambda **_kwargs: injected_manifest,
    )
    assert "prediction.prediction_injected" in prediction_workflow_step_contracts()
    preparation = data_preparation_workflow_step_contracts()
    assert "imputation.imputation_injected" in preparation
    assert "resample.sampling_injected" in preparation

    existing_recipe = recipe_contracts.RECIPE_CONTRACTS["time_series.ets"]
    monkeypatch.setattr(
        recipe_contracts,
        "RECIPE_CONTRACTS",
        {
            **dict(recipe_contracts.RECIPE_CONTRACTS),
            "time_series.injected": replace(
                existing_recipe,
                recipe_id="time_series.injected",
            ),
        },
    )
    assert "model.time_series.injected" in recipe_workflow_step_contracts()

    monkeypatch.setattr(capability_contract, "MODEL_TYPE_SELECTORS", frozenset({"auto", "injected"}))
    assert "model.injected" in selector_workflow_step_contracts()
