"""Admission contracts for time-series Recipes."""

from __future__ import annotations

import pytest
import pandas as pd

from workbench.agent.recipe_contracts import (
    RecipeValidationError,
    recipe_contract,
    validate_recipe_genesis_params,
)
from workbench.model_options import bind_new_model_options


def test_registered_recipes_own_time_value_inputs_and_result_projection() -> None:
    ets = recipe_contract("time_series.ets")
    arma_garch = recipe_contract("time_series.arma_garch")

    assert ets.requires_nonempty_predictors is False
    assert ets.source_option_fields == ("time_column", "value_column")
    assert ets.expected_artifacts == ("ets_1",)
    assert ets.result_projection == "forecast_summary"
    assert ets.runtime_outcome_option_field == "value_column"
    assert ets.planning_required_option_fields == ("time_index_semantics",)
    assert arma_garch.requires_nonempty_predictors is False
    assert arma_garch.source_option_fields == ("time_column", "value_column")
    assert arma_garch.expected_artifacts == ("ts.artifact_manifest",)
    assert arma_garch.result_projection == "time_series_manifest"


def test_registered_recipes_resolve_server_owned_public_projection_builders() -> None:
    from workbench.agent.recipes.registry import resolve_public_result_projection

    ets = resolve_public_result_projection("time_series.ets")
    arma_garch = resolve_public_result_projection("time_series.arma_garch")

    assert ets.recipe_id == "time_series.ets"
    assert ets.projection_id == "forecast_summary"
    assert ets.owner == "time_series.ets"
    assert arma_garch.recipe_id == "time_series.arma_garch"
    assert arma_garch.projection_id == "time_series_manifest"
    assert arma_garch.owner == "time_series.arma_garch"
    assert callable(ets.build)
    assert callable(arma_garch.build)

    with pytest.raises(KeyError, match="no public projection"):
        resolve_public_result_projection("time_series.unknown")


def test_ets_recipe_vocabulary_reuses_its_authoritative_component_choices() -> None:
    """Planner-visible ETS choices must not drift from the fit contract."""

    from workbench.contracts.model.ets import (
        ERROR_COMPONENTS,
        SEASONAL_COMPONENTS,
        TIME_INDEX_SEMANTICS,
        TREND_COMPONENTS,
    )

    fields = recipe_contract("time_series.ets").parameter_vocabulary["fields"]

    assert fields["error"]["allowed_values"] == list(ERROR_COMPONENTS)
    assert fields["trend"]["allowed_values"] == list(TREND_COMPONENTS)
    assert fields["seasonal"]["allowed_values"] == list(SEASONAL_COMPONENTS)
    assert fields["time_index_semantics"]["allowed_values"] == list(
        TIME_INDEX_SEMANTICS
    )


def test_recipe_payload_omits_server_owned_fields_from_agent_vocabulary() -> None:
    payload = recipe_contract("time_series.arma_garch").to_payload()

    assert payload["server_owned_option_fields"] == ["dataset_ref"]
    fields = payload["parameter_vocabulary"]["fields"]
    assert all(field["path"] != "dataset_ref" for field in fields)


def test_recipe_payload_publishes_only_registered_memory_default_targets() -> None:
    ets = recipe_contract("time_series.ets").to_payload()
    arma_garch = recipe_contract("time_series.arma_garch").to_payload()

    assert ets["memory_targets"] == [
        "model.genesis.time_series.ets.time_index_semantics.regular_calendar",
        "model.genesis.time_series.ets.time_index_semantics.business_or_trading_observations",
        "model.genesis.time_series.ets.time_index_semantics.observation_order",
    ]
    assert arma_garch["memory_targets"] == [
        "model.genesis.time_series.arma_garch.time_index_semantics.regular_calendar",
        "model.genesis.time_series.arma_garch.time_index_semantics.business_or_trading_observations",
        "model.genesis.time_series.arma_garch.time_index_semantics.observation_order",
    ]


def test_recipe_rejects_a_provider_supplied_server_owned_option() -> None:
    contract = recipe_contract("time_series.arma_garch")

    with pytest.raises(RecipeValidationError, match="RECIPE_SERVER_OWNED_OPTION_FORBIDDEN"):
        contract.bind_server_owned_options(
            {"dataset_ref": "provider:chosen"},
            source_reference="upload:server-pinned",
        )


def test_recipe_genesis_rejects_missing_source_columns_and_regression_fields() -> None:
    valid_ets = {
        "model_type": "time_series.ets",
        "model_options": {
            "time_column": "when",
            "value_column": "value",
            "error": "add",
            "trend": None,
            "seasonal": None,
            "damped_trend": False,
        },
    }

    with pytest.raises(RecipeValidationError, match="RECIPE_SOURCE_COLUMN_MISSING"):
        validate_recipe_genesis_params(valid_ets, columns=("when",))

    with pytest.raises(RecipeValidationError, match="RECIPE_REGRESSION_FIELD_FORBIDDEN"):
        validate_recipe_genesis_params({**valid_ets, "y": "value"}, columns=("when", "value"))


def test_recipe_planning_requires_resolved_time_index_semantics() -> None:
    contract = recipe_contract("time_series.ets")
    params = {
        "model_type": "time_series.ets",
        "model_options": {
            "time_column": "when",
            "value_column": "value",
            "error": "add",
            "trend": None,
            "seasonal": None,
            "damped_trend": False,
        },
    }

    with pytest.raises(RecipeValidationError, match="RECIPE_PLANNING_OPTION_REQUIRED"):
        contract.validate_planning_params(params, columns=("when", "value"))

    contract.validate_planning_params(
        {
            **params,
            "model_options": {
                **params["model_options"],
                "time_index_semantics": "observation_order",
            },
        },
        columns=("when", "value"),
    )


def test_recipe_preflight_reuses_the_owner_ets_input_diagnostic() -> None:
    """A Recipe does not recreate time-series quality rules at the Notebook edge."""

    contract = recipe_contract("time_series.ets")
    params = {
        "model_type": "time_series.ets",
        "model_options": {
            "time_column": "when",
            "value_column": "value",
            "time_index_semantics": "regular_calendar",
            "error": "add",
            "trend": None,
            "seasonal": None,
            "damped_trend": False,
        },
    }
    source = pd.DataFrame(
        {
            "when": [
                "2020-01-01",
                "2020-01-02",
                "2020-01-02",
                "2020-01-03",
            ],
            "value": [1.0, 2.0, 3.0, 4.0],
        }
    )

    with pytest.raises(
        RecipeValidationError,
        match="RECIPE_INPUT_PREFLIGHT_FAILED: time_series.ets .*ETS_DUPLICATE_TIMESTAMP",
    ):
        contract.validate_input_preflight(params, source=source)


def test_recipe_preflight_reuses_the_owner_arma_transform_gate() -> None:
    """A confirmed but ineligible transform must be blocked before a Draft exists."""

    contract = recipe_contract("time_series.arma_garch")
    options = bind_new_model_options(
        "time_series.arma_garch",
        {
            "dataset_ref": "upload:pinned",
            "time_column": "when",
            "value_column": "value",
            "time_index_semantics": "observation_order",
            "transform": "log_return_pct",
            "transform_confirmed": True,
            "analysis_goal": "balanced",
            "selection_mode": "auto",
            "arma": {"p": None, "q": None, "constant_mode": "auto"},
            "variance": {"model": "auto", "arch_p": None, "garch_p": None, "garch_q": None},
            "estimation_strategy": "auto",
            "innovation_distribution": "normal",
            "missing_value_policy": "drop_missing_confirmed",
            "validation": {"validation_n": 20, "refit_every": 1},
            "random_seed": 1,
        },
    ).payload
    source = pd.DataFrame(
        {
            "when": ["2020-01-01", "2020-01-02", "2020-01-03", "2020-01-04"],
            "value": [1.0, 0.0, 2.0, 3.0],
        }
    )

    with pytest.raises(
        RecipeValidationError,
        match="RECIPE_INPUT_PREFLIGHT_FAILED: time_series.arma_garch .*LOG_REQUIRES_POSITIVE_VALUES",
    ):
        contract.validate_input_preflight(
            {"model_type": "time_series.arma_garch", "model_options": options},
            source=source,
        )
