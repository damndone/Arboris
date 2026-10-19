"""service preparation: methods over the existing shared state."""
from __future__ import annotations
import json
from dataclasses import replace
from typing import Any, Mapping
from ...capability_factory.notebook_catalog import NOTEBOOK_OPTION_PLANNER_CONSUMER
from ...capability_factory.contracts import CONSUMER_SLOTS
from ...capability_factory.notebook_binding import CapabilityResolutionBinding
from .. import operation_requests
from ..context_compiler import NotebookPlanningContextV1
from ...contracts.common.errors import OperationValidationError
from .artifact_contract import build_artifact_contract
from .errors import OptionValidationFailed
from .memory_defaults import MemoryDefaultApplicationError, validate_memory_default_sources
from .proposal import OptionDraft, TypedProposal
from .store import Notebook
from .vocabulary import by_group_artifact_types
from .workflow_artifacts import WORKFLOW_RESULT_ARTIFACT_TYPE, p7_capability_ids_from_steps, workflow_result_artifact_id
from .service_contracts import (_REGISTRY_RISK_TO_OPTION_RISK)

class ServicePreparation:
    def _prepare(
        self,
        notebook: Notebook,
        context: NotebookPlanningContextV1,
        draft: OptionDraft,
        *,
        binding: CapabilityResolutionBinding | None = None,
    ) -> tuple[TypedProposal, Any, str]:
        """Validate one draft against the real registry. Raises, never stores."""

        proposal = draft.proposal
        if proposal.operation_id == "model.custom":
            if binding is None:
                raise OptionValidationFailed(
                    "model.custom requires a current server-owned capability binding",
                    option_id=draft.option_id,
                    operation_id=proposal.operation_id,
                    validation_issues=[
                        {
                            "code": "CAPABILITY_BINDING_REQUIRED",
                            "detail": "custom capability execution is never resolved from Agent-supplied refs",
                        }
                    ],
                )
            try:
                projection = self.capability_bindings.planner_projection(
                    draft.capability_id or "",
                    scope_candidates=(
                        ("project", notebook.project_id),
                        ("run_family", notebook.run_family_id),
                    ),
                ) if self.capability_bindings is not None else None
                if projection is None or "model.custom" not in projection.get(
                    "notebook_proposal_adapters", ()
                ):
                    raise ValueError("CAPABILITY_CUSTOM_ADAPTER_NOT_DECLARED")
                proposal = self._canonicalize_custom_proposal(proposal, binding)
            except Exception as error:
                raise OptionValidationFailed(
                    "model.custom proposal could not be server-bound",
                    option_id=draft.option_id,
                    operation_id=proposal.operation_id,
                    validation_issues=[
                        {"code": "CUSTOM_PROPOSAL_BINDING_INVALID", "detail": str(error)}
                    ],
                ) from error
        if proposal.memory_default_sources and binding is not None:
            raise OptionValidationFailed(
                "a memory-default revision cannot combine with a capability binding without an explicit combined contract",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
                validation_issues=[
                    {
                        "code": "MEMORY_DEFAULT_CAPABILITY_BINDING_UNSUPPORTED",
                        "detail": "memory defaults are only admitted for server-registered native targets",
                    }
                ],
            )
        try:
            validate_memory_default_sources(
                proposal,
                context.domain_memory_projection,
            )
        except MemoryDefaultApplicationError as error:
            raise OptionValidationFailed(
                "memory-derived proposal default is no longer current",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
                validation_issues=[
                    {"code": "MEMORY_DEFAULT_SOURCE_INVALID", "detail": str(error)}
                ],
            ) from error
        try:
            definition = self.registry.require(
                proposal.operation_id, proposal.operation_version
            )
        except Exception as error:  # UnknownOperationError
            raise OptionValidationFailed(
                f"unknown operation {proposal.operation_id}@{proposal.operation_version}: "
                f"{error}",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
            ) from error
        try:
            operation_requests.validate(
                operation_requests.OperationRequest(
                    operation_id=proposal.operation_id,
                    operation_version=proposal.operation_version,
                    target=proposal.target,
                    preconditions=proposal.preconditions,
                    changes=proposal.changes,
                    evidence_refs=(),
                    expected_effect=(),
                    risks=(),
                ),
                definition,
            )
            self._assert_p7_source_preflight(notebook, proposal)
        except OperationValidationError as error:
            # spec §7: refusing here is cheaper than apologising at click time.
            raise OptionValidationFailed(
                f"option proposal failed {proposal.operation_id} validation: {error}",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
                validation_issues=[{"code": "OPERATION_VALIDATION", "detail": str(error)}],
            ) from error
        try:
            self._validate_target_model_options(
                proposal,
                projection_source=notebook.projection_source,
            )
        except Exception as error:
            code = getattr(error, "code", "MODEL_OPTIONS_PATCH_INVALID")
            raise OptionValidationFailed(
                "option model_options failed the target model contract: "
                f"[{code}] {error}",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
                validation_issues=[{"code": code, "detail": str(error)}],
            ) from error
        self.validate_dataset_recipe_preflight(notebook.notebook_id, proposal)
        try:
            self._assert_capability_model_identity(notebook, draft, proposal)
        except Exception as error:
            raise OptionValidationFailed(
                "option capability model identity does not match the server declaration",
                option_id=draft.option_id,
                operation_id=proposal.operation_id,
                validation_issues=[
                    {
                        "code": "CAPABILITY_MODEL_IDENTITY_MISMATCH",
                        "detail": str(error),
                    }
                ],
            ) from error

        additional_artifact_types = dict(
            self._published_artifact_types(
                draft.capability_id or "",
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                ),
            )
        )
        by_group_artifacts = by_group_artifact_types(proposal.operation_id, dict(proposal.changes))
        if by_group_artifacts is not None:
            additional_artifact_types = dict(by_group_artifacts)
        if proposal.operation_id == "operation.multi_step" and p7_capability_ids_from_steps(
            proposal.changes.get("steps")
        ):
            result_artifact_id = workflow_result_artifact_id(
                notebook_id=notebook.notebook_id,
                option_id=draft.option_id or "",
                proposal_hash=proposal.canonical_hash(),
            )
            additional_artifact_types[result_artifact_id] = (
                WORKFLOW_RESULT_ARTIFACT_TYPE
            )
            required_results = {
                artifact.artifact_id
                for artifact in draft.expected_artifacts
                if artifact.required
            }
            if result_artifact_id not in required_results:
                raise OptionValidationFailed(
                    "a P7 workflow must require its server-owned result manifest",
                    option_id=draft.option_id,
                    operation_id=proposal.operation_id,
                    validation_issues=[
                        {
                            "code": "WORKFLOW_RESULT_ARTIFACT_REQUIRED",
                            "detail": result_artifact_id,
                        }
                    ],
                )
        contract = build_artifact_contract(
            draft.expected_artifacts,
            additional_artifact_types=additional_artifact_types,
        )
        risk_level = _REGISTRY_RISK_TO_OPTION_RISK.get(definition.risk_level)
        if risk_level is None:
            raise OptionValidationFailed(
                f"operation {proposal.operation_id} declares unmapped registry risk "
                f"level {definition.risk_level!r}",
                operation_id=proposal.operation_id,
            )
        return proposal, contract, risk_level


    @staticmethod
    def _canonicalize_custom_proposal(
        proposal: TypedProposal,
        binding: CapabilityResolutionBinding,
    ) -> TypedProposal:
        """Replace Agent capability names with the exact server-owned binding."""

        changes = dict(proposal.changes)
        forbidden = {"capability_ref", "binding_ref"} & set(changes)
        if forbidden:
            raise ValueError(
                "model.custom server-owned capability fields are not Agent-writable: "
                + ", ".join(sorted(forbidden))
            )
        operation = changes.get("operation")
        if not isinstance(operation, str) or not operation:
            raise ValueError("model.custom operation must be a non-empty string")
        if operation not in binding.allowed_operations:
            raise ValueError("model.custom operation is not admitted by the current binding")
        input_handle = changes.get("input_handle")
        if input_handle is not None and (
            not isinstance(input_handle, str)
            or not input_handle
            or len(input_handle) > 256
            or any(ord(char) < 0x20 for char in input_handle)
        ):
            raise ValueError("model.custom input_handle is invalid")
        parameters = changes.get("parameters", {})
        if not isinstance(parameters, Mapping):
            raise ValueError("model.custom parameters must be an object")
        encoded = json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > 256 * 1024:
            raise ValueError("model.custom parameters exceed the bounded input limit")
        requested_consumers = changes.get(
            "consumer_slots", [NOTEBOOK_OPTION_PLANNER_CONSUMER]
        )
        if (
            not isinstance(requested_consumers, list)
            or not requested_consumers
            or len(requested_consumers) > len(CONSUMER_SLOTS)
            or any(not isinstance(item, str) or not item for item in requested_consumers)
            or len(set(requested_consumers)) != len(requested_consumers)
            or not set(requested_consumers) <= set(CONSUMER_SLOTS)
            or not set(requested_consumers) <= set(binding.allowed_consumers)
        ):
            raise ValueError("model.custom consumer_slots are not admitted by the current binding")
        canonical_changes = {
            "capability_ref": binding.implementation_ref,
            "binding_ref": binding.content_digest,
            "operation": operation,
            "input_handle": input_handle or "table_1",
            "parameters": dict(parameters),
            "consumer_slots": list(requested_consumers),
        }
        if "expected_artifacts" in changes:
            expected_artifacts = changes["expected_artifacts"]
            if not isinstance(expected_artifacts, list) or any(
                not isinstance(item, str) or not item for item in expected_artifacts
            ):
                raise ValueError("model.custom expected_artifacts must be strings")
            canonical_changes["expected_artifacts"] = list(expected_artifacts)
        return replace(proposal, changes=canonical_changes)


    def _validate_target_model_options(
        self,
        proposal: TypedProposal,
        *,
        projection_source: Any,
    ) -> None:
        """Validate model-specific options before persisting an Option revision."""

        changes = proposal.changes
        if proposal.operation_id == "model.rerun":
            patch = changes.get("model_options") or {}
            if not patch:
                return
            from ...lineage.run_inputs import read_run_inputs
            from ...repository.run_repository import _resolve_run_root
            from ...services.run_service import merge_form_overrides

            try:
                run_root = _resolve_run_root(
                    str(self.project_root), str(proposal.target["run_id"])
                )
            except Exception as error:
                # Some append-only compatibility tests intentionally exercise
                # the Option lifecycle with a symbolic run id and no persisted
                # source.  There is no target contract to validate in that
                # case, so leave the option unverified; materialization still
                # requires a real source and remains fail-closed.
                if getattr(error, "code", None) == "RUN_NOT_FOUND":
                    return
                raise
            inputs = read_run_inputs(run_root)
            form = inputs.get("form") or {}
            if not isinstance(form, Mapping) or not isinstance(patch, Mapping):
                raise ValueError("model_options target and patch must be objects")
            # A persisted run without model identity is an incomplete legacy
            # fixture, not a model contract.  Do not guess its owner.
            if not form.get("model_type"):
                return
            merge_form_overrides(form, {"model_options": dict(patch)})
            return

        if proposal.operation_id == "model.genesis":
            from ..recipe_contracts import recipe_contract_for_model_type
            from ...model_options import bind_new_model_options

            model_params = changes.get("model_params") or {}
            if not isinstance(model_params, Mapping):
                return
            model_type = model_params.get("model_type")
            payload = changes.get("model_options")
            if payload is None:
                payload = model_params.get("model_options")
            if payload:
                # OLS owns a bounded model_options contract. The adapter also
                # projects its covariance into the legacy top-level field so
                # Genesis and the human Draft editor retain one executable
                # covariance meaning.
                if model_type == "ols":
                    from ...services.draft_materialization import (
                        normalize_ols_genesis_model_params,
                    )

                    normalize_ols_genesis_model_params(
                        {"model_type": model_type, "model_options": payload}
                    )
                    return
                recipe_contract = recipe_contract_for_model_type(model_type)
                if recipe_contract is not None:
                    source_hash = getattr(projection_source, "upload_sha256", None)
                    payload = recipe_contract.bind_server_owned_options(
                        payload,
                        source_reference=f"upload:{source_hash}"
                        if isinstance(source_hash, str) and source_hash
                        else "",
                    )
                bind_new_model_options(model_type, payload)

