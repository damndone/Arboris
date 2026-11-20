"""Operation proposal schemas and validators: workflow steps, model rerun/genesis/custom, metadata edit, graph fork, casts and code execution."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..contracts.common.errors import OperationValidationError
from .operation_definitions import OperationDefinition


def _workflow_step_operation_definitions() -> tuple[OperationDefinition, ...]:
    """Project the single workflow-step contract table into the registry."""

    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

    definitions: list[OperationDefinition] = []
    for operation_id, contract in WORKFLOW_STEP_SPEC_CONTRACTS.items():
        # These two identities also have top-level operation definitions with
        # the same operation/version. Their shared editable fields and runtime
        # metadata are projected into those definitions during registry setup.
        if operation_id in {"model.genesis", "model.custom"}:
            continue
        if not contract.dispatcher_key:
            raise ValueError(f"workflow step {operation_id} has no dispatcher key")
        spec_schema = contract.to_schema()
        definitions.append(
            OperationDefinition(
                operation_id=operation_id,
                operation_version="v1",
                effect_level=contract.effect_level,
                scope_requirements=contract.scope_requirements,
                scope=contract.scope,
                risk_level=contract.risk_level,
                confirmation_policy=contract.confirmation_policy,
                proposal_schema=_workflow_step_schema(
                    operation_id,
                    changes=spec_schema["properties"],
                    required_changes=list(contract.required),
                ),
                editable_schema=spec_schema,
                contract_owner="operation_registry",
                executor_key=contract.dispatcher_key,
                reconciler_key=contract.reconciler_key or contract.dispatcher_key,
                diff_builder_key=contract.diff_builder_key or "",
                verification_builder_key=contract.verification_builder_key or "",
                ui_description=contract.ui_description,
                example_prompts=contract.example_prompts,
                natural_language_enabled=contract.natural_language_enabled,
                validator=_validate_workflow_step,
            )
        )
    return tuple(definitions)


def _workflow_step_schema(
    operation_id: str,
    *,
    changes: dict[str, Any],
    required_changes: list[str],
) -> dict[str, Any]:
    return {
        "type": "object",
        "required": [
            "operation_id",
            "operation_version",
            "target",
            "preconditions",
            "changes",
            "evidence_refs",
            "expected_effect",
            "risks",
        ],
        "properties": {
            "operation_id": {"const": operation_id},
            "operation_version": {"const": "v1"},
            "target": {
                "type": "object",
                "required": ["run_id", "node_ref", "artifact_id", "workflow_id", "step_id"],
                "properties": {
                    key: {"type": "string", "minLength": 1}
                    for key in ("run_id", "node_ref", "artifact_id", "workflow_id", "step_id")
                },
                "additionalProperties": False,
            },
            "preconditions": {
                "type": "object",
                "required": ["source_fingerprint", "dependency_fingerprints"],
                "properties": {
                    "source_fingerprint": {"type": "string", "minLength": 1},
                    "dependency_fingerprints": {"type": "array", "items": {"type": "string"}},
                },
                "additionalProperties": False,
            },
            "changes": {
                "type": "object",
                "required": required_changes,
                "properties": changes,
                "additionalProperties": False,
            },
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "expected_effect": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }


def _validate_workflow_step(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    required_target = {"run_id", "node_ref", "artifact_id", "workflow_id", "step_id"}
    missing_target = {key for key in required_target if not target.get(key)}
    if missing_target:
        raise OperationValidationError(
            "workflow step target missing: " + ", ".join(sorted(missing_target))
        )
    if not preconditions.get("source_fingerprint"):
        raise OperationValidationError("workflow step source_fingerprint is required")
    if not isinstance(preconditions.get("dependency_fingerprints"), list):
        raise OperationValidationError(
            "workflow step dependency_fingerprints must be a list"
        )
    if not isinstance(changes, dict) or not changes:
        raise OperationValidationError("workflow step changes must not be empty")


def _proposal_schema(
    *,
    target_required: list[str],
    changes: dict[str, Any],
    target_properties: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Build one operation's proposal schema.

    Target fields default to strings because most references are ids, but any
    field whose shape is richer (an array of casts, an enum) must declare it via
    ``target_properties`` — a mistyped field here is unsatisfiable, and the
    model has no way to tell that from its own mistake.
    """

    properties = {key: {"type": "string"} for key in target_required}
    properties.update(target_properties or {})
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
            "operation_id": {"type": "string"},
            "operation_version": {"type": "string"},
            "target": {
                "type": "object",
                "required": target_required,
                "properties": properties,
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
                    key: {"type": "string"}
                    for key in (
                        "context_version",
                        "context_fingerprint",
                        "active_head_run_id",
                        "owner_resolution",
                    )
                },
                "additionalProperties": True,
            },
            "changes": changes,
            "evidence_refs": {"type": "array", "items": {"type": "string"}},
            "expected_effect": {"type": "array", "items": {"type": "string"}},
            "risks": {"type": "array", "items": {"type": "string"}},
        },
        "additionalProperties": False,
    }


def _model_rerun_change_branch() -> dict[str, Any]:
    """The normal rerun patch, as the *model* is shown it.

    Built from the same declaration as the validator. These are two different
    schemas -- `editable_schema` describes the operation, `proposal_schema` is
    what reaches the language model -- and aligning only one of them yields a
    tool contract that forbids a field the validator would have accepted, so the
    model cannot emit it at all.
    """
    from ..survey.fields import DESIGN_FIELD_SPECS

    properties: dict[str, Any] = {
        "model_options": {"type": "object"},
        "labels": {
            "type": "object",
            "description": (
                "Column metadata. `measurement_level` maps column names to one of "
                "nominal / ordinal / scale / count and changes how a column that is "
                "already in the model is treated (for example an ordinal outcome "
                "routes to ordinal logit). It never adds a column to the model: to "
                "add a regressor, propose model.genesis with it in predictors or "
                "categorical. `variable_labels` and `value_labels` change how "
                "columns and their values are displayed in tables and answers. "
                "`user_missing_values` declares codes (e.g. -99, or a {low, high} "
                "range) that mean no valid answer; they become missing before any "
                "model runs, which changes the estimation sample. Declare every "
                "column in one proposal rather than one at a time. Only columns "
                "present in the data may be named."
            ),
            "properties": {
                "measurement_level": {
                    "type": "object",
                    "additionalProperties": {
                        "type": "string",
                        "enum": ["nominal", "ordinal", "scale", "count", "unspecified"],
                    },
                },
                "variable_labels": {
                    "type": "object",
                    "additionalProperties": {"type": "string", "minLength": 1},
                },
                "value_labels": {
                    "type": "object",
                    "description": "Column -> {stored value as string -> label}.",
                    "additionalProperties": {
                        "type": "object",
                        "additionalProperties": {"type": "string", "minLength": 1},
                    },
                },
                "user_missing_values": {
                    "type": "object",
                    "description": "Column -> list of codes; a code is a number, a string, or {low, high}.",
                    "additionalProperties": {
                        "type": "array",
                        "minItems": 1,
                        "items": {
                            "anyOf": [
                                {"type": "number"},
                                {"type": "string", "minLength": 1},
                                {
                                    "type": "object",
                                    "required": ["low", "high"],
                                    "properties": {"low": {"type": "number"}, "high": {"type": "number"}},
                                    "additionalProperties": False,
                                },
                            ]
                        },
                    },
                },
            },
        },
        # No enum here on purpose: the legal families are a runtime registry, and
        # a list frozen into this schema would drift the moment a pack is added.
        # `inspect_operation_contract` returns the live set together with the
        # target family's required fields, which is what a switch actually needs.
        "model_type": {
            "type": "string",
            "description": (
                "Switch the model family. This changes what the analysis means, "
                "not just how it is estimated. Read the legal values and "
                "family_switch_requirements from inspect_operation_contract first. "
                "Required fields may be retained from the source; to set bindings "
                "outside this patch use model.genesis inside operation.multi_step."
            ),
        },
    }
    for field_name in model_rerun_change_fields():
        if field_name.endswith("_weight"):
            properties[field_name] = {
                "type": "string",
                "description": f"Column holding the {field_name.removesuffix('_weight')} weight.",
            }
    for spec in DESIGN_FIELD_SPECS:
        entry: dict[str, Any] = {
            "type": "array" if spec["kind"] == "columns" else "string",
            "description": spec["label"],
        }
        if spec["kind"] == "columns":
            entry["items"] = {"type": "string"}
        if spec.get("options"):
            entry["enum"] = list(spec["options"])
        properties[spec["key"]] = entry
    return {
        "type": "object",
        "description": (
            "The normal v1 rerun patch. Use one-level model_options only; do not "
            "use an old/new field-diff wrapper. The survey_* fields declare a "
            "complex sampling design: setting them re-runs the model with "
            "design-based standard errors, and they require a sampling weight."
        ),
        "properties": properties,
        "additionalProperties": False,
    }


def _model_rerun_proposal_schema() -> dict[str, Any]:
    return _proposal_schema(
        target_required=["run_id", "node_ref", "node_hash", "forest_node_key"],
        changes={
            "oneOf": [
                _model_rerun_change_branch(),
                {
                    "type": "object",
                    "description": (
                        "Legacy Analysis Loop compatibility patch. This is valid only "
                        "when preconditions.analysis_loop is present."
                    ),
                    "properties": {
                        "covariance": {"type": ["string", "object"]},
                        "entity_col": {"type": ["string", "object"]},
                    },
                    "additionalProperties": False,
                    "minProperties": 1,
                },
            ],
        },
    )


def _metadata_edit_proposal_schema() -> dict[str, Any]:
    labels = deepcopy(_model_rerun_change_branch()["properties"]["labels"])
    labels["minProperties"] = 1
    return _proposal_schema(
        target_required=["run_id", "node_ref", "node_hash", "forest_node_key"],
        changes={
            "type": "object",
            "description": (
                "Only `labels`: declare metadata for any column (inside or outside "
                "the model). To add or remove model variables use model.genesis."
            ),
            "required": ["labels"],
            "properties": {"labels": labels},
            "additionalProperties": False,
        },
    )


def _validate_metadata_edit(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    if set(changes) != {"labels"} or not isinstance(changes.get("labels"), dict) or not changes["labels"]:
        raise OperationValidationError("metadata.edit changes must be exactly a non-empty labels object")
    _validate_model_rerun(target, preconditions, changes)


def _model_genesis_proposal_schema() -> dict[str, Any]:
    schema = _proposal_schema(
        target_required=["dataset_source_id"],
        changes={
            "type": "object",
            "properties": {
                "table_params": {"type": "object"},
                "model_params": {"type": "object"},
                "model_options": {"type": "object"},
            },
            "additionalProperties": False,
        },
    )
    preconditions = schema["properties"]["preconditions"]
    preconditions["required"] = ["context_version", "context_fingerprint", "owner_resolution"]
    return schema


def _graph_fork_proposal_schema() -> dict[str, Any]:
    return _proposal_schema(
        target_required=[
            "run_id",
            "node_ref",
            "node_hash",
            "forest_node_key",
            "source_session_entry_id",
        ],
        changes={
            "type": "object",
            "properties": {
                "reason": {"type": "string", "maxLength": 1000},
            },
            "additionalProperties": False,
        },
    )


def _data_column_cast_proposal_schema() -> dict[str, Any]:
    return _proposal_schema(
        target_required=["run_id", "node_ref", "artifact_id", "column", "target_dtype"],
        changes={
            "type": "object",
            "required": ["column", "target_dtype"],
            "properties": {
                "column": {"type": "string"},
                "target_dtype": {
                    "type": "string",
                    "enum": ["numeric", "string", "datetime"],
                },
            },
            "additionalProperties": False,
        },
    )


def _code_execute_proposal_schema() -> dict[str, Any]:
    return _proposal_schema(
        target_required=["run_id", "node_ref", "artifact_id", "code"],
        changes={
            "type": "object",
            "required": ["code"],
            "properties": {
                "code": {"type": "string", "minLength": 1, "maxLength": 20000},
                "language": {"type": "string", "enum": ["python"]},
                "output_format": {"type": "string", "enum": ["csv", "xlsx"]},
            },
            "additionalProperties": False,
        },
    )


def _validate_code_execute(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    missing_target = {
        key for key in ("run_id", "node_ref", "artifact_id", "code") if not target.get(key)
    }
    if missing_target:
        raise OperationValidationError(
            "code.execute target missing: " + ", ".join(sorted(missing_target))
        )
    code = target.get("code")
    if not isinstance(code, str) or not code.strip():
        raise OperationValidationError("code.execute code must be a non-empty string")
    if len(code) > 20000:
        raise OperationValidationError("code.execute code is too long")
    language = target.get("language", "python")
    if language != "python":
        raise OperationValidationError("code.execute language is unsupported")
    output_format = target.get("output_format", "csv")
    if output_format not in {"csv", "xlsx"}:
        raise OperationValidationError("code.execute output_format is unsupported")
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
            "code.execute preconditions missing: " + ", ".join(sorted(missing_preconditions))
        )
    if changes.get("code") != code:
        raise OperationValidationError("code.execute changes must match target code")
    if changes.get("language", "python") != language:
        raise OperationValidationError("code.execute changes language must match target")
    if changes.get("output_format", "csv") != output_format:
        raise OperationValidationError("code.execute changes output_format must match target")


def _data_columns_cast_proposal_schema() -> dict[str, Any]:
    cast_item = {
        "type": "object",
        "required": ["column", "target_dtype"],
        "properties": {
            "column": {"type": "string"},
            "target_dtype": {
                "type": "string",
                "enum": ["numeric", "string", "datetime"],
            },
        },
        "additionalProperties": False,
    }
    return _proposal_schema(
        target_required=["run_id", "node_ref", "artifact_id", "casts"],
        # `casts` is an array; the string default would make this operation
        # literally unproposable (the live DeepSeek smoke hit exactly that and
        # correctly guessed the schema — not itself — was wrong).
        target_properties={
            "casts": {"type": "array", "minItems": 1, "items": cast_item},
            "output_format": {"type": "string", "enum": ["csv", "xlsx"]},
        },
        changes={
            "type": "object",
            "required": ["casts"],
            "properties": {
                "casts": {"type": "array", "minItems": 1, "items": cast_item},
                "output_format": {"type": "string", "enum": ["csv", "xlsx"]},
            },
            "additionalProperties": False,
        },
    )


def _validate_data_columns_cast(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    missing_target = {
        key for key in ("run_id", "node_ref", "artifact_id", "casts") if not target.get(key)
    }
    if missing_target:
        raise OperationValidationError(
            "data.columns.cast target missing: " + ", ".join(sorted(missing_target))
        )
    casts = target.get("casts")
    if not isinstance(casts, list) or not casts:
        raise OperationValidationError("data.columns.cast casts must be a non-empty list")
    seen: set[str] = set()
    for item in casts:
        if not isinstance(item, dict):
            raise OperationValidationError("data.columns.cast cast items must be objects")
        column = item.get("column")
        dtype = item.get("target_dtype")
        if not isinstance(column, str) or not column:
            raise OperationValidationError("data.columns.cast cast column missing")
        if dtype not in {"numeric", "string", "datetime"}:
            raise OperationValidationError("data.columns.cast target_dtype is unsupported")
        if column in seen:
            raise OperationValidationError("data.columns.cast has a duplicate column")
        seen.add(column)
    output_format = target.get("output_format", "csv")
    if output_format not in {"csv", "xlsx"}:
        raise OperationValidationError("data.columns.cast output_format is unsupported")
    missing_preconditions = {
        key
        for key in ("context_version", "context_fingerprint", "active_head_run_id", "owner_resolution")
        if not preconditions.get(key)
    }
    if missing_preconditions:
        raise OperationValidationError(
            "data.columns.cast preconditions missing: "
            + ", ".join(sorted(missing_preconditions))
        )
    if changes.get("casts") != casts:
        raise OperationValidationError("data.columns.cast changes must match target casts")
    if changes.get("output_format", "csv") != output_format:
        raise OperationValidationError("data.columns.cast changes output_format must match target")


def model_rerun_change_fields() -> tuple[str, ...]:
    """Top-level fields a `model.rerun` proposal may carry.

    Declared in one place because the operation's `editable_schema` and its
    validator both consume it: a schema that advertises a field the validator
    rejects teaches an Agent to emit proposals that always fail, and reads as
    authoritative while doing so.

    The survey design fields are flat rather than nested under one object
    because `op_overrides` merges straight into the run form, where they are
    flat -- a nested shape would need a translation step whose only job would be
    to undo the nesting.
    """
    from ..survey.fields import DESIGN_FIELDS
    from ..contracts.model.family import MODEL_FAMILY_CONTRACTS

    # The weight columns travel with the design, not separately: a design
    # without a sampling weight is refused by the engine, so an Agent able to
    # propose one but not the other could only ever produce a rejected run.
    # Which weights a given family accepts is still enforced downstream against
    # that family's published params -- this is the union of what may be asked.
    weights = {
        f"{kind}_weight"
        for contract in MODEL_FAMILY_CONTRACTS.values()
        for kind in contract.allows_weights
    }
    # `model_type` switches the family. The executor has re-resolved the
    # contract against the new family since v1.6.0 (`resolve_overrides_target`),
    # and validates the rest of the patch against *that* family's params, so an
    # under-specified switch is refused there rather than silently running a
    # model configured by omission. Only the Agent whitelist stood in the way.
    # `labels` carries the measurement-level declarations (v1.8.7 A2). A
    # questionnaire has fifty columns; declared one at a time nobody declares
    # any, so the batch has to be one proposal. It rides a rerun rather than a
    # bespoke data operation because a measurement level is run metadata, not a
    # transformation, and a rerun already gives the child node, the lineage and
    # the confirmation gate.
    return ("model_type", "model_options", "labels", *sorted(weights), *DESIGN_FIELDS)


def _model_rerun_editable_schema() -> dict[str, Any]:
    properties: dict[str, Any] = {
        "model_options": {
            "type": "object",
            "description": (
                "A one-level model-options patch, not an old/new field-diff wrapper."
            ),
        },
    }
    for field_name in model_rerun_change_fields():
        properties.setdefault(
            field_name,
            {
                "description": (
                    "Complex survey design declaration; changing it re-runs the model "
                    "with design-based variance."
                ),
            },
        )
    return {
        "type": "object",
        "description": "Field-level model rerun changes.",
        "properties": properties,
        "additionalProperties": True,
    }


def _validate_model_rerun(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    missing_target = {
        key
        for key in ("run_id", "node_ref", "node_hash", "forest_node_key")
        if not target.get(key)
    }
    if missing_target:
        raise OperationValidationError(
            f"model.rerun target missing: {', '.join(sorted(missing_target))}"
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
            "model.rerun preconditions missing: "
            + ", ".join(sorted(missing_preconditions))
        )
    if not changes:
        raise OperationValidationError("model.rerun changes must not be empty")
    unknown = set(changes) - set(model_rerun_change_fields())
    # The pre-existing Analysis Loop has its own canonical PlanDiff binding and
    # stores a legacy wire patch (covariance/entity_col) alongside the binding.
    # Keep that adapter interoperable while making every ordinary Notebook or
    # generic model.rerun proposal use the closed model_options envelope.
    analysis_loop_compat = (
        isinstance(preconditions.get("analysis_loop"), dict)
        or preconditions.get("owner_resolution") == "active_head_contains_node"
    )
    if unknown and not analysis_loop_compat:
        raise OperationValidationError(
            "model.rerun changes contain unknown field(s): "
            + ", ".join(sorted(unknown))
        )
    if "model_options" in changes:
        model_options = changes["model_options"]
        # Unlike legacy scalar changes, model_options is itself a generic
        # object-valued patch. Treating an ``old``/``new`` pair as a diff wrapper
        # would silently corrupt a future handler whose legitimate option keys
        # happen to use those names.
        if not isinstance(model_options, dict):
            raise OperationValidationError("model.rerun model_options must be an object")


def _validate_model_genesis(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    if not target.get("dataset_source_id"):
        raise OperationValidationError("model.genesis target requires dataset_source_id")
    missing = {
        key
        for key in ("context_version", "context_fingerprint", "owner_resolution")
        if not preconditions.get(key)
    }
    if missing:
        raise OperationValidationError(
            "model.genesis preconditions missing: " + ", ".join(sorted(missing))
        )
    if not isinstance(changes, dict) or not changes:
        raise OperationValidationError("model.genesis changes must not be empty")
    allowed = {"table_params", "model_params", "model_options"}
    unknown = set(changes) - allowed
    if unknown:
        raise OperationValidationError(
            "model.genesis changes contain unknown field(s): " + ", ".join(sorted(unknown))
        )
    for key, value in changes.items():
        if not isinstance(value, dict):
            raise OperationValidationError(f"model.genesis {key} must be an object")


def _model_custom_proposal_schema(contract: Any | None = None) -> dict[str, Any]:
    if contract is None:
        from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

        contract = WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"]
    if not hasattr(contract, "to_schema"):
        raise TypeError("model.custom contract must expose to_schema")
    contract_schema = contract.to_schema()
    changes = dict(contract_schema)
    properties: dict[str, Any] = {}
    for name, schema in contract_schema["properties"].items():
        normalized = dict(schema)
        if normalized.get("type") == "string":
            normalized["minLength"] = 1
        elif normalized.get("type") == "array":
            normalized["items"] = {"type": "string", "minLength": 1}
        properties[name] = normalized
    changes["properties"] = properties
    return _proposal_schema(
        target_required=[],
        changes=changes,
        target_properties={
            "dataset_source_id": {"type": "string", "minLength": 1},
            "run_id": {"type": "string", "minLength": 1},
            "node_ref": {"type": "string", "minLength": 1},
            "node_hash": {"type": "string", "minLength": 1},
            "forest_node_key": {"type": "string", "minLength": 1},
        },
    )


def _validate_model_custom(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    dataset_target = bool(target.get("dataset_source_id"))
    run_target = all(target.get(key) for key in ("run_id", "node_ref", "node_hash", "forest_node_key"))
    if dataset_target == run_target:
        raise OperationValidationError(
            "model.custom target must identify exactly one dataset source or run model node"
        )
    missing_preconditions = {
        key
        for key in ("context_version", "context_fingerprint", "owner_resolution")
        if not preconditions.get(key)
    }
    if missing_preconditions:
        raise OperationValidationError(
            "model.custom preconditions missing: " + ", ".join(sorted(missing_preconditions))
        )
    if not isinstance(changes, dict) or not changes:
        raise OperationValidationError("model.custom changes must not be empty")
    required = {"capability_ref", "binding_ref", "operation"}
    missing = sorted(field for field in required if not changes.get(field))
    if missing:
        raise OperationValidationError(
            "model.custom changes missing: " + ", ".join(missing)
        )
    allowed = required | {"input_handle", "parameters", "consumer_slots", "expected_artifacts"}
    unknown = set(changes) - allowed
    if unknown:
        raise OperationValidationError(
            "model.custom changes contain unknown field(s): " + ", ".join(sorted(unknown))
        )
    for key in required | {"input_handle"}:
        if key in changes and (not isinstance(changes[key], str) or not changes[key]):
            raise OperationValidationError(f"model.custom {key} must be a non-empty string")
    if "parameters" in changes and not isinstance(changes["parameters"], dict):
        raise OperationValidationError("model.custom parameters must be an object")
    if "consumer_slots" in changes:
        slots = changes["consumer_slots"]
        if (
            not isinstance(slots, list)
            or not slots
            or any(not isinstance(item, str) or not item for item in slots)
            or len(set(slots)) != len(slots)
        ):
            raise OperationValidationError("model.custom consumer_slots must be unique non-empty strings")
    if "expected_artifacts" in changes:
        artifacts = changes["expected_artifacts"]
        if not isinstance(artifacts, list) or any(
            not isinstance(item, str) or not item for item in artifacts
        ):
            raise OperationValidationError("model.custom expected_artifacts must be strings")


def _validate_graph_fork(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    missing_target = {
        key
        for key in (
            "run_id",
            "node_ref",
            "node_hash",
            "forest_node_key",
            "source_session_entry_id",
        )
        if not target.get(key)
    }
    if missing_target:
        raise OperationValidationError(
            "graph.fork target missing: " + ", ".join(sorted(missing_target))
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
            "graph.fork preconditions missing: "
            + ", ".join(sorted(missing_preconditions))
        )
    if set(changes) - {"reason"}:
        raise OperationValidationError("graph.fork changes only allow reason")
    reason = changes.get("reason")
    if reason is not None and (not isinstance(reason, str) or len(reason) > 1_000):
        raise OperationValidationError("graph.fork reason must be a bounded string")


def _validate_data_column_cast(
    target: dict[str, Any],
    preconditions: dict[str, Any],
    changes: dict[str, Any],
) -> None:
    required_target = {"run_id", "node_ref", "artifact_id", "column", "target_dtype"}
    missing_target = {key for key in required_target if not target.get(key)}
    if missing_target:
        raise OperationValidationError(
            "data.column.cast target missing: " + ", ".join(sorted(missing_target))
        )
    if target.get("target_dtype") not in {"numeric", "string", "datetime"}:
        raise OperationValidationError("data.column.cast target_dtype is unsupported")
    missing_preconditions = {
        key
        for key in ("context_version", "context_fingerprint", "active_head_run_id", "owner_resolution")
        if not preconditions.get(key)
    }
    if missing_preconditions:
        raise OperationValidationError(
            "data.column.cast preconditions missing: "
            + ", ".join(sorted(missing_preconditions))
        )
    if changes.get("column") != target.get("column"):
        raise OperationValidationError("data.column.cast column change does not match target")
    if changes.get("target_dtype") != target.get("target_dtype"):
        raise OperationValidationError("data.column.cast dtype change does not match target")
