"""Server-owned contracts for Agent-composed multi-step workflows."""

from __future__ import annotations

import re

from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from .operations import OperationValidationError


WORKFLOW_OPERATION_ID = "operation.multi_step"
WORKFLOW_OPERATION_VERSION = "v1"
WORKFLOW_TEMPLATE = "agent-composed-v1"


def workflow_authorization(
    *,
    workflow_id: str,
    confirmation_id: str,
    step_id: str,
    plan_fingerprint: str,
) -> dict[str, str]:
    values = {
        "workflow_id": workflow_id,
        "workflow_confirmation_id": confirmation_id,
        "workflow_step_id": step_id,
        "workflow_plan_fingerprint": plan_fingerprint,
    }
    if any(not isinstance(value, str) or not value for value in values.values()):
        raise ValueError("workflow authorization values must be non-empty strings")
    return {
        **values,
        "confirmation_mode": "single_workflow_confirmation",
    }


def workflow_proposal_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "operation_id",
            "target",
            "preconditions",
            "changes",
            "evidence_refs",
            "expected_effect",
            "risks",
        ],
        "properties": {
            "operation_id": {"const": WORKFLOW_OPERATION_ID},
            "operation_version": {"const": WORKFLOW_OPERATION_VERSION},
            "target": {
                "type": "object",
                "required": ["run_id", "node_ref", "artifact_id"],
                "properties": {
                    "run_id": {"type": "string", "minLength": 1},
                    "node_ref": {"type": "string", "minLength": 1},
                    "artifact_id": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            "preconditions": {
                "type": "object",
                "required": [
                    "context_version",
                    "context_fingerprint",
                    "active_head_run_id",
                    "owner_resolution",
                ],
                "properties": {
                    "context_version": {"type": "string", "minLength": 1},
                    "context_fingerprint": {"type": "string", "minLength": 1},
                    "active_head_run_id": {"type": "string", "minLength": 1},
                    "owner_resolution": {"type": "string", "minLength": 1},
                },
                "additionalProperties": False,
            },
            # An Agent-composed step list is the only accepted form. A named
            # preset used to be a second one, and its bindings were one
            # assignment's variables (a "poverty_column", a fixed year set)
            # frozen into the server. Removing it removes the only place where
            # a specific exercise could be privileged over any other.
            "changes": {
                "type": "object",
                "required": ["steps"],
                "properties": {
                    "steps": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "type": "object",
                            "required": ["step_id", "operation_id", "spec"],
                            "properties": {
                                "step_id": {"type": "string", "minLength": 1},
                                "operation_id": {
                                    "type": "string",
                                    "enum": list(WORKFLOW_STEP_OPERATIONS),
                                },
                                "spec": {"type": "object"},
                                "depends_on": {
                                    "type": "array",
                                    "items": {"type": "string", "minLength": 1},
                                },
                                "expected_artifacts": {
                                    "type": "array",
                                    "items": {"type": "string"},
                                },
                            },
                            "additionalProperties": False,
                        },
                    },
                },
                "additionalProperties": False,
            },
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "expected_effect": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }


def validate_workflow_operation(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    missing_target = {key for key in ("run_id", "node_ref", "artifact_id") if not target.get(key)}
    if missing_target:
        raise OperationValidationError(
            "operation.multi_step target missing: " + ", ".join(sorted(missing_target))
        )
    missing_preconditions = {
        key
        for key in (
            "context_version",
            "context_fingerprint",
            "active_head_run_id",
            "owner_resolution",
        )
        if not preconditions.get(key)
    }
    if missing_preconditions:
        raise OperationValidationError(
            "operation.multi_step preconditions missing: "
            + ", ".join(sorted(missing_preconditions))
        )
    if "steps" not in changes:
        raise OperationValidationError(
            "operation.multi_step changes must contain a steps list"
        )
    unknown = set(changes) - {"steps", "workflow_template"}
    if unknown:
        raise OperationValidationError(
            "operation.multi_step changes contain unknown field(s): "
            + ", ".join(sorted(unknown))
        )
    validate_workflow_steps(changes["steps"])


# ── generic, plan-shaped workflow contract ──────────────────────────────
#
# A workflow is an arbitrary DAG of typed steps. The server owns the step
# KINDS and validates every spec with the same validators the manual UI uses;
# the Agent owns only the composition (which steps, over which columns, in
# what order). Nothing here knows what assignment is being answered.

# The percentile grid summarize_detail reports; a derived threshold must be
# traceable to one of them.
_REPORTED_PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)

@dataclass(frozen=True)
class StepSpecContract:
    """What one composable step accepts, in one declarative place.

    This is the single source for three consumers that used to drift apart:
    the validator's allowed-field set, the error text an agent reads after a
    rejection, and the vocabulary ``inspect_operation_contract`` publishes
    *before* a plan is written. Adding a step operation means adding one entry
    here; nothing else has to be remembered.
    """

    summary: str
    fields: Mapping[str, str]
    required: tuple[str, ...] = ()
    field_types: Mapping[str, str] = field(default_factory=dict)
    semantic_validator_key: str | None = None
    reference_resolver_key: str | None = None
    column_extractor_key: str | None = None
    risk_class: str = "low"
    confirmation_policy: str = "proposal_confirmation"
    output_schema_ref: str | None = None
    dispatcher_key: str | None = None
    effect_level: str = "mutation"
    scope_requirements: tuple[str, ...] = ("chain", "active_head")
    scope: str = "workflow step"
    risk_level: str = "mutating"
    reconciler_key: str | None = None
    diff_builder_key: str | None = None
    verification_builder_key: str | None = None
    ui_description: str = ""
    example_prompts: tuple[str, ...] = ()
    natural_language_enabled: bool = False

    @property
    def allowed(self) -> frozenset[str]:
        return frozenset(self.fields)

    def to_payload(self) -> dict[str, Any]:
        return {
            "summary": self.summary,
            "required": list(self.required),
            "fields": dict(self.fields),
            "optional": sorted(set(self.fields) - set(self.required)),
            "field_types": dict(self.field_types),
            "semantic_validator_key": self.semantic_validator_key,
            "reference_resolver_key": self.reference_resolver_key,
            "column_extractor_key": self.column_extractor_key,
            "risk_class": self.risk_class,
            "confirmation_policy": self.confirmation_policy,
            "output_schema_ref": self.output_schema_ref,
            "dispatcher_key": self.dispatcher_key,
            "effect_level": self.effect_level,
            "scope_requirements": list(self.scope_requirements),
            "scope": self.scope,
            "risk_level": self.risk_level,
            "reconciler_key": self.reconciler_key,
            "diff_builder_key": self.diff_builder_key,
            "verification_builder_key": self.verification_builder_key,
            "ui_description": self.ui_description,
            "example_prompts": list(self.example_prompts),
            "natural_language_enabled": self.natural_language_enabled,
        }

    def to_schema(self) -> dict[str, Any]:
        """Build the editable spec schema from the same field declarations."""

        type_map = {
            "string": "string",
            "list": "array",
            "object": "object",
        }
        properties: dict[str, dict[str, Any]] = {}
        for name, description in self.fields.items():
            field_schema: dict[str, Any] = {"description": description}
            declared_type = self.field_types.get(name)
            if declared_type is not None:
                field_schema["type"] = type_map.get(declared_type, declared_type)
            properties[name] = field_schema
        return {
            "type": "object",
            "required": list(self.required),
            "properties": properties,
            "additionalProperties": False,
        }


ModelParameterBuilder = Callable[[Mapping[str, Any], Mapping[str, Any], list[str], str], dict[str, Any]]
ModelFamilySpecValidator = Callable[[Mapping[str, Any]], None]
ModelFamilyDataValidator = Callable[[pd.DataFrame, Mapping[str, Any]], None]


from .result_shapes import (  # noqa: E402  -- keeps the contract next to its registry
    ResultShapeError,
    get_result_shape,
    is_registered,
    register_result_shape,
    registered_result_shapes,
)


@dataclass(frozen=True)
class ModelFamilyContract:
    """The complete workflow admission contract for one model family.

    The contract separates a family from the runtime's execution mechanics:
    validation, Genesis parameters, required evidence, and result semantics all
    travel together.  A future family therefore cannot silently inherit OLS
    diagnostics or coefficient-interval assumptions merely because it reaches
    the generic workflow executor.
    """

    family: str
    required_spec_fields: tuple[str, ...]
    required_spec_field_mode: str
    forbidden_spec_fields: tuple[str, ...]
    build_model_params: ModelParameterBuilder
    expected_artifacts: tuple[str, ...]
    result_shape: str
    missing_required_fields_message: str | None = None
    forbidden_spec_fields_message: str | None = None
    cluster_requires_entity: bool = False
    allows_categorical_terms: bool = True
    allows_polynomial_terms: bool = True
    requires_nonempty_predictors: bool = True
    allows_covariance: bool = True
    allows_weights: tuple[str, ...] = ()
    #: v1.8.7. Which statsmodels GLM link this family's fit corresponds to, if
    #: any. Declaring it is the whole cost of joining the design-variance engine
    #: -- the shared adapter does the rest, and neither the engine nor the
    #: adapter ever asks which family it is holding.
    survey_glm_family: str | None = None
    supported_split_kinds: tuple[str, ...] = ()
    requires_branch_figures: bool = False
    context_spec_fields: tuple[str, ...] = ()
    column_spec_fields: tuple[str, ...] = ()
    builds_native_params: bool = False
    validate_spec: ModelFamilySpecValidator | None = None
    validate_branch_frame: ModelFamilyDataValidator | None = None
    model_options_fields: tuple[str, ...] = ()
    model_options_required_fields: tuple[str, ...] = ()
    model_options_column_fields: tuple[str, ...] = ()
    validate_model_options: ModelFamilySpecValidator | None = None

    def __post_init__(self) -> None:
        if self.required_spec_field_mode not in {"all", "any"}:
            raise ValueError("ModelFamilyContract required_spec_field_mode is invalid")
        # The shape must be declared, not drawn from a fixed list.  A closed
        # enum here is what kept factor loadings, reliability coefficients and
        # cluster assignments from being registrable at all -- their results are
        # none of the three kinds a regression produces.
        if not is_registered(self.result_shape):
            raise ResultShapeError(
                f"ModelFamilyContract result_shape {self.result_shape!r} is not declared; "
                "call register_result_shape() with its minimal payload schema first"
            )
        if not self.family or not self.expected_artifacts:
            raise ValueError("ModelFamilyContract requires family and expected artifacts")
        if not set(self.column_spec_fields) <= set(self.context_spec_fields):
            raise ValueError("ModelFamilyContract column fields must be context fields")
        allowed_weight_kinds = {"sampling", "analysis", "frequency"}
        if any(weight not in allowed_weight_kinds for weight in self.allows_weights):
            raise ValueError("ModelFamilyContract allows_weights contains an unknown weight kind")
        if len(set(self.allows_weights)) != len(self.allows_weights):
            raise ValueError("ModelFamilyContract allows_weights must not contain duplicates")
        allowed_split_kinds = {"iid", "grouped", "temporal", "panel"}
        if any(split not in allowed_split_kinds for split in self.supported_split_kinds):
            raise ValueError("ModelFamilyContract supported_split_kinds contains an unknown split kind")
        if len(set(self.supported_split_kinds)) != len(self.supported_split_kinds):
            raise ValueError("ModelFamilyContract supported_split_kinds must not contain duplicates")
        if len(set(self.model_options_fields)) != len(self.model_options_fields):
            raise ValueError("ModelFamilyContract model_options_fields must not contain duplicates")
        if not set(self.model_options_required_fields) <= set(self.model_options_fields):
            raise ValueError(
                "ModelFamilyContract model_options_required_fields must be declared"
            )
        if not set(self.model_options_column_fields) <= set(self.model_options_fields):
            raise ValueError(
                "ModelFamilyContract model_options_column_fields must be declared"
            )


def _build_ols_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "ols",
        "y": branch["outcome"],
        "x": list(predictors),
        "covariance": covariance,
        "model_options": {"covariance": covariance},
    }


def _build_panel_ols_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "panel_ols",
        "y": branch["outcome"],
        "x": list(predictors),
        "covariance": covariance,
        "model_options": {"covariance": covariance},
        "entity_col": spec.get("entity_col"),
        "time_col": spec.get("time_col"),
    }


def _build_generalized_model_params(
    model_type: str,
) -> ModelParameterBuilder:
    def _build(
        spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
    ) -> dict[str, Any]:
        return {
            "model_type": model_type,
            "y": branch["outcome"],
            "x": list(predictors),
        }

    return _build


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
    from ..survey.fields import DESIGN_FIELDS

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
    return params


def _build_model_params_with_options(
    model_type: str,
) -> ModelParameterBuilder:
    def _build(
        spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
    ) -> dict[str, Any]:
        return {
            "model_type": model_type,
            "y": branch["outcome"],
            "x": list(predictors),
            "model_options": dict(spec.get("model_options") or {}),
        }

    return _build


def _validate_family_options(
    spec: Mapping[str, Any], contract: ModelFamilyContract
) -> None:
    raw_options = spec.get("model_options")
    options = {} if raw_options is None else raw_options
    if not isinstance(options, Mapping):
        raise OperationValidationError(
            f"model.genesis {contract.family} model_options must be an object"
        )
    unknown = sorted(set(options) - set(contract.model_options_fields))
    if unknown:
        raise OperationValidationError(
            f"model.genesis {contract.family} model_options does not accept field(s): "
            + ", ".join(unknown)
        )
    missing = sorted(
        field_name
        for field_name in contract.model_options_required_fields
        if field_name not in options or options[field_name] in (None, "")
    )
    if missing:
        raise OperationValidationError(
            f"model.genesis {contract.family} model_options requires: "
            + ", ".join(missing)
        )
    if contract.validate_model_options is not None:
        contract.validate_model_options(options)


def _validate_ordinal_model_options(options: Mapping[str, Any]) -> None:
    if "optimizer" in options and options["optimizer"] not in {"bfgs", "lbfgs"}:
        raise OperationValidationError(
            "model.genesis ordinal_logit model_options.optimizer must be bfgs or lbfgs"
        )
    if "link" in options and options["link"] not in {"logit", "probit"}:
        raise OperationValidationError(
            "model.genesis ordinal_logit model_options.link must be logit or probit"
        )
    outcome_order = options.get("outcome_order")
    if outcome_order is not None and (
        not isinstance(outcome_order, list)
        or len(outcome_order) < 3
        or any(not isinstance(level, str) or not level for level in outcome_order)
        or len(set(outcome_order)) != len(outcome_order)
    ):
        raise OperationValidationError(
            "model.genesis ordinal_logit model_options.outcome_order must be a list of at least three unique non-empty labels"
        )
    maxiter = options.get("maxiter")
    if maxiter is not None and (
        not isinstance(maxiter, int) or isinstance(maxiter, bool) or not 50 <= maxiter <= 5000
    ):
        raise OperationValidationError(
            "model.genesis ordinal_logit model_options.maxiter must be an integer between 50 and 5000"
        )


def _validate_multinomial_model_options(options: Mapping[str, Any]) -> None:
    if "base_category" in options and (
        not isinstance(options["base_category"], str) or not options["base_category"]
    ):
        raise OperationValidationError(
            "model.genesis multinomial_logit model_options.base_category must be a non-empty string"
        )
    maxiter = options.get("maxiter")
    if maxiter is not None and (
        not isinstance(maxiter, int) or isinstance(maxiter, bool) or not 50 <= maxiter <= 5000
    ):
        raise OperationValidationError(
            "model.genesis multinomial_logit model_options.maxiter must be an integer between 50 and 5000"
        )


def _validate_survival_model_options(options: Mapping[str, Any]) -> None:
    for field_name in ("event_column", "group_column", "entry_column"):
        if field_name in options and (
            not isinstance(options[field_name], str) or not options[field_name]
        ):
            raise OperationValidationError(
                f"model.genesis survival_cox model_options.{field_name} must be a non-empty string"
            )
    if options.get("ties", "breslow") not in {"breslow", "efron"}:
        raise OperationValidationError(
            "model.genesis survival_cox model_options.ties must be breslow or efron"
        )


def _validate_quantile_model_options(options: Mapping[str, Any]) -> None:
    quantiles = options.get("quantiles", [0.25, 0.5, 0.75])
    if (
        not isinstance(quantiles, list)
        or not quantiles
        or any(
            isinstance(value, bool)
            or not isinstance(value, (int, float))
            or not np.isfinite(float(value))
            or not 0 < float(value) < 1
            for value in quantiles
        )
        or len(set(float(value) for value in quantiles)) != len(quantiles)
        or len(quantiles) > 7
    ):
        raise OperationValidationError(
            "model.genesis quantile_regression model_options.quantiles must be a unique list of at most seven values strictly between 0 and 1"
        )
    bootstrap_reps = options.get("bootstrap_reps", 0)
    if (
        not isinstance(bootstrap_reps, int)
        or isinstance(bootstrap_reps, bool)
        or not 0 <= bootstrap_reps <= 1000
    ):
        raise OperationValidationError(
            "model.genesis quantile_regression model_options.bootstrap_reps must be an integer between 0 and 1000"
        )
    random_state = options.get("random_state")
    if random_state is not None and (
        not isinstance(random_state, int)
        or isinstance(random_state, bool)
        or random_state < 0
    ):
        raise OperationValidationError(
            "model.genesis quantile_regression model_options.random_state must be a non-negative integer"
        )


def _validate_ordinal_outcome(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
    outcome = branch.get("outcome")
    if not isinstance(outcome, str) or outcome not in frame.columns:
        raise OperationValidationError(
            "model.genesis ordinal_logit requires an available outcome before execution"
        )
    if frame[outcome].dropna().nunique() < 3:
        raise OperationValidationError(
            "model.genesis ordinal_logit requires at least three ordered outcome levels"
        )


def _validate_multinomial_outcome(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
    outcome = branch.get("outcome")
    if not isinstance(outcome, str) or outcome not in frame.columns:
        raise OperationValidationError(
            "model.genesis multinomial_logit requires an available outcome before execution"
        )
    if frame[outcome].dropna().nunique() < 3:
        raise OperationValidationError(
            "model.genesis multinomial_logit requires at least three outcome levels"
        )


def _validate_continuous_outcome(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
    _require_outcome_values(frame, branch, "quantile_regression")


def _require_outcome_values(
    frame: pd.DataFrame, branch: Mapping[str, Any], family: str
) -> pd.Series:
    outcome = branch.get("outcome")
    if not isinstance(outcome, str) or outcome not in frame.columns:
        raise OperationValidationError(
            f"model.genesis {family} requires an available outcome before execution"
        )
    values = pd.to_numeric(frame[outcome], errors="coerce").dropna()
    if values.empty or not np.isfinite(values).all():
        raise OperationValidationError(
            f"model.genesis {family} requires finite numeric outcome values before execution"
        )
    return values


def _validate_binary_outcome(
    family: str,
) -> ModelFamilyDataValidator:
    def _validate(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
        values = _require_outcome_values(frame, branch, family)
        if not values.isin((0, 1)).all():
            raise OperationValidationError(
                f"model.genesis {family} requires a binary 0/1 outcome before execution"
            )

    return _validate


def _validate_count_outcome(
    family: str,
) -> ModelFamilyDataValidator:
    def _validate(frame: pd.DataFrame, branch: Mapping[str, Any]) -> None:
        values = _require_outcome_values(frame, branch, family)
        if (values < 0).any() or not np.isclose(values, np.round(values)).all():
            raise OperationValidationError(
                f"model.genesis {family} requires a non-negative integer count outcome before execution"
            )

    return _validate


def _build_iv_2sls_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "iv_2sls",
        "y": branch["outcome"],
        "x": list(predictors),
        "iv_endog": list(spec["iv_endog"]),
        "iv_instruments": list(spec["iv_instruments"]),
        "covariance": covariance,
    }


def _build_did_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    model_params = {
        "model_type": "did",
        "y": branch["outcome"],
        "x": list(predictors),
        "entity_col": spec["entity_col"],
        "time_col": spec["time_col"],
        "did_mode": spec["did_mode"],
        "covariance": covariance,
    }
    for field_name in ("did_cohort_col", "did_treat_col", "did_post_col", "did_status_col"):
        value = spec.get(field_name)
        if value is not None:
            model_params[field_name] = value
    return model_params


def _require_column_list(spec: Mapping[str, Any], field_name: str, family: str) -> list[str]:
    value = spec.get(field_name)
    if not isinstance(value, list) or not value or any(
        not isinstance(item, str) or not item for item in value
    ):
        raise OperationValidationError(
            f"model.genesis {family} requires a non-empty {field_name} column list"
        )
    if len(set(value)) != len(value):
        raise OperationValidationError(
            f"model.genesis {family} {field_name} must not contain duplicate columns"
        )
    return list(value)


def _validate_iv_2sls_spec(spec: Mapping[str, Any]) -> None:
    from ..engine.iv_spec import IVSpecError, validate_iv_spec

    endog = _require_column_list(spec, "iv_endog", "iv_2sls")
    instruments = _require_column_list(spec, "iv_instruments", "iv_2sls")
    for branch in spec["branches"]:
        try:
            validate_iv_spec(
                y=str(branch["outcome"]),
                exog=[str(item) for item in branch["predictors"]],
                endog=endog,
                instruments=instruments,
            )
        except IVSpecError as exc:
            raise OperationValidationError(f"model.genesis iv_2sls: {exc}") from exc


def _require_column(spec: Mapping[str, Any], field_name: str, family: str) -> str:
    value = spec.get(field_name)
    if not isinstance(value, str) or not value:
        raise OperationValidationError(
            f"model.genesis {family} requires {field_name} for the selected treatment definition"
        )
    return value


def _validate_did_spec(spec: Mapping[str, Any]) -> None:
    mode = spec.get("did_mode")
    if mode not in {"cohort", "two_by_two", "status"}:
        raise OperationValidationError(
            "model.genesis did requires did_mode: cohort, two_by_two, or status"
        )
    if mode == "cohort":
        _require_column(spec, "did_cohort_col", "did")
    elif mode == "two_by_two":
        _require_column(spec, "did_treat_col", "did")
        _require_column(spec, "did_post_col", "did")
    else:
        _require_column(spec, "did_status_col", "did")


def _build_cs_did_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "cs_did",
        "y": branch["outcome"],
        "x": list(predictors),
        "entity_col": spec["entity_col"],
        "time_col": spec["time_col"],
        "did_mode": "cohort",
        "did_cohort_col": spec["cohort_col"],
    }


def _build_sa_did_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "sa_did",
        "y": branch["outcome"],
        "x": list(predictors),
        "entity_col": spec["entity_col"],
        "time_col": spec["time_col"],
        "did_mode": "cohort",
        "did_cohort_col": spec["cohort_col"],
    }


def _build_dcdh_model_params(
    spec: Mapping[str, Any], branch: Mapping[str, Any], predictors: list[str], covariance: str
) -> dict[str, Any]:
    return {
        "model_type": "dcdh",
        "y": branch["outcome"],
        "x": list(predictors),
        "entity_col": spec["entity_col"],
        "time_col": spec["time_col"],
        "did_treatment_path": spec["treatment_path_col"],
    }


MODEL_FAMILY_CONTRACTS: dict[str, ModelFamilyContract] = {
    "anova": ModelFamilyContract(
        family="anova",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=lambda spec: {},
        expected_artifacts=("anova_1",),
        result_shape="anova_table",
        allows_covariance=False,
        model_options_fields=("sums_of_squares", "categorical", "interactions", "posthoc"),
        model_options_required_fields=("sums_of_squares",),
    ),
    "ols": ModelFamilyContract(
        family="ols",
        survey_glm_family="gaussian",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_ols_model_params,
        expected_artifacts=("ols_1", "diagnostic_summary"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis ols does not accept panel entity_col or time_col",
        allows_weights=("frequency", "analysis", "sampling"),
        supported_split_kinds=("iid", "grouped"),
        requires_branch_figures=True,
    ),
    "logit": ModelFamilyContract(
        family="logit",
        survey_glm_family="binomial",
        allows_weights=("sampling",),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("logit"),
        expected_artifacts=("logit_1", "diagnostics_logit_1", "diagnostic_summary"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis logit does not accept panel entity_col or time_col",
        allows_covariance=False,
        validate_branch_frame=_validate_binary_outcome("logit"),
    ),
    "probit": ModelFamilyContract(
        family="probit",
        survey_glm_family="binomial",
        allows_weights=("sampling",),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("probit"),
        expected_artifacts=("probit_1", "diagnostics_probit_1", "diagnostic_summary"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis probit does not accept panel entity_col or time_col",
        allows_covariance=False,
        validate_branch_frame=_validate_binary_outcome("probit"),
    ),
    "poisson": ModelFamilyContract(
        family="poisson",
        survey_glm_family="poisson",
        allows_weights=("sampling",),
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("poisson"),
        expected_artifacts=("poisson_1", "diagnostics_poisson_1", "diagnostic_summary"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis poisson does not accept panel entity_col or time_col",
        allows_covariance=False,
        validate_branch_frame=_validate_count_outcome("poisson"),
    ),
    "negative_binomial": ModelFamilyContract(
        family="negative_binomial",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("negative_binomial"),
        expected_artifacts=(
            "negative_binomial_1",
            "diagnostics_negative_binomial_1",
            "diagnostic_summary",
        ),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis negative_binomial does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        validate_branch_frame=_validate_count_outcome("negative_binomial"),
    ),
    "glm:binomial": ModelFamilyContract(
        family="glm:binomial",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("glm:binomial"),
        expected_artifacts=("glm_1",),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis glm:binomial does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        validate_branch_frame=_validate_binary_outcome("glm:binomial"),
    ),
    "glm:poisson": ModelFamilyContract(
        family="glm:poisson",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("glm:poisson"),
        expected_artifacts=("glm_1",),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis glm:poisson does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        validate_branch_frame=_validate_count_outcome("glm:poisson"),
    ),
    "glm:negative_binomial": ModelFamilyContract(
        family="glm:negative_binomial",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_generalized_model_params("glm:negative_binomial"),
        expected_artifacts=("glm_1",),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis glm:negative_binomial does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        validate_branch_frame=_validate_count_outcome("glm:negative_binomial"),
    ),
    "panel_ols": ModelFamilyContract(
        family="panel_ols",
        required_spec_fields=("entity_col", "time_col"),
        required_spec_field_mode="any",
        forbidden_spec_fields=(),
        build_model_params=_build_panel_ols_model_params,
        expected_artifacts=("panel_ols_1",),
        result_shape="coefficient_intervals",
        missing_required_fields_message=(
            "model.genesis panel_ols requires entity_col or time_col"
        ),
        cluster_requires_entity=True,
        allows_categorical_terms=False,
        context_spec_fields=("entity_col", "time_col"),
        column_spec_fields=("entity_col", "time_col"),
    ),
    "iv_2sls": ModelFamilyContract(
        family="iv_2sls",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_iv_2sls_model_params,
        expected_artifacts=(
            "iv_2sls_1",
            "diagnostics_iv_2sls_1",
            "iv_diagnostics",
            "diagnostic_summary",
        ),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message="model.genesis iv_2sls does not accept panel entity_col or time_col",
        requires_nonempty_predictors=False,
        context_spec_fields=("iv_endog", "iv_instruments"),
        column_spec_fields=("iv_endog", "iv_instruments"),
        builds_native_params=True,
        validate_spec=_validate_iv_2sls_spec,
    ),
    "did": ModelFamilyContract(
        family="did",
        required_spec_fields=("entity_col", "time_col"),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=_build_did_model_params,
        expected_artifacts=(
            "did_1",
            "diagnostics_did_1",
            "did_diagnostics",
            "diagnostic_summary",
        ),
        result_shape="coefficient_intervals",
        missing_required_fields_message="model.genesis did requires entity_col and time_col",
        requires_nonempty_predictors=False,
        context_spec_fields=(
            "entity_col",
            "time_col",
            "did_mode",
            "did_cohort_col",
            "did_treat_col",
            "did_post_col",
            "did_status_col",
        ),
        column_spec_fields=(
            "entity_col",
            "time_col",
            "did_cohort_col",
            "did_treat_col",
            "did_post_col",
            "did_status_col",
        ),
        builds_native_params=True,
        validate_spec=_validate_did_spec,
    ),
    "cs_did": ModelFamilyContract(
        family="cs_did",
        required_spec_fields=("entity_col", "time_col", "cohort_col"),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=_build_cs_did_model_params,
        expected_artifacts=("cs_did_1", "cs_did"),
        result_shape="effect_estimate_bundle",
        missing_required_fields_message=(
            "model.genesis cs_did requires entity_col, time_col, and cohort_col"
        ),
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        requires_nonempty_predictors=False,
        allows_covariance=False,
        context_spec_fields=("entity_col", "time_col", "cohort_col"),
        column_spec_fields=("entity_col", "time_col", "cohort_col"),
        builds_native_params=True,
    ),
    "sa_did": ModelFamilyContract(
        family="sa_did",
        required_spec_fields=("entity_col", "time_col", "cohort_col"),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=_build_sa_did_model_params,
        expected_artifacts=("sa_did_1", "sa_did"),
        result_shape="effect_estimate_bundle",
        missing_required_fields_message=(
            "model.genesis sa_did requires entity_col, time_col, and cohort_col"
        ),
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        requires_nonempty_predictors=False,
        allows_covariance=False,
        context_spec_fields=("entity_col", "time_col", "cohort_col"),
        column_spec_fields=("entity_col", "time_col", "cohort_col"),
        builds_native_params=True,
    ),
    "dcdh": ModelFamilyContract(
        family="dcdh",
        required_spec_fields=("entity_col", "time_col", "treatment_path_col"),
        required_spec_field_mode="all",
        forbidden_spec_fields=(),
        build_model_params=_build_dcdh_model_params,
        expected_artifacts=("dcdh_1", "dcdh"),
        result_shape="event_study_bundle",
        missing_required_fields_message=(
            "model.genesis dcdh requires entity_col, time_col, and treatment_path_col"
        ),
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        requires_nonempty_predictors=False,
        allows_covariance=False,
        context_spec_fields=("entity_col", "time_col", "treatment_path_col"),
        column_spec_fields=("entity_col", "time_col", "treatment_path_col"),
        builds_native_params=True,
    ),
    "ordinal_logit": ModelFamilyContract(
        family="ordinal_logit",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("ordinal_logit"),
        expected_artifacts=("ordinal_logit_1", "diagnostics_ordinal_logit_1"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis ordinal_logit does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=("optimizer", "maxiter", "link", "outcome_order"),
        validate_model_options=_validate_ordinal_model_options,
        validate_branch_frame=_validate_ordinal_outcome,
        supported_split_kinds=("iid", "grouped"),
    ),
    "multinomial_logit": ModelFamilyContract(
        family="multinomial_logit",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("multinomial_logit"),
        expected_artifacts=("multinomial_logit_1", "diagnostics_multinomial_logit_1"),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis multinomial_logit does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=("maxiter", "base_category"),
        validate_model_options=_validate_multinomial_model_options,
        validate_branch_frame=_validate_multinomial_outcome,
        supported_split_kinds=("iid", "grouped"),
    ),
    "survival_cox": ModelFamilyContract(
        family="survival_cox",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("survival_cox"),
        expected_artifacts=("survival_cox_1", "survival_evidence"),
        result_shape="effect_estimate_bundle",
        forbidden_spec_fields_message=(
            "model.genesis survival_cox does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=("event_column", "group_column", "entry_column", "ties"),
        model_options_required_fields=("event_column",),
        model_options_column_fields=("event_column", "group_column", "entry_column"),
        validate_model_options=_validate_survival_model_options,
        supported_split_kinds=("iid", "grouped"),
    ),
    # v1.8.7. LMM was the one family the form could run and an Agent could not
    # start. Nothing about its execution changes here -- the options contract,
    # the pre-fit sealed input and the packet envelope are untouched; this only
    # states, where every other family states it, which declarations it takes.
    "linear_mixed_effects": ModelFamilyContract(
        family="linear_mixed_effects",
        required_spec_fields=(),
        required_spec_field_mode="all",
        # The repeated-measures structure lives in model_options, not in the
        # panel fields: `subject_id` is the unit measured repeatedly, which is
        # not the same idea as a panel entity with fixed effects.
        forbidden_spec_fields=("entity_col", "time_col"),
        forbidden_spec_fields_message=(
            "model.genesis linear_mixed_effects takes subject_id and time through "
            "model_options, not the panel entity_col/time_col fields"
        ),
        build_model_params=_build_model_params_with_options("linear_mixed_effects"),
        expected_artifacts=("linear_mixed_effects_1",),
        result_shape="coefficient_intervals",
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=(
            "subject_id", "time", "group", "fit_method", "random_slope",
        ),
        # A plan without these would fit an ordinary regression and call it a
        # repeated-measures model.
        model_options_required_fields=("subject_id", "time", "group"),
        model_options_column_fields=("subject_id", "time", "group"),
        supported_split_kinds=("grouped",),
    ),
    "quantile_regression": ModelFamilyContract(
        family="quantile_regression",
        required_spec_fields=(),
        required_spec_field_mode="all",
        forbidden_spec_fields=("entity_col", "time_col"),
        build_model_params=_build_model_params_with_options("quantile_regression"),
        expected_artifacts=("quantile_regression_1",),
        result_shape="coefficient_intervals",
        forbidden_spec_fields_message=(
            "model.genesis quantile_regression does not accept panel entity_col or time_col"
        ),
        allows_covariance=False,
        allows_categorical_terms=False,
        allows_polynomial_terms=False,
        model_options_fields=("quantiles", "bootstrap_reps", "random_state"),
        validate_model_options=_validate_quantile_model_options,
        validate_branch_frame=_validate_continuous_outcome,
        supported_split_kinds=("iid", "grouped"),
    ),
}

MODEL_FAMILY_SPEC_FIELDS = frozenset(
    field_name
    for contract in MODEL_FAMILY_CONTRACTS.values()
    for field_name in contract.context_spec_fields
)


def notebook_workflow_capability_ids() -> tuple[str, ...]:
    """Return the native capabilities admitted to the Notebook planner.

    The manual capability manifest is intentionally broader than the typed
    Notebook workflow surface. A handler or legacy UI alias is not enough to
    make a model workflow-executable: it must have the shared family contract
    or a published Recipe contract that defines its input and result boundary.
    Importing Recipes lazily keeps the contract module free of an import cycle.
    """

    from .recipe_contracts import RECIPE_CONTRACTS

    return tuple(sorted({*MODEL_FAMILY_CONTRACTS, *RECIPE_CONTRACTS}))


def model_family_contract(model_family: Any) -> ModelFamilyContract:
    if not isinstance(model_family, str) or model_family not in MODEL_FAMILY_CONTRACTS:
        raise OperationValidationError(
            "model.genesis model_family must be a workflow-executable family: "
            + " or ".join(MODEL_FAMILY_CONTRACTS)
        )
    return MODEL_FAMILY_CONTRACTS[model_family]


def family_context_columns(
    contract: ModelFamilyContract, spec: Mapping[str, Any]
) -> tuple[str, ...]:
    """Project only source-column fields, preserving declared lists elementwise."""

    values: list[str] = []
    for field_name in contract.column_spec_fields:
        value = spec.get(field_name)
        if value is None:
            continue
        if isinstance(value, str) and value:
            values.append(value)
            continue
        if isinstance(value, list) and value and all(
            isinstance(item, str) and item for item in value
        ):
            values.extend(value)
            continue
        raise OperationValidationError(
            f"model.genesis {contract.family} {field_name} must declare source column names"
        )
    options = spec.get("model_options")
    if options is not None:
        if not isinstance(options, Mapping):
            raise OperationValidationError(
                f"model.genesis {contract.family} model_options must be an object"
            )
        for field_name in contract.model_options_column_fields:
            value = options.get(field_name)
            if value is None:
                continue
            if not isinstance(value, str) or not value:
                raise OperationValidationError(
                    f"model.genesis {contract.family} model_options.{field_name} must declare a source column"
                )
            values.append(value)
    return tuple(dict.fromkeys(values))


def validate_model_genesis_spec(spec: Mapping[str, Any]) -> ModelFamilyContract:
    """Validate family-owned Genesis semantics and return its exact contract."""

    from ..contracts.model.ols import OLS_COVARIANCE_VALUES
    from ..model_terms import ModelTermError, validate_branch_terms

    contract = model_family_contract(spec.get("model_family"))
    _validate_family_options(spec, contract)
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
        if split_kind not in {"iid", "grouped", "temporal", "panel"}:
            raise OperationValidationError(
                "model.genesis split_kind must be iid, grouped, temporal, or panel"
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
        if contract.cluster_requires_entity and covariance == "clustered" and not dimensions.get("entity_col"):
            raise OperationValidationError(
                "model.genesis clustered panel_ols requires entity_col"
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


def _workflow_executable_family_sentence() -> str:
    """The families an Agent may name, derived from the registry."""
    families = sorted(key for key in MODEL_FAMILY_CONTRACTS if key != "auto")
    return (
        "Registered workflow-executable model family: "
        + ", ".join(families)
        + ". Every branch in one step uses this same family."
    )


def _genesis_survey_fields() -> dict[str, str]:
    """The sampling-design declarations, described where they are declared.

    A first run must be able to state a design: reachable only on a rerun means
    the analysis has to be built by hand before an Agent can touch it, which is
    the opposite of driving the workbench from one sentence.
    """
    from ..survey.fields import DESIGN_FIELD_SPECS

    described = {
        spec["key"]: (
            f"{spec['label']}."
            + (f" One of: {', '.join(spec['options'])}." if spec.get("options") else "")
        )
        for spec in DESIGN_FIELD_SPECS
    }
    described["sampling_weight"] = (
        "Column holding the sampling weight. A survey design requires one, and a "
        "sampling weight without a declared design is refused -- give both or neither."
    )
    return described


WORKFLOW_STEP_SPEC_CONTRACTS: dict[str, StepSpecContract] = {
    "statistical.explore": StepSpecContract(
        summary=(
            "One exploration over the source table: summarize / summarize_detail / "
            "misstable / corr, or a scatter step when `plots` is present."
        ),
        fields={
            "operation": "summarize | summarize_detail | misstable | corr.",
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
        summary="Estimate one or more models from the source table.",
        fields={
            # Read off the registry, never typed out: this sentence is the only
            # place an Agent learns which families exist, and a hand-written
            # list goes stale the first time one is added. `anova` shipped in
            # v1.8.7 while this text still named the previous eighteen, so a
            # request for a factorial ANOVA had nowhere to land -- and nothing
            # failed, because prose does not fail.
            "model_family": _workflow_executable_family_sentence(),
            "covariance": "Default covariance for every branch.",
            "model_options": (
                "Family-owned JSON options. Only the selected model family's declared "
                "option fields are accepted; do not copy options from another family."
            ),
            "entity_col": (
                "Panel entity column. panel_ols requires entity_col or time_col; "
                "clustered panel covariance requires entity_col."
            ),
            "time_col": "Optional panel time column for time fixed effects.",
            "cohort_col": "First-treatment period for cs_did or sa_did (0 for never treated).",
            "treatment_path_col": "Binary treatment path for dcdh, which may switch on and off.",
            "iv_endog": "Non-empty endogenous-regressor column list for iv_2sls.",
            "iv_instruments": "Non-empty instrument column list for iv_2sls; must not overlap endog or predictors.",
            "did_mode": "TWFE DID treatment definition: cohort, two_by_two, or status.",
            "did_cohort_col": "First-treatment period for did_mode cohort (0 for never treated).",
            "did_treat_col": "Treatment-group indicator for did_mode two_by_two.",
            "did_post_col": "Post-period indicator for did_mode two_by_two.",
            "did_status_col": "Absorbing treatment-status indicator for did_mode status.",
            **_genesis_survey_fields(),
            "labels": (
                "Column metadata. `measurement_level` maps column names to "
                "nominal / ordinal / scale / count and decides how each column is "
                "modelled -- an integer rating left undeclared is analysed as a "
                "count. Declare every column in one step rather than one at a time."
            ),
            "branches": (
                "List of {branch_id, outcome, predictors[, categorical]"
                "[, polynomials][, covariance]}; one estimated model per entry. "
                "Entries in `predictors` enter LINEARLY, exactly as the column "
                "stands — listing a categorical code column there estimates a "
                "linear effect on the code, which is a different model. Use "
                "`categorical` for dummy expansion and `polynomials` for powers. "
                "Interaction terms cannot be expressed; say so rather than "
                "approximating one."
            ),
            "categorical": (
                "Per branch: list of column names to expand into dummy "
                "indicators. One level is dropped as the reference category to "
                "avoid perfect collinearity with the intercept; the lowest "
                "sorted level is the reference. A column listed here must NOT "
                "also appear in `predictors`."
            ),
            "polynomials": (
                "Per branch: list of {column, degree}. degree 2 adds the square, "
                "3 adds square and cube, and so on; generated columns are named "
                "{column}_pow2, {column}_pow3. The linear term is not added "
                "implicitly — list the column in `predictors` as well when the "
                "model should contain it."
            ),
            "context_columns": "Extra columns to carry into the model context.",
        },
        required=("model_family", "branches"),
        field_types={
            "model_family": "string",
            "covariance": "string",
            "model_options": "object",
            "entity_col": "string",
            "time_col": "string",
            "cohort_col": "string",
            "treatment_path_col": "string",
            "iv_endog": "list",
            "iv_instruments": "list",
            "did_mode": "string",
            "did_cohort_col": "string",
            "did_treat_col": "string",
            "did_post_col": "string",
            "did_status_col": "string",
            "branches": "list",
            "categorical": "list",
            "polynomials": "list",
            "context_columns": "list",
        },
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
    ),
}

WORKFLOW_STEP_OPERATIONS = tuple(WORKFLOW_STEP_SPEC_CONTRACTS)

_ALLOWED_SPEC_FIELDS = {
    operation_id: contract.allowed
    for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
}


def workflow_step_vocabulary() -> dict[str, Any]:
    """The composable-step vocabulary, for publication to a planning agent.

    Read before a plan is written, this is what makes the difference between
    composing against real field names and guessing at them.
    """

    return {
        "step_operations": {
            operation_id: contract.to_payload()
            for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
        },
        "reported_percentiles": list(_REPORTED_PERCENTILES),
        "step_id_pattern": _STEP_ID_PATTERN.pattern,
        "ordering": (
            "Steps form a DAG via `depends_on` (step_ids) and run in topological "
            "order. A step whose dependency failed is blocked, never skipped."
        ),
    }


def workflow_dispatcher_key(operation_id: str) -> str:
    """Return the trusted runtime key published by one step contract."""

    contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)
    if contract is None or not contract.dispatcher_key:
        raise OperationValidationError(
            f"workflow step operation has no trusted dispatcher: {operation_id!r}"
        )
    return contract.dispatcher_key

_STEP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")

# The only output binding a step may commit to consuming today. Keeping this a
# closed set means a typo is a compile error rather than a runtime KeyError.
SUPPORTED_STEP_OUTPUTS = frozenset({"produced_dataset"})


def _spec_columns(operation_id: str, spec: Mapping[str, Any]) -> set[str]:
    """Every source column a step spec references, for schema checking."""

    columns: set[str] = set()
    extractor_key = (
        WORKFLOW_STEP_SPEC_CONTRACTS[operation_id].column_extractor_key
        if operation_id in WORKFLOW_STEP_SPEC_CONTRACTS
        else None
    )
    if extractor_key == "statistical.explore":
        columns.update(str(item) for item in spec.get("selected_columns", []) or [])
        for item in spec.get("filters", []) or []:
            if isinstance(item, Mapping) and item.get("column"):
                columns.add(str(item["column"]))
        options = spec.get("options") or {}
        if isinstance(options, Mapping) and options.get("group_by"):
            columns.add(str(options["group_by"]))
        for plot in spec.get("plots", []) or []:
            if isinstance(plot, Mapping):
                columns.update(str(plot[key]) for key in ("x_column", "y_column") if plot.get(key))
    elif extractor_key == "statistical.derive_boolean":
        for recipe in spec.get("recipes", []) or []:
            if isinstance(recipe, Mapping) and recipe.get("source_column"):
                columns.add(str(recipe["source_column"]))
    elif extractor_key == "statistical.derive_numeric":
        for recipe in spec.get("recipes", []) or []:
            if isinstance(recipe, Mapping):
                columns.update(
                    str(column) for column in recipe.get("input_columns", []) or []
                )
    elif extractor_key == "statistical.derived_group_summarize":
        columns.update(str(item) for item in spec.get("summarize_columns", []) or [])
        for group in spec.get("groups", []) or []:
            if isinstance(group, Mapping) and group.get("source_column"):
                columns.add(str(group["source_column"]))
    elif extractor_key == "model.genesis":
        columns.update(
            family_context_columns(model_family_contract(spec.get("model_family")), spec)
        )
        for branch in spec.get("branches", []) or []:
            if isinstance(branch, Mapping):
                if branch.get("outcome"):
                    columns.add(str(branch["outcome"]))
                columns.update(str(item) for item in branch.get("predictors", []) or [])
                # Derived-term sources are real source columns too; leaving them
                # out let a typo in a dummy or polynomial column reach execution.
                columns.update(str(item) for item in branch.get("categorical", []) or [])
                for entry in branch.get("polynomials", []) or []:
                    if isinstance(entry, Mapping) and entry.get("column"):
                        columns.add(str(entry["column"]))
    elif extractor_key == "model.post_estimation":
        if spec.get("column"):
            columns.add(str(spec["column"]))
        for selector in spec.get("term_selectors", []) or []:
            if isinstance(selector, Mapping) and selector.get("column"):
                columns.add(str(selector["column"]))
    return columns


def _validate_step_spec(operation_id: str, spec: Mapping[str, Any]) -> None:
    """Validate a spec with the same server validators the manual paths use."""

    from ..statistical_exploration import (
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
    if validator_key == "capability_factory.custom_operation":
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


def _validate_declared_field_types(
    operation_id: str,
    spec: Mapping[str, Any],
    contract: StepSpecContract,
) -> None:
    """Apply only the small JSON type vocabulary declared by a contract."""

    for field_name, type_name in contract.field_types.items():
        if field_name not in spec or spec[field_name] is None:
            continue
        value = spec[field_name]
        valid = {
            "string": isinstance(value, str) and not isinstance(value, bool),
            "list": isinstance(value, list),
            "object": isinstance(value, Mapping),
        }.get(type_name)
        if valid is None:
            raise OperationValidationError(
                f"{operation_id} contract declares unsupported field type: {type_name}"
            )
        if not valid:
            raise OperationValidationError(
                f"{operation_id} field {field_name} must be a {type_name}"
            )


def validate_workflow_steps(
    steps: Any,
    *,
    available_columns: list[str] | tuple[str, ...] | None = None,
) -> list[dict[str, Any]]:
    """Validate an Agent-composed plan: identity, DAG, specs, and schema."""

    if not isinstance(steps, list) or not steps:
        raise OperationValidationError("workflow steps must be a non-empty list")
    seen_ids: set[str] = set()
    normalized: list[dict[str, Any]] = []
    for entry in steps:
        if not isinstance(entry, Mapping):
            raise OperationValidationError("each workflow step must be an object")
        unknown = set(entry) - {"step_id", "operation_id", "spec", "depends_on", "expected_artifacts"}
        if unknown:
            raise OperationValidationError(
                "workflow step contains unknown field(s): " + ", ".join(sorted(unknown))
            )
        step_id = entry.get("step_id")
        if not isinstance(step_id, str) or _STEP_ID_PATTERN.fullmatch(step_id) is None:
            raise OperationValidationError(f"invalid workflow step_id: {step_id!r}")
        if step_id in seen_ids:
            raise OperationValidationError(f"duplicate workflow step_id: {step_id}")
        seen_ids.add(step_id)
        operation_id = entry.get("operation_id")
        if operation_id not in WORKFLOW_STEP_OPERATIONS:
            raise OperationValidationError(
                f"workflow step {step_id} operation_id is unsupported: {operation_id!r}"
            )
        spec = entry.get("spec")
        if not isinstance(spec, Mapping):
            raise OperationValidationError(f"workflow step {step_id} spec must be an object")
        depends_on = entry.get("depends_on", [])
        if not isinstance(depends_on, list) or any(
            not isinstance(item, str) or not item for item in depends_on
        ):
            raise OperationValidationError(f"workflow step {step_id} depends_on must be step ids")
        # `source` is a composition-level field owned by the workflow, not by
        # any one operation's spec contract, so it is validated here and kept
        # out of the per-operation validator that would reject it as unknown.
        # Keyed on presence, not on truthiness: an explicit `"source": None` is
        # a malformed commitment and must be rejected, never silently dropped.
        declares_source = "source" in spec
        source_commitment = spec.get("source")
        operation_spec = {key: value for key, value in spec.items() if key != "source"}
        if declares_source:
            _validate_source_commitment(step_id, source_commitment)
        _validate_step_spec(str(operation_id), operation_spec)
        normalized_spec = operation_spec
        if declares_source:
            normalized_spec["source"] = {
                "from_step": source_commitment["from_step"],
                "output": source_commitment["output"],
            }
        normalized.append(
            {
                "step_id": step_id,
                "operation_id": str(operation_id),
                "spec": normalized_spec,
                "depends_on": list(dict.fromkeys(depends_on)),
                "expected_artifacts": [
                    str(item) for item in entry.get("expected_artifacts", []) or []
                ],
            }
        )

    known = {step["step_id"] for step in normalized}
    for step in normalized:
        missing = [dep for dep in step["depends_on"] if dep not in known]
        if missing:
            raise OperationValidationError(
                f"workflow step {step['step_id']} depends on unknown step(s): "
                + ", ".join(missing)
            )
        if step["step_id"] in step["depends_on"]:
            raise OperationValidationError(f"workflow step {step['step_id']} depends on itself")

    ordered = _topological_order(normalized)

    if available_columns is not None:
        available = {str(column) for column in available_columns}
        # Columns a step creates become available to later steps: a derived
        # indicator is a legitimate input downstream even though it is absent
        # from the raw source schema.
        produced: set[str] = set()
        for step in ordered:
            referenced = _spec_columns(step["operation_id"], step["spec"])
            missing = sorted(referenced - available - produced)
            if missing:
                raise OperationValidationError(
                    f"workflow step {step['step_id']} references missing column(s): "
                    + ", ".join(missing)
                )
            if step["operation_id"] == "statistical.derive_boolean":
                produced.update(
                    str(recipe["output_name"]) for recipe in step["spec"]["recipes"]
                )
            if step["operation_id"] == "statistical.derive_numeric":
                outputs = {
                    str(recipe["output_name"]) for recipe in step["spec"]["recipes"]
                }
                collisions = sorted(outputs & (available | produced))
                if collisions:
                    raise OperationValidationError(
                        "derive_numeric output column already exists: " + ", ".join(collisions)
                    )
                produced.update(outputs)
    return ordered


def _validate_source_commitment(step_id: str, source: Any) -> None:
    """Validate one step's declared upstream input reference."""

    if not isinstance(source, Mapping):
        raise OperationValidationError(f"workflow step {step_id} source must be an object")
    unknown = set(source) - {"from_step", "output"}
    if unknown:
        raise OperationValidationError(
            f"workflow step {step_id} source contains unknown field(s): "
            + ", ".join(sorted(unknown))
        )
    from_step = source.get("from_step")
    if not isinstance(from_step, str) or not from_step:
        raise OperationValidationError(
            f"workflow step {step_id} source.from_step must name another step in this plan"
        )
    output = source.get("output")
    if output not in SUPPORTED_STEP_OUTPUTS:
        raise OperationValidationError(
            f"workflow step {step_id} source.output must be one of: "
            + ", ".join(sorted(SUPPORTED_STEP_OUTPUTS))
        )


def _topological_order(steps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Order the plan by dependency, refusing a cycle rather than looping."""

    by_id = {step["step_id"]: step for step in steps}
    state: dict[str, int] = {}
    ordered: list[dict[str, Any]] = []

    def visit(step_id: str, trail: tuple[str, ...]) -> None:
        mark = state.get(step_id, 0)
        if mark == 2:
            return
        if mark == 1:
            raise OperationValidationError(
                "workflow steps contain a dependency cycle: "
                + " -> ".join((*trail, step_id))
            )
        state[step_id] = 1
        for dependency in by_id[step_id]["depends_on"]:
            visit(dependency, (*trail, step_id))
        state[step_id] = 2
        ordered.append(by_id[step_id])

    for step in steps:
        visit(step["step_id"], ())
    return ordered

__all__ = [
    "SUPPORTED_STEP_OUTPUTS",
    "WORKFLOW_OPERATION_ID",
    "WORKFLOW_OPERATION_VERSION",
    "WORKFLOW_STEP_OPERATIONS",
    "WORKFLOW_STEP_SPEC_CONTRACTS",
    "WORKFLOW_TEMPLATE",
    "StepSpecContract",
    "validate_workflow_operation",
    "validate_workflow_steps",
    "workflow_authorization",
    "workflow_proposal_schema",
    "workflow_step_vocabulary",
    "workflow_dispatcher_key",
]
