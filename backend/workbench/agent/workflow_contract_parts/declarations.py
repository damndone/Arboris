"""Build workflow operation declarations from their native contracts."""
from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any

from ...contracts.model.genesis_schema import (
    model_genesis_parameters,
)
from .contracts import StepSpecContract


def _p5_exposure_note(capability_id: str) -> str:
    return (
        f"{capability_id} is composable through operation.multi_step; it is "
        "not a standalone natural-language proposal."
    )


def statistical_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Derive one named-test step from every live statistical family."""

    from ...statistical_tests import TEST_FAMILIES

    return {
        f"test.{family}": StepSpecContract(
            summary=contract.summary,
            fields={
                "analysis_columns": (
                    "Explicit source columns for this named statistical family; "
                    "columns are never inferred or silently dropped."
                ),
                "reference_means": (
                    "Optional column-to-population-mean declarations for the "
                    "evidence family."
                ),
                "paired_columns": (
                    "Optional list of explicit two-column before/after pairs for "
                    "the evidence family."
                ),
                "by_group": (
                    "Optional grouping column: the test runs separately within each group "
                    "(a missing value is a group of its own; at most 50 groups), and each "
                    "test's p-values are also adjusted across groups (Holm and "
                    "Benjamini-Hochberg). Groups side by side are not a test of a difference."
                ),
            },
            required=("analysis_columns",),
            field_types={
                "analysis_columns": "list",
                "reference_means": "object",
                "paired_columns": "list",
                "by_group": "string",
            },
            semantic_validator_key="statistical.named_test",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="statistical.named_test",
            risk_class="low",
            confirmation_policy="proposal_confirmation",
            output_schema_ref=f"workbench.statistical_tests.{family}/v1",
            dispatcher_key="workbench.agent.workflow_runtime.statistical_named_test",
            effect_level="read_only",
            scope="named statistical evidence",
            risk_level="none",
            reconciler_key="statistical.named_test",
            diff_builder_key="statistical.named_test.diff.v1",
            verification_builder_key="statistical.named_test.verification.v1",
            ui_description=f"Run the named {family} statistical evidence family.",
            example_prompts=(
                f"Run the {family} test family on the declared analysis columns.",
            ),
            capability_kind="statistical_test",
            top_level_exposure_note=_p5_exposure_note(f"test.{family}"),
        )
        for family, contract in sorted(TEST_FAMILIES.items())
    }


def prediction_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Derive prediction steps from the live prediction manifest."""

    from workbench.engine.capabilities import build_capabilities

    fields = {
        "y": "Target column for the out-of-sample prediction protocol.",
        "x": "Feature columns passed to the prediction estimator.",
        "final_holdout_fraction": "Final holdout fraction used by the split plan.",
        "cv_folds": "Number of cross-validation folds.",
        "shuffle": "Whether the IID split is shuffled.",
        "random_seed": "Deterministic control seed for the split and estimator.",
        "data_structure": "Confirmed structure kind for the prediction split.",
        "entity_column": "Optional entity column for a declared structure.",
        "group_column": "Optional group column for a grouped split.",
        "time_column": "Optional time column for a declared structure.",
        "sampling": "Typed sampling-weight declaration for the prediction protocol.",
        "imputation_method": "Optional fold-local imputation method.",
        "imputation_max_iter": "Maximum fold-local imputation iterations.",
        "imputation_max_missing_rate": "Maximum accepted missing-rate threshold.",
    }
    field_types = {
        "y": "string",
        "x": "list",
        "final_holdout_fraction": "number",
        "cv_folds": "integer",
        "shuffle": "boolean",
        "random_seed": "integer",
        "data_structure": "string",
        "entity_column": "nullable_string",
        "group_column": "nullable_string",
        "time_column": "nullable_string",
        "sampling": "object",
        "imputation_method": "nullable_string",
        "imputation_max_iter": "integer",
        "imputation_max_missing_rate": "number",
    }
    structure_kinds = ("unknown", "iid", "grouped", "temporal", "panel")
    return {
        f"prediction.{entry['key']}": StepSpecContract(
            summary=(
                f"{str(entry.get('description') or entry['key']).rstrip('.')}. "
                "Run the typed out-of-sample prediction protocol."
            ),
            fields=dict(fields),
            required=(
                "y",
                "x",
                "final_holdout_fraction",
                "cv_folds",
                "shuffle",
                "random_seed",
                "data_structure",
            ),
            field_types=dict(field_types),
            field_enums={"data_structure": structure_kinds},
            semantic_validator_key="prediction.model",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="prediction.model",
            risk_class="high",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.prediction.protocol/v1",
            dispatcher_key="workbench.agent.workflow_runtime.prediction_model",
            scope="out-of-sample prediction",
            risk_level="high",
            reconciler_key="prediction.model",
            diff_builder_key="prediction.model.diff.v1",
            verification_builder_key="prediction.model.verification.v1",
            ui_description=f"Run {entry['key']} through the typed prediction protocol.",
            example_prompts=(
                f"Run {entry['key']} with an explicit holdout and cross-validation plan.",
            ),
            capability_kind="prediction_model",
            top_level_exposure_note=_p5_exposure_note(f"prediction.{entry['key']}"),
        )
        for entry in build_capabilities(bootstrap_packs=False)["prediction_models"]
    }


def data_preparation_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Derive dataset-producing preparation steps from live registries."""

    from workbench.engine.capabilities import build_capabilities

    manifest = build_capabilities(bootstrap_packs=False)
    contracts: dict[str, StepSpecContract] = {}
    for entry in manifest["imputation_methods"]:
        capability_id = f"imputation.{entry['key']}"
        contracts[capability_id] = StepSpecContract(
            summary=str(entry["description"]),
            fields={
                "columns": "Numeric columns selected for the imputation method.",
                "m": (
                    "Must be 1: this step prepares one completed dataset. For pooled "
                    "multiple-imputation estimates set multiple_imputations on model.genesis."
                ),
                "max_iter": "Maximum imputation iterations.",
                "random_seed": "Deterministic imputation seed.",
                "max_missing_rate": "Maximum accepted missing-rate threshold.",
            },
            required=("columns",),
            field_types={
                "columns": "list",
                "m": "integer",
                "max_iter": "integer",
                "random_seed": "integer",
                "max_missing_rate": "number",
            },
            semantic_validator_key="data_preparation.imputation",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="data_preparation.imputation",
            risk_class="high",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.data_preparation.imputation/v1",
            dispatcher_key="workbench.agent.workflow_runtime.imputation",
            scope="dataset imputation",
            risk_level="high",
            reconciler_key="data_preparation.imputation",
            diff_builder_key="data_preparation.imputation.diff.v1",
            verification_builder_key="data_preparation.imputation.verification.v1",
            ui_description=f"Run {capability_id} on the resolved input dataset.",
            capability_kind="data_preparation",
            top_level_exposure_note=_p5_exposure_note(capability_id),
            produces_dataset=True,
            produced_dataset_kind="prepared_data",
            consumes_input_frame=True,
            replayable_by_recipe=False,
        )
    for entry in manifest["sampling_methods"]:
        capability_id = f"resample.{entry['key']}"
        label = str(entry.get("label") or entry["key"])
        contracts[capability_id] = StepSpecContract(
            summary=(
                f"{label} class-imbalance resampling on the training split before "
                "a prediction model is fit."
            ),
            fields={
                "target_column": "Target column used to determine class balance.",
                "feature_columns": "Feature columns passed to the sampler.",
                "random_seed": "Deterministic sampler seed.",
            },
            required=("target_column", "feature_columns"),
            field_types={
                "target_column": "string",
                "feature_columns": "list",
                "random_seed": "integer",
            },
            semantic_validator_key="data_preparation.resampling",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="data_preparation.resampling",
            risk_class="high",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.data_preparation.resampling/v1",
            dispatcher_key="workbench.agent.workflow_runtime.resampling",
            scope="prediction training resampling",
            risk_level="high",
            reconciler_key="data_preparation.resampling",
            diff_builder_key="data_preparation.resampling.diff.v1",
            verification_builder_key="data_preparation.resampling.verification.v1",
            ui_description=f"Run {capability_id} on a prediction training frame.",
            capability_kind="data_preparation",
            top_level_exposure_note=_p5_exposure_note(capability_id),
            produces_dataset=True,
            produced_dataset_kind="prepared_data",
            consumes_input_frame=True,
            replayable_by_recipe=False,
        )
    return contracts


def recipe_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Derive time-series workflow steps from live RecipeContracts."""

    from ..recipe_contracts import RECIPE_CONTRACTS

    contracts: dict[str, StepSpecContract] = {}
    for recipe_id, recipe in sorted(RECIPE_CONTRACTS.items()):
        vocabulary = recipe.parameter_vocabulary
        vocabulary_fields = vocabulary.get("fields", []) if isinstance(vocabulary, Mapping) else []
        field_descriptions: dict[str, str] = {
            "model_options": (
                "Recipe-owned options. Use the published parameter vocabulary; "
                "the source reference and source columns remain server-verified."
            )
        }
        field_types: dict[str, str] = {"model_options": "object"}
        for source_field in recipe.source_option_fields:
            field_descriptions[source_field] = f"Recipe source column: {source_field}."
            field_types[source_field] = "string"
        for planning_field in recipe.planning_required_option_fields:
            field_descriptions.setdefault(
                planning_field, f"Required planning declaration: {planning_field}."
            )
            field_types.setdefault(planning_field, "string")
        field_enums: dict[str, tuple[str, ...]] = {}
        if isinstance(vocabulary_fields, Mapping):
            vocabulary_fields = [
                {"path": path, **(dict(value) if isinstance(value, Mapping) else {})}
                for path, value in vocabulary_fields.items()
            ]
        if isinstance(vocabulary_fields, list):
            for item in vocabulary_fields:
                if not isinstance(item, Mapping):
                    continue
                path = item.get("path")
                if not isinstance(path, str) or "." in path:
                    continue
                field_descriptions.setdefault(
                    path, str(item.get("description") or f"Recipe option: {path}.")
                )
                declared_type = str(item.get("type") or item.get("kind") or "string")
                declared_type = {
                    "column": "string",
                    "positive_integer": "integer",
                }.get(declared_type, declared_type)
                field_types.setdefault(path, declared_type)
                values = item.get("enum") or item.get("allowed_values")
                if values and all(type(value) is str and value for value in values):
                    field_enums[path] = tuple(values)
        operation_id = f"model.{recipe_id}"
        contracts[operation_id] = StepSpecContract(
            summary=(
                f"Run the {recipe_id} Recipe with its owner contract and published "
                "time-index semantics."
            ),
            fields=field_descriptions,
            required=("model_options",),
            field_types=field_types,
            field_enums=field_enums,
            semantic_validator_key="model.time_series.recipe",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="model.time_series.recipe",
            risk_class="high",
            confirmation_policy="proposal_authorization",
            output_schema_ref=f"workbench.recipe.{recipe_id}/v1",
            dispatcher_key="workbench.agent.workflow_runtime.time_series_recipe",
            scope="time-series Recipe workflow",
            risk_level="high",
            reconciler_key="model.time_series.recipe",
            diff_builder_key="time_series.recipe.diff.v1",
            verification_builder_key="time_series.recipe.verification.v1",
            ui_description=f"Run the typed {recipe_id} Recipe workflow step.",
            capability_kind="model_family",
            top_level_exposure_note=_p5_exposure_note(operation_id),
        )
    return contracts


def _string_list_field_schema() -> dict[str, Any]:
    return {
        "type": "array",
        "minItems": 1,
        "uniqueItems": True,
        "items": {"type": "string", "minLength": 1},
    }


def _growth_policy_field_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "max_rows": {"type": "integer", "minimum": 0},
            "max_growth_factor": {"type": "number", "exclusiveMinimum": 0},
        },
        "additionalProperties": False,
        "minProperties": 1,
    }


def _data_management_step_contracts() -> dict[str, StepSpecContract]:
    """The P4 declarations projected into every workflow consumer."""

    dispatcher = "workbench.agent.workflow_runtime.data_operation"
    filter_schema = {
        "type": "object",
        "required": ["column", "op"],
        "properties": {
            "column": {"type": "string", "minLength": 1},
            "op": {
                "type": "string",
                "enum": [
                    "eq",
                    "ne",
                    "gt",
                    "ge",
                    "lt",
                    "le",
                    "in",
                    "not_in",
                    "between",
                    "is_missing",
                    "not_missing",
                ],
            },
            # Values are checked against the selected operator by the semantic
            # validator; JSON values are intentionally not coerced here.
            "value": {},
        },
        "additionalProperties": False,
    }
    aggregation_schema = {
        "type": "object",
        "required": ["column", "func", "output"],
        "properties": {
            "column": {"type": "string", "minLength": 1},
            "func": {
                "type": "string",
                "enum": ["sum", "mean", "median", "min", "max", "count", "std"],
            },
            "output": {"type": "string", "minLength": 1},
        },
        "additionalProperties": False,
    }
    fill_strategy_schema = {
        "type": "object",
        "required": ["column", "strategy"],
        "properties": {
            "column": {"type": "string", "minLength": 1},
            "strategy": {
                "type": "string",
                "enum": ["drop_rows", "constant", "mean", "median", "mode"],
            },
            "value": {},
        },
        "additionalProperties": False,
    }
    recipe_parameters_schema = {
        "type": "object",
        "properties": {
            "left": {"type": "string", "minLength": 1},
            "right": {"type": "string", "minLength": 1},
            "input": {"type": "string", "minLength": 1},
            "base": {},
            "numerator": {"type": "string", "minLength": 1},
            "denominator": {"type": "string", "minLength": 1},
            "zero_policy": {"type": "string", "enum": ["fail_closed"]},
            "mapping": {
                "type": "object",
                "additionalProperties": {},
            },
            "default": {},
            "operator": {
                "type": "string",
                "enum": ["add", "subtract", "multiply"],
            },
        },
        "additionalProperties": False,
    }

    def contract(
        operation_id: str,
        summary: str,
        fields: Mapping[str, str],
        required: tuple[str, ...],
        field_types: Mapping[str, str],
        field_schemas: Mapping[str, Mapping[str, Any]],
        *,
        field_enums: Mapping[str, tuple[str, ...]] | None = None,
        natural_language_enabled: bool = False,
    ) -> StepSpecContract:
        return StepSpecContract(
            summary=summary,
            fields=fields,
            required=required,
            field_types=field_types,
            field_enums=field_enums or {},
            field_schemas=field_schemas,
            semantic_validator_key=f"data.{operation_id.removeprefix('data.')}",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key=f"data.{operation_id.removeprefix('data.')}",
            output_schema_ref=f"workbench.data.{operation_id.removeprefix('data.')}/v1",
            dispatcher_key=dispatcher,
            scope="dataset data management",
            risk_level="mutating",
            reconciler_key=dispatcher,
            diff_builder_key="data.operation.diff.v1",
            verification_builder_key="data.operation.verification.v1",
            ui_description=summary,
            natural_language_enabled=natural_language_enabled,
            produces_dataset=True,
            produced_dataset_kind="derived_data",
            consumes_input_frame=True,
            replayable_by_recipe=False,
            capability_kind="data_operation",
        )

    contracts: dict[str, StepSpecContract] = {
        "data.feature_recipe": contract(
            "data.feature_recipe",
            "Create one typed feature recipe child from the registered recipe vocabulary.",
            {
                "recipe_id": "Stable feature recipe identity.",
                "recipe_operation_id": "interaction, log, ratio, recode, or derived_variable.",
                "inputs": "Source columns consumed by the recipe.",
                "output": "One output column name.",
                "output_type": "Output type label.",
                "parameters": "Closed operation-specific recipe parameters.",
                "fit_scope": "stateless, date_local, or period_fitted.",
                "missing_policy": "Explicit missing-value policy.",
                "outlier_policy": "Explicit outlier policy.",
            },
            ("recipe_id", "recipe_operation_id", "inputs", "output", "parameters"),
            {
                "recipe_id": "string",
                "recipe_operation_id": "string",
                "inputs": "list",
                "output": "string",
                "output_type": "string",
                "parameters": "object",
                "fit_scope": "string",
                "missing_policy": "string",
                "outlier_policy": "string",
            },
            {
                "recipe_id": {"type": "string", "minLength": 1},
                "recipe_operation_id": {
                    "type": "string",
                    "enum": ["interaction", "log", "ratio", "recode", "derived_variable"],
                },
                "inputs": _string_list_field_schema(),
                "output": {"type": "string", "minLength": 1},
                "output_type": {"type": "string", "enum": ["numeric", "string", "boolean"]},
                "parameters": recipe_parameters_schema,
                "fit_scope": {
                    "type": "string",
                    "enum": ["stateless", "date_local", "period_fitted"],
                },
                "missing_policy": {"type": "string", "minLength": 1},
                "outlier_policy": {"type": "string", "minLength": 1},
            },
            field_enums={
                "recipe_operation_id": (
                    "interaction",
                    "log",
                    "ratio",
                    "recode",
                    "derived_variable",
                ),
                "fit_scope": ("stateless", "date_local", "period_fitted"),
                "output_type": ("numeric", "string", "boolean"),
            },
            natural_language_enabled=True,
        ),
    }
    # Every other data operation is declared in the data-operation registry;
    # its step contract, including a worked example, comes from the
    # declaration.
    from ...data_operation_registry import data_operation_declarations

    for declaration in data_operation_declarations():
        example = json.dumps(dict(declaration.example), ensure_ascii=False, sort_keys=True)
        contracts[declaration.workflow_operation_id] = contract(
            declaration.workflow_operation_id,
            f"{declaration.summary} Example spec: {example}",
            dict(declaration.fields),
            declaration.required,
            dict(declaration.field_types),
            {name: dict(schema) for name, schema in declaration.field_schemas.items()},
            field_enums=dict(declaration.field_enums),
            natural_language_enabled=declaration.natural_language_enabled,
        )
    return contracts


def base_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Declare the foundational operations before registry-derived extensions."""

    return {
        "statistical.explore": StepSpecContract(
            summary=(
                "One exploration over the source table: summarize / summarize_detail / "
                "misstable / tabulate / corr, or a scatter step when `plots` is present."
            ),
            fields={
                "operation": (
                    "summarize | summarize_detail | misstable | tabulate | corr. "
                    "summarize/summarize_detail cover numeric columns and list the "
                    "others as non_numeric_columns; tabulate gives frequency tables "
                    "for any column (use it for categorical variables)."
                ),
                "selected_columns": "List of column names to analyse. NOT `columns`.",
                "filters": "List of {column, operator, value}; combined with AND.",
                "options": (
                    "Operation options. Grouping lives HERE as options.group_by "
                    "(a column name), never at the top level. options.group_values "
                    "is optional and defaults to every observed value of that column."
                ),
                "plots": "List of {x_column, y_column}; presence makes this a scatter step.",
                "missing_policy": "listwise | variablewise.",
            },
            required=("operation",),
            field_types={
                "operation": "string",
                "selected_columns": "list",
                "filters": "list",
                "options": "object",
                "plots": "list",
                "missing_policy": "string",
            },
            semantic_validator_key="statistical.exploration",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="statistical.explore",
            output_schema_ref="workbench.statistical.exploration/v1",
            dispatcher_key="workbench.agent.workflow_runtime.statistical_explore",
            effect_level="read_only",
            scope="Raw data statistical exploration",
            risk_level="none",
            reconciler_key="statistical.explore",
            diff_builder_key="exploration.diff.v1",
            verification_builder_key="exploration.verification.v1",
            ui_description="Run one server-defined statistical exploration step.",
        ),
        "statistical.derive_boolean": StepSpecContract(
            summary="Derive boolean group-membership columns from percentile thresholds.",
            fields={
                "operation": "Optional label; the recipes carry the meaning.",
                "recipes": (
                    "List of {source_column, percentile, comparison, output_name}. "
                    "percentile is a WHOLE NUMBER from the reported grid, comparison "
                    "is lte or gte."
                ),
                "quantile_method": "Percentile definition to use.",
                "threshold_source": "step_id of the summarize_detail step the thresholds come from.",
            },
            required=("recipes",),
            field_types={
                "operation": "string",
                "recipes": "list",
                "quantile_method": "string",
                "threshold_source": "string",
            },
            semantic_validator_key="statistical.derive_boolean",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="statistical.derive_boolean",
            output_schema_ref="workbench.statistical.exploration/v1",
            dispatcher_key="workbench.agent.workflow_runtime.statistical_derive_boolean",
            scope="Raw data derived grouping",
            reconciler_key="statistical.derive_boolean",
            diff_builder_key="exploration.derived_diff.v1",
            verification_builder_key="exploration.derived_verification.v1",
            ui_description="Create one server-defined boolean grouping node.",
        ),
        "statistical.derive_numeric": StepSpecContract(
            summary=(
                "Create numeric columns with a small server-defined transform vocabulary. "
                "Expressions, formulas, code, and overwrite behavior are not accepted."
            ),
            fields={
                "recipes": (
                    "List of {operator, input_columns, output_name}. operator is "
                    "natural_log (exactly one positive numeric input) or multiply "
                    "(exactly two distinct numeric inputs)."
                ),
            },
            required=("recipes",),
            field_types={"recipes": "list"},
            semantic_validator_key="statistical.derive_numeric",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="statistical.derive_numeric",
            output_schema_ref="workbench.workflow.derived-numeric/v1",
            dispatcher_key="workbench.agent.workflow_runtime.statistical_derive_numeric",
            scope="Raw data numeric derivation",
            reconciler_key="statistical.derive_numeric",
            diff_builder_key="exploration.derived_diff.v1",
            verification_builder_key="exploration.derived_verification.v1",
            ui_description="Create declared numeric columns without arbitrary code.",
            # workflow_runtime's `_persist_numeric_derivation` writes a dataset
            # child; the data transforms join it in P3.
            produces_dataset=True,
            produced_dataset_kind="derived_data",
            # `_upstream_numeric_steps` reconstructs exactly this operation by
            # re-applying its recipes to the workflow target. It is the only one it
            # can, which is why the replay path is a whitelist and not a default.
            replayable_by_recipe=True,
        ),
        "statistical.derived_group_summarize": StepSpecContract(
            summary="Summarize columns within each derived group.",
            fields={
                "groups": (
                    "List of OBJECTS {source_column, percentile, comparison, output_name} "
                    "— not a list of column-name strings."
                ),
                "summarize_columns": "List of column names to summarize inside each group.",
                "missing_policy": "listwise | variablewise.",
            },
            required=("groups", "summarize_columns"),
            field_types={
                "groups": "list",
                "summarize_columns": "list",
                "missing_policy": "string",
            },
            semantic_validator_key="statistical.derived_group_summarize",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="statistical.derived_group_summarize",
            output_schema_ref="workbench.statistical.exploration/v1",
            dispatcher_key="workbench.agent.workflow_runtime.statistical_derived_group_summarize",
            scope="derived group comparison",
            reconciler_key="statistical.derived_group_summarize",
            diff_builder_key="exploration.derived_diff.v1",
            verification_builder_key="exploration.derived_verification.v1",
            ui_description="Summarize columns within each derived group.",
        ),
        "model.genesis": StepSpecContract(
            **model_genesis_parameters(),
            semantic_validator_key="model.genesis",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="model.genesis",
            risk_class="high",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.model.genesis/v1",
            dispatcher_key="workbench.services.genesis",
            scope="dataset model genesis",
            risk_level="high",
            reconciler_key="model.genesis",
            diff_builder_key="genesis.diff.v1",
            verification_builder_key="genesis.verification.v1",
            ui_description="Estimate one or more models from the source table.",
            accepted_dataset_kinds=("derived_data", "prepared_data"),
            produces_model_branches=True,
        ),
        "model.joint_f_test": StepSpecContract(
            summary=(
                "Test whether one or more declared OLS term groups are jointly zero. "
                "Selectors can reference only linear predictors, categorical dummy "
                "sets, or generated polynomial powers that the dependent model "
                "branch already declared."
            ),
            fields={
                "branch_id": "Declared model branch to read from a direct dependency.",
                "term_selectors": (
                    "Non-empty list of {kind, column}; kind is linear, categorical, "
                    "or polynomial. `column` is a source column, not a generated "
                    "coefficient name or formula fragment."
                ),
            },
            required=("branch_id", "term_selectors"),
            field_types={"branch_id": "string", "term_selectors": "list"},
            semantic_validator_key="model.joint_f_test",
            reference_resolver_key="workflow.model_branch",
            column_extractor_key="model.post_estimation",
            risk_class="low",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.model.joint-f-test/v1",
            dispatcher_key="workbench.agent.workflow_runtime.model_joint_f_test",
            effect_level="read_only",
            scope="declared OLS post-estimation",
            risk_level="none",
            reconciler_key="model.joint_f_test",
            diff_builder_key="model.post_estimation.diff.v1",
            verification_builder_key="model.post_estimation.verification.v1",
            ui_description=(
                "Run a joint F test over terms already present in a completed, "
                "unadjusted OLS branch."
            ),
        ),
        "model.white_test": StepSpecContract(
            summary=(
                "Run White's heteroskedasticity test on a completed OLS branch. "
                "The auxiliary regression is derived server-side from the fitted "
                "design matrix; formulas and user-provided terms are not accepted."
            ),
            fields={
                "branch_id": "Declared model branch to read from a direct dependency.",
            },
            required=("branch_id",),
            field_types={"branch_id": "string"},
            semantic_validator_key="model.white_test",
            reference_resolver_key="workflow.model_branch",
            column_extractor_key="model.post_estimation",
            risk_class="low",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.model.white-test/v1",
            dispatcher_key="workbench.agent.workflow_runtime.model_white_test",
            effect_level="read_only",
            scope="declared OLS post-estimation",
            risk_level="none",
            reconciler_key="model.white_test",
            diff_builder_key="model.post_estimation.diff.v1",
            verification_builder_key="model.post_estimation.verification.v1",
            ui_description=(
                "Run White's test for heteroskedasticity on a completed OLS branch."
            ),
        ),
        "model.quadratic_stationary_point": StepSpecContract(
            summary=(
                "Compute the stationary point of one declared linear-plus-square "
                "term in a completed unadjusted OLS branch."
            ),
            fields={
                "branch_id": "Declared model branch to read from a direct dependency.",
                "column": (
                    "Source column declared both as a linear predictor and as a "
                    "degree-two polynomial term."
                ),
            },
            required=("branch_id", "column"),
            field_types={"branch_id": "string", "column": "string"},
            semantic_validator_key="model.quadratic_stationary_point",
            reference_resolver_key="workflow.model_branch",
            column_extractor_key="model.post_estimation",
            risk_class="low",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.model.quadratic-stationary-point/v1",
            dispatcher_key="workbench.agent.workflow_runtime.model_quadratic_stationary_point",
            effect_level="read_only",
            scope="declared OLS post-estimation",
            risk_level="none",
            reconciler_key="model.quadratic_stationary_point",
            diff_builder_key="model.post_estimation.diff.v1",
            verification_builder_key="model.post_estimation.verification.v1",
            ui_description=(
                "Compute -beta_linear / (2 * beta_square) only when both declared "
                "terms are present in a completed quadratic OLS branch."
            ),
        ),
        "report.compose": StepSpecContract(
            summary="Assemble the completed steps into a report.",
            fields={
                "report_contract": "Report contract identifier.",
                "required_steps": "step_ids that must have completed before composing.",
                "formats": "Output formats to emit.",
                "sections": "Ordered report sections.",
                "complete_on": "Completion condition.",
            },
            semantic_validator_key="report.compose",
            reference_resolver_key="workflow.step_artifacts",
            output_schema_ref="workbench.report.collection/v1",
            dispatcher_key="workbench.agent.workflow_runtime.report",
            scope="workflow report",
            reconciler_key="report.compose",
            diff_builder_key="report.compose.diff.v1",
            verification_builder_key="report.compose.verification.v1",
            ui_description="Assemble the completed steps into a report.",
            # Composes completed steps' evidence; it never opens the data at all.
            consumes_input_frame=False,
        ),
        "model.custom": StepSpecContract(
            summary=(
                "Declare a server-bound custom capability operation. The binding, "
                "risk decision, and execution authorization are server-owned; this "
                "workflow contract never grants code execution by itself."
            ),
            fields={
                "capability_ref": "Registered capability implementation reference.",
                "binding_ref": "Current server-owned resolution binding reference.",
                "operation": "Declared adapter operation, such as fit or predict.",
                "input_handle": "Graph/data handle resolved by the Workbench.",
                "parameters": "JSON object of adapter parameters.",
                "consumer_slots": "Explicit consumer slots requested by the capability.",
                "expected_artifacts": "Artifact roles expected from the adapter.",
            },
            required=("capability_ref", "binding_ref", "operation"),
            field_types={
                "capability_ref": "string",
                "binding_ref": "string",
                "operation": "string",
                "input_handle": "string",
                "parameters": "object",
                "consumer_slots": "list",
                "expected_artifacts": "list",
            },
            semantic_validator_key="capability_factory.custom_operation",
            reference_resolver_key="capability_factory.binding",
            column_extractor_key="none",
            risk_class="high",
            confirmation_policy="proposal_authorization",
            output_schema_ref="capability_factory.artifact_contract/v1.1",
            dispatcher_key="capability_factory.custom_dispatcher",
            scope="dataset custom capability",
            risk_level="high",
            reconciler_key="capability_factory.custom_dispatcher",
            diff_builder_key="capability_factory.custom.diff.v1",
            verification_builder_key="capability_factory.custom.verification.v1",
            ui_description="Run one explicitly admitted custom capability through the Proposal/Risk and containment gates.",
            # The authorized gateway resolves its own data through the binding the
            # server owns; the runtime never hands it the workflow's input frame.
            consumes_input_frame=False,
        ),
    }
