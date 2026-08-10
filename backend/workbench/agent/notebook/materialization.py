"""Turn a selected, evidence-backed Notebook Option into a Pipeline Draft."""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, TYPE_CHECKING
from uuid import uuid4

import pandas as pd

from ...canonical import sha256_canonical
from ...contracts.agent.notebook_option import (
    NotebookOptionRevisionV11,
    OptionMaterialization,
    OptionMaterializationV11,
)
from ...engine.capabilities import COVARIANCE_UI, build_capabilities
from ...lineage.pipeline_drafts import PipelineDraftStore, StoredDraft, schema_hash
from ...lineage.upload_store import verify_upload
from ...model_options import (
    ModelOptionsError,
    bind_new_model_options,
)
from ...services.draft_materialization import (
    create_genesis_draft,
    create_rerun_draft_from_node,
    normalize_ols_genesis_model_params,
)
from ..context_compiler import NotebookPlanningContextV1
from ..trace import TraceWriter
from ..workflow_contracts import (
    MODEL_FAMILY_SPEC_FIELDS,
    OperationValidationError,
    family_context_columns,
    model_family_contract,
    validate_model_genesis_spec,
)
from ..recipe_contracts import (
    RecipeValidationError,
    recipe_contract_for_model_type,
)
from .errors import (
    OptionLifecycleTransitionInvalid,
    OptionMaterializationFailed,
    OptionRevisionStale,
)
from .freshness import assert_executable
from .evidence import MAX_SOURCE_ROWS

if TYPE_CHECKING:
    from .service import NotebookService


@dataclass(frozen=True)
class MaterializationResult:
    materialization: OptionMaterialization
    draft: StoredDraft

    def to_dict(self) -> dict[str, Any]:
        return {
            "materialization": self.materialization.to_dict(),
            "draft": self.draft.draft,
            "draft_hash": self.draft.draft_hash,
        }


def _fail(message: str, **details: Any) -> OptionMaterializationFailed:
    return OptionMaterializationFailed(message, **details)


class NotebookOptionMaterializer:
    """Own the fail-closed boundary between Option and Draft."""

    def __init__(self, service: "NotebookService") -> None:
        self.service = service

    def materialize(
        self,
        notebook_id: str,
        option_id: str,
        *,
        context: NotebookPlanningContextV1,
        trace: TraceWriter | None = None,
        materialization_id: str | None = None,
        draft_id: str | None = None,
    ) -> MaterializationResult:
        notebook = self.service.get_notebook(notebook_id)
        view = self.service.store.read_option(notebook_id, option_id)
        current = view.current_revision
        self.service._assert_current_memory_default_sources(view, context)
        binding_ref = getattr(current, "capability_resolution_binding_ref", None)
        if binding_ref is not None:
            self.service._assert_current_capability_binding(current)
        if not isinstance(current, NotebookOptionRevisionV11):
            self.service.assert_materializable(notebook_id, option_id)
        if view.lifecycle_status not in {"selected", "materialized", "executed"}:
            raise OptionLifecycleTransitionInvalid(
                f"option {option_id} is {view.lifecycle_status}; materialization requires selected",
                option_id=option_id,
                lifecycle_status=view.lifecycle_status,
            )

        existing = self.service.store.read_materialization(
            notebook_id, option_id, current.option_revision
        )
        if existing is not None:
            if (
                materialization_id is not None
                and materialization_id != existing.materialization_id
            ):
                raise _fail(
                    "the requested materialization id conflicts with the persisted materialization",
                    option_id=option_id,
                    reason="MATERIALIZATION_ID_CONFLICT",
                )
            if draft_id is not None and draft_id != existing.draft_id:
                raise _fail(
                    "the requested draft id conflicts with the persisted materialization",
                    option_id=option_id,
                    reason="DRAFT_ID_CONFLICT",
                )
            draft = PipelineDraftStore(self.service.project_root).get(existing.draft_id)
            self._validate_binding_provenance(current, existing, draft)
            return MaterializationResult(existing, draft)
        if view.lifecycle_status == "executed":
            raise _fail("an executed option cannot be materialized again", option_id=option_id)

        assert_executable(current, context)
        decision = self.service.store.read_decision(notebook_id, current.batch_id)
        if decision is None or decision.recommendation_decision_id != current.recommendation_decision_id:
            raise _fail(
                "the option's recommendation decision is missing or does not match",
                option_id=option_id,
                option_revision=current.option_revision,
            )
        if decision.generation_context_hash != current.generation_context_hash:
            raise OptionRevisionStale(
                f"option {option_id} recommendation context no longer matches its revision",
                option_id=option_id,
                requested_revision=current.option_revision,
                current_revision=current.option_revision,
                reason="recommendation_context_mismatch",
            )
        self._validate_evidence_pins(notebook_id, current, decision)
        proposal = view.current_stored_revision.proposal
        self._validate_proposal(current, proposal, notebook.projection_source)

        provenance = {
            "notebook_id": notebook_id,
            "option_id": option_id,
            "option_revision": str(current.option_revision),
            "recommendation_decision_id": current.recommendation_decision_id,
            # The Draft is the durable handoff between Notebook and the run
            # dispatcher.  Carry the immutable line identity through that
            # handoff so a Genesis run is born in the Notebook's family.
            "run_family_id": notebook.run_family_id,
        }
        if binding_ref is not None:
            provenance["capability_resolution_binding_ref"] = binding_ref
        source = notebook.projection_source
        try:
            if source is not None and source.kind == "run":
                draft = self._materialize_run(
                    notebook,
                    proposal.to_dict(),
                    provenance,
                    draft_id=draft_id,
                )
                mode = "rerun_child"
                pins = {
                    "source_run_id": proposal.target["run_id"],
                    "source_model_node_id": proposal.target["node_ref"],
                    "source_op_node_id": proposal.target["node_ref"],
                    "source_node_hash": proposal.target["node_hash"],
                    "source_forest_node_key": proposal.target["forest_node_key"],
                    "source_context_fingerprint": proposal.preconditions["context_fingerprint"],
                    "dataset_upload_sha256": None,
                }
            elif source is not None and source.kind == "dataset":
                draft = self._materialize_dataset(
                    notebook,
                    proposal.to_dict(),
                    provenance,
                    draft_id=draft_id,
                )
                mode = "genesis"
                pins = {
                    "source_run_id": None,
                    "source_model_node_id": None,
                    "source_op_node_id": None,
                    "source_node_hash": None,
                    "source_forest_node_key": None,
                    "source_context_fingerprint": None,
                    "dataset_upload_sha256": source.upload_sha256,
                }
            else:
                raise _fail("a source-bound projection is required", option_id=option_id)
        except OptionMaterializationFailed:
            raise
        except (OSError, ValueError, KeyError, ModelOptionsError, TypeError) as exc:
            raise _fail(
                "the selected Option could not produce a valid Pipeline Draft",
                option_id=option_id,
                reason=str(exc),
            ) from exc

        materialization_kwargs: dict[str, Any] = {
            "materialization_id": (
                f"mat_{uuid4().hex}"
                if materialization_id is None
                else materialization_id
            ),
            "option_id": option_id,
            "option_revision": current.option_revision,
            "proposal_id": current.typed_proposal_id,
            "proposal_revision": current.typed_proposal_revision,
            "freshness_dependency_fingerprint": current.freshness_dependency_fingerprint,
            "generation_context_id": current.generation_context_id,
            "draft_id": draft.draft["draft_id"],
            "draft_hash": draft.draft_hash,
            "draft_execution_mode": mode,
            "run_family_id": notebook.run_family_id,
            **pins,
        }
        if binding_ref is not None:
            materialization_kwargs["capability_resolution_binding_ref"] = binding_ref
            materialization = OptionMaterializationV11(**materialization_kwargs)
        else:
            materialization = OptionMaterialization(**materialization_kwargs)
        self._validate_binding_provenance(current, materialization, draft)
        self.service.store.append_materialization(notebook_id, materialization)
        if view.lifecycle_status == "selected":
            self.service._transition(
                notebook_id,
                view,
                to_status="materialized",
                actor="agent",
                reason="draft_materialized",
                trace=trace,
            )
        if trace is not None:
            lifecycle_payload = {
                "option_id": option_id,
                "option_revision": current.option_revision,
                "from_status": "selected",
                "to_status": "materialized",
                "axis": "lifecycle",
                "reason": "draft_materialized",
            }
            if binding_ref is not None:
                lifecycle_payload["capability_resolution_binding_ref"] = binding_ref
            trace.emit(
                "option.lifecycle.changed",
                payload=lifecycle_payload,
            )
        return MaterializationResult(materialization, draft)

    def _validate_binding_provenance(
        self,
        revision: Any,
        materialization: OptionMaterialization,
        draft: StoredDraft,
    ) -> None:
        """Require one binding identity across Option, Materialization, Draft."""

        expected = getattr(revision, "capability_resolution_binding_ref", None)
        materialization_ref = getattr(
            materialization, "capability_resolution_binding_ref", None
        )
        draft_provenance = draft.draft.get("notebook_provenance") or {}
        draft_ref = draft_provenance.get("capability_resolution_binding_ref")
        if expected is None:
            if materialization_ref is not None or draft_ref is not None:
                raise _fail(
                    "an unbound option cannot carry capability binding provenance",
                    option_id=revision.option_id,
                    reason="CAPABILITY_BINDING_PROVENANCE_UNEXPECTED",
                )
            return
        if materialization_ref != expected or draft_ref != expected:
            raise OptionRevisionStale(
                "capability binding provenance does not match the current option",
                option_id=revision.option_id,
                option_revision=revision.option_revision,
                reason="capability_binding_provenance_mismatch",
            )

    def _validate_evidence_pins(
        self,
        notebook_id: str,
        revision: NotebookOptionRevisionV11,
        decision: Any,
    ) -> None:
        packs = []
        for pack_hash in decision.evidence_pack_hashes:
            pack = self.service.store.read_evidence_pack(notebook_id, pack_hash)
            if pack is None:
                raise _fail(
                    "a recommendation evidence pack is missing",
                    option_id=revision.option_id,
                    evidence_pack_hash=pack_hash,
                )
            packs.append(pack)
        records = {
            record.get("evidence_id"): record
            for pack in packs
            for record in pack.get("records", [])
            if isinstance(record, Mapping)
        }
        for reference in revision.evidence_refs:
            record = records.get(reference.evidence_id)
            if not isinstance(record, Mapping) or record.get("result_hash") != reference.result_hash:
                raise _fail(
                    "an option evidence ref is not present in its persisted pack",
                    option_id=revision.option_id,
                    evidence_id=reference.evidence_id,
                )

    def _validate_proposal(
        self,
        revision: NotebookOptionRevisionV11,
        proposal: Any,
        source: Any,
    ) -> None:
        definition = self.service.registry.require(
            proposal.operation_id, proposal.operation_version
        )
        try:
            definition.validate(
                target=proposal.target,
                preconditions=proposal.preconditions,
                changes=proposal.changes,
            )
        except Exception as exc:
            raise _fail("the persisted typed proposal is no longer valid", reason=str(exc)) from exc
        if source is None:
            raise _fail("projection source is missing")
        if source.kind == "run" and proposal.operation_id not in {
            "model.rerun",
            "model.custom",
        }:
            raise _fail("run projections require a model.rerun or model.custom proposal")
        if source.kind == "dataset" and proposal.operation_id not in {
            "model.genesis",
            "model.custom",
        }:
            raise _fail("dataset projections require a model.genesis or model.custom proposal")

    def _materialize_run(
        self,
        notebook: Any,
        proposal: Mapping[str, Any],
        provenance: Mapping[str, str],
        *,
        draft_id: str | None = None,
    ) -> StoredDraft:
        if proposal["target"]["run_id"] != notebook.active_head_run_id:
            raise OptionRevisionStale(
                "the rerun proposal is not pinned to the Notebook active head",
                option_id=provenance["option_id"],
                requested_revision=int(provenance["option_revision"]),
                current_revision=int(provenance["option_revision"]),
                reason="rerun_target_not_active_head",
            )
        changes = proposal.get("changes") or {}
        if proposal.get("operation_id") == "model.custom":
            return self._materialize_custom_run(
                notebook,
                proposal,
                provenance,
                draft_id=draft_id,
            )
        if set(changes) - {"model_options"}:
            raise _fail("run materialization only accepts model_options changes")
        model = None
        store = PipelineDraftStore(self.service.project_root)
        # The operation registry intentionally exposes one provider-neutral
        # ``model_options`` envelope.  Drafts are narrower: only a source model
        # whose published editable schema declares that envelope can carry a
        # non-empty patch.  Check that semantic seam before creating the Draft;
        # otherwise a provider proposal reaches ``update_params`` as
        # NON_EDITABLE_PARAM and leaves an orphan file behind.
        if changes.get("model_options"):
            source_draft = create_rerun_draft_from_node(
                self.service.project_root,
                source_run_id=proposal["target"]["run_id"],
                source_model_node_id=proposal["target"]["node_ref"],
                source_op_node_id=proposal["target"]["node_ref"],
                source_node_hash=proposal["target"]["node_hash"],
                source_forest_node_key=proposal["target"]["forest_node_key"],
                source_context_fingerprint=proposal["preconditions"]["context_fingerprint"],
                notebook_provenance=provenance,
                persist=False,
                draft_id=draft_id,
            )
            model = next(
                node
                for node in source_draft.draft["graph"]["nodes"]
                if node["node_type"] == "model"
            )
            editable_keys = {
                str(item.get("key"))
                for item in model.get("editable_schema", [])
                if item.get("key")
            }
            if "model_options" not in editable_keys:
                raise _fail(
                    "run model_options patch is not editable for the source model",
                    option_id=provenance["option_id"],
                    reason="NON_EDITABLE_PARAM",
                )
            try:
                from ...lineage.run_inputs import read_run_inputs
                from ...repository.run_repository import _resolve_run_root
                from ...services.run_service import merge_form_overrides

                source_inputs = read_run_inputs(
                    _resolve_run_root(str(self.service.project_root), proposal["target"]["run_id"])
                )
                source_form = source_inputs.get("form") or {}
                merge_form_overrides(
                    source_form,
                    {"model_options": dict(changes["model_options"])},
                )
            except (ModelOptionsError, FileNotFoundError, OSError, TypeError, ValueError) as exc:
                raise _fail(
                    "run model_options patch failed the target model contract",
                    option_id=provenance["option_id"],
                    reason=getattr(exc, "code", str(exc)),
                ) from exc
            draft = store.create(source_draft.draft)
        else:
            draft = create_rerun_draft_from_node(
                self.service.project_root,
                source_run_id=proposal["target"]["run_id"],
                source_model_node_id=proposal["target"]["node_ref"],
                source_op_node_id=proposal["target"]["node_ref"],
                source_node_hash=proposal["target"]["node_hash"],
                source_forest_node_key=proposal["target"]["forest_node_key"],
                source_context_fingerprint=proposal["preconditions"]["context_fingerprint"],
                notebook_provenance=provenance,
                draft_id=draft_id,
            )
        # An empty typed model-options patch is the explicit “retain the
        # verified active model path” option. It must still produce a pinned
        # Draft, but must not be turned into a params update: the existing
        # editable-schema gate correctly rejects a synthetic model_options
        # field for handlers that have no non-empty options yet.
        if not changes.get("model_options"):
            return draft
        model = next(node for node in draft.draft["graph"]["nodes"] if node["node_type"] == "model")
        params = dict(model.get("params") or {})
        params["model_options"] = dict(changes["model_options"])
        try:
            return store.update_params(
                draft.draft["draft_id"],
                model_node_id=model["node_id"],
                base_draft_hash=draft.draft_hash,
                params=params,
            )
        except Exception:
            store.delete(draft.draft["draft_id"])
            raise

    def _materialize_custom_run(
        self,
        notebook: Any,
        proposal: Mapping[str, Any],
        provenance: Mapping[str, str],
        *,
        draft_id: str | None = None,
    ) -> StoredDraft:
        """Create a source-pinned child Draft whose execution stays CF4-owned."""

        source = notebook.projection_source
        current = self.service.store.read_option(
            notebook.notebook_id, provenance["option_id"]
        ).current_revision
        expected_binding_ref = getattr(current, "capability_resolution_binding_ref", None)
        changes = dict(proposal.get("changes") or {})
        if not expected_binding_ref or changes.get("binding_ref") != expected_binding_ref:
            raise OptionRevisionStale(
                "custom capability rerun is not bound to the current resolution",
                option_id=provenance["option_id"],
                option_revision=int(provenance["option_revision"]),
                current_revision=int(provenance["option_revision"]),
                reason="custom_binding_mismatch",
            )
        if self.service.capability_bindings is None:
            raise _fail("custom capability binding catalog is unavailable")
        try:
            capability_id = self.service.capability_bindings.capability_id_for_reference(
                expected_binding_ref,
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                ),
            )
            if capability_id is None:
                raise ValueError("custom capability binding is not registered")
            binding = self.service.capability_bindings.require(
                capability_id,
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                ),
            )
        except Exception as exc:
            raise _fail("custom capability binding is not currently usable") from exc
        if changes.get("capability_ref") != binding.implementation_ref:
            raise _fail("custom capability implementation is not server-bound")
        operation = changes.get("operation")
        if operation not in binding.allowed_operations:
            raise _fail("custom capability operation is not admitted")
        target_node = proposal["target"]["node_ref"]
        input_handle = changes.get("input_handle", target_node)
        if input_handle != target_node:
            raise _fail("custom capability input_handle is not the pinned source node")
        parameters = changes.get("parameters", {})
        encoded = json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > 256 * 1024:
            raise _fail("custom capability parameters exceed the bounded input limit")
        consumers = changes.get("consumer_slots") or ["notebook_option_planner"]
        if not set(consumers) <= set(binding.allowed_consumers):
            raise _fail("custom capability consumer slot is not admitted")
        source_draft = create_rerun_draft_from_node(
            self.service.project_root,
            source_run_id=proposal["target"]["run_id"],
            source_model_node_id=target_node,
            source_op_node_id=target_node,
            source_node_hash=proposal["target"]["node_hash"],
            source_forest_node_key=proposal["target"]["forest_node_key"],
            source_context_fingerprint=proposal["preconditions"]["context_fingerprint"],
            notebook_provenance=provenance,
            persist=False,
            draft_id=draft_id,
        )
        draft = source_draft.draft
        model = next(node for node in draft["graph"]["nodes"] if node["node_type"] == "model")
        model["model_family"] = "custom"
        model["model_type"] = "custom"
        model["editable_schema"] = []
        model["editable_schema_hash"] = schema_hash([])
        model["source_params"] = {}
        model["params"] = {
            "model_type": "custom",
            "capability_ref": binding.implementation_ref,
            "binding_ref": binding.content_digest,
            "operation": operation,
            "input_handle": input_handle,
            "parameters": dict(parameters),
            "consumer_slots": list(consumers),
        }
        if "expected_artifacts" in changes:
            model["params"]["expected_artifacts"] = list(changes["expected_artifacts"])
        draft["default_execution_mode"] = "rerun_child"
        return PipelineDraftStore(self.service.project_root).create(draft)

    def _materialize_dataset(
        self,
        notebook: Any,
        proposal: Mapping[str, Any],
        provenance: Mapping[str, str],
        *,
        draft_id: str | None = None,
    ) -> StoredDraft:
        source = notebook.projection_source
        if proposal["target"]["dataset_source_id"] != source.upload_sha256:
            raise OptionRevisionStale(
                "the genesis proposal is not pinned to the Notebook dataset",
                option_id=provenance["option_id"],
                requested_revision=int(provenance["option_revision"]),
                current_revision=int(provenance["option_revision"]),
                reason="dataset_source_changed",
            )
        if proposal.get("operation_id") == "model.custom":
            return self._materialize_custom_dataset(
                notebook,
                proposal,
                provenance,
                draft_id=draft_id,
            )
        profile = self.service._dataset_header_profile(source)
        columns = tuple(item["name"] for item in profile.get("columns", []) if item.get("name"))
        changes = proposal.get("changes") or {}
        table_params = dict(changes.get("table_params") or {})
        model_params = dict(changes.get("model_params") or {})
        if "model_options" in changes:
            model_params["model_options"] = dict(changes["model_options"])
        allowed_table = {"sheet_name", "transpose"}
        if set(table_params) - allowed_table:
            raise _fail("genesis materialization received unknown table params")
        base_allowed_model = {
            "model_type",
            "y",
            "x",
            "focal_x",
            "covariance",
            "model_options",
            "entity_col",
            "time_col",
            "cohort_col",
            "treatment_path_col",
        }
        model_type = model_params.get("model_type")
        if not isinstance(model_type, str) or not model_type:
            raise _fail("genesis model_params requires model_type")
        capability_entries = build_capabilities().get("model_types", [])
        known = {str(entry["key"]) for entry in capability_entries}
        if model_type not in known or model_type == "auto":
            raise _fail("genesis model_type is not a registered executable capability")
        capability = next(
            entry for entry in capability_entries if str(entry.get("key")) == model_type
        )
        recipe_contract = recipe_contract_for_model_type(model_type)
        try:
            family_contract = model_family_contract(model_type)
        except OperationValidationError:
            family_contract = None
        if recipe_contract is not None:
            allowed_model = set(recipe_contract.allowed_model_param_fields)
        else:
            allowed_model = base_allowed_model | set(
                family_contract.context_spec_fields if family_contract is not None else ()
            )
        if set(model_params) - allowed_model:
            raise _fail("genesis materialization received unknown model params")
        try:
            model_params = normalize_ols_genesis_model_params(model_params)
        except ValueError as exc:
            raise _fail(str(exc)) from exc
        if recipe_contract is not None:
            try:
                model_params["model_options"] = recipe_contract.bind_server_owned_options(
                    model_params.get("model_options"),
                    source_reference=f"upload:{source.upload_sha256}",
                )
                recipe_contract.validate_genesis_params(model_params, columns=columns)
            except RecipeValidationError as exc:
                raise _fail(str(exc)) from exc
            y: str | None = None
        else:
            y = model_params.get("y")
            if not isinstance(y, str) or not y:
                raise _fail("genesis model_params requires evidence-backed y")
            if y not in columns:
                raise _fail("genesis y is not a column in the verified dataset", column=y)
        declared_dimensions = {
            key: model_params.get(key)
            for key in ("entity_col", "time_col", "cohort_col", "treatment_path_col")
            if model_params.get(key) is not None
        }
        family_builds_native_params = bool(
            family_contract is not None and family_contract.builds_native_params
        )
        if family_builds_native_params:
            accepted_dimensions = set(family_contract.context_spec_fields)
            unexpected_dimensions = sorted(set(declared_dimensions) - accepted_dimensions)
            if unexpected_dimensions:
                raise _fail(
                    f"genesis {model_type} does not accept " + ", ".join(unexpected_dimensions)
                )
            missing_dimensions = [
                field_name
                for field_name in family_contract.required_spec_fields
                if field_name not in declared_dimensions
            ]
            if missing_dimensions:
                raise _fail(
                    family_contract.missing_required_fields_message
                    or f"genesis {model_type} requires family timing fields"
                )
        panel_dimensions = {
            key: value
            for key, value in declared_dimensions.items()
            if key in {"entity_col", "time_col"}
        }
        if model_type == "panel_ols" and not panel_dimensions:
            raise _fail(
                "genesis panel_ols requires an evidence-backed entity_col or time_col"
            )
        if model_type != "panel_ols" and panel_dimensions and not family_builds_native_params:
            raise _fail(
                "genesis non-panel model does not accept entity_col or time_col"
            )
        if not family_builds_native_params and any(
            key in declared_dimensions for key in ("cohort_col", "treatment_path_col")
        ):
            raise _fail("genesis selected model does not accept DID timing fields")
        for field_name, value in declared_dimensions.items():
            if not isinstance(value, str) or not value:
                raise _fail(
                    f"genesis {field_name} must be a non-empty evidence-backed column"
                )
            if value not in columns:
                raise _fail(
                    f"genesis {field_name} is not a column in the verified dataset",
                    column=value,
                )
        # A model takes X regressors only when its published capability declares a
        # required parameter with role "x". Univariate models (ETS, ARMA-GARCH, ...)
        # declare none, so the model-agnostic Notebook must not demand one; keying
        # this to a capability signal keeps every future model working unpatched.
        model_requires_x = (
            recipe_contract.requires_nonempty_predictors
            if recipe_contract is not None
            else family_contract.requires_nonempty_predictors
            if family_contract is not None
            else any(
                isinstance(param, dict)
                and param.get("role") == "x"
                and param.get("required")
                for param in capability.get("params", [])
            )
        )
        x = model_params.get("x", [])
        if not isinstance(x, list) or any(not isinstance(item, str) or not item for item in x):
            raise _fail("genesis x must be an evidence-backed column list")
        if model_requires_x:
            if (
                not x
            ):
                raise _fail("genesis model_params requires non-empty evidence-backed x")
        missing_x = sorted(set(x) - set(columns))
        if missing_x:
            raise _fail(
                "genesis x contains columns absent from the verified dataset",
                columns=missing_x,
            )
        if "covariance" in model_params:
            if family_contract is not None and not family_contract.allows_covariance:
                raise _fail(f"genesis {model_type} does not accept OLS covariance settings")
            allowed_covariance = {str(entry["key"]) for entry in COVARIANCE_UI}
            if model_params["covariance"] not in allowed_covariance:
                raise _fail("genesis covariance is not a registered option")
        if "model_options" in model_params:
            try:
                model_params["model_options"] = bind_new_model_options(
                    model_type, model_params["model_options"]
                ).payload
            except ModelOptionsError as exc:
                raise _fail("genesis model_options failed validation", reason=exc.code) from exc
        if recipe_contract is not None:
            try:
                recipe_contract.validate_input_preflight(
                    model_params,
                    source=self._read_recipe_preflight_source(
                        source, recipe_contract, model_params
                    ),
                )
            except RecipeValidationError as exc:
                raise _fail(str(exc)) from exc
        if family_contract is not None:
            family_spec: dict[str, Any] = {
                "model_family": model_type,
                "branches": [
                    {"branch_id": "notebook", "outcome": y, "predictors": list(x)}
                ],
            }
            for field_name in MODEL_FAMILY_SPEC_FIELDS:
                if field_name in model_params:
                    family_spec[field_name] = model_params[field_name]
            if "covariance" in model_params:
                family_spec["covariance"] = model_params["covariance"]
            try:
                validated_contract = validate_model_genesis_spec(family_spec)
                missing_family_columns = sorted(
                    set(family_context_columns(validated_contract, family_spec)) - set(columns)
                )
            except OperationValidationError as exc:
                raise _fail(str(exc)) from exc
            if missing_family_columns:
                raise _fail(
                    "genesis family fields contain columns absent from the verified dataset",
                    columns=missing_family_columns,
                )
        if family_builds_native_params:
            model_params = family_contract.build_model_params(
                family_spec,
                {"outcome": y, "predictors": x},
                list(x),
                str(model_params.get("covariance", "unadjusted")),
            )
        draft = create_genesis_draft(
            self.service.project_root,
            upload_sha256=source.upload_sha256 or "",
            filename=source.filename or "dataset.csv",
            sheet_names=tuple(source.sheet_names),
            columns=columns,
            model_family=(recipe_contract.model_family if recipe_contract is not None else "regression"),
            notebook_provenance=provenance,
            draft_id=draft_id,
        )
        store = PipelineDraftStore(self.service.project_root)
        try:
            if table_params:
                draft = store.update_node_params(
                    draft.draft["draft_id"], "table_1", table_params
                )
            if model_params:
                draft = store.update_node_params(
                    draft.draft["draft_id"], "model_1", model_params
                )
            return draft
        except Exception:
            store.delete(draft.draft["draft_id"])
            raise

    def _read_recipe_preflight_source(
        self,
        source: Any,
        recipe_contract: Any,
        model_params: Mapping[str, object],
    ) -> pd.DataFrame:
        """Read only a Recipe's declared columns, completely or not at all.

        Evidence inspection can report a truncated sample. Admission cannot:
        a sample cannot prove there are no later duplicate timestamps, gaps, or
        transform-ineligible values.  This keeps the existing bounded source
        policy while rejecting a source that exceeds it instead of inspecting a
        prefix and treating the result as complete.
        """

        upload_sha256 = getattr(source, "upload_sha256", None)
        if not isinstance(upload_sha256, str) or not upload_sha256:
            raise _fail(
                "RECIPE_PREFLIGHT_SOURCE_UNAVAILABLE: the pinned upload identity is missing"
            )
        try:
            path = verify_upload(self.service.project_root, upload_sha256)
            columns = list(dict.fromkeys(recipe_contract.source_columns(model_params)))
            suffix = Path(getattr(source, "filename", "") or "").suffix.lower()
            read_limit = MAX_SOURCE_ROWS + 1
            if suffix == ".csv":
                frame = pd.read_csv(path, usecols=columns, nrows=read_limit)
            elif suffix in {".xlsx", ".xls"}:
                with pd.ExcelFile(path) as workbook:
                    sheet_names = tuple(getattr(source, "sheet_names", ()) or ())
                    sheet = sheet_names[0] if sheet_names else workbook.sheet_names[0]
                    frame = pd.read_excel(
                        workbook,
                        sheet_name=sheet,
                        usecols=columns,
                        nrows=read_limit,
                    )
            else:
                raise ValueError(f"unsupported dataset upload type: {suffix or 'unknown'}")
        except RecipeValidationError:
            raise
        except (ImportError, OSError, TypeError, UnicodeError, ValueError) as exc:
            raise _fail(
                "RECIPE_PREFLIGHT_SOURCE_UNAVAILABLE: the verified source could not be opened"
            ) from exc
        if len(frame) > MAX_SOURCE_ROWS:
            raise _fail(
                "RECIPE_PREFLIGHT_SOURCE_BOUNDED: the complete source exceeds the preflight row limit"
            )
        try:
            verify_upload(self.service.project_root, upload_sha256)
        except (OSError, ValueError) as exc:
            raise _fail(
                "RECIPE_PREFLIGHT_SOURCE_UNAVAILABLE: the verified source changed during preflight"
            ) from exc
        return frame

    def _materialize_custom_dataset(
        self,
        notebook: Any,
        proposal: Mapping[str, Any],
        provenance: Mapping[str, str],
        *,
        draft_id: str | None = None,
    ) -> StoredDraft:
        """Create a provenance-only Draft for the authorized custom gateway."""

        source = notebook.projection_source
        if source is None or source.kind != "dataset":
            raise _fail("custom capability materialization requires a dataset source")
        current = self.service.store.read_option(
            notebook.notebook_id, provenance["option_id"]
        ).current_revision
        expected_binding_ref = getattr(current, "capability_resolution_binding_ref", None)
        changes = dict(proposal.get("changes") or {})
        if not expected_binding_ref or changes.get("binding_ref") != expected_binding_ref:
            raise OptionRevisionStale(
                "custom capability materialization is not bound to the current resolution",
                option_id=provenance["option_id"],
                option_revision=int(provenance["option_revision"]),
                current_revision=int(provenance["option_revision"]),
                reason="custom_binding_mismatch",
            )
        if self.service.capability_bindings is None:
            raise _fail("custom capability binding catalog is unavailable")
        try:
            capability_id = self.service.capability_bindings.capability_id_for_reference(
                expected_binding_ref,
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                ),
            )
            if capability_id is None:
                raise ValueError("custom capability binding is not registered")
            binding = self.service.capability_bindings.require(
                capability_id,
                scope_candidates=(
                    ("project", notebook.project_id),
                    ("run_family", notebook.run_family_id),
                ),
            )
        except Exception as exc:
            raise _fail("custom capability binding is not currently usable") from exc
        if changes.get("capability_ref") != binding.implementation_ref:
            raise _fail("custom capability implementation is not server-bound")
        operation = changes.get("operation")
        if operation not in binding.allowed_operations:
            raise _fail("custom capability operation is not admitted")
        input_handle = changes.get("input_handle", "table_1")
        if input_handle != "table_1":
            raise _fail("custom capability input_handle is not a verified dataset handle")
        parameters = changes.get("parameters", {})
        encoded = json.dumps(
            parameters,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
            allow_nan=False,
        ).encode("utf-8")
        if len(encoded) > 256 * 1024:
            raise _fail("custom capability parameters exceed the bounded input limit")
        consumers = changes.get("consumer_slots") or ["notebook_option_planner"]
        if not set(consumers) <= set(binding.allowed_consumers):
            raise _fail("custom capability consumer slot is not admitted")
        profile = self.service._dataset_header_profile(source)
        columns = tuple(item["name"] for item in profile.get("columns", []) if item.get("name"))
        model_params: dict[str, Any] = {
            "model_type": "custom",
            "capability_ref": binding.implementation_ref,
            "binding_ref": binding.content_digest,
            "operation": operation,
            "input_handle": input_handle,
            "parameters": dict(parameters),
            "consumer_slots": list(consumers),
        }
        if "expected_artifacts" in changes:
            model_params["expected_artifacts"] = list(changes["expected_artifacts"])
        try:
            return create_genesis_draft(
                self.service.project_root,
                upload_sha256=source.upload_sha256 or "",
                filename=source.filename or "dataset.csv",
                sheet_names=tuple(source.sheet_names),
                columns=columns,
                model_family="custom",
                model_params=model_params,
                notebook_provenance=provenance,
                draft_id=draft_id,
            )
        except (OSError, ValueError, KeyError, TypeError) as exc:
            raise _fail(
                "the custom capability could not produce a valid provenance Draft",
                reason=str(exc),
            ) from exc


__all__ = ["MaterializationResult", "NotebookOptionMaterializer"]
