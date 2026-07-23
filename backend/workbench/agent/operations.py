"""Append-only typed operation records for confirmed proposals."""

from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from threading import RLock
from typing import Any, Callable

from .proposals import ProposalConfirmation
from .storage import append_jsonl_atomic, read_jsonl


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class OperationRecordTransitionError(RuntimeError):
    """Raised when an operation record attempts an invalid state transition."""


class UnknownOperationError(RuntimeError):
    """Raised when an agent proposes an operation that is not registered."""


class OperationValidationError(RuntimeError):
    """Raised when a registered operation proposal is structurally invalid."""


OperationValidator = Callable[[dict[str, Any], dict[str, Any], dict[str, Any]], None]


@dataclass(frozen=True)
class OperationDefinition:
    operation_id: str
    operation_version: str = "v1"
    effect_level: str = "mutation"
    scope_requirements: tuple[str, ...] = ()
    scope: str = ""
    risk_level: str = "mutating"
    confirmation_policy: str = "required"
    proposal_schema: dict[str, Any] = field(default_factory=dict)
    editable_schema: dict[str, Any] = field(default_factory=dict)
    executor_key: str = ""
    reconciler_key: str = ""
    diff_builder_key: str = ""
    verification_builder_key: str = ""
    ui_description: str = ""
    example_prompts: tuple[str, ...] = ()
    natural_language_enabled: bool = False
    validator: OperationValidator | None = None

    @property
    def risk_authorization_policy(self) -> str:
        """Return the backend policy implied by the registry risk level."""

        return "explicit_single_use" if self.risk_level == "high" else "none"

    @property
    def requires_risk_authorization(self) -> bool:
        return self.risk_level == "high"

    def validate(
        self,
        *,
        target: dict[str, Any],
        preconditions: dict[str, Any],
        changes: dict[str, Any],
    ) -> None:
        if self.validator is not None:
            self.validator(target, preconditions, changes)


class OperationRegistry:
    """Explicit registry for agent-facing operation identities."""

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], OperationDefinition] = {}
        self.register(
            OperationDefinition(
                operation_id="model.rerun",
                operation_version="v1",
                effect_level="mutation",
                scope_requirements=("chain", "active_head"),
                scope="model node",
                risk_level="mutating",
                confirmation_policy="required",
                proposal_schema=_model_rerun_proposal_schema(),
                editable_schema={
                    "type": "object",
                    "description": "Field-level model rerun changes.",
                    "properties": {
                        "model_options": {
                            "type": "object",
                            "description": (
                                "A one-level model-options patch, not an old/new field-diff wrapper."
                            ),
                        },
                    },
                    "additionalProperties": True,
                },
                executor_key="model.rerun",
                reconciler_key="model.rerun",
                diff_builder_key="rerun.diff.v1",
                verification_builder_key="rerun.verification.v1",
                ui_description="Change the current model parameters and rerun.",
                example_prompts=(
                    "Change the current model covariance from clustered to unadjusted, then rerun.",
                ),
                natural_language_enabled=True,
                validator=_validate_model_rerun,
            )
        )
        self.register(
            OperationDefinition(
                operation_id="model.genesis",
                operation_version="v1",
                effect_level="mutation",
                scope_requirements=("dataset",),
                scope="dataset source",
                risk_level="mutating",
                confirmation_policy="required",
                proposal_schema=_model_genesis_proposal_schema(),
                editable_schema={
                    "type": "object",
                    "properties": {
                        "table_params": {"type": "object"},
                        "model_params": {"type": "object"},
                        "model_options": {"type": "object"},
                    },
                    "additionalProperties": False,
                },
                executor_key="model.genesis",
                reconciler_key="model.genesis",
                diff_builder_key="genesis.diff.v1",
                verification_builder_key="genesis.verification.v1",
                ui_description="Create a first-run model Draft from a verified dataset source.",
                natural_language_enabled=False,
                validator=_validate_model_genesis,
            )
        )
        self.register(
            OperationDefinition(
                operation_id="graph.fork",
                operation_version="v1",
                effect_level="mutation",
                scope_requirements=("chain", "active_head"),
                scope="current chain/node",
                risk_level="mutating",
                confirmation_policy="required",
                proposal_schema=_graph_fork_proposal_schema(),
                editable_schema={
                    "type": "object",
                    "properties": {
                        "reason": {
                            "type": "string",
                            "maxLength": 1000,
                        }
                    },
                    "additionalProperties": False,
                },
                executor_key="graph.fork",
                reconciler_key="graph.fork",
                diff_builder_key="none",
                verification_builder_key="fork.verification.v1",
                ui_description="Create a new Chain branch from the current verified node.",
                example_prompts=(
                    "Create a new branch from the current node so I can test another robust standard-error specification.",
                ),
                natural_language_enabled=True,
                validator=_validate_graph_fork,
            )
        )
        self.register(
            OperationDefinition(
                operation_id="data.column.cast",
                operation_version="v1",
                effect_level="mutation",
                scope_requirements=("data_node", "active_head"),
                scope="dataset node",
                risk_level="mutating",
                confirmation_policy="required",
                proposal_schema=_data_column_cast_proposal_schema(),
                editable_schema={
                    "type": "object",
                    "properties": {
                        "column": {"type": "string"},
                        "target_dtype": {
                            "type": "string",
                            "enum": ["numeric", "string", "datetime"],
                        },
                    },
                    "additionalProperties": False,
                },
                executor_key="data.column.cast",
                reconciler_key="data.column.cast",
                diff_builder_key="data.schema_diff.v1",
                verification_builder_key="data.column_cast.verification.v1",
                ui_description="Cast one existing column in the current dataset node to a supported target type.",
                example_prompts=("Cast the age column in the current dataset node to numeric.",),
                natural_language_enabled=False,
                validator=_validate_data_column_cast,
            )
        )
        self.register(
            OperationDefinition(
                operation_id="data.columns.cast",
                operation_version="v1",
                effect_level="mutation",
                # "chain" is here because the Chain Agent must be able to reach
                # this operation: the natural-language allowlist selects on
                # operations requiring at least the caller's scope, and a data
                # cast really does execute inside a chain (`data_chain:<run>`).
                # The manual UI path is unaffected — it resolves by id.
                scope_requirements=("chain", "data_node", "active_head"),
                scope="dataset node",
                risk_level="mutating",
                confirmation_policy="required",
                proposal_schema=_data_columns_cast_proposal_schema(),
                editable_schema={
                    "type": "object",
                    "properties": {
                        "casts": {
                            "type": "array",
                            "minItems": 1,
                            "items": {
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
                        },
                    },
                    "additionalProperties": False,
                },
                executor_key="data.columns.cast",
                reconciler_key="data.columns.cast",
                diff_builder_key="data.schema_diff.v1",
                verification_builder_key="data.column_cast.verification.v1",
                ui_description="Cast multiple existing columns in the current dataset node in one operation, producing one child dataset node.",
                example_prompts=(
                    "Cast both the age and income columns in the current dataset node to numeric.",
                    "Cast region to string and wage to numeric.",
                ),
                # v1.7 优先级 6：NL Agent 生成同一份 typed proposal。批量 cast 是
                # 最佳目标形态——一句话本来就是一个意图。artifact_id 与
                # context_fingerprint 由后端在 canonicalization 时绑定，模型只出意图。
                natural_language_enabled=True,
                validator=_validate_data_columns_cast,
            )
        )
        self.register(
            OperationDefinition(
                operation_id="code.execute",
                operation_version="v1",
                effect_level="mutation",
                scope_requirements=("data_node", "active_head"),
                scope="dataset node",
                # Arbitrary user code, so it is not merely "mutating": preview
                # and execution each really run it (sandboxed), and the result
                # is only as reviewable as the diff the user reads.
                risk_level="high",
                confirmation_policy="required",
                proposal_schema=_code_execute_proposal_schema(),
                editable_schema={
                    "type": "object",
                    "properties": {
                        "code": {"type": "string", "minLength": 1, "maxLength": 20000},
                        "language": {"type": "string", "enum": ["python"]},
                        "output_format": {"type": "string", "enum": ["csv", "xlsx"]},
                    },
                    "additionalProperties": False,
                },
                executor_key="code.execute",
                reconciler_key="code.execute",
                diff_builder_key="data.schema_diff.v1",
                verification_builder_key="data.column_cast.verification.v1",
                ui_description=(
                    "Run a Python transformation in the sandbox against the current dataset node "
                    "(read df and produce result), creating a child dataset node; the source is read-only, "
                    "network access is disabled, and resources are limited."
                ),
                example_prompts=(),
                natural_language_enabled=False,
                validator=_validate_code_execute,
            )
        )

    def register(self, definition: OperationDefinition) -> None:
        key = (definition.operation_id, definition.operation_version)
        if key in self._definitions:
            raise ValueError(f"operation already registered: {definition.operation_id}")
        self._definitions[key] = definition

    def operation_ids(self) -> list[str]:
        """Registered operation identities, for tool schemas and UI enums."""
        return sorted({operation_id for operation_id, _version in self._definitions})

    def capabilities(self) -> list[dict[str, Any]]:
        """Return the public, JSON-safe capability registry projection."""

        definitions = sorted(
            self._definitions.values(),
            key=lambda definition: (definition.operation_id, definition.operation_version),
        )
        return [
            {
                "operation_id": definition.operation_id,
                "operation_version": definition.operation_version,
                "effect_level": definition.effect_level,
                "scope": definition.scope,
                "scope_requirements": list(definition.scope_requirements),
                "risk_level": definition.risk_level,
                "risk_authorization_policy": definition.risk_authorization_policy,
                "confirmation_policy": definition.confirmation_policy,
                "proposal_schema": definition.proposal_schema,
                "editable_schema": definition.editable_schema,
                "executor": definition.executor_key,
                "reconciler": definition.reconciler_key,
                "diff_builder": definition.diff_builder_key,
                "verification_builder": definition.verification_builder_key,
                "ui_description": definition.ui_description,
                "example_prompts": list(definition.example_prompts),
                "natural_language_enabled": definition.natural_language_enabled,
            }
            for definition in definitions
        ]

    def natural_language_operation_ids(
        self,
        *,
        scope_requirements: tuple[str, ...] = (),
    ) -> list[str]:
        required = set(scope_requirements)
        return sorted(
            definition.operation_id
            for definition in self._definitions.values()
            if definition.natural_language_enabled
            and required.issubset(set(definition.scope_requirements))
        )

    def requires_risk_authorization(
        self,
        operation_id: str,
        operation_version: str = "v1",
    ) -> bool:
        return self.require(operation_id, operation_version).requires_risk_authorization

    def boundary(self) -> dict[str, list[dict[str, str]]]:
        """Return registry-owned non-mutating and unavailable boundaries."""

        return {
            "advisory": [
                {
                    "id": "analysis.explain",
                    "label": "Compare results and explain diagnostics",
                    "description": "Ask for evidence-based explanations without directly changing the graph or running data.",
                },
                {
                    "id": "analysis.suggest",
                    "label": "Suggest the next analysis step",
                    "description": "Get recommendations without automatically executing a multi-step plan.",
                },
            ],
            "unsupported": [
                {
                    "id": "data.cleaning",
                    "label": "Modify data-cleaning rules",
                    "description": "No corresponding typed operation is available yet.",
                },
                {
                    "id": "workspace.arbitrary",
                    "label": "Arbitrary file, code, or network operations",
                    "description": "The Agent has no arbitrary shell, file, Python, or network tools.",
                },
                {
                    "id": "operation.multi_step",
                    "label": "Multi-step automatic execution",
                    "description": "Only individually confirmed typed operations are supported.",
                },
            ],
        }

    def proposal_tool_schema(self) -> dict[str, Any]:
        """Build one tool schema with an operation-specific ``oneOf`` union."""

        base = deepcopy(self.require("model.rerun").proposal_schema)
        base["properties"]["operation_id"] = {
            "type": "string",
            "enum": self.natural_language_operation_ids(
                scope_requirements=("chain", "active_head")
            ),
        }
        # The envelope must not impose one operation's shape on all of them.
        # This base is copied from model.rerun for its common fields, but a
        # JSON Schema `oneOf` is an AND with its parent: leaving model.rerun's
        # `target` here demanded node_hash/forest_node_key from every operation
        # and rejected `casts` as an unexpected property, making data.columns.cast
        # unproposable. graph.fork only survived because its target happens to be
        # a superset of model.rerun's — an accident, not a design.
        # The oneOf branches below carry each operation's real shape.
        for field in ("target", "preconditions", "changes"):
            base["properties"][field] = {"type": "object"}
        schemas: list[dict[str, Any]] = []
        for definition in sorted(
            self._definitions.values(),
            key=lambda item: (item.operation_id, item.operation_version),
        ):
            if not definition.proposal_schema or not definition.natural_language_enabled:
                continue
            schema = deepcopy(definition.proposal_schema)
            schema["properties"]["operation_id"] = {
                "type": "string",
                "const": definition.operation_id,
            }
            if definition.operation_id == "graph.fork":
                # The source Agent entry is a backend-bound fact: requiring the
                # model to invent it would turn a durable Chain leaf into an
                # untrusted input. The persisted proposal remains validated by
                # the full operation schema after canonicalization.
                schema["properties"]["target"]["required"] = [
                    field
                    for field in schema["properties"]["target"].get("required", [])
                    if field != "source_session_entry_id"
                ]
                schema["properties"]["target"]["description"] = (
                    "The backend binds source_session_entry_id to the current Chain leaf."
                )
            if definition.operation_id == "data.columns.cast":
                # Same precedent: the artifact behind a data node is a backend
                # fact. A model naming it could aim a confirmed operation at
                # data the user never selected, so don't ask it to.
                schema["properties"]["target"]["required"] = [
                    field
                    for field in schema["properties"]["target"].get("required", [])
                    if field != "artifact_id"
                ]
                schema["properties"]["target"]["description"] = (
                    "Supply run_id, node_ref and casts. The backend binds artifact_id "
                    "from the data node and computes the preview fingerprint."
                )
                # The preview fingerprint (and the context identity around it)
                # is computed here from the real data during canonicalization.
                # Demanding it from the model is asking it to invent a value we
                # are about to overwrite — the live smoke showed exactly that
                # failure mode on model.rerun.
                schema["properties"]["preconditions"]["required"] = ["active_head_run_id"]
                schema["properties"]["preconditions"]["description"] = (
                    "Supply active_head_run_id. The backend binds context_version, "
                    "context_fingerprint and owner_resolution from the data node."
                )
            schemas.append(schema)
        base["oneOf"] = schemas
        base["description"] = "A typed, confirmation-gated Workbench operation proposal."
        return base

    def require(self, operation_id: str, operation_version: str = "v1") -> OperationDefinition:
        try:
            return self._definitions[(operation_id, operation_version)]
        except KeyError as exc:
            raise UnknownOperationError(
                f"operation is not registered: {operation_id}@{operation_version}"
            ) from exc


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


def _model_rerun_proposal_schema() -> dict[str, Any]:
    return _proposal_schema(
        target_required=["run_id", "node_ref", "node_hash", "forest_node_key"],
        changes={
            "type": "object",
            "properties": {
                "model_options": {
                    "type": "object",
                    "description": (
                        "A one-level model-options patch, not an old/new field-diff wrapper."
                    ),
                }
            },
            "additionalProperties": True,
        },
    )


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


@dataclass(frozen=True)
class OperationRecord:
    record_id: str
    operation_id: str
    operation_version: str
    proposal_id: str
    proposal_revision: int
    proposal_fingerprint: str
    agent_session_id: str
    chain_id: str
    command_id: str | None
    target: dict[str, Any]
    preconditions: dict[str, Any]
    actor_type: str
    status: str
    confirmation: dict[str, Any]
    execution: dict[str, Any] = field(default_factory=dict)
    outputs: dict[str, Any] = field(default_factory=dict)
    diff_ref: dict[str, Any] | None = None
    verification: dict[str, Any] = field(default_factory=dict)
    error: dict[str, Any] | None = None
    # The domain effect and its read-model projection have separate durable
    # states.  A crash after domain commit must be recoverable without
    # re-running the effect or mistaking an unfinished projection for a second
    # execution.
    effect_status: str = "pending"
    projection_status: str = "pending"
    created_at: str = ""
    updated_at: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "record_type": "state",
            "record_id": self.record_id,
            "operation_id": self.operation_id,
            "operation_version": self.operation_version,
            "proposal_id": self.proposal_id,
            "proposal_revision": self.proposal_revision,
            "proposal_fingerprint": self.proposal_fingerprint,
            "agent_session_id": self.agent_session_id,
            "chain_id": self.chain_id,
            "command_id": self.command_id,
            "target": self.target,
            "preconditions": self.preconditions,
            "actor_type": self.actor_type,
            "status": self.status,
            "confirmation": self.confirmation,
            "execution": self.execution,
            "outputs": self.outputs,
            "diff_ref": self.diff_ref,
            "verification": self.verification,
            "error": self.error,
            "effect_status": self.effect_status,
            "projection_status": self.projection_status,
            "created_at": self.created_at,
            "updated_at": self.updated_at,
        }

    @classmethod
    def from_dict(cls, value: dict[str, Any]) -> "OperationRecord":
        return cls(
            record_id=str(value["record_id"]),
            operation_id=str(value["operation_id"]),
            operation_version=str(value["operation_version"]),
            proposal_id=str(value["proposal_id"]),
            proposal_revision=int(value["proposal_revision"]),
            proposal_fingerprint=str(value["proposal_fingerprint"]),
            agent_session_id=str(value["agent_session_id"]),
            chain_id=str(value["chain_id"]),
            command_id=value.get("command_id"),
            target=dict(value.get("target") or {}),
            preconditions=dict(value.get("preconditions") or {}),
            actor_type=str(value["actor_type"]),
            status=str(value["status"]),
            confirmation=dict(value.get("confirmation") or {}),
            execution=dict(value.get("execution") or {}),
            outputs=dict(value.get("outputs") or {}),
            diff_ref=dict(value["diff_ref"]) if value.get("diff_ref") else None,
            verification=dict(value.get("verification") or {}),
            error=dict(value["error"]) if value.get("error") else None,
            effect_status=str(value.get("effect_status") or "pending"),
            projection_status=str(value.get("projection_status") or "pending"),
            created_at=str(value["created_at"]),
            updated_at=str(value["updated_at"]),
        )


class OperationRecordStore:
    """Persist lifecycle states without overwriting completed history."""

    def __init__(self, root: Path | str, *, create: bool = True) -> None:
        self.root = Path(root)
        self.records_dir = self.root / "operation-records"
        if create:
            self.records_dir.mkdir(parents=True, exist_ok=True)
        self._lock = RLock()

    def create_pending(
        self,
        confirmation: ProposalConfirmation,
        *,
        command_id: str | None = None,
    ) -> OperationRecord:
        with self._lock:
            record_id = self._record_id(confirmation, command_id=command_id)
            path = self._path(record_id)
            if path.exists():
                return self.get(record_id)
            now = _now()
            record = OperationRecord(
                record_id=record_id,
                operation_id=confirmation.operation_id,
                operation_version=confirmation.operation_version,
                proposal_id=confirmation.proposal_id,
                proposal_revision=confirmation.revision,
                proposal_fingerprint=confirmation.fingerprint,
                agent_session_id=confirmation.session_id,
                chain_id=confirmation.chain_id,
                command_id=command_id or confirmation.command_id,
                target=confirmation.target,
                preconditions=confirmation.preconditions,
                actor_type=confirmation.actor_type,
                status="pending",
                confirmation=confirmation.to_dict(),
                created_at=now,
                updated_at=now,
            )
            append_jsonl_atomic(path, record.to_dict())
            return record

    def bind_risk_authorization(
        self,
        record_id: str,
        authorization_id: str,
    ) -> OperationRecord:
        """Durably bind a high-risk grant before its token is consumed."""

        if not authorization_id:
            raise ValueError("authorization_id is required")
        with self._lock:
            current = self.get(record_id)
            existing = current.execution.get("risk_authorization_id")
            if existing is not None and existing != authorization_id:
                # A grant may expire or be rejected after this pending record
                # was created. Reauthorization is safe until execution is
                # claimed; after a claim, changing the authorization binding
                # would make recovery ambiguous and must fail closed.
                if current.execution.get("execution_key") is not None:
                    raise OperationRecordTransitionError(
                        f"operation already has another risk authorization: {record_id}"
                    )
            if existing == authorization_id:
                return current
            return self.append_status(
                record_id,
                current.status,
                execution={
                    **current.execution,
                    "risk_authorization_id": authorization_id,
                },
            )

    def claim_execution(
        self,
        record_id: str,
        *,
        execution_key: str,
        lease_owner: str,
        lease_seconds: int = 300,
    ) -> OperationRecord:
        """Claim one operation execution idempotently under the store lock."""

        from .execution import OperationClaimConflict

        if not execution_key or not lease_owner:
            raise ValueError("execution_key and lease_owner are required")
        with self._lock:
            current = self.get(record_id)
            if current.status in {"completed", "failed", "stale", "cancelled"}:
                raise OperationClaimConflict(
                    f"terminal operation cannot be claimed: {record_id}"
                )
            existing_key = current.execution.get("execution_key")
            if existing_key is not None:
                if existing_key == execution_key:
                    existing_owner = current.execution.get("claim_owner")
                    if (
                        existing_owner
                        and existing_owner != lease_owner
                        and current.status != "recovering"
                    ):
                        raise OperationClaimConflict(
                            f"operation is already owned by {existing_owner}"
                        )
                    if existing_owner != lease_owner:
                        now = datetime.now(timezone.utc)
                        execution = {
                            **current.execution,
                            "claim_owner": lease_owner,
                            "claimed_at": now.isoformat(),
                            "lease_expires_at": (
                                now + timedelta(seconds=lease_seconds)
                            ).isoformat(),
                        }
                        return self.append_status(
                            record_id,
                            current.status,
                            execution=execution,
                        )
                    return current
                raise OperationClaimConflict(
                    f"operation already claimed by execution key: {existing_key}"
                )
            now = datetime.now(timezone.utc)
            execution = {
                **current.execution,
                "execution_key": execution_key,
                "claim_owner": lease_owner,
                "claimed_at": now.isoformat(),
                "lease_expires_at": (
                    now + timedelta(seconds=lease_seconds)
                ).isoformat(),
                "bindings": {},
            }
            return self.append_status(
                record_id,
                "submitted",
                execution=execution,
            )

    def bind_effect(
        self,
        record_id: str,
        *,
        execution_key: str,
        bindings: dict[str, str],
    ) -> OperationRecord:
        """Persist effect ids only after verifying the claimed execution key."""

        from .execution import OperationClaimConflict

        with self._lock:
            current = self.get(record_id)
            if current.execution.get("execution_key") != execution_key:
                raise OperationClaimConflict(
                    f"effect binding does not match execution key: {record_id}"
                )
            existing = dict(current.execution.get("bindings") or {})
            for key, value in bindings.items():
                if key in existing and existing[key] != value:
                    raise OperationClaimConflict(
                        f"effect binding already exists for {key}: {record_id}"
                    )
            existing.update({str(key): str(value) for key, value in bindings.items()})
            execution = {**current.execution, "bindings": existing}
            return self.append_status(
                record_id,
                current.status,
                execution=execution,
            )

    def append_status(
        self,
        record_id: str,
        status: str,
        *,
        execution: dict[str, Any] | None = None,
        outputs: dict[str, Any] | None = None,
        diff_ref: dict[str, Any] | None = None,
        verification: dict[str, Any] | None = None,
        error: dict[str, Any] | None = None,
        effect_status: str | None = None,
        projection_status: str | None = None,
    ) -> OperationRecord:
        with self._lock:
            current = self.get(record_id)
            has_payload = any(
                value is not None
                for value in (
                    execution,
                    outputs,
                    diff_ref,
                    verification,
                    error,
                    effect_status,
                    projection_status,
                )
            )
            if status == current.status and not has_payload:
                return current
            allowed = {
                "pending": {"submitted", "running", "completed", "failed", "stale", "cancelled", "recovering"},
                "submitted": {"running", "completed", "failed", "stale", "cancelled", "recovering"},
                "running": {"completed", "failed", "stale", "cancelled", "recovering"},
                "recovering": {"submitted", "running", "completed", "failed", "stale", "cancelled"},
                "completed": set(),
                "failed": set(),
                "stale": set(),
                "cancelled": set(),
            }
            if status != current.status and status not in allowed.get(current.status, set()):
                raise OperationRecordTransitionError(
                    f"invalid operation record transition: {current.status} -> {status}"
                )
            updated = OperationRecord(
                **{
                    **current.__dict__,
                    "status": status,
                    "execution": execution if execution is not None else current.execution,
                    "outputs": outputs if outputs is not None else current.outputs,
                    "diff_ref": diff_ref if diff_ref is not None else current.diff_ref,
                    "verification": verification if verification is not None else current.verification,
                    "error": error if error is not None else current.error,
                    "effect_status": (
                        effect_status
                        if effect_status is not None
                        else current.effect_status
                    ),
                    "projection_status": (
                        projection_status
                        if projection_status is not None
                        else current.projection_status
                    ),
                    "updated_at": _now(),
                }
            )
            if updated == current:
                return current
            append_jsonl_atomic(self._path(record_id), updated.to_dict())
            return updated

    def get(self, record_id: str) -> OperationRecord:
        records = [
            OperationRecord.from_dict(item)
            for item in read_jsonl(self._path(record_id))
            if item.get("record_type") == "state"
        ]
        if not records:
            raise KeyError(f"unknown operation record: {record_id}")
        return records[-1]

    def list_records(self) -> list[OperationRecord]:
        with self._lock:
            return [self.get(path.stem) for path in sorted(self.records_dir.glob("oprec_*.jsonl"))]

    def _path(self, record_id: str) -> Path:
        if not record_id or Path(record_id).name != record_id:
            raise ValueError("record_id must be path-safe")
        return self.records_dir / f"{record_id}.jsonl"

    @staticmethod
    def _record_id(confirmation: ProposalConfirmation, *, command_id: str | None) -> str:
        identity = {
            "operation_id": confirmation.operation_id,
            "proposal_id": confirmation.proposal_id,
            "proposal_revision": confirmation.revision,
            "proposal_fingerprint": confirmation.fingerprint,
            "active_head_run_id": confirmation.preconditions.get("active_head_run_id"),
        }
        encoded = json.dumps(identity, ensure_ascii=False, sort_keys=True).encode("utf-8")
        return f"oprec_{hashlib.sha256(encoded).hexdigest()[:24]}"
