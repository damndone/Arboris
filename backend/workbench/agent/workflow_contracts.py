"""Server-owned contracts for Agent-composed multi-step workflows."""

from __future__ import annotations

import math
import re

from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any, Callable

import numpy as np
import pandas as pd

from .operations import OperationValidationError


WORKFLOW_OPERATION_ID = "operation.multi_step"
WORKFLOW_OPERATION_VERSION = "v1"
WORKFLOW_TEMPLATE = "agent-composed-v1"

# Closed values are declarations owned by the workflow contract. Consumers
# (schema projection, validation, and Agent vocabulary) must derive from these
# tuples instead of maintaining another list of accepted strings.
WORKFLOW_SPLIT_KINDS = ("iid", "grouped", "temporal", "panel")
DID_MODE_VALUES = ("cohort", "two_by_two", "status")


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
                                    "enum": list(workflow_step_operations()),
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
    #: Whether this step persists a dataset child a later step can consume as
    #: its `source`. A per-operation fact, so it is declared here with the rest
    #: of them rather than in a set maintained alongside the registry.
    produces_dataset: bool = False
    #: Server-owned semantic role published by a dataset producer.
    produced_dataset_kind: str | None = None
    #: Closed input roles accepted by a consumer. An empty tuple means this
    #: operation has no role-specific restriction.
    accepted_dataset_kinds: tuple[str, ...] = ()
    #: Whether the runtime hands this step the resolved input frame at all.
    #: A step that never receives one cannot honour a `source`: the resolution
    #: would succeed, every check would pass, and the frame would be dropped
    #: while the step read the workflow's original target instead. Declaring
    #: `source` on such a step is refused rather than silently ignored.
    consumes_input_frame: bool = True
    #: Whether the runtime can reconstruct this step's effect by replaying its
    #: declared spec onto the workflow target. Only true for the one operation
    #: `_upstream_numeric_steps` knows how to replay; every other dataset
    #: producer must be read through `source`, because an unreplayable
    #: transform that nothing reads is a step whose work silently vanishes.
    replayable_by_recipe: bool = False
    #: Closed values for fields whose vocabulary is smaller than their JSON type.
    field_enums: Mapping[str, tuple[str, ...]] = field(default_factory=dict)
    #: Nested schemas for object-valued fields. These are published alongside
    #: the outer workflow step fields so a consumer can write a typed request
    #: without guessing keys inside ``column_bindings`` or ``options``; the
    #: same declaration also enforces object keys, item shapes, and bounds.
    field_schemas: Mapping[str, Mapping[str, Any]] = field(default_factory=dict)
    #: Capability inventory identity projected from this declaration.
    capability_kind: str = "data_operation"
    #: Informational explanation for a capability that is composable but not a
    #: top-level proposal. This is deliberately independent of reachability
    #: exemptions.
    top_level_exposure_note: str | None = None

    def __post_init__(self) -> None:
        field_names = set(self.fields)
        unknown_required = set(self.required) - field_names
        if unknown_required:
            raise ValueError(
                "workflow step required field(s) are undeclared: "
                + ", ".join(sorted(unknown_required))
            )
        unknown_types = set(self.field_types) - field_names
        if unknown_types:
            raise ValueError(
                "workflow step field type(s) are undeclared: "
                + ", ".join(sorted(unknown_types))
            )
        unknown_enums = set(self.field_enums) - field_names
        if unknown_enums:
            raise ValueError(
                "workflow step enum field(s) are undeclared: "
                + ", ".join(sorted(unknown_enums))
            )
        for name, values in self.field_enums.items():
            if not isinstance(values, tuple) or not values:
                raise ValueError(
                    f"workflow step field enum {name!r} must be a non-empty tuple"
                )
            if any(type(value) is not str or not value for value in values):
                raise ValueError(
                    f"workflow step field enum {name!r} must contain non-empty strings"
                )
            if len(set(values)) != len(values):
                raise ValueError(f"workflow step field enum {name!r} contains duplicates")
        unknown_schemas = set(self.field_schemas) - field_names
        if unknown_schemas:
            raise ValueError(
                "workflow step schema field(s) are undeclared: "
                + ", ".join(sorted(unknown_schemas))
            )
        for name, schema in self.field_schemas.items():
            if not isinstance(schema, Mapping) or not schema:
                raise ValueError(
                    f"workflow step field schema {name!r} must be a non-empty object"
                )
        from .capability_contract import CAPABILITY_KINDS

        if self.capability_kind not in CAPABILITY_KINDS:
            raise ValueError(
                "workflow step capability kind must be one of: "
                + ", ".join(sorted(CAPABILITY_KINDS))
            )
        if self.top_level_exposure_note is not None and not self.top_level_exposure_note.strip():
            raise ValueError("workflow step top-level exposure note must not be blank")
        if self.produces_dataset != (self.produced_dataset_kind is not None):
            raise ValueError(
                "workflow step dataset producer must declare exactly one produced_dataset_kind"
            )
        if self.produced_dataset_kind is not None and (
            type(self.produced_dataset_kind) is not str or not self.produced_dataset_kind.strip()
        ):
            raise ValueError("workflow step produced_dataset_kind must be a non-empty string")
        if any(type(item) is not str or not item for item in self.accepted_dataset_kinds):
            raise ValueError("workflow step accepted_dataset_kinds must contain non-empty strings")
        if len(set(self.accepted_dataset_kinds)) != len(self.accepted_dataset_kinds):
            raise ValueError("workflow step accepted_dataset_kinds contains duplicates")

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
            "field_enums": {
                name: list(values) for name, values in self.field_enums.items()
            },
            "field_schemas": {
                name: deepcopy(dict(schema))
                for name, schema in self.field_schemas.items()
            },
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
            "produces_dataset": self.produces_dataset,
            "produced_dataset_kind": self.produced_dataset_kind,
            "accepted_dataset_kinds": list(self.accepted_dataset_kinds),
            "consumes_input_frame": self.consumes_input_frame,
            "replayable_by_recipe": self.replayable_by_recipe,
            "capability_kind": self.capability_kind,
            "top_level_exposure_note": self.top_level_exposure_note,
        }

    def to_schema(self) -> dict[str, Any]:
        """Build the editable spec schema from the same field declarations."""

        type_map = {
            "string": "string",
            "list": "array",
            "object": "object",
            "nullable_string": ["string", "null"],
            "number": "number",
            "integer": "integer",
            "boolean": "boolean",
        }
        properties: dict[str, dict[str, Any]] = {}
        for name, description in self.fields.items():
            field_schema: dict[str, Any] = deepcopy(
                dict(self.field_schemas.get(name, {}))
            )
            field_schema.setdefault("description", description)
            declared_type = self.field_types.get(name)
            if declared_type is not None and "type" not in field_schema and "oneOf" not in field_schema:
                field_schema["type"] = type_map.get(declared_type, declared_type)
            if name in self.field_enums:
                field_schema["enum"] = list(self.field_enums[name])
            properties[name] = field_schema
        return {
            "type": "object",
            "required": list(self.required),
            "properties": properties,
            "additionalProperties": False,
        }


def pack_step_contract(
    *,
    summary: str,
    fields: Mapping[str, str],
    required: tuple[str, ...],
    field_types: Mapping[str, str],
    dispatcher_key: str,
    output_schema_ref: str,
    field_enums: Mapping[str, tuple[str, ...]] | None = None,
    field_schemas: Mapping[str, Mapping[str, Any]] | None = None,
    consumes_input_frame: bool = True,
    accepted_dataset_kinds: tuple[str, ...] = ("derived_data", "prepared_data"),
    top_level_exposure_note: str | None = None,
) -> StepSpecContract:
    """Build a non-top-level pack declaration for workflow composition."""

    return StepSpecContract(
        summary=summary,
        fields=dict(fields),
        required=tuple(required),
        field_types=dict(field_types),
        field_enums=dict(field_enums or {}),
        field_schemas=dict(field_schemas or {}),
        semantic_validator_key="p7.pack",
        column_extractor_key="p7.pack",
        output_schema_ref=output_schema_ref,
        dispatcher_key=dispatcher_key,
        ui_description=summary,
        capability_kind="pack",
        natural_language_enabled=False,
        produces_dataset=False,
        accepted_dataset_kinds=accepted_dataset_kinds,
        consumes_input_frame=consumes_input_frame,
        replayable_by_recipe=False,
        top_level_exposure_note=top_level_exposure_note,
    )


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
        allowed_split_kinds = set(WORKFLOW_SPLIT_KINDS)
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
    if mode not in DID_MODE_VALUES:
        raise OperationValidationError(
            "model.genesis did requires did_mode: " + ", ".join(DID_MODE_VALUES)
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


def _validate_workflow_step_entry(
    operation_id: str,
    contract: StepSpecContract,
) -> None:
    if type(operation_id) is not str or not operation_id.strip():
        raise ValueError("workflow step operation_id must be a non-empty string")
    if not isinstance(contract, StepSpecContract):
        raise TypeError("workflow step registry values must be StepSpecContract instances")


class WorkflowStepContractRegistry(dict[str, StepSpecContract]):
    """Live workflow declarations with synchronized derived projections."""

    def __init__(
        self,
        initial: Mapping[str, StepSpecContract] | None = None,
    ) -> None:
        values = dict(initial or {})
        for operation_id, contract in values.items():
            _validate_workflow_step_entry(operation_id, contract)
        super().__init__(values)

    def __setitem__(self, operation_id: str, contract: StepSpecContract) -> None:
        _validate_workflow_step_entry(operation_id, contract)
        super().__setitem__(operation_id, contract)
        _refresh_workflow_contract_views()

    def __delitem__(self, operation_id: str) -> None:
        super().__delitem__(operation_id)
        _refresh_workflow_contract_views()

    def update(
        self,
        *args: Mapping[str, StepSpecContract],
        **kwargs: StepSpecContract,
    ) -> None:
        values = dict(*args, **kwargs)
        for operation_id, contract in values.items():
            _validate_workflow_step_entry(operation_id, contract)
        super().update(values)
        _refresh_workflow_contract_views()


def _refresh_workflow_contract_views() -> None:
    """Refresh every compatibility projection from the live declaration map."""

    global _ALLOWED_SPEC_FIELDS
    global STEP_CONSUMES_INPUT_FRAME
    global STEP_PRODUCES_DATASET
    global STEP_REPLAYABLE_BY_RECIPE
    global WORKFLOW_STEP_OPERATIONS

    WORKFLOW_STEP_OPERATIONS = tuple(WORKFLOW_STEP_SPEC_CONTRACTS)
    _ALLOWED_SPEC_FIELDS = {
        operation_id: contract.allowed
        for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
    }
    STEP_PRODUCES_DATASET = frozenset(
        operation_id
        for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
        if contract.produces_dataset
    )
    STEP_CONSUMES_INPUT_FRAME = frozenset(
        operation_id
        for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
        if contract.consumes_input_frame
    )
    STEP_REPLAYABLE_BY_RECIPE = frozenset(
        operation_id
        for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items()
        if contract.replayable_by_recipe
    )


def _p5_exposure_note(capability_id: str) -> str:
    return (
        f"{capability_id} is composable through operation.multi_step; it is "
        "not a standalone natural-language proposal."
    )


def statistical_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Derive one named-test step from every live statistical family."""

    from ..statistical_tests import TEST_FAMILIES

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
            },
            required=("analysis_columns",),
            field_types={
                "analysis_columns": "list",
                "reference_means": "object",
                "paired_columns": "list",
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
        for entry in build_capabilities()["prediction_models"]
    }


def data_preparation_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Derive dataset-producing preparation steps from live registries."""

    from workbench.engine.capabilities import build_capabilities

    manifest = build_capabilities()
    contracts: dict[str, StepSpecContract] = {}
    for entry in manifest["imputation_methods"]:
        capability_id = f"imputation.{entry['key']}"
        contracts[capability_id] = StepSpecContract(
            summary=str(entry["description"]),
            fields={
                "columns": "Numeric columns selected for the imputation method.",
                "m": "Number of imputed datasets requested by the method.",
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

    from .recipe_contracts import RECIPE_CONTRACTS

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


def selector_workflow_step_contracts() -> dict[str, StepSpecContract]:
    """Derive selector steps from the live model selector registry."""

    from .capability_contract import MODEL_TYPE_SELECTORS

    genesis = WORKFLOW_STEP_SPEC_CONTRACTS["model.genesis"]
    fields = {
        name: description
        for name, description in genesis.fields.items()
        if name != "model_family"
    }
    field_types = {
        name: type_name
        for name, type_name in genesis.field_types.items()
        if name != "model_family"
    }
    return {
        f"model.{selector}": StepSpecContract(
            summary=(
                f"Resolve the live {selector} model selector against the declared "
                "branches and target structure."
            ),
            fields=fields,
            required=("branches",),
            field_types=field_types,
            semantic_validator_key="model.auto",
            reference_resolver_key="workflow.source_columns",
            column_extractor_key="model.auto",
            risk_class="high",
            confirmation_policy="proposal_authorization",
            output_schema_ref="workbench.model.auto/v1",
            dispatcher_key="workbench.agent.workflow_runtime.model_auto",
            scope="automatic model selector",
            risk_level="high",
            reconciler_key="model.auto",
            diff_builder_key="model.auto.diff.v1",
            verification_builder_key="model.auto.verification.v1",
            ui_description=f"Resolve and run the live {selector} model selector.",
            capability_kind="selector",
            top_level_exposure_note=_p5_exposure_note(f"model.{selector}"),
        )
        for selector in sorted(MODEL_TYPE_SELECTORS)
    }


def _p5_workflow_step_contracts() -> dict[str, StepSpecContract]:
    contracts: dict[str, StepSpecContract] = {}
    for derived in (
        statistical_workflow_step_contracts(),
        prediction_workflow_step_contracts(),
        data_preparation_workflow_step_contracts(),
        recipe_workflow_step_contracts(),
        selector_workflow_step_contracts(),
    ):
        overlap = set(contracts) & set(derived)
        if overlap:
            raise ValueError(
                "P5 workflow contract identity collision: "
                + ", ".join(sorted(overlap))
            )
        contracts.update(derived)
    return contracts


WORKFLOW_STEP_SPEC_CONTRACTS: WorkflowStepContractRegistry = WorkflowStepContractRegistry({
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
        accepted_dataset_kinds=("derived_data", "prepared_data"),
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
})

from .p7_pack_registry import p7_workflow_step_contracts  # noqa: E402
from .workflow_capability_registry import workflow_capability_step_contracts  # noqa: E402


WORKFLOW_STEP_SPEC_CONTRACTS.update(_p5_workflow_step_contracts())
WORKFLOW_STEP_SPEC_CONTRACTS.update(p7_workflow_step_contracts())
WORKFLOW_STEP_SPEC_CONTRACTS.update(workflow_capability_step_contracts())
_refresh_workflow_contract_views()


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

    secondary_fields = {
        "secondary_run_id": "Real run id for the secondary dataset, discovered from project evidence.",
        "secondary_node_id": "Real graph node id for the secondary dataset.",
        "secondary_artifact_id": "Real artifact-index id for the secondary dataset.",
    }
    contracts: dict[str, StepSpecContract] = {
        "data.merge": contract(
            "data.merge",
            "Merge the current dataset with a declared secondary dataset.",
            {
                **secondary_fields,
                "keys": "Non-empty join-key column list present in both datasets.",
                "how": "Join mode: left, right, inner, or outer.",
                "indicator": "Optional true or a non-empty output-column name.",
                "growth_policy": "Explicit row-growth bound.",
                "max_growth_factor": "Legacy growth-factor bound.",
            },
            ("secondary_run_id", "secondary_node_id", "secondary_artifact_id", "keys"),
            {
                "secondary_run_id": "string",
                "secondary_node_id": "string",
                "secondary_artifact_id": "string",
                "keys": "list",
                "how": "string",
                "growth_policy": "object",
                "max_growth_factor": "number",
            },
            {
                "secondary_run_id": {"type": "string", "minLength": 1},
                "secondary_node_id": {"type": "string", "minLength": 1},
                "secondary_artifact_id": {"type": "string", "minLength": 1},
                "keys": _string_list_field_schema(),
                "how": {"type": "string", "enum": ["left", "right", "inner", "outer"]},
                "indicator": {"type": ["boolean", "string"], "minLength": 1},
                "growth_policy": _growth_policy_field_schema(),
                "max_growth_factor": {"type": "number", "exclusiveMinimum": 0},
            },
            field_enums={"how": ("left", "right", "inner", "outer")},
            natural_language_enabled=True,
        ),
        "data.append": contract(
            "data.append",
            "Append a declared secondary dataset with an explicit schema policy.",
            {
                **secondary_fields,
                "schema_policy": "Schema policy: exact or union.",
                "row_growth_policy": "Explicit row-growth bound.",
                "max_growth_factor": "Legacy growth-factor bound.",
            },
            ("secondary_run_id", "secondary_node_id", "secondary_artifact_id"),
            {
                "secondary_run_id": "string",
                "secondary_node_id": "string",
                "secondary_artifact_id": "string",
                "schema_policy": "string",
                "row_growth_policy": "object",
                "max_growth_factor": "number",
            },
            {
                "secondary_run_id": {"type": "string", "minLength": 1},
                "secondary_node_id": {"type": "string", "minLength": 1},
                "secondary_artifact_id": {"type": "string", "minLength": 1},
                "schema_policy": {"type": "string", "enum": ["exact", "union"]},
                "row_growth_policy": _growth_policy_field_schema(),
                "max_growth_factor": {"type": "number", "exclusiveMinimum": 0},
            },
            field_enums={"schema_policy": ("exact", "union")},
            natural_language_enabled=True,
        ),
        "data.reshape": contract(
            "data.reshape",
            "Reshape the current dataset with an explicitly declared direction.",
            {
                "direction": "Direction: wide_to_long or long_to_wide.",
                "id_columns": "Identifier columns for wide_to_long.",
                "value_columns": "Measured wide columns for wide_to_long.",
                "index": "Index columns for long_to_wide.",
                "columns": "Long-form column containing wide labels.",
                "values": "Long-form value column.",
                "var_name": "Output variable-name column for wide_to_long.",
                "value_name": "Output value column for wide_to_long.",
            },
            ("direction",),
            {
                "direction": "string",
                "id_columns": "list",
                "value_columns": "list",
                "index": "list",
                "columns": "string",
                "values": "string",
                "var_name": "string",
                "value_name": "string",
            },
            {
                "direction": {"type": "string", "enum": ["wide_to_long", "long_to_wide"]},
                "id_columns": _string_list_field_schema(),
                "value_columns": _string_list_field_schema(),
                "index": _string_list_field_schema(),
                "columns": {"type": "string", "minLength": 1},
                "values": {"type": "string", "minLength": 1},
                "var_name": {"type": "string", "minLength": 1},
                "value_name": {"type": "string", "minLength": 1},
            },
            field_enums={"direction": ("wide_to_long", "long_to_wide")},
            natural_language_enabled=True,
        ),
        "data.subset": contract(
            "data.subset",
            "Subset rows and columns with closed comparison operators.",
            {
                "columns": "Explicit output columns.",
                "filters": "ANDed closed filters with column, op, and operator value.",
                "equals": "Legacy equality map retained for compatibility.",
                "row_indices": "Explicit zero-based row indices.",
                "row_index_range": "Bounded half-open row range.",
                "row_range": "Legacy alias for row_index_range.",
            },
            ("columns",),
            {
                "columns": "list",
                "filters": "list",
                "equals": "object",
                "row_indices": "list",
                "row_index_range": "object",
                "row_range": "object",
            },
            {
                "columns": _string_list_field_schema(),
                "filters": {"type": "array", "items": filter_schema},
                "equals": {"type": "object", "additionalProperties": {}},
                "row_indices": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "integer", "minimum": 0},
                },
                "row_index_range": {
                    "type": "object",
                    "required": ["start", "stop"],
                    "properties": {
                        "start": {"type": "integer", "minimum": 0},
                        "stop": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
                "row_range": {
                    "type": "object",
                    "required": ["start", "stop"],
                    "properties": {
                        "start": {"type": "integer", "minimum": 0},
                        "stop": {"type": "integer", "minimum": 0},
                    },
                    "additionalProperties": False,
                },
            },
            natural_language_enabled=True,
        ),
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
        "data.dedupe": contract(
            "data.dedupe",
            "Remove duplicate rows using an explicit key and keep policy.",
            {"columns": "Deduplication key columns.", "keep": "first or last occurrence."},
            ("columns", "keep"),
            {"columns": "list", "keep": "string"},
            {
                "columns": _string_list_field_schema(),
                "keep": {"type": "string", "enum": ["first", "last"]},
            },
        ),
        "data.rename": contract(
            "data.rename",
            "Rename existing columns with collision-checked mapping.",
            {"mapping": "Non-empty old-column to new-column mapping."},
            ("mapping",),
            {"mapping": "object"},
            {
                "mapping": {
                    "type": "object",
                    "minProperties": 1,
                    "additionalProperties": {"type": "string", "minLength": 1},
                }
            },
        ),
        "data.aggregate": contract(
            "data.aggregate",
            "Aggregate rows by declared groups and named functions.",
            {"group_by": "Group-key columns.", "aggregations": "Named aggregation declarations."},
            ("group_by", "aggregations"),
            {"group_by": "list", "aggregations": "list"},
            {
                "group_by": _string_list_field_schema(),
                "aggregations": {"type": "array", "minItems": 1, "items": aggregation_schema},
            },
        ),
        "data.fill_missing": contract(
            "data.fill_missing",
            "Resolve missing values with an explicit per-column strategy.",
            {"strategies": "Per-column drop, constant, mean, median, or mode strategies."},
            ("strategies",),
            {"strategies": "list"},
            {"strategies": {"type": "array", "minItems": 1, "items": fill_strategy_schema}},
        ),
        "data.tsset": contract(
            "data.tsset",
            "Declare and stably order a time or panel-time index.",
            {
                "time_column": "Time column.",
                "frequency": "Declared frequency: D, W, M, Q, or Y.",
                "panel_id_column": "Optional panel identifier column.",
            },
            ("time_column", "frequency"),
            {"time_column": "string", "frequency": "string", "panel_id_column": "string"},
            {
                "time_column": {"type": "string", "minLength": 1},
                "frequency": {"type": "string", "enum": ["D", "W", "M", "Q", "Y"]},
                "panel_id_column": {"type": "string", "minLength": 1},
            },
            field_enums={"frequency": ("D", "W", "M", "Q", "Y")},
        ),
        "data.lag": contract(
            "data.lag",
            "Create deterministic lag columns from an ordered dataset.",
            {
                "columns": "Columns to lag.",
                "lags": "Positive integer lag periods.",
                "difference": "Optional non-negative difference order before lagging.",
            },
            ("columns", "lags"),
            {"columns": "list", "lags": "list", "difference": "integer"},
            {
                "columns": _string_list_field_schema(),
                "lags": {
                    "type": "array",
                    "minItems": 1,
                    "uniqueItems": True,
                    "items": {"type": "integer", "minimum": 1},
                },
                "difference": {"type": "integer", "minimum": 0},
            },
        ),
    }
    return contracts


for _data_operation_id, _data_operation_contract in _data_management_step_contracts().items():
    WORKFLOW_STEP_SPEC_CONTRACTS[_data_operation_id] = _data_operation_contract


def register_workflow_step(operation_id: str, contract: StepSpecContract) -> None:
    """Register one workflow step and refresh all declaration projections."""

    WORKFLOW_STEP_SPEC_CONTRACTS[operation_id] = contract


def workflow_step_operations() -> tuple[str, ...]:
    """Return the current operation IDs from the live step registry."""

    return tuple(WORKFLOW_STEP_SPEC_CONTRACTS)


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
        # The composition seam. Every value below is read from the same
        # declarations the validator refuses against, so an operation that
        # gains `produces_dataset` becomes nameable by a plan in the same edit
        # that registers it. A hand-written list here would be the second place
        # to remember, and the one that goes stale.
        "source": {
            "purpose": (
                "By default every step reads the workflow's own target dataset. "
                "A step that must instead read the dataset an earlier step "
                "produced declares `source` inside its `spec`."
            ),
            "shape": {
                "from_step": (
                    "The step_id of the earlier step in this same plan whose "
                    "output this step reads."
                ),
                "output": (
                    "Which of that step's outputs to read, from the supported "
                    "output values listed with this entry."
                ),
            },
            "outputs": sorted(SUPPORTED_STEP_OUTPUTS),
            "produced_by": sorted(STEP_PRODUCES_DATASET),
            "declarable_by": sorted(STEP_CONSUMES_INPUT_FRAME),
            "semantics": (
                "from_step may only name a step whose operation is one of the "
                "dataset producers listed here, and only a step whose operation "
                "is listed as able to declare a source may carry one. Declaring "
                "a source is also "
                "declaring a dependency: from_step is folded into depends_on, so "
                "the step runs after its producer and is blocked, never run "
                "against the original table, if that producer fails. A step has "
                "exactly one data source -- `source` is a single object, never a "
                "list -- and a step that declares none reads the workflow target. "
                "To work from two produced datasets, produce the combination in "
                "one step and read that step."
            ),
        },
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
    elif extractor_key and extractor_key.startswith("data."):
        operation = extractor_key.removeprefix("data.")
        if operation in {"merge", "append"}:
            columns.update(str(item) for item in spec.get("keys", []) or [])
        elif operation == "reshape":
            direction = spec.get("direction")
            if direction == "wide_to_long":
                columns.update(str(item) for item in spec.get("id_columns", []) or [])
                columns.update(str(item) for item in spec.get("value_columns", []) or [])
            elif direction == "long_to_wide":
                columns.update(str(item) for item in spec.get("index", []) or [])
                columns.update(str(item) for item in ("columns", "values") if spec.get(item))
        elif operation == "subset":
            columns.update(str(item) for item in spec.get("columns", []) or [])
            equals = spec.get("equals")
            if isinstance(equals, Mapping):
                columns.update(str(item) for item in equals)
            for item in spec.get("filters", []) or []:
                if isinstance(item, Mapping) and item.get("column"):
                    columns.add(str(item["column"]))
        elif operation == "feature_recipe":
            columns.update(str(item) for item in spec.get("inputs", []) or [])
        elif operation == "dedupe":
            columns.update(str(item) for item in spec.get("columns", []) or [])
        elif operation == "rename":
            mapping = spec.get("mapping")
            if isinstance(mapping, Mapping):
                columns.update(str(item) for item in mapping)
        elif operation == "aggregate":
            columns.update(str(item) for item in spec.get("group_by", []) or [])
            for item in spec.get("aggregations", []) or []:
                if isinstance(item, Mapping) and item.get("column"):
                    columns.add(str(item["column"]))
        elif operation == "fill_missing":
            for item in spec.get("strategies", []) or []:
                if isinstance(item, Mapping) and item.get("column"):
                    columns.add(str(item["column"]))
        elif operation == "tsset":
            for key in ("time_column", "panel_id_column"):
                if spec.get(key):
                    columns.add(str(spec[key]))
        elif operation == "lag":
            columns.update(str(item) for item in spec.get("columns", []) or [])
    elif extractor_key == "statistical.named_test":
        columns.update(str(item) for item in spec.get("analysis_columns", []) or [])
        for column in (spec.get("reference_means") or {}):
            columns.add(str(column))
        for pair in spec.get("paired_columns", []) or []:
            if isinstance(pair, (list, tuple)):
                columns.update(str(item) for item in pair if item)
    elif extractor_key == "prediction.model":
        if spec.get("y"):
            columns.add(str(spec["y"]))
        columns.update(str(item) for item in spec.get("x", []) or [])
        for field_name in ("entity_column", "group_column", "time_column"):
            if spec.get(field_name):
                columns.add(str(spec[field_name]))
    elif extractor_key == "data_preparation.imputation":
        columns.update(str(item) for item in spec.get("columns", []) or [])
    elif extractor_key == "data_preparation.resampling":
        if spec.get("target_column"):
            columns.add(str(spec["target_column"]))
        columns.update(str(item) for item in spec.get("feature_columns", []) or [])
    elif extractor_key == "model.time_series.recipe":
        options = spec.get("model_options") or {}
        if isinstance(options, Mapping):
            for field_name in ("time_column", "value_column"):
                if options.get(field_name):
                    columns.add(str(options[field_name]))
        for field_name in ("time_column", "value_column"):
            if spec.get(field_name):
                columns.add(str(spec[field_name]))
    elif extractor_key == "model.auto":
        for branch in spec.get("branches", []) or []:
            if isinstance(branch, Mapping):
                if branch.get("outcome"):
                    columns.add(str(branch["outcome"]))
                columns.update(str(item) for item in branch.get("predictors", []) or [])
                columns.update(str(item) for item in branch.get("categorical", []) or [])
                for entry in branch.get("polynomials", []) or []:
                    if isinstance(entry, Mapping) and entry.get("column"):
                        columns.add(str(entry["column"]))
        columns.update(str(item) for item in spec.get("context_columns", []) or [])
    elif extractor_key == "p7.pack":
        from .p7_pack_registry import p7_pack_registry

        operation = p7_pack_registry.get(operation_id)
        columns.update(
            operation.extract_columns(
                {
                    "operation_id": operation_id,
                    "input_mode": spec.get("input_mode"),
                    "column_bindings": spec.get("column_bindings"),
                    "options": spec.get("options"),
                }
            )
        )
    elif extractor_key == "workflow_capability":
        from .workflow_capability_registry import workflow_capability_registry

        operation = workflow_capability_registry().require(operation_id)
        request = operation.validate(
            {
                "operation_id": operation_id,
                "input_mode": spec.get("input_mode"),
                "column_bindings": spec.get("column_bindings"),
                "options": spec.get("options"),
            }
        )
        for value in request["column_bindings"].values():
            if isinstance(value, str) and value:
                columns.add(value)
            elif isinstance(value, list):
                columns.update(
                    str(item) for item in value if isinstance(item, str) and item
                )
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
    if validator_key and validator_key.startswith("data."):
        _validate_data_management_step(operation_id, spec)
        return
    if validator_key == "capability_factory.custom_operation":
        return
    if validator_key == "p7.pack":
        from .p7_pack_registry import p7_pack_registry

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
        from .workflow_capability_registry import workflow_capability_registry

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
    from .recipe_contracts import recipe_contract

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


def _validate_data_management_step(operation_id: str, spec: Mapping[str, Any]) -> None:
    """Validate semantic choices that JSON shape alone cannot express."""

    from ..data_operations import (
        AGGREGATE_FUNCTIONS,
        FILL_MISSING_STRATEGIES,
        SUBSET_FILTER_OPERATORS,
        TSSET_FREQUENCIES,
    )

    operation = operation_id.removeprefix("data.")

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

    if operation in {"merge", "append"}:
        if operation == "merge":
            keys = strings(spec.get("keys"), "keys")
            how = spec.get("how", "left")
            if how not in {"left", "right", "inner", "outer"}:
                raise OperationValidationError(
                    f"{operation_id} how must be left, right, inner, or outer"
                )
            indicator = spec.get("indicator")
            if indicator is not None and not (
                indicator is True or (isinstance(indicator, str) and indicator.strip())
            ):
                raise OperationValidationError(
                    f"{operation_id} indicator must be true or a non-empty string"
                )
            if not keys:
                raise OperationValidationError(f"{operation_id} requires keys")
        else:
            if spec.get("schema_policy", "exact") not in {"exact", "union"}:
                raise OperationValidationError(
                    f"{operation_id} schema_policy must be exact or union"
                )
        return
    if operation == "reshape":
        direction = spec.get("direction")
        if direction == "wide_to_long":
            id_columns = strings(spec.get("id_columns"), "id_columns")
            value_columns = strings(spec.get("value_columns"), "value_columns")
            if set(id_columns) & set(value_columns):
                raise OperationValidationError(
                    f"{operation_id} id_columns and value_columns must be disjoint"
                )
            if any(key in spec for key in ("index", "columns", "values")):
                raise OperationValidationError(
                    f"{operation_id} wide_to_long does not accept long_to_wide fields"
                )
            var_name = text(spec.get("var_name", "variable"), "var_name")
            value_name = text(spec.get("value_name", "value"), "value_name")
            if var_name == value_name or var_name in id_columns or value_name in id_columns:
                raise OperationValidationError(
                    f"{operation_id} output names must not collide with id_columns"
                )
        elif direction == "long_to_wide":
            index = strings(spec.get("index"), "index")
            columns = text(spec.get("columns"), "columns")
            values = text(spec.get("values"), "values")
            if len(set(index + [columns, values])) != len(index) + 2:
                raise OperationValidationError(
                    f"{operation_id} index, columns, and values must be distinct"
                )
            if any(key in spec for key in ("id_columns", "value_columns", "var_name", "value_name")):
                raise OperationValidationError(
                    f"{operation_id} long_to_wide does not accept wide_to_long fields"
                )
        else:
            raise OperationValidationError(
                f"{operation_id} direction must be wide_to_long or long_to_wide"
            )
        return
    if operation == "subset":
        strings(spec.get("columns"), "columns")
        filters = spec.get("filters", [])
        if not isinstance(filters, list):
            raise OperationValidationError(f"{operation_id} filters must be a list")
        filter_columns: list[str] = []
        for index, item in enumerate(filters):
            if not isinstance(item, Mapping):
                raise OperationValidationError(f"{operation_id} filters[{index}] must be an object")
            column = text(item.get("column"), f"filters[{index}].column")
            operator = item.get("op")
            if operator not in SUBSET_FILTER_OPERATORS:
                raise OperationValidationError(
                    f"{operation_id} filters[{index}].op is not a closed comparison operator"
                )
            has_value = "value" in item
            if operator in {"is_missing", "not_missing"} and has_value:
                raise OperationValidationError(
                    f"{operation_id} filters[{index}] must not carry value for {operator}"
                )
            if operator not in {"is_missing", "not_missing"} and not has_value:
                raise OperationValidationError(
                    f"{operation_id} filters[{index}] requires value for {operator}"
                )
            if operator in {"in", "not_in"} and (
                not isinstance(item.get("value"), list) or not item["value"]
            ):
                raise OperationValidationError(
                    f"{operation_id} filters[{index}] value must be a non-empty list"
                )
            if operator == "between":
                value = item.get("value")
                if not isinstance(value, list) or len(value) != 2:
                    raise OperationValidationError(
                        f"{operation_id} filters[{index}] between requires two bounds"
                    )
                try:
                    if value[0] > value[1]:
                        raise OperationValidationError(
                            f"{operation_id} filters[{index}] lower bound exceeds upper bound"
                        )
                except TypeError as exc:
                    raise OperationValidationError(
                        f"{operation_id} filters[{index}] bounds are not comparable"
                    ) from exc
            filter_columns.append(column)
        equals = spec.get("equals", {})
        if not isinstance(equals, Mapping):
            raise OperationValidationError(f"{operation_id} equals must be an object")
        overlap = set(equals) & set(filter_columns)
        if overlap:
            raise OperationValidationError(
                f"{operation_id} equals and filters overlap: {', '.join(sorted(overlap))}"
            )
        if spec.get("row_indices") is not None and (
            spec.get("row_index_range") is not None or spec.get("row_range") is not None
        ):
            raise OperationValidationError(
                f"{operation_id} row_indices and row range are mutually exclusive"
            )
        return
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
    if operation == "dedupe":
        strings(spec.get("columns"), "columns")
        if spec.get("keep") not in {"first", "last"}:
            raise OperationValidationError(f"{operation_id} keep must be first or last")
        return
    if operation == "rename":
        mapping = spec.get("mapping")
        if not isinstance(mapping, Mapping) or not mapping:
            raise OperationValidationError(f"{operation_id} mapping must be a non-empty object")
        old = list(mapping)
        new = list(mapping.values())
        if any(not isinstance(item, str) or not item.strip() for item in old + new):
            raise OperationValidationError(f"{operation_id} mapping names must be non-empty strings")
        if len(set(new)) != len(new):
            raise OperationValidationError(f"{operation_id} mapping values must be distinct")
        return
    if operation == "aggregate":
        group_by = strings(spec.get("group_by"), "group_by")
        aggregations = spec.get("aggregations")
        if not isinstance(aggregations, list) or not aggregations:
            raise OperationValidationError(f"{operation_id} aggregations must be non-empty")
        outputs: set[str] = set()
        for item in aggregations:
            if not isinstance(item, Mapping):
                raise OperationValidationError(f"{operation_id} aggregation must be an object")
            if item.get("func") not in AGGREGATE_FUNCTIONS:
                raise OperationValidationError(f"{operation_id} aggregation function is not registered")
            output = text(item.get("output"), "aggregation.output")
            if output in outputs or output in group_by:
                raise OperationValidationError(f"{operation_id} aggregation output collides: {output}")
            outputs.add(output)
        return
    if operation == "fill_missing":
        strategies = spec.get("strategies")
        if not isinstance(strategies, list) or not strategies:
            raise OperationValidationError(f"{operation_id} strategies must be non-empty")
        seen: set[str] = set()
        for item in strategies:
            if not isinstance(item, Mapping):
                raise OperationValidationError(f"{operation_id} strategy must be an object")
            column = text(item.get("column"), "strategy.column")
            strategy = item.get("strategy")
            if strategy not in FILL_MISSING_STRATEGIES:
                raise OperationValidationError(f"{operation_id} strategy is not registered")
            if column in seen:
                raise OperationValidationError(f"{operation_id} declares duplicate column: {column}")
            seen.add(column)
            if strategy == "constant" and "value" not in item:
                raise OperationValidationError(f"{operation_id} constant requires value")
            if strategy != "constant" and "value" in item:
                raise OperationValidationError(f"{operation_id} value is only valid for constant")
        return
    if operation == "tsset":
        text(spec.get("time_column"), "time_column")
        if spec.get("frequency") not in TSSET_FREQUENCIES:
            raise OperationValidationError(f"{operation_id} frequency is not registered")
        if spec.get("panel_id_column") == spec.get("time_column"):
            raise OperationValidationError(f"{operation_id} panel and time columns must differ")
        return
    if operation == "lag":
        strings(spec.get("columns"), "columns")
        lags = spec.get("lags")
        if not isinstance(lags, list) or not lags or any(
            type(lag) is not int or lag <= 0 for lag in lags
        ) or len(set(lags)) != len(lags):
            raise OperationValidationError(f"{operation_id} lags must be unique positive integers")
        difference = spec.get("difference", 0)
        if type(difference) is not int or difference < 0:
            raise OperationValidationError(f"{operation_id} difference must be non-negative")
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
                f"{operation_id} field {field_name} does not match its closed schema"
            )


def _data_output_columns(
    operation_id: str, spec: Mapping[str, Any], visible: set[str]
) -> set[str]:
    """Project a data-operation output shape for downstream compile checks."""

    operation = operation_id.removeprefix("data.")
    if operation == "subset":
        return {str(column) for column in spec.get("columns", [])}
    if operation == "rename":
        mapping = spec.get("mapping", {})
        return (visible - set(mapping)) | {str(value) for value in mapping.values()}
    if operation == "aggregate":
        return {
            *[str(column) for column in spec.get("group_by", [])],
            *[
                str(item["output"])
                for item in spec.get("aggregations", [])
                if isinstance(item, Mapping) and item.get("output")
            ],
        }
    if operation == "reshape":
        if spec.get("direction") == "wide_to_long":
            return {
                *[str(column) for column in spec.get("id_columns", [])],
                str(spec.get("var_name", "variable")),
                str(spec.get("value_name", "value")),
            }
        # Long-to-wide output labels are data values, not declaration fields;
        # retain only the deterministic index/value columns until runtime sees
        # the actual materialized categories.
        return {
            *[str(column) for column in spec.get("index", [])],
            str(spec.get("values")),
        }
    if operation == "lag":
        return {
            *visible,
            *[
                f"{column}_lag{lag}"
                for column in spec.get("columns", [])
                for lag in spec.get("lags", [])
            ],
        }
    if operation == "feature_recipe":
        return {*visible, str(spec.get("output"))}
    # append/merge may add columns from the secondary dataset, which is a
    # runtime-bound identity. Keep the known primary columns and add the
    # declared merge indicator when it is deterministic.
    if operation == "merge" and spec.get("indicator") is not None:
        indicator = spec["indicator"]
        return {*visible, "_merge" if indicator is True else str(indicator)}
    return set(visible)


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
            # `source` beside depends_on is the mistake the published vocabulary
            # invites: both are composition-level, but only one lives at the top.
            # "unknown field" would read as "this seam does not exist" and send
            # the author away from a plan that is one move from being correct.
            misplaced = " Did you mean to put it inside `spec`?" if "source" in unknown else ""
            raise OperationValidationError(
                "workflow step contains unknown field(s): "
                + ", ".join(sorted(unknown))
                + misplaced
            )
        step_id = entry.get("step_id")
        if not isinstance(step_id, str) or _STEP_ID_PATTERN.fullmatch(step_id) is None:
            raise OperationValidationError(f"invalid workflow step_id: {step_id!r}")
        if step_id in seen_ids:
            raise OperationValidationError(f"duplicate workflow step_id: {step_id}")
        seen_ids.add(step_id)
        operation_id = entry.get("operation_id")
        if operation_id not in workflow_step_operations():
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
            # The commitment is only meaningful if the executor is handed the
            # frame it resolves. On an operation that resolves its own data the
            # reference would validate, resolve, pass every integrity check, and
            # then be discarded -- an accepted declaration with no effect, which
            # is the shape this seam exists to eliminate. Close the contract on
            # the consuming side too.
            if operation_id not in STEP_CONSUMES_INPUT_FRAME:
                raise OperationValidationError(
                    f"workflow step {step_id} operation {operation_id} does not read "
                    "a workflow input frame, so it cannot declare a source. Operations "
                    "that can: " + ", ".join(sorted(STEP_CONSUMES_INPUT_FRAME))
                )
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

    # Resolve source commitments before `_topological_order` runs: until the
    # reference is folded into depends_on, neither the ordering nor the cycle
    # refusal can see that edge at all.
    by_id = {step["step_id"]: step for step in normalized}
    for step in normalized:
        # Keyed on presence for the same reason the spec check above is: an
        # explicit `source: null` was already refused, so a missing key here
        # means the step declared no source rather than a malformed one.
        if "source" not in step["spec"]:
            continue
        source = step["spec"]["source"]
        from_step = source["from_step"]
        if from_step == step["step_id"]:
            raise OperationValidationError(
                f"workflow step {step['step_id']} source refers to itself"
            )
        producer = by_id.get(from_step)
        if producer is None:
            raise OperationValidationError(
                f"workflow step {step['step_id']} source refers to unknown step: {from_step}"
            )
        if producer["operation_id"] not in STEP_PRODUCES_DATASET:
            raise OperationValidationError(
                f"workflow step {step['step_id']} source refers to {from_step}, which "
                f"does not produce a dataset: {producer['operation_id']}. Steps that "
                "produce a dataset: " + ", ".join(sorted(STEP_PRODUCES_DATASET))
            )
        producer_contract = WORKFLOW_STEP_SPEC_CONTRACTS[producer["operation_id"]]
        consumer_contract = WORKFLOW_STEP_SPEC_CONTRACTS[step["operation_id"]]
        accepted_roles = consumer_contract.accepted_dataset_kinds
        produced_role = producer_contract.produced_dataset_kind
        if accepted_roles and produced_role not in accepted_roles:
            raise OperationValidationError(
                f"workflow step {step['step_id']} cannot consume dataset role "
                f"{produced_role!r} from {from_step}; accepted roles: "
                + ", ".join(accepted_roles)
            )
        # Consuming a step's output is an ordering constraint, so the reference
        # becomes a real dependency. Reusing depends_on means the existing
        # topological sort, cycle refusal, fail-closed gating and
        # dependency_fingerprints all cover chained steps with no new machinery.
        if from_step not in step["depends_on"]:
            step["depends_on"] = [*step["depends_on"], from_step]

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
    # Takes the ordered plan, not the raw one: ancestor resolution depends on it.
    _reject_unreadable_data_sources(ordered)

    if available_columns is not None:
        available = {str(column) for column in available_columns}
        # Each source commitment names a dataset branch, so column visibility
        # is branch-local rather than a mutable global set.  Sibling steps that
        # all consume `first` must see the columns published by `first`, not
        # whichever sibling happened to be validated immediately before them.
        output_columns: dict[str, set[str]] = {}
        ancestors = _step_ancestors(ordered)
        for step in ordered:
            source = step["spec"].get("source")
            if isinstance(source, Mapping):
                input_visible = set(output_columns[source["from_step"]])
            else:
                input_visible = set(available)
                # Preserve the established sourceless replay contract for the
                # two declaration-defined column derivations.  They are not
                # persisted source branches, so their declared output columns
                # are the only ancestor state a sourceless consumer can see.
                for ancestor_id in ancestors[step["step_id"]]:
                    ancestor = next(
                        candidate
                        for candidate in ordered
                        if candidate["step_id"] == ancestor_id
                    )
                    if ancestor["operation_id"] in {
                        "statistical.derive_numeric",
                        "statistical.derive_boolean",
                    }:
                        input_visible.update(output_columns[ancestor_id])
            referenced = _spec_columns(step["operation_id"], step["spec"])
            missing = sorted(referenced - input_visible)
            if missing:
                raise OperationValidationError(
                    f"workflow step {step['step_id']} references missing column(s): "
                    + ", ".join(missing)
                )
            result_visible = set(input_visible)
            if step["operation_id"] == "statistical.derive_boolean":
                result_visible.update(
                    str(recipe["output_name"]) for recipe in step["spec"]["recipes"]
                )
            if step["operation_id"] == "statistical.derive_numeric":
                outputs = {
                    str(recipe["output_name"]) for recipe in step["spec"]["recipes"]
                }
                collisions = sorted(outputs & input_visible)
                if collisions:
                    raise OperationValidationError(
                        "derive_numeric output column already exists: " + ", ".join(collisions)
                    )
                result_visible.update(outputs)
            if step["operation_id"].startswith("data."):
                result_visible = _data_output_columns(
                    step["operation_id"], step["spec"], input_visible
                )
            output_columns[step["step_id"]] = result_visible
    return ordered


def _step_ancestors(steps: list[dict[str, Any]]) -> dict[str, frozenset[str]]:
    """Transitive dependencies per step, from an already topologically ordered plan.

    The ordering is a real precondition, so it is enforced structurally rather
    than by a comment: every dependency is resolved before the step that names
    it, and an unordered input raises KeyError on the spot instead of recursing.
    """

    ancestors: dict[str, frozenset[str]] = {}
    for step in steps:
        collected: set[str] = set()
        for dependency in step["depends_on"]:
            collected.add(dependency)
            collected |= ancestors[dependency]
        ancestors[step["step_id"]] = frozenset(collected)
    return ancestors


def _reject_unreadable_data_sources(steps: list[dict[str, Any]]) -> None:
    """Refuse plans whose declared transforms could not all reach the step reading them.

    Two shapes, one failure: a step estimating on data that is not what the plan
    reads as its input, with nothing going red.

    First, a step that commits to `source` reads exactly that dataset at
    execution time, so any *other* dataset-producing ancestor it declares is
    computed and then dropped without a word -- the author reads the plan as
    "both transforms applied" and gets one of them. Ancestors of the declared
    source are exempt: they are how that dataset was built, so they are already
    inside the frame the step reads.

    Second, a step that declares *no* source is served by the runtime's replay
    path, which reconstructs its ancestors by re-applying their specs to the
    workflow target. That path only knows how to replay
    STEP_REPLAYABLE_BY_RECIPE. Any other dataset producer upstream of it would
    simply be skipped, and the step would run against the original table while
    the plan says otherwise. Today the two sets are equal so this cannot happen;
    the rule exists so that the day P3 adds a transform without wiring it up,
    the plan fails to compile rather than quietly reporting the wrong number.
    """

    by_id = {step["step_id"]: step for step in steps}
    ancestors = _step_ancestors(steps)

    for step in steps:
        step_id = step["step_id"]
        if "source" not in step["spec"]:
            unreplayable = sorted(
                candidate
                for candidate in ancestors[step_id]
                if by_id[candidate]["operation_id"] in STEP_PRODUCES_DATASET
                and by_id[candidate]["operation_id"] not in STEP_REPLAYABLE_BY_RECIPE
            )
            if unreplayable:
                raise OperationValidationError(
                    f"workflow step {step_id} does not declare a source, so it reads "
                    "the original table; the dataset(s) produced by "
                    + ", ".join(unreplayable)
                    + " would be ignored. Declare source.from_step to read them."
                )
            continue
        from_step = str(step["spec"]["source"]["from_step"])
        declared_lineage = {from_step} | ancestors[from_step]
        discarded = sorted(
            candidate
            for candidate in ancestors[step_id] - declared_lineage
            if by_id[candidate]["operation_id"] in STEP_PRODUCES_DATASET
        )
        if discarded:
            raise OperationValidationError(
                f"workflow step {step_id} declares more than one data source: "
                f"it reads {from_step}, so the dataset(s) produced by "
                + ", ".join(discarded)
                + " would be silently discarded. A step can only have one data "
                "source; route the other transform through it."
            )


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
    # Held to the same pattern as step_id itself: an id that could never name a
    # step is a format error, and reporting it later as an unresolvable
    # reference would point the author at a missing step rather than the typo.
    from_step = source.get("from_step")
    if not isinstance(from_step, str) or _STEP_ID_PATTERN.fullmatch(from_step) is None:
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
    "STEP_CONSUMES_INPUT_FRAME",
    "STEP_PRODUCES_DATASET",
    "STEP_REPLAYABLE_BY_RECIPE",
    "SUPPORTED_STEP_OUTPUTS",
    "WORKFLOW_OPERATION_ID",
    "WORKFLOW_OPERATION_VERSION",
    "WORKFLOW_STEP_OPERATIONS",
    "WORKFLOW_STEP_SPEC_CONTRACTS",
    "WORKFLOW_TEMPLATE",
    "StepSpecContract",
    "WorkflowStepContractRegistry",
    "data_preparation_workflow_step_contracts",
    "pack_step_contract",
    "prediction_workflow_step_contracts",
    "recipe_workflow_step_contracts",
    "register_workflow_step",
    "selector_workflow_step_contracts",
    "statistical_workflow_step_contracts",
    "validate_workflow_operation",
    "validate_workflow_steps",
    "workflow_authorization",
    "workflow_proposal_schema",
    "workflow_step_operations",
    "workflow_step_vocabulary",
    "workflow_dispatcher_key",
]
