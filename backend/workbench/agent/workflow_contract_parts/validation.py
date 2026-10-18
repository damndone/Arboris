"""Validate model and workflow step semantics against native contracts."""
from __future__ import annotations

import json
import math
import re
from collections.abc import Mapping
from typing import Any

from ...contracts.common.errors import OperationValidationError
from ...contracts.model.family import (
    MODEL_FAMILY_CONTRACTS, MODEL_FAMILY_SPEC_FIELDS, WORKFLOW_SPLIT_KINDS,
    ModelFamilyContract, family_context_columns, model_family_contract, validate_family_options,
)
from .contracts import StepSpecContract, _REPORTED_PERCENTILES
from .registry import WORKFLOW_STEP_SPEC_CONTRACTS

def genesis_run_params(spec: Mapping[str, Any]) -> dict[str, Any]:
    """Run-level declarations a genesis step carries, for any family.

    These are properties of the *data and how it was collected*, not of the
    model: a sampling design and a measurement level mean the same thing
    whichever estimator reads them. Extracted once here rather than in each
    family's parameter builder, which is where they were being dropped -- an
    Agent could name a design in its plan, the run would succeed, and ordinary
    standard errors would come back with nothing reporting the loss.

    Empty declarations are omitted rather than passed as "": downstream an empty
    string reads as a column literally named "".
    """
    from ...survey.fields import DESIGN_FIELDS

    params: dict[str, Any] = {}
    for key in ("sampling_weight", "frequency_weight", "analysis_weight", *DESIGN_FIELDS):
        value = spec.get(key)
        if isinstance(value, str) and value.strip():
            params[key] = value.strip()
        elif isinstance(value, (list, tuple)) and value:
            params[key] = [str(item) for item in value]
    labels = spec.get("labels")
    if isinstance(labels, Mapping) and labels:
        params["labels"] = dict(labels)
    # Multiple imputation changes how every number is computed, not the model:
    # it travels with the run like a sampling design does.
    m = spec.get("multiple_imputations")
    if type(m) is int:
        params["imputation"] = json.dumps({"method": "mice", "m": m})
    by_group = spec.get("by_group")
    if isinstance(by_group, str) and by_group.strip():
        params["by_group"] = json.dumps({"column": by_group.strip()})
    return params


def notebook_workflow_capability_ids() -> tuple[str, ...]:
    """Return the native capabilities admitted to the Notebook planner.

    The manual capability manifest is intentionally broader than the typed
    Notebook workflow surface. A handler or legacy UI alias is not enough to
    make a model workflow-executable: it must have the shared family contract
    or a published Recipe contract that defines its input and result boundary.
    Importing Recipes lazily keeps the contract module free of an import cycle.
    """

    from ..recipe_contracts import RECIPE_CONTRACTS

    return tuple(sorted({*MODEL_FAMILY_CONTRACTS, *RECIPE_CONTRACTS}))


def _validate_multiple_imputations(spec: Mapping[str, Any], family: str) -> None:
    m = spec.get("multiple_imputations")
    if m is None:
        return
    from ...combinators.multiple_imputation import (
        MAX_IMPUTATIONS, MI_VALIDATED, MIN_IMPUTATIONS, validated_text,
    )

    if type(m) is not int or not MIN_IMPUTATIONS <= m <= MAX_IMPUTATIONS:
        raise OperationValidationError(
            f"model.genesis multiple_imputations must be an integer from {MIN_IMPUTATIONS} to {MAX_IMPUTATIONS}"
        )
    if family not in {validated_family for validated_family, _ in MI_VALIDATED}:
        raise OperationValidationError(
            f"model.genesis multiple imputation is not offered for {family} yet: pooling it has not "
            f"been checked against a reference implementation. Offered for: {validated_text()}."
        )
    if any(str(spec.get(key) or "").strip() for key in ("sampling_weight", "survey_strata_col", "survey_psu_col")):
        raise OperationValidationError(
            "model.genesis multiple imputation with a sampling design is not supported yet"
        )


def _validate_by_group(spec: Mapping[str, Any], family: str) -> None:
    column = spec.get("by_group")
    if column is None:
        return
    from ...combinators.by_group import BY_GROUP_OPEN

    if not isinstance(column, str) or not column.strip():
        raise OperationValidationError("model.genesis by_group must name one grouping column")
    if family not in BY_GROUP_OPEN:
        offered = ", ".join(sorted(name for name in BY_GROUP_OPEN if "." not in name))
        raise OperationValidationError(
            f"model.genesis by_group is not offered for {family} yet. Offered for: {offered}."
        )
    if spec.get("multiple_imputations") is not None:
        raise OperationValidationError(
            "model.genesis by_group cannot be combined with multiple_imputations yet"
        )
    for branch in spec.get("branches") or ():
        if isinstance(branch, Mapping) and (
            branch.get("outcome") == column or column in (branch.get("predictors") or ())
        ):
            raise OperationValidationError(
                f"model.genesis by_group column {column} cannot also be the outcome or a predictor"
            )


def validate_model_genesis_spec(spec: Mapping[str, Any]) -> ModelFamilyContract:
    """Validate family-owned Genesis semantics and return its exact contract."""

    from ...contracts.model.ols import OLS_COVARIANCE_VALUES
    from ...model_terms import ModelTermError, validate_branch_terms

    contract = model_family_contract(spec.get("model_family"))
    validate_family_options(spec, contract)
    _validate_multiple_imputations(spec, contract.family)
    _validate_by_group(spec, contract.family)
    weight_kind = spec.get("weight_kind")
    if weight_kind is not None:
        if weight_kind not in {"sampling", "analysis", "frequency"}:
            raise OperationValidationError(
                "model.genesis weight_kind must be sampling, analysis, or frequency"
            )
        if weight_kind not in contract.allows_weights:
            raise OperationValidationError(
                f"model.genesis {contract.family} does not accept weight_kind {weight_kind}"
            )
    split_kind = spec.get("split_kind")
    if split_kind is not None:
        if split_kind not in WORKFLOW_SPLIT_KINDS:
            raise OperationValidationError(
                "model.genesis split_kind must be " + ", ".join(WORKFLOW_SPLIT_KINDS)
            )
        if split_kind not in contract.supported_split_kinds:
            raise OperationValidationError(
                f"model.genesis {contract.family} does not accept split_kind {split_kind}"
            )
    declared_family_fields = {
        field_name
        for field_name in MODEL_FAMILY_SPEC_FIELDS
        if spec.get(field_name) is not None
    }
    unexpected_family_fields = sorted(
        declared_family_fields - set(contract.context_spec_fields)
    )
    family_fields = set(contract.required_spec_fields) | set(contract.forbidden_spec_fields)
    dimensions: dict[str, str | None] = {}
    for field_name in family_fields:
        value = spec.get(field_name)
        if value is not None and (not isinstance(value, str) or not value):
            raise OperationValidationError(
                f"model.genesis {field_name} must be a non-empty string"
            )
        dimensions[field_name] = value
    forbidden = [field_name for field_name in contract.forbidden_spec_fields if dimensions[field_name] is not None]
    if forbidden:
        raise OperationValidationError(
            contract.forbidden_spec_fields_message
            or "model.genesis contains a field the selected family does not accept"
        )
    if unexpected_family_fields:
        raise OperationValidationError(
            f"model.genesis {contract.family} does not accept "
            + ", ".join(unexpected_family_fields)
        )
    required_values = [dimensions[field_name] for field_name in contract.required_spec_fields]
    missing_required = (
        contract.required_spec_field_mode == "all" and any(value is None for value in required_values)
    ) or (
        contract.required_spec_field_mode == "any" and contract.required_spec_fields and not any(required_values)
    )
    if missing_required:
        raise OperationValidationError(
            contract.missing_required_fields_message
            or "model.genesis is missing a family-required field"
        )
    branches = spec.get("branches")
    if not isinstance(branches, list) or not branches:
        raise OperationValidationError("model.genesis step requires a non-empty branches list")
    seen: set[str] = set()
    for branch in branches:
        if not isinstance(branch, Mapping):
            raise OperationValidationError("each model branch must be an object")
        branch_id = branch.get("branch_id")
        if not isinstance(branch_id, str) or not branch_id.strip():
            raise OperationValidationError("each model branch requires a branch_id")
        if branch_id in seen:
            raise OperationValidationError(f"duplicate model branch_id: {branch_id}")
        seen.add(branch_id)
        predictors = branch.get("predictors")
        if not isinstance(predictors, list) or (
            contract.requires_nonempty_predictors and not predictors
        ):
            raise OperationValidationError(f"model branch {branch_id} requires predictors")
        if not branch.get("outcome"):
            raise OperationValidationError(f"model branch {branch_id} requires an outcome")
        if branch.get("outcome") in predictors:
            raise OperationValidationError(
                f"model branch {branch_id} outcome must not also be a predictor"
            )
        covariance = branch.get("covariance", spec.get("covariance"))
        if not contract.allows_covariance and covariance is not None:
            raise OperationValidationError(
                f"model.genesis {contract.family} does not accept OLS covariance settings"
            )
        if contract.allows_covariance and covariance is not None and covariance not in OLS_COVARIANCE_VALUES:
            raise OperationValidationError(
                f"model branch {branch_id} covariance must be one of: "
                + ", ".join(OLS_COVARIANCE_VALUES)
            )
        cluster_option = None
        if contract.allows_covariance:
            # Covariance-specific options (HAC's time order, a panel's cluster
            # column) are checked with the covariance they belong to.
            from ...contracts.model.ols import (
                OLS_HAC_FIELDS,
                PANEL_COVARIANCE_FAMILIES,
                validate_ols_model_options,
                validate_panel_model_options,
            )

            options = spec.get("model_options") or {}
            try:
                if contract.family in PANEL_COVARIANCE_FAMILIES:
                    cluster_option = options.get("cluster")
                    validate_panel_model_options(
                        {"covariance": covariance or contract.default_covariance,
                         **{key: options[key] for key in ("cluster", *OLS_HAC_FIELDS) if key in options}},
                        family=contract.family,
                    )
                else:
                    validate_ols_model_options(
                        {"covariance": covariance or "robust",
                         **{key: options[key] for key in OLS_HAC_FIELDS if key in options}},
                        family=contract.family,
                    )
            except ValueError as error:
                raise OperationValidationError(f"model branch {branch_id}: {error}") from error
        if (
            contract.cluster_requires_entity
            and (covariance or contract.default_covariance) == "clustered"
            and not dimensions.get("entity_col")
            and not cluster_option
        ):
            raise OperationValidationError(
                f"model.genesis {contract.family} clusters its standard errors by entity: set entity_col, "
                "name another cluster column in model_options.cluster, or choose covariance robust"
            )
        if not contract.allows_categorical_terms and branch.get("categorical"):
            raise OperationValidationError(
                f"model.genesis {contract.family} does not accept categorical expansion"
            )
        if not contract.allows_polynomial_terms and branch.get("polynomials"):
            raise OperationValidationError(
                f"model.genesis {contract.family} does not accept polynomial expansion"
            )
        try:
            validate_branch_terms(branch)
        except ModelTermError as exc:
            raise OperationValidationError(
                f"model branch {branch_id}: {exc}"
            ) from exc
    family_context_columns(contract, spec)
    if contract.validate_spec is not None:
        contract.validate_spec(spec)
    return contract


def _validate_step_spec(operation_id: str, spec: Mapping[str, Any]) -> None:
    """Validate a spec with the same server validators the manual paths use."""

    from ...statistical_exploration import (
        ExplorationSpec,
        FilterSpec,
        StatisticalExplorationValidationError,
    )

    # Fail closed on field names. A spec carrying `columns` instead of
    # `selected_columns` silently became "all columns"; the plan validated and
    # then meant something the author never wrote. Naming the unknown field is
    # what lets the agent correct itself on the next attempt.
    contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)
    allowed = contract.allowed if contract is not None else frozenset()
    unknown = sorted(set(spec) - allowed - {"source_artifact_fingerprint"})
    if unknown:
        raise OperationValidationError(
            f"{operation_id} spec contains unsupported field(s): "
            + ", ".join(unknown)
            + ". Supported fields: "
            + ", ".join(sorted(allowed))
        )
    if contract is not None:
        missing = sorted(
            field_name
            for field_name in contract.required
            if field_name not in spec or spec[field_name] is None
        )
        if missing:
            raise OperationValidationError(
                f"{operation_id} spec is missing required field(s): "
                + ", ".join(missing)
            )
        _validate_declared_field_types(operation_id, spec, contract)
    validator_key = contract.semantic_validator_key if contract is not None else None
    if validator_key and validator_key.startswith("data."):
        _validate_data_management_step(operation_id, spec)
        return
    if validator_key == "capability_factory.custom_operation":
        return
    if validator_key == "postestimation":
        from ..postestimation_steps import validate_postestimation_spec

        validate_postestimation_spec(operation_id, spec)
        return
    if validator_key == "p7.pack":
        from ..p7_pack_registry import p7_pack_registry

        try:
            operation = p7_pack_registry.get(operation_id)
            operation.validate(
                {
                    "operation_id": operation_id,
                    "input_mode": spec.get("input_mode"),
                    "column_bindings": spec.get("column_bindings"),
                    "options": spec.get("options"),
                }
            )
        except Exception as exc:
            raise OperationValidationError(
                f"invalid {operation_id} P7 pack spec: {exc}"
            ) from exc
        return
    if validator_key == "workflow_capability":
        from ..workflow_capability_registry import workflow_capability_registry

        try:
            operation = workflow_capability_registry().require(operation_id)
            operation.validate(
                {
                    "operation_id": operation_id,
                    "input_mode": spec.get("input_mode"),
                    "column_bindings": spec.get("column_bindings"),
                    "options": spec.get("options"),
                }
            )
        except Exception as exc:
            raise OperationValidationError(
                f"invalid workflow capability {operation_id} spec: {exc}"
            ) from exc
        return
    if validator_key == "statistical.exploration":
        if "plots" in spec:
            plots = spec.get("plots")
            if not isinstance(plots, list) or not plots:
                raise OperationValidationError("scatter step requires a non-empty plots list")
            for plot in plots:
                if not isinstance(plot, Mapping) or not plot.get("x_column") or not plot.get("y_column"):
                    raise OperationValidationError("each plot requires x_column and y_column")
            return
        try:
            ExplorationSpec(
                operation=str(spec.get("operation", "")),
                selected_columns=tuple(str(item) for item in spec.get("selected_columns", []) or []),
                filters=tuple(
                    FilterSpec(
                        column=str(item["column"]),
                        operator=str(item["operator"]),
                        value=item.get("value"),
                    )
                    for item in spec.get("filters", []) or []
                ),
                options=dict(spec.get("options") or {}),
            )
        except (StatisticalExplorationValidationError, KeyError, TypeError, ValueError) as exc:
            raise OperationValidationError(f"invalid statistical.explore spec: {exc}") from exc
    elif validator_key == "statistical.derive_boolean":
        recipes = spec.get("recipes")
        if not isinstance(recipes, list) or not recipes:
            raise OperationValidationError("derive_boolean step requires a non-empty recipes list")
        for recipe in recipes:
            if not isinstance(recipe, Mapping):
                raise OperationValidationError("each derive_boolean recipe must be an object")
            percentile = recipe.get("percentile")
            # The threshold must be traceable to a percentile the detail step
            # actually reports, so it has to be one of that grid. 0.25 is a
            # fraction, not the 25th percentile, and silently accepting it
            # produced a plan that only failed at execution.
            if isinstance(percentile, bool) or percentile not in _REPORTED_PERCENTILES:
                raise OperationValidationError(
                    "derive_boolean percentile must be one of the reported "
                    "percentiles (as a whole number, not a fraction): "
                    + ", ".join(str(item) for item in _REPORTED_PERCENTILES)
                    + f" (got: {percentile!r})"
                )
            if recipe.get("comparison") not in {"lte", "gte"}:
                raise OperationValidationError("derive_boolean comparison must be lte or gte")
            name = recipe.get("output_name")
            if not isinstance(name, str) or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", name) is None:
                raise OperationValidationError("derive_boolean output_name must be a valid column name")
    elif validator_key == "statistical.derive_numeric":
        recipes = spec.get("recipes")
        if not isinstance(recipes, list) or not recipes:
            raise OperationValidationError("derive_numeric step requires a non-empty recipes list")
        output_names: set[str] = set()
        for recipe in recipes:
            if not isinstance(recipe, Mapping):
                raise OperationValidationError("each derive_numeric recipe must be an object")
            if set(recipe) != {"operator", "input_columns", "output_name"}:
                raise OperationValidationError(
                    "derive_numeric recipe must contain only operator, input_columns, output_name"
                )
            operator = recipe.get("operator")
            inputs = recipe.get("input_columns")
            output_name = recipe.get("output_name")
            if operator not in {"natural_log", "multiply"}:
                raise OperationValidationError(
                    "derive_numeric operator must be natural_log or multiply"
                )
            if not isinstance(inputs, list) or any(
                not isinstance(column, str) or not column for column in inputs
            ):
                raise OperationValidationError(
                    "derive_numeric input_columns must be a non-empty list of column names"
                )
            expected_count = 1 if operator == "natural_log" else 2
            if len(inputs) != expected_count or len(set(inputs)) != len(inputs):
                raise OperationValidationError(
                    f"derive_numeric {operator} requires {expected_count} distinct input column(s)"
                )
            if (
                not isinstance(output_name, str)
                or re.fullmatch(r"[A-Za-z_][A-Za-z0-9_]*", output_name) is None
            ):
                raise OperationValidationError(
                    "derive_numeric output_name must be a valid column name"
                )
            if output_name in output_names:
                raise OperationValidationError(
                    f"derive_numeric output_name is duplicated: {output_name}"
                )
            output_names.add(output_name)
    elif validator_key == "statistical.derived_group_summarize":
        groups = spec.get("groups")
        if not isinstance(groups, list) or not groups:
            raise OperationValidationError("derived_group_summarize requires a non-empty groups list")
        for group in groups:
            if not isinstance(group, Mapping):
                raise OperationValidationError(
                    "each derived_group_summarize group must be an object with "
                    "source_column, percentile, comparison and output_name "
                    f"(got: {group!r})"
                )
            missing = sorted(
                {"source_column", "percentile", "comparison", "output_name"} - set(group)
            )
            if missing:
                raise OperationValidationError(
                    "derived_group_summarize group is missing: " + ", ".join(missing)
                )
            if group.get("comparison") not in {"lte", "gte"}:
                raise OperationValidationError(
                    "derived_group_summarize comparison must be lte or gte"
                )
            if isinstance(group.get("percentile"), bool) or group.get(
                "percentile"
            ) not in _REPORTED_PERCENTILES:
                raise OperationValidationError(
                    "derived_group_summarize percentile must be one of: "
                    + ", ".join(str(item) for item in _REPORTED_PERCENTILES)
                )
        if not isinstance(spec.get("summarize_columns"), list) or not spec["summarize_columns"]:
            raise OperationValidationError("derived_group_summarize requires summarize_columns")
    elif validator_key == "model.genesis":
        validate_model_genesis_spec(spec)
    elif validator_key == "model.joint_f_test":
        selectors = spec.get("term_selectors")
        if not isinstance(selectors, list) or not selectors:
            raise OperationValidationError(
                "model.joint_f_test requires a non-empty term_selectors list"
            )
        seen: set[tuple[str, str]] = set()
        for selector in selectors:
            if not isinstance(selector, Mapping):
                raise OperationValidationError(
                    "each model.joint_f_test term selector must be an object"
                )
            unknown = sorted(set(selector) - {"kind", "column"})
            if unknown:
                raise OperationValidationError(
                    "model.joint_f_test term selector contains unsupported field(s): "
                    + ", ".join(unknown)
                )
            kind = selector.get("kind")
            column = selector.get("column")
            if kind not in {"linear", "categorical", "polynomial"}:
                raise OperationValidationError(
                    "model.joint_f_test selector kind must be linear, categorical, or polynomial"
                )
            if not isinstance(column, str) or not column:
                raise OperationValidationError(
                    "model.joint_f_test selector column must be a non-empty string"
                )
            identity = (kind, column)
            if identity in seen:
                raise OperationValidationError(
                    "model.joint_f_test contains a duplicate term selector: "
                    f"{kind}:{column}"
                )
            seen.add(identity)
    elif validator_key == "model.quadratic_stationary_point":
        column = spec.get("column")
        if not isinstance(column, str) or not column:
            raise OperationValidationError(
                "model.quadratic_stationary_point column must be a non-empty string"
            )
    elif validator_key == "model.white_test":
        branch_id = spec.get("branch_id")
        if not isinstance(branch_id, str) or not branch_id:
            raise OperationValidationError(
                "model.white_test branch_id must be a non-empty string"
            )
    elif validator_key == "statistical.named_test":
        by_group = spec.get("by_group")
        if by_group is not None:
            if not isinstance(by_group, str) or not by_group.strip():
                raise OperationValidationError(f"{operation_id} by_group must name one column")
            if by_group in (spec.get("analysis_columns") or []):
                raise OperationValidationError(
                    f"{operation_id} by_group cannot also be an analysis column"
                )
        analysis_columns = spec.get("analysis_columns")
        if not isinstance(analysis_columns, list) or not analysis_columns:
            raise OperationValidationError(
                f"{operation_id} requires a non-empty analysis_columns list"
            )
        if any(not isinstance(column, str) or not column for column in analysis_columns):
            raise OperationValidationError(
                f"{operation_id} analysis_columns must contain non-empty strings"
            )
        if len(set(analysis_columns)) != len(analysis_columns):
            raise OperationValidationError(
                f"{operation_id} analysis_columns must not contain duplicates"
            )
        reference_means = spec.get("reference_means")
        if reference_means is not None:
            if not isinstance(reference_means, Mapping):
                raise OperationValidationError(
                    f"{operation_id} reference_means must be an object"
                )
            if any(
                not isinstance(value, (int, float))
                or isinstance(value, bool)
                or not math.isfinite(float(value))
                for value in reference_means.values()
            ):
                raise OperationValidationError(
                    f"{operation_id} reference_means values must be finite numbers"
                )
        paired_columns = spec.get("paired_columns")
        if paired_columns is not None:
            if not isinstance(paired_columns, list):
                raise OperationValidationError(
                    f"{operation_id} paired_columns must be a list"
                )
            for pair in paired_columns:
                if (
                    not isinstance(pair, list)
                    or len(pair) != 2
                    or any(not isinstance(column, str) or not column for column in pair)
                    or pair[0] == pair[1]
                ):
                    raise OperationValidationError(
                        f"{operation_id} paired_columns must contain distinct two-column lists"
                    )
    elif validator_key == "prediction.model":
        x_columns = spec.get("x")
        if not isinstance(spec.get("y"), str) or not spec["y"]:
            raise OperationValidationError(f"{operation_id} y must be a non-empty string")
        if not isinstance(x_columns, list) or not x_columns:
            raise OperationValidationError(f"{operation_id} x must be a non-empty list")
        if any(not isinstance(column, str) or not column for column in x_columns):
            raise OperationValidationError(
                f"{operation_id} x must contain non-empty column names"
            )
        if len(set(x_columns)) != len(x_columns):
            raise OperationValidationError(f"{operation_id} x must not contain duplicates")
        fraction = spec.get("final_holdout_fraction")
        if fraction is not None and not 0 < float(fraction) < 1:
            raise OperationValidationError(
                f"{operation_id} final_holdout_fraction must be strictly between 0 and 1"
            )
        folds = spec.get("cv_folds")
        if folds is not None and int(folds) < 2:
            raise OperationValidationError(f"{operation_id} cv_folds must be at least 2")
        structure = spec.get("data_structure")
        if structure == "unknown":
            raise OperationValidationError(
                f"{operation_id} data_structure must be explicitly declared"
            )
        sampling = spec.get("sampling")
        if sampling is not None and not isinstance(sampling, Mapping):
            raise OperationValidationError(f"{operation_id} sampling must be an object")
    elif validator_key == "data_preparation.imputation":
        columns = spec.get("columns")
        if not isinstance(columns, list) or not columns:
            raise OperationValidationError(f"{operation_id} columns must be a non-empty list")
        if any(not isinstance(column, str) or not column for column in columns):
            raise OperationValidationError(
                f"{operation_id} columns must contain non-empty column names"
            )
        if len(set(columns)) != len(columns):
            raise OperationValidationError(f"{operation_id} columns must not contain duplicates")
        _validate_positive_integer_field(operation_id, spec, "m")
        if spec.get("m", 1) != 1:
            raise OperationValidationError(
                f"{operation_id} prepares one completed dataset, so m must be 1. A model fitted to "
                "it treats imputed values as observed; for pooled estimates across m imputations, "
                "set multiple_imputations on model.genesis instead."
            )
        _validate_positive_integer_field(operation_id, spec, "max_iter")
        _validate_nonnegative_integer_field(operation_id, spec, "random_seed")
        _validate_fraction_field(operation_id, spec, "max_missing_rate", inclusive=True)
    elif validator_key == "data_preparation.resampling":
        target = spec.get("target_column")
        features = spec.get("feature_columns")
        if not isinstance(target, str) or not target:
            raise OperationValidationError(
                f"{operation_id} target_column must be a non-empty string"
            )
        if not isinstance(features, list) or not features:
            raise OperationValidationError(
                f"{operation_id} feature_columns must be a non-empty list"
            )
        if any(not isinstance(column, str) or not column for column in features):
            raise OperationValidationError(
                f"{operation_id} feature_columns must contain non-empty column names"
            )
        if target in features or len(set(features)) != len(features):
            raise OperationValidationError(
                f"{operation_id} target_column and feature_columns must be disjoint"
            )
        _validate_nonnegative_integer_field(operation_id, spec, "random_seed")
    elif validator_key == "model.time_series.recipe":
        _validate_recipe_workflow_spec(operation_id, spec)
    elif validator_key in {"model.auto"}:
        _validate_auto_workflow_spec(operation_id, spec)


def _validate_positive_integer_field(
    operation_id: str, spec: Mapping[str, Any], field_name: str
) -> None:
    value = spec.get(field_name)
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
        raise OperationValidationError(
            f"{operation_id} {field_name} must be a positive integer"
        )


def _validate_nonnegative_integer_field(
    operation_id: str, spec: Mapping[str, Any], field_name: str
) -> None:
    value = spec.get(field_name)
    if value is not None and (
        not isinstance(value, int) or isinstance(value, bool) or value < 0
    ):
        raise OperationValidationError(
            f"{operation_id} {field_name} must be a non-negative integer"
        )


def _validate_fraction_field(
    operation_id: str,
    spec: Mapping[str, Any],
    field_name: str,
    *,
    inclusive: bool = False,
) -> None:
    value = spec.get(field_name)
    if value is None:
        return
    if (
        not isinstance(value, (int, float))
        or isinstance(value, bool)
        or not math.isfinite(float(value))
        or (not 0 <= float(value) <= 1 if inclusive else not 0 < float(value) < 1)
    ):
        raise OperationValidationError(
            f"{operation_id} {field_name} must be a valid fraction"
        )


def _recipe_option_mapping(
    operation_id: str, spec: Mapping[str, Any]
) -> tuple[Any, Mapping[str, Any]]:
    recipe_id = operation_id.removeprefix("model.")
    from ..recipe_contracts import recipe_contract

    contract = recipe_contract(recipe_id)
    options = spec.get("model_options")
    if not isinstance(options, Mapping):
        raise OperationValidationError(
            f"{operation_id} model_options must be an object owned by {recipe_id}"
        )
    if any(field in options for field in contract.server_owned_option_fields):
        raise OperationValidationError(
            f"{operation_id} model_options contains server-owned field(s): "
            + ", ".join(contract.server_owned_option_fields)
        )
    vocabulary = contract.parameter_vocabulary
    raw_fields = vocabulary.get("fields", []) if isinstance(vocabulary, Mapping) else []
    allowed_roots: set[str] = set(contract.source_option_fields)
    if isinstance(raw_fields, Mapping):
        allowed_roots.update(str(name) for name in raw_fields)
    elif isinstance(raw_fields, list):
        for item in raw_fields:
            if isinstance(item, Mapping) and isinstance(item.get("path"), str):
                allowed_roots.add(str(item["path"]).split(".", 1)[0])
    unknown = sorted(set(options) - allowed_roots)
    if unknown:
        raise OperationValidationError(
            f"{operation_id} model_options contains fields not owned by {recipe_id}: "
            + ", ".join(unknown)
        )
    for field_name in contract.source_option_fields:
        if not isinstance(options.get(field_name), str) or not options[field_name]:
            raise OperationValidationError(
                f"{operation_id} model_options.{field_name} is required"
            )
    missing_planning = [
        field_name
        for field_name in contract.planning_required_option_fields
        if not isinstance(options.get(field_name), str) or not options[field_name]
    ]
    if missing_planning:
        raise OperationValidationError(
            f"{operation_id} model_options requires planning field(s): "
            + ", ".join(missing_planning)
        )
    return contract, options


def _validate_recipe_workflow_spec(operation_id: str, spec: Mapping[str, Any]) -> None:
    _recipe_option_mapping(operation_id, spec)


def _validate_auto_workflow_spec(operation_id: str, spec: Mapping[str, Any]) -> None:
    branches = spec.get("branches")
    if not isinstance(branches, list) or not branches:
        raise OperationValidationError(f"{operation_id} requires a non-empty branches list")
    seen_branch_ids: set[str] = set()
    for branch in branches:
        if not isinstance(branch, Mapping):
            raise OperationValidationError(f"{operation_id} branches must contain objects")
        missing = [
            field_name
            for field_name in ("branch_id", "outcome", "predictors")
            if not branch.get(field_name)
        ]
        if missing:
            raise OperationValidationError(
                f"{operation_id} branch is missing: " + ", ".join(missing)
            )
        branch_id = branch["branch_id"]
        if not isinstance(branch_id, str) or branch_id in seen_branch_ids:
            raise OperationValidationError(
                f"{operation_id} branch_id must be unique and non-empty"
            )
        seen_branch_ids.add(branch_id)
        if not isinstance(branch["outcome"], str):
            raise OperationValidationError(f"{operation_id} branch outcome must be a string")
        predictors = branch["predictors"]
        if not isinstance(predictors, list) or not predictors:
            raise OperationValidationError(
                f"{operation_id} branch predictors must be a non-empty list"
            )
        if any(not isinstance(column, str) or not column for column in predictors):
            raise OperationValidationError(
                f"{operation_id} branch predictors must contain non-empty strings"
            )


def _schema_value_matches(value: Any, schema: Mapping[str, Any]) -> bool:
    """Small closed-schema evaluator for workflow declarations."""

    if not isinstance(schema, Mapping):
        return False
    if value is None and schema.get("nullable") is True:
        const = schema.get("const")
        if const is not None and value != const:
            return False
        return True
    if "const" in schema:
        expected = schema["const"]
        if type(value) is not type(expected) or value != expected:
            return False
    if "enum" in schema:
        if not any(type(value) is type(candidate) and value == candidate for candidate in schema["enum"]):
            return False
    for union_key in ("oneOf", "anyOf"):
        if union_key in schema:
            matches = sum(
                _schema_value_matches(value, candidate)
                for candidate in schema[union_key]
            )
            if union_key == "oneOf" and matches != 1:
                return False
            if union_key == "anyOf" and matches == 0:
                return False
    declared_type = schema.get("type")
    if declared_type is not None:
        types = declared_type if isinstance(declared_type, list) else [declared_type]
        if not any(
            {
                "object": isinstance(value, Mapping),
                "array": isinstance(value, list),
                "string": isinstance(value, str) and not isinstance(value, bool),
                "boolean": type(value) is bool,
                "integer": type(value) is int,
                "number": (isinstance(value, (int, float)) and not isinstance(value, bool)),
                "null": value is None,
            }.get(type_name, False)
            for type_name in types
        ):
            return False
    if isinstance(value, str) and "minLength" in schema and len(value) < schema["minLength"]:
        return False
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return False
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return False
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return False
        if schema.get("uniqueItems") and len({repr(item) for item in value}) != len(value):
            return False
        item_schema = schema.get("items")
        if item_schema is not None and any(
            not _schema_value_matches(item, item_schema) for item in value
        ):
            return False
    if isinstance(value, Mapping):
        required = schema.get("required", [])
        if any(field_name not in value for field_name in required):
            return False
        properties = schema.get("properties", {})
        if not isinstance(properties, Mapping):
            return False
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                if not _schema_value_matches(item, properties[key]):
                    return False
            elif additional is False:
                return False
            elif isinstance(additional, Mapping) and not _schema_value_matches(item, additional):
                return False
        if "minProperties" in schema and len(value) < schema["minProperties"]:
            return False
    return True


def _schema_mismatch(value: Any, schema: Mapping[str, Any], path: str) -> str:
    """Where a value leaves its closed schema, for the refusal message.

    Only called after ``_schema_value_matches`` has said no; it descends into
    objects and arrays to the first failing member and names what is allowed.
    """

    if isinstance(value, Mapping) and isinstance(schema.get("properties"), Mapping):
        properties = schema["properties"]
        for name in schema.get("required", []):
            if name not in value:
                return f"{path}.{name} is required"
        additional = schema.get("additionalProperties", True)
        for key, item in value.items():
            if key in properties:
                if not _schema_value_matches(item, properties[key]):
                    return _schema_mismatch(item, properties[key], f"{path}.{key}")
            elif additional is False:
                return f"{path}.{key} is not a field here; allowed: {', '.join(sorted(properties))}"
            elif isinstance(additional, Mapping) and not _schema_value_matches(item, additional):
                return _schema_mismatch(item, additional, f"{path}.{key}")
    if isinstance(value, list) and isinstance(schema.get("items"), Mapping):
        for index, item in enumerate(value):
            if not _schema_value_matches(item, schema["items"]):
                return _schema_mismatch(item, schema["items"], f"{path}[{index}]")
    if "enum" in schema:
        return f"{path} must be one of: {', '.join(map(str, schema['enum']))}"
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        if "minimum" in schema and value < schema["minimum"]:
            return f"{path} must be at least {schema['minimum']}"
        if "exclusiveMinimum" in schema and value <= schema["exclusiveMinimum"]:
            return f"{path} must be greater than {schema['exclusiveMinimum']}"
    if isinstance(value, (str, list)) and ("minLength" in schema or "minItems" in schema):
        return f"{path} is too short"
    if "const" in schema:
        return f"{path} must be {schema['const']!r}"
    if "type" in schema:
        return f"{path} must be {schema['type']}" + (" or null" if schema.get("nullable") else "")
    return f"{path} does not match its closed schema"


def _validate_data_management_step(operation_id: str, spec: Mapping[str, Any]) -> None:
    """Validate semantic choices that JSON shape alone cannot express."""

    operation = operation_id.removeprefix("data.")
    from ...data_operation_registry import get_data_operation

    declared = get_data_operation(operation)
    if declared is not None:
        try:
            declared.validate(spec)
        except ValueError as exc:
            raise OperationValidationError(f"{operation_id}: {exc}") from exc
        return

    def text(value: Any, label: str) -> str:
        if not isinstance(value, str) or not value.strip():
            raise OperationValidationError(f"{operation_id} {label} must be a non-empty string")
        return value

    def strings(value: Any, label: str) -> list[str]:
        if not isinstance(value, list) or not value or any(
            not isinstance(item, str) or not item.strip() for item in value
        ):
            raise OperationValidationError(f"{operation_id} {label} must be a non-empty string list")
        if len(set(value)) != len(value):
            raise OperationValidationError(f"{operation_id} {label} must not contain duplicates")
        return list(value)

    if operation == "feature_recipe":
        recipe_operation = spec.get("recipe_operation_id")
        inputs = strings(spec.get("inputs"), "inputs")
        parameters = spec.get("parameters")
        if not isinstance(parameters, Mapping):
            raise OperationValidationError(f"{operation_id} parameters must be an object")
        allowed: dict[str, set[str]] = {
            "interaction": {"left", "right"},
            "log": {"input", "base"},
            "ratio": {"numerator", "denominator", "zero_policy"},
            "recode": {"input", "mapping", "default"},
            "derived_variable": {"operator"},
        }
        required: dict[str, set[str]] = {
            "interaction": {"left", "right"},
            "log": {"input"},
            "ratio": {"numerator", "denominator", "zero_policy"},
            "recode": {"input", "mapping"},
            "derived_variable": {"operator"},
        }
        if recipe_operation not in allowed:
            raise OperationValidationError(f"{operation_id} recipe operation is not registered")
        unknown = set(parameters) - allowed[recipe_operation]
        if unknown:
            raise OperationValidationError(
                f"{operation_id} parameters contain unsupported fields: {sorted(unknown)}"
            )
        missing = required[recipe_operation] - set(parameters)
        if missing:
            raise OperationValidationError(
                f"{operation_id} parameters are missing: {sorted(missing)}"
            )
        if recipe_operation in {"interaction", "ratio"} and len(inputs) != 2:
            raise OperationValidationError(f"{operation_id} {recipe_operation} requires two inputs")
        if recipe_operation in {"log", "recode"} and len(inputs) != 1:
            raise OperationValidationError(f"{operation_id} {recipe_operation} requires one input")
        if recipe_operation == "derived_variable" and len(inputs) != 2:
            raise OperationValidationError(f"{operation_id} derived_variable requires two inputs")
        for key in ("left", "right", "input", "numerator", "denominator"):
            if key in parameters and parameters[key] not in inputs:
                raise OperationValidationError(
                    f"{operation_id} parameter {key} must reference inputs"
                )
        if recipe_operation == "ratio" and parameters.get("zero_policy") != "fail_closed":
            raise OperationValidationError(f"{operation_id} ratio requires zero_policy=fail_closed")
        if recipe_operation == "recode" and not isinstance(parameters.get("mapping"), Mapping):
            raise OperationValidationError(f"{operation_id} recode mapping must be an object")
        if recipe_operation == "derived_variable" and parameters.get("operator") not in {
            "add",
            "subtract",
            "multiply",
        }:
            raise OperationValidationError(
                f"{operation_id} derived_variable operator is not registered"
            )
        for policy_name in ("missing_policy", "outlier_policy"):
            if policy_name in spec and spec[policy_name] == "silent":
                raise OperationValidationError(
                    f"{operation_id} {policy_name} cannot be silent"
                )
        return


def _validate_declared_field_types(
    operation_id: str,
    spec: Mapping[str, Any],
    contract: StepSpecContract,
) -> None:
    """Apply the declaration's top-level and nested closed schema."""

    for field_name, type_name in contract.field_types.items():
        if field_name not in spec or spec[field_name] is None:
            continue
        value = spec[field_name]
        valid = {
            "string": isinstance(value, str) and not isinstance(value, bool),
            "nullable_string": (
                value is None
                or (isinstance(value, str) and not isinstance(value, bool))
            ),
            "list": isinstance(value, list),
            "object": isinstance(value, Mapping),
            "number": (
                isinstance(value, (int, float))
                and not isinstance(value, bool)
                and math.isfinite(float(value))
            ),
            "integer": isinstance(value, int) and not isinstance(value, bool),
            "boolean": isinstance(value, bool),
        }.get(type_name)
        if valid is None:
            raise OperationValidationError(
                f"{operation_id} contract declares unsupported field type: {type_name}"
            )
        if not valid:
            raise OperationValidationError(
                f"{operation_id} field {field_name} must be a {type_name}"
            )
    for field_name, enum_values in contract.field_enums.items():
        if field_name in spec and spec[field_name] is not None and spec[field_name] not in enum_values:
            raise OperationValidationError(
                f"{operation_id} field {field_name} must be one of: "
                + ", ".join(enum_values)
            )
    for field_name, schema in contract.field_schemas.items():
        if field_name in spec and spec[field_name] is not None and not _schema_value_matches(
            spec[field_name], schema
        ):
            raise OperationValidationError(
                f"{operation_id} field "
                + _schema_mismatch(spec[field_name], schema, field_name)
            )
