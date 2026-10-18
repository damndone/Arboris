"""Semantic planning admission with explicit server-owned dependencies."""

from __future__ import annotations

from dataclasses import replace
from typing import Any, Mapping
from ...contracts.agent.notebook_option import ExpectedArtifact
from ..operations import OperationRegistry
from ..context_compiler import NotebookPlanningContextV1
from ..notebook.artifact_contract import build_artifact_contract
from ..notebook.evidence import DataEvidencePackV1
from ..notebook.memory_defaults import (
    MemoryDefaultApplicationError,
    apply_memory_defaults,
)
from ..notebook.vocabulary import by_group_artifact_types, capability_artifact_types
from ..notebook.workflow_artifacts import (
    WORKFLOW_RESULT_ARTIFACT_TYPE,
    p7_capability_ids_from_steps,
    workflow_result_artifact_id,
)
from ..workflow_contracts import (
    GENESIS_RUN_LEVEL_FIELDS,
    NOTEBOOK_GENESIS_MODEL_PARAMS,
    validate_model_genesis_spec,
)
from ...contracts.model.family import (
    MODEL_FAMILY_SPEC_FIELDS,
    family_context_columns,
    model_family_contract,
)
from ...contracts.common.errors import (
    OperationValidationError as WorkflowOperationValidationError,
)
from ..recipe_contracts import RecipeValidationError, recipe_contract_for_model_type

from .types import (
    NotebookPlanningUnavailable,
    NotebookPlanningContractError,
    AgentOptionSubmission,
    ProposalValidator,
)
from .normalize import (
    _execution_pins,
    _canonicalize_server_owned_pins,
    _canonicalize_provider_capability_id,
    _strip_unsupported_model_options,
)


def _published_artifact_types(
    capability_id: str,
    artifact_types_by_capability: Mapping[str, Mapping[str, str]],
) -> Mapping[str, str]:
    dynamic = artifact_types_by_capability.get(capability_id)
    if dynamic is not None:
        return dynamic
    return capability_artifact_types(capability_id)


def _workflow_primary_artifacts(
    steps: Any,
    catalog: Mapping[str, Any],
    artifact_types_by_capability: Mapping[str, Mapping[str, str]],
) -> tuple[dict[str, str], dict[str, int], frozenset[str]]:
    """Derive any model-primary results from a composed option's steps."""

    artifact_types: dict[str, str] = {}
    counts: dict[str, int] = {}
    families: set[str] = set()
    for step in steps if isinstance(steps, list) else []:
        if not isinstance(step, Mapping) or step.get("operation_id") != "model.genesis":
            continue
        spec = step.get("spec")
        if not isinstance(spec, Mapping):
            continue
        model_family = spec.get("model_family")
        if not isinstance(model_family, str) or not model_family:
            raise NotebookPlanningContractError(
                "model.genesis workflow step requires a registered model_family"
            )
        declaration = catalog.get(model_family)
        if not isinstance(declaration, Mapping):
            raise NotebookPlanningContractError(
                "model.genesis model_family is not a server-published capability: "
                + model_family
            )
        declared_model_type = declaration.get("model_type")
        if declared_model_type is not None and declared_model_type != model_family:
            raise NotebookPlanningContractError(
                "model.genesis model_family does not match its server capability identity"
            )
        branches = spec.get("branches")
        branch_count = len(branches) if isinstance(branches, list) else 0
        published = _published_artifact_types(model_family, artifact_types_by_capability)
        if branch_count and not published:
            raise NotebookPlanningContractError(
                "model.genesis model_family has no published primary artifact: "
                + model_family
            )
        families.add(model_family)
        for artifact_id, artifact_type in published.items():
            previous = artifact_types.setdefault(artifact_id, artifact_type)
            if previous != artifact_type:
                raise NotebookPlanningContractError(
                    "model family artifact vocabulary assigns conflicting types to: "
                    + artifact_id
                )
            counts[artifact_id] = counts.get(artifact_id, 0) + branch_count
    return artifact_types, counts, frozenset(families)


def _validate_submissions(
    context: NotebookPlanningContextV1,
    evidence: DataEvidencePackV1,
    submissions: tuple[AgentOptionSubmission, ...],
    catalog: Mapping[str, Any],
    *,
    operation_registry: OperationRegistry,
    proposal_validator: ProposalValidator | None,
    artifact_types_by_capability: Mapping[str, Mapping[str, str]],
    max_options: int = 3,
) -> tuple[AgentOptionSubmission, ...]:
    if len(submissions) > max_options or not submissions:
        raise NotebookPlanningContractError(
            f"option batch must contain 1 to {max_options} options"
        )
    if max_options == 1 and submissions[0].rank != 1:
        raise NotebookPlanningContractError("Action mode option must have rank 1")
    evidence_by_id = {record.evidence_id: record for record in evidence.records}
    option_ids = [submission.option_id or f"candidate_{index + 1}" for index, submission in enumerate(submissions)]
    if any(submission.option_id is None for submission in submissions):
        raise NotebookPlanningContractError("every provider option needs a stable option_id")
    if len(set(option_ids)) != len(option_ids):
        raise NotebookPlanningContractError("option ids must be unique")
    ranks = [submission.rank for submission in submissions]
    if len(set(ranks)) != len(ranks):
        raise NotebookPlanningContractError("option ranks must be unique")
    normalized_submissions: list[AgentOptionSubmission] = []
    for submission in submissions:
        _assert_user_visible_domain_language(submission)
        submission = _canonicalize_server_owned_pins(context, submission)
        submission = _canonicalize_provider_capability_id(submission, catalog)
        submission = _strip_unsupported_model_options(submission, catalog)
        # Recipe options are canonically nested under model_params.  Keep
        # the accepted top-level compatibility envelope useful for model
        # providers, but normalize it before memory defaults are applied;
        # otherwise a valid memory hint is reported as if its container
        # were malformed and the provider receives no actionable repair.
        if submission.proposal.operation_id == "model.genesis":
            changes = submission.proposal.changes
            model_params = changes.get("model_params")
            if isinstance(model_params, Mapping):
                model_type = model_params.get("model_type")
                recipe_contract = (
                    recipe_contract_for_model_type(model_type)
                    if isinstance(model_type, str)
                    else None
                )
                if recipe_contract is not None:
                    model_options = model_params.get("model_options")
                    top_level_options = changes.get("model_options")
                    if model_options is None and isinstance(top_level_options, Mapping):
                        normalized_params = {
                            **model_params,
                            "model_options": dict(top_level_options),
                        }
                        submission = replace(
                            submission,
                            proposal=replace(
                                submission.proposal,
                                changes={
                                    **changes,
                                    "model_params": normalized_params,
                                },
                            ),
                        )
                    elif not isinstance(model_options, Mapping):
                        required_inputs = ", ".join(
                            f"model_options.{field_name}"
                            for field_name in recipe_contract.source_option_fields
                        )
                        raise NotebookPlanningContractError(
                            f"RECIPE_MODEL_OPTIONS_REQUIRED: {model_type} requires "
                            f"model_options containing {required_inputs}; a memory "
                            "default can fill only its registered field after those "
                            "source columns are declared"
                        )
        try:
            submission = replace(
                submission,
                proposal=apply_memory_defaults(
                    submission.proposal,
                    context.domain_memory_projection,
                ),
            )
        except MemoryDefaultApplicationError as error:
            raise NotebookPlanningContractError(
                f"memory-derived proposal default is invalid: {error}"
            ) from error
        if submission.capability_id not in catalog:
            if submission.proposal.operation_id == "operation.multi_step":
                raise NotebookPlanningContractError(
                    "operation.multi_step capability_id must name a server-published "
                    "model capability, not operation.multi_step"
                )
            raise NotebookPlanningUnavailable(f"capability is not registered: {submission.capability_id}")
        try:
            definition = operation_registry.require(
                submission.proposal.operation_id,
                submission.proposal.operation_version,
            )
            definition.validate(
                target=submission.proposal.target,
                preconditions=submission.proposal.preconditions,
                changes=submission.proposal.changes,
            )
        except Exception as error:
            raise NotebookPlanningContractError(
                f"typed proposal failed registry validation: {error}"
            ) from error
        if proposal_validator is not None:
            try:
                proposal_validator(context, submission)
            except NotebookPlanningContractError:
                raise
            except Exception as error:
                code = getattr(error, "code", "MODEL_OPTIONS_PATCH_INVALID")
                raise NotebookPlanningContractError(
                    f"model_options target contract rejected [{code}]: {error}"
                ) from error
        operation_id = submission.proposal.operation_id
        changes = submission.proposal.changes
        workflow_artifact_types: dict[str, str] = {}
        workflow_artifact_counts: dict[str, int] = {}
        workflow_families: frozenset[str] = frozenset()
        workflow_p7_capabilities: frozenset[str] = frozenset()
        evidence_columns = {
            str(column.get("name"))
            for record in evidence.records
            if isinstance(record.observations, Mapping)
            for column in (record.observations.get("columns") or [])
            if isinstance(column, Mapping) and column.get("name")
        }
        if operation_id == "model.genesis":
            unknown_changes = set(changes) - {"table_params", "model_params", "model_options"}
            if unknown_changes:
                raise NotebookPlanningContractError(
                    "model.genesis changes contain unknown field(s): "
                    + ", ".join(sorted(unknown_changes))
                )
            model_params = changes.get("model_params")
            if not isinstance(model_params, Mapping):
                raise NotebookPlanningContractError(
                    "model.genesis model_params must be an object containing model_type, y, and x"
                )
            model_type = model_params.get("model_type")
            if not isinstance(model_type, str) or not model_type:
                raise NotebookPlanningContractError(
                    "model.genesis model_params must include model_type"
                )
            declaration = catalog.get(submission.capability_id) or {}
            declared_model_type = declaration.get("model_type")
            if declared_model_type is not None and model_type != declared_model_type:
                raise NotebookPlanningContractError(
                    "model.genesis model_type does not match the server-declared "
                    "capability model identity"
                )
            if not evidence_columns:
                raise NotebookPlanningContractError(
                    "model.genesis requires completed column evidence before proposing inputs"
                )
            recipe_contract = recipe_contract_for_model_type(model_type)
            y: str | None = None
            if recipe_contract is not None:
                try:
                    recipe_contract.validate_planning_params(
                        model_params, columns=tuple(sorted(evidence_columns))
                    )
                except RecipeValidationError as error:
                    raise NotebookPlanningContractError(str(error)) from error
                family_contract = None
                requires_x = recipe_contract.requires_nonempty_predictors
            else:
                try:
                    declared_family = model_family_contract(model_type)
                except WorkflowOperationValidationError:
                    declared_family = None
                allowed_params = set(NOTEBOOK_GENESIS_MODEL_PARAMS) | set(
                    declared_family.context_spec_fields if declared_family is not None else ()
                )
                unknown_params = sorted(set(model_params) - allowed_params)
                if unknown_params:
                    # The same set materialization admits: refusing here lets
                    # the planner fix the option instead of the user meeting a
                    # failure after confirming it.
                    raise NotebookPlanningContractError(
                        "model.genesis model_params contains unsupported field(s): "
                        + ", ".join(unknown_params)
                        + ". A single-model option estimates one model from y and x; "
                        "propose one option per model, or a composed workflow for several."
                    )
                y = model_params.get("y")
                if not isinstance(y, str) or not y:
                    raise NotebookPlanningContractError(
                        "model.genesis model_params must include evidence-backed y"
                    )
                if y not in evidence_columns:
                    raise NotebookPlanningContractError(
                        f"model.genesis y is not present in completed evidence columns: {y}"
                    )
                try:
                    family_contract = model_family_contract(model_type)
                except WorkflowOperationValidationError:
                    family_contract = None
                requires_x = (
                    family_contract.requires_nonempty_predictors
                    if family_contract is not None
                    else True
                )
            if family_contract is not None:
                family_values = {
                    field_name: model_params.get(field_name)
                    for field_name in family_contract.required_spec_fields
                }
                if family_contract.required_spec_field_mode == "all":
                    missing_family_fields = [
                        field_name
                        for field_name, value in family_values.items()
                        if not isinstance(value, str) or not value
                    ]
                else:
                    missing_family_fields = (
                        list(family_values)
                        if family_values
                        and not any(
                            isinstance(value, str) and value
                            for value in family_values.values()
                        )
                        else []
                    )
                if missing_family_fields:
                    raise NotebookPlanningContractError(
                        family_contract.missing_required_fields_message
                        or "model.genesis is missing family-required fields"
                    )
                for field_name, value in family_values.items():
                    if value is None:
                        continue
                    if not isinstance(value, str) or not value:
                        raise NotebookPlanningContractError(
                            f"model.genesis {field_name} must be an evidence-backed column"
                        )
                    if value not in evidence_columns:
                        raise NotebookPlanningContractError(
                            f"model.genesis {field_name} is not present in completed evidence columns: {value}"
                        )
                if not family_contract.allows_covariance and "covariance" in model_params:
                    raise NotebookPlanningContractError(
                        f"model.genesis {model_type} does not accept OLS covariance settings"
                    )
            x = model_params.get("x", [])
            if (
                not isinstance(x, list)
                or any(not isinstance(item, str) or not item for item in x)
                or (requires_x and not x)
            ):
                raise NotebookPlanningContractError(
                    "model.genesis model_params must include non-empty evidence-backed x"
                )
            missing_x = sorted(set(x) - evidence_columns)
            if missing_x:
                raise NotebookPlanningContractError(
                    "model.genesis x is not present in completed evidence columns: "
                    + ", ".join(missing_x)
                )
            if family_contract is not None:
                family_spec: dict[str, Any] = {
                    "model_family": model_type,
                    "branches": [
                        {
                            "branch_id": "notebook",
                            "outcome": y,
                            "predictors": list(x),
                        }
                    ],
                }
                for field_name in (*MODEL_FAMILY_SPEC_FIELDS, *GENESIS_RUN_LEVEL_FIELDS):
                    if field_name in model_params:
                        family_spec[field_name] = model_params[field_name]
                if "covariance" in model_params:
                    family_spec["covariance"] = model_params["covariance"]
                # Options that belong to the covariance (HAC's time order) are checked
                # with it here, as the workflow step checks them, so planning and
                # materialization cannot disagree about them.
                covariance_options = model_params.get("model_options") or changes.get("model_options") or {}
                if family_contract.allows_covariance and isinstance(covariance_options, Mapping):
                    declared_options = {
                        key: value for key, value in covariance_options.items()
                        if key in family_contract.model_options_fields
                    }
                    if declared_options:
                        family_spec["model_options"] = declared_options
                try:
                    validated_contract = validate_model_genesis_spec(family_spec)
                    declared_columns = family_context_columns(
                        validated_contract, family_spec
                    )
                except WorkflowOperationValidationError as error:
                    raise NotebookPlanningContractError(str(error)) from error
                missing_family_columns = sorted(
                    set(declared_columns) - evidence_columns
                )
                if missing_family_columns:
                    raise NotebookPlanningContractError(
                        "model.genesis family fields are not present in completed evidence columns: "
                        + ", ".join(missing_family_columns)
                    )
        elif operation_id == "operation.multi_step":
            workflow_source = _execution_pins(context).get("workflow_source")
            if workflow_source is None:
                raise NotebookPlanningContractError(
                    "operation.multi_step requires one server-pinned raw source"
                )
            if submission.proposal.target != workflow_source["target"]:
                raise NotebookPlanningContractError(
                    "operation.multi_step target does not copy the server workflow source pin"
                )
            if submission.proposal.preconditions != workflow_source["preconditions"]:
                raise NotebookPlanningContractError(
                    "operation.multi_step preconditions do not copy the server workflow source pin"
                )
            if not evidence_columns:
                raise NotebookPlanningContractError(
                    "operation.multi_step requires completed column evidence"
                )
            from ..workflow_contracts import validate_workflow_steps

            try:
                validate_workflow_steps(
                    changes.get("steps"),
                    available_columns=sorted(evidence_columns),
                )
            except Exception as error:
                raise NotebookPlanningContractError(
                    f"operation.multi_step source columns are invalid: {error}"
                ) from error
            (
                workflow_artifact_types,
                workflow_artifact_counts,
                workflow_families,
            ) = _workflow_primary_artifacts(
                changes.get("steps"), catalog, artifact_types_by_capability
            )
            workflow_p7_capabilities = p7_capability_ids_from_steps(
                changes.get("steps")
            )
            workflow_capabilities = workflow_families | workflow_p7_capabilities
            if not workflow_capabilities:
                raise NotebookPlanningContractError(
                    "operation.multi_step has no contractible model or P7 result"
                )
            if submission.capability_id not in workflow_capabilities:
                raise NotebookPlanningContractError(
                    "operation.multi_step capability_id must name one declared "
                    "model_family or P7 operation"
                )
            if workflow_p7_capabilities:
                result_artifact_id = workflow_result_artifact_id(
                    notebook_id=context.notebook_id,
                    option_id=submission.option_id or "",
                    proposal_hash=submission.proposal.canonical_hash(),
                )
                workflow_artifact_types[result_artifact_id] = (
                    WORKFLOW_RESULT_ARTIFACT_TYPE
                )
                workflow_artifact_counts[result_artifact_id] = 1
        elif operation_id == "model.custom":
            unknown_changes = set(changes) - {
                "operation",
                "input_handle",
                "parameters",
                "consumer_slots",
            }
            if unknown_changes:
                raise NotebookPlanningContractError(
                    "model.custom changes contain server-owned or unknown field(s): "
                    + ", ".join(sorted(unknown_changes))
                )
            operation = changes.get("operation")
            if not isinstance(operation, str) or not operation:
                raise NotebookPlanningContractError(
                    "model.custom changes.operation must be a non-empty string"
                )
            if "input_handle" in changes and (
                not isinstance(changes["input_handle"], str)
                or not changes["input_handle"]
            ):
                raise NotebookPlanningContractError(
                    "model.custom input_handle must be a non-empty string"
                )
            if "parameters" in changes and not isinstance(
                changes["parameters"], Mapping
            ):
                raise NotebookPlanningContractError(
                    "model.custom parameters must be an object"
                )
            if "consumer_slots" in changes:
                slots = changes["consumer_slots"]
                if (
                    not isinstance(slots, list)
                    or not slots
                    or any(not isinstance(item, str) or not item for item in slots)
                    or len(set(slots)) != len(slots)
                ):
                    raise NotebookPlanningContractError(
                        "model.custom consumer_slots must be unique non-empty strings"
                    )
        elif operation_id == "model.rerun":
            unknown_changes = set(changes) - {"model_options"}
            if unknown_changes:
                raise NotebookPlanningContractError(
                    "model.rerun changes contain unknown field(s): "
                    + ", ".join(sorted(unknown_changes))
                )
        if not submission.evidence_refs:
            raise NotebookPlanningContractError("every option needs at least one evidence ref")
        published_artifacts: Mapping[str, str] = (
            workflow_artifact_types
            if operation_id == "operation.multi_step"
            else _published_artifact_types(submission.capability_id, artifact_types_by_capability)
        )
        by_group_artifacts = by_group_artifact_types(operation_id, dict(changes))
        if by_group_artifacts is not None:
            # A by-group run writes one result per group and the collection
            # listing them, not the family's single primary result.
            published_artifacts = dict(by_group_artifacts)
        canonical_expected_artifacts = submission.expected_artifacts
        if published_artifacts:
            # Artifact ids and types are server output.  The provider may
            # describe them for humans, but its guess must never make a
            # valid native capability fail admission.  A composed workflow
            # registers one primary result per declared branch; a regular
            # capability registers one primary result.
            canonical_expected_artifacts = tuple(
                ExpectedArtifact(
                    artifact_id=artifact_id,
                    artifact_type=artifact_type,
                    required=True,
                    count=(
                        workflow_artifact_counts[artifact_id]
                        if operation_id == "operation.multi_step"
                        else 1
                    ),
                    step=None,
                )
                for artifact_id, artifact_type in sorted(published_artifacts.items())
            )
        try:
            build_artifact_contract(
                canonical_expected_artifacts,
                additional_artifact_types=published_artifacts,
            )
        except Exception as error:
            raise NotebookPlanningContractError(
                f"expected artifact failed published artifact vocabulary validation: {error}"
            ) from error
        if published_artifacts:
            required_ids = {
                artifact.artifact_id
                for artifact in canonical_expected_artifacts
                if artifact.required
            }
            missing_artifacts = set(published_artifacts) - required_ids
            if missing_artifacts:
                raise NotebookPlanningContractError(
                    "capability required artifact(s) missing: "
                    + ", ".join(sorted(missing_artifacts))
                )
        for reference in submission.evidence_refs:
            record = evidence_by_id.get(reference.evidence_id)
            if record is None or record.result_hash != reference.result_hash or record.status != "completed":
                raise NotebookPlanningContractError("option evidence ref is missing, changed, or incomplete")
        if context.active_head_run_id:
            is_dataset_recipe_genesis = (
                submission.proposal.operation_id == "model.genesis"
                and isinstance(context.projection_source, Mapping)
                and context.projection_source.get("kind") == "dataset"
                and isinstance(submission.proposal.changes.get("model_params"), Mapping)
                and recipe_contract_for_model_type(
                    submission.proposal.changes["model_params"].get("model_type")
                )
                is not None
            )
            if is_dataset_recipe_genesis:
                if (
                    submission.proposal.target.get("dataset_source_id")
                    != context.projection_source.get("upload_sha256")
                ):
                    raise NotebookPlanningContractError(
                        "dataset-source proposal is not pinned to the source upload"
                    )
                if (
                    submission.proposal.preconditions
                    != _execution_pins(context)["genesis_preconditions"]
                ):
                    raise NotebookPlanningContractError(
                        "dataset-source proposal does not copy the server execution pins"
                    )
            elif submission.proposal.operation_id == "operation.multi_step":
                workflow_source = _execution_pins(context).get("workflow_source")
                if workflow_source is None:
                    raise NotebookPlanningContractError(
                        "operation.multi_step requires one server-pinned raw source"
                    )
                if (
                    submission.proposal.target != workflow_source["target"]
                    or submission.proposal.preconditions
                    != workflow_source["preconditions"]
                ):
                    raise NotebookPlanningContractError(
                        "operation.multi_step is not pinned to the current raw source"
                    )
            elif submission.proposal.operation_id not in {"model.rerun", "model.custom"} or submission.proposal.target.get("run_id") != context.active_head_run_id:
                raise NotebookPlanningContractError("run-source proposal is not a rerun-child of the active head")
            else:
                pins = _execution_pins(context)
                matching_pins = [
                    item
                    for item in pins["rerun_preconditions_by_target"]
                    if item["target"] == submission.proposal.target
                ]
                if not matching_pins:
                    raise NotebookPlanningContractError(
                        "run-source proposal target is not a server-pinned model node"
                    )
                if submission.proposal.preconditions != matching_pins[0]["preconditions"]:
                    raise NotebookPlanningContractError("run-source proposal does not copy the server execution pins")
        elif context.projection_source and context.projection_source.get("kind") == "dataset":
            if submission.proposal.operation_id == "operation.multi_step":
                # The preceding workflow-specific branch already verified
                # the immutable raw-source pin.  A composed workflow has
                # no single Pipeline Draft, so it must not be forced into
                # the genesis-materialization path used by one-model
                # dataset proposals.
                pass
            elif submission.proposal.operation_id not in {"model.genesis", "model.custom"}:
                raise NotebookPlanningContractError(
                    "dataset-source proposal requires a genesis, custom, or source-pinned workflow path"
                )
            elif submission.proposal.target.get("dataset_source_id") != context.projection_source.get("upload_sha256"):
                raise NotebookPlanningContractError("dataset-source proposal is not pinned to the source upload")
            elif submission.proposal.preconditions != _execution_pins(context)["genesis_preconditions"]:
                raise NotebookPlanningContractError("dataset-source proposal does not copy the server execution pins")
        normalized_submissions.append(
            replace(
                submission,
                expected_artifacts=canonical_expected_artifacts,
            )
        )
    proposal_hashes = [
        submission.proposal.canonical_hash()
        for submission in normalized_submissions
    ]
    if len(set(proposal_hashes)) != len(proposal_hashes):
        raise NotebookPlanningContractError(
            "option batch contains duplicate executable proposals"
        )
    return tuple(normalized_submissions)


def _assert_user_visible_domain_language(
    submission: AgentOptionSubmission,
) -> None:
    """Reject executable protocol vocabulary from human-facing option prose."""

    from ..p7_pack_registry import P7PackRegistryError, p7_pack_registry

    protocol_markers = {
        "capability_id",
        "operation_id",
        "proposal_id",
        "server default",
        "the pack",
        "by the pack",
        "typed adapter",
        "typed workflow",
        "typed proposal",
        "server-owned pin",
        submission.proposal.operation_id.casefold(),
    }
    if any(separator in submission.capability_id for separator in (".", "_", ":", "/")):
        protocol_markers.add(submission.capability_id.casefold())
    raw_steps = submission.proposal.changes.get("steps")
    if isinstance(raw_steps, list):
        for step in raw_steps:
            if not isinstance(step, Mapping):
                continue
            operation_id = step.get("operation_id")
            if not isinstance(operation_id, str):
                continue
            protocol_markers.add(operation_id.casefold())
            try:
                request_schema = p7_pack_registry.get(operation_id).request_schema
            except P7PackRegistryError:
                continue
            protocol_markers.update(
                name.casefold()
                for name in (
                    *request_schema.binding_shapes,
                    *request_schema.option_shapes,
                )
                if "_" in name
            )
    visible_text = (
        submission.rationale,
        *submission.assumptions,
        *submission.comparative_claims,
    )
    if any(
        marker and marker in text.casefold()
        for text in visible_text
        for marker in protocol_markers
    ):
        raise NotebookPlanningContractError(
            "user-visible option text contains internal protocol vocabulary"
        )
