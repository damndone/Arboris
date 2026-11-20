"""Workflow declaration types and closed composition constants."""
from __future__ import annotations

import re
from copy import deepcopy
from collections.abc import Mapping
from dataclasses import dataclass, field
from typing import Any

WORKFLOW_OPERATION_ID = "operation.multi_step"
WORKFLOW_OPERATION_VERSION = "v1"
WORKFLOW_TEMPLATE = "agent-composed-v1"
_REPORTED_PERCENTILES = (1, 5, 10, 25, 50, 75, 90, 95, 99)
_STEP_ID_PATTERN = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.-]{0,63}$")
SUPPORTED_STEP_OUTPUTS = frozenset({"produced_dataset"})
GENESIS_RUN_LEVEL_FIELDS = ("multiple_imputations", "by_group", "estimation_engine")
NOTEBOOK_GENESIS_MODEL_PARAMS = frozenset({
    "model_type", "y", "x", "focal_x", "covariance", "model_options",
    "entity_col", "time_col", "cohort_col", "treatment_path_col", *GENESIS_RUN_LEVEL_FIELDS,
})

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
    #: Persisted, named model branches available to subsequent inference steps.
    produces_model_branches: bool = False
    #: Fields whose model references may bind to a producer in this same plan.
    model_reference_fields: tuple[str, ...] = ()
    #: Method requirements and alternatives retained in server-written replies.
    proposal_notes: Mapping[str, str] = field(default_factory=dict)
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
    #: Root spec variants bind a discriminator to its nested parameter schema.
    #: Published by to_schema and read by the corresponding semantic validator.
    spec_branches: tuple[Mapping[str, Any], ...] = ()
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
        from ..capability_contract import CAPABILITY_KINDS

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
            **({"spec_branches": deepcopy(list(self.spec_branches))} if self.spec_branches else {}),
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
        schema = {
            "type": "object",
            "required": list(self.required),
            "properties": properties,
            "additionalProperties": False,
        }
        if self.spec_branches:
            schema["oneOf"] = deepcopy(list(self.spec_branches))
        return schema


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
