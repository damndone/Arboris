"""Append-only typed operation records for confirmed proposals."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

# Definitions, proposal schemas/validators and records live in operation_*;
# the names callers import from this module are re-exported here.
from .operation_definitions import (
    OperationRecordTransitionError,
    UnknownOperationError,
    OperationDefinition,
    RERUN_OPERATIONS,
    is_rerun_operation,
    is_workflow_step_only,
)
from .operation_schemas import (
    _workflow_step_operation_definitions,
    _model_rerun_change_branch,
    _model_rerun_proposal_schema,
    _metadata_edit_proposal_schema,
    _validate_metadata_edit,
    _model_genesis_proposal_schema,
    _graph_fork_proposal_schema,
    _data_column_cast_proposal_schema,
    _code_execute_proposal_schema,
    _validate_code_execute,
    _data_columns_cast_proposal_schema,
    _validate_data_columns_cast,
    model_rerun_change_fields,
    _model_rerun_editable_schema,
    _validate_model_rerun,
    _validate_model_genesis,
    _model_custom_proposal_schema,
    _validate_model_custom,
    _validate_graph_fork,
    _validate_data_column_cast,
)
from .operation_records import (  # noqa: F401  (moved; re-exported)
    OperationRecord,
    OperationRecordStore,
)


#: Node identity the backend binds from run_id + node_ref (design §5.3). Proposals
#: may carry them (copied from a node read) but never need to: model.rerun used to
#: require node_hash/forest_node_key while operation.multi_step refused them and
#: required artifact_id, so a model that had done one rejected the other
#: (free-route round, 2026-10-22: 11 of 35 refused calls).
_BOUND_IDENTITY = ("node_hash", "forest_node_key")
#: Operations whose canonicalization also binds the node's artifact_id.
_ARTIFACT_BOUND = frozenset({"operation.multi_step", "data.columns.cast"})


_IDENTITY_FIELDS = ("artifact_id", "node_hash", "forest_node_key")


def normalize_operation_target(registry: "OperationRegistry", arguments: dict[str, Any]) -> dict[str, Any]:
    """Identity in a proposal target that this operation does not use is dropped, not refused.

    ``node_id`` names the node the way node reads do; it means ``node_ref``.
    """
    from .tools import tool_note

    target = arguments.get("target")
    if not isinstance(target, dict):
        return arguments
    target = dict(target)
    if "node_id" in target:
        node_id = target.pop("node_id")
        if "node_ref" not in target:
            target["node_ref"] = node_id
            tool_note("target.node_id is spelled node_ref; used as node_ref.")
        elif node_id != target["node_ref"]:
            target["node_id"] = node_id  # contradictory: leave it for validation to refuse
        else:
            tool_note("target.node_id duplicates node_ref; ignored.")
    try:
        definition = registry.require(str(arguments.get("operation_id")))
    except Exception:
        return {**arguments, "target": target}
    own = set(((definition.proposal_schema or {}).get("properties", {}).get("target") or {}).get("properties") or {})
    if definition.operation_id in _ARTIFACT_BOUND:
        own.add("artifact_id")
    unused = [field for field in _IDENTITY_FIELDS if field in target and field not in own]
    for field in unused:
        target.pop(field)
    if unused:
        tool_note(f"{definition.operation_id} does not use target.{', target.'.join(unused)}; ignored "
                  "(the backend binds node identity from run_id and node_ref).")
    return {**arguments, "target": target}


def _accept_backend_bound_identity(schema: dict[str, Any], operation_id: str) -> None:
    """Agent-facing target: references required, backend-bound identity optional and unused."""
    target = schema.get("properties", {}).get("target")
    if not isinstance(target, dict) or "properties" not in target:
        return
    bound = [*_BOUND_IDENTITY, *(["artifact_id"] if operation_id in _ARTIFACT_BOUND else [])]
    target["required"] = [field for field in target.get("required", []) if field not in bound]
    for field in bound:
        target["properties"].setdefault(field, {"type": "string", "maxLength": 500})
    note = ("The backend binds " + ", ".join(bound) + " from run_id and node_ref; values given here are not used.")
    target["description"] = (target.get("description", "") + " " + note).strip()


class OperationRegistry:
    """Explicit registry for agent-facing operation identities."""

    def __init__(self) -> None:
        self._definitions: dict[tuple[str, str], OperationDefinition] = {}
        # The workflow contracts import the registry's validation error type.
        # Keep this import local so importing this module does not create a
        # module-initialization cycle.
        from .workflow_contracts import (
            WORKFLOW_STEP_SPEC_CONTRACTS,
            workflow_proposal_schema,
            validate_workflow_operation,
            workflow_step_vocabulary,
        )

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
                editable_schema=_model_rerun_editable_schema(),
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
                operation_id="metadata.edit",
                operation_version="v1",
                effect_level="mutation",
                scope_requirements=("chain", "active_head"),
                scope="run variable metadata",
                risk_level="mutating",
                confirmation_policy="required",
                proposal_schema=_metadata_edit_proposal_schema(),
                editable_schema={
                    "type": "object",
                    "properties": {"labels": _model_rerun_change_branch()["properties"]["labels"]},
                    "required": ["labels"],
                    "additionalProperties": False,
                },
                executor_key="model.rerun",
                reconciler_key="model.rerun",
                diff_builder_key="rerun.diff.v1",
                verification_builder_key="rerun.verification.v1",
                ui_description=(
                    "Declare or change variable labels, value labels, measurement "
                    "levels or missing-value codes for any column. Never changes "
                    "which variables are in the model; the run is re-estimated "
                    "with the new metadata (missing codes change the sample)."
                ),
                example_prompts=(
                    "把 region 的取值标上标签：1 是北方，2 是南方",
                    "hours 里的 999 表示未回答，当作缺失值",
                ),
                natural_language_enabled=True,
                validator=_validate_metadata_edit,
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
                operation_id="model.custom",
                operation_version="v1",
                effect_level="mutation",
                scope_requirements=("dataset",),
                scope="dataset source",
                risk_level="high",
                confirmation_policy="required",
                proposal_schema=_model_custom_proposal_schema(
                    WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"]
                ),
                editable_schema=WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"].to_schema(),
                executor_key=WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"].dispatcher_key or "",
                reconciler_key=WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"].reconciler_key or "",
                diff_builder_key=WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"].diff_builder_key or "",
                verification_builder_key=WORKFLOW_STEP_SPEC_CONTRACTS["model.custom"].verification_builder_key or "",
                ui_description=(
                    "Run one explicitly admitted custom capability through the "
                    "Proposal/Risk and containment gates."
                ),
                natural_language_enabled=False,
                validator=_validate_model_custom,
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
        # ``operation.multi_step`` is the natural-language entry point for a
        # multi-step statistical workflow. The Agent composes which steps run
        # over which columns; every step's statistical semantics are still
        # validated and executed by the same server-owned validators the manual
        # UI uses. A named preset is one accepted shape, not the only one.
        self.register(
            OperationDefinition(
                operation_id="operation.multi_step",
                operation_version="v1",
                effect_level="mutation",
                scope_requirements=("chain", "active_head"),
                scope="dataset workflow",
                risk_level="mutating",
                confirmation_policy="required",
                proposal_schema=workflow_proposal_schema(),
                # The editable surface is the proposal's `changes` object, which
                # is a composed step list OR a preset binding. Requiring the
                # preset here contradicted the proposal schema and told an Agent
                # that composing steps was illegal.
                editable_schema=workflow_proposal_schema()["properties"]["changes"],
                contract_owner="operation_registry",
                vocabulary_builder=workflow_step_vocabulary,
                executor_key="operation.multi_step",
                reconciler_key="operation.multi_step",
                diff_builder_key="workflow.diff.v1",
                verification_builder_key="workflow.verification.v1",
                ui_description=(
                    "Compile and execute a multi-step statistical workflow with one "
                    "confirmation and auditable per-step artifacts."
                ),
                example_prompts=(
                    "Summarize every variable by year, then correlate them, then "
                    "regress spending on the demographic shares.",
                ),
                natural_language_enabled=True,
                validator=validate_workflow_operation,
            )
        )
        # These identities describe the only operations a compiled workflow
        # may use.  They are intentionally typed but not Agent-facing: the
        # user confirms the parent workflow once, while the executor records
        # each child step with the parent's authorization metadata.
        for definition in _workflow_step_operation_definitions():
            self.register(definition)

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
            and not is_workflow_step_only(definition)
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
                {
                    "id": "operation.multi_step",
                    "label": "Run a multi-step statistical workflow",
                    "description": (
                        "Compile the selected Raw data into nine typed steps under one "
                        "confirmation; the Agent cannot change statistical semantics."
                    ),
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
            if definition.operation_id == "model.rerun":
                # A request selector, consumed when binding the canonical PlanDiff;
                # the durable proposal still uses the source-resolved target.
                schema["properties"]["target"]["properties"]["result_id"] = {
                    "type": "string", "minLength": 1, "maxLength": 500,
                    "description": "Optional exact source result for a clustered OLS Analysis Loop; invalid for other reruns.",
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
            _accept_backend_bound_identity(schema, definition.operation_id)
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


