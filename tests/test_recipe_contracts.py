"""Admission contracts for time-series Recipes."""

from __future__ import annotations

import pytest

from workbench.agent.recipe_contracts import (
    RecipeValidationError,
    recipe_contract,
    validate_recipe_genesis_params,
)


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


def test_recipe_planning_requires_explicit_time_index_semantics() -> None:
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
