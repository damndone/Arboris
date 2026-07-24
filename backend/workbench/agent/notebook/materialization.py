"""Turn a selected, evidence-backed Notebook Option into a Pipeline Draft."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Mapping, TYPE_CHECKING
from uuid import uuid4

from ...canonical import sha256_canonical
from ...contracts.agent.notebook_option import NotebookOptionRevisionV11, OptionMaterialization
from ...engine.capabilities import COVARIANCE_UI, build_capabilities
from ...lineage.pipeline_drafts import PipelineDraftStore, StoredDraft
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
from .errors import (
    OptionLifecycleTransitionInvalid,
    OptionMaterializationFailed,
    OptionRevisionStale,
)
from .freshness import assert_executable

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
    ) -> MaterializationResult:
        notebook = self.service.get_notebook(notebook_id)
        view = self.service.store.read_option(notebook_id, option_id)
        current = view.current_revision
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
            draft = PipelineDraftStore(self.service.project_root).get(existing.draft_id)
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
        source = notebook.projection_source
        try:
            if source is not None and source.kind == "run":
                draft = self._materialize_run(
                    notebook,
                    proposal.to_dict(),
                    provenance,
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

        materialization = OptionMaterialization(
            materialization_id=f"mat_{uuid4().hex}",
            option_id=option_id,
            option_revision=current.option_revision,
            proposal_id=current.typed_proposal_id,
            proposal_revision=current.typed_proposal_revision,
            freshness_dependency_fingerprint=current.freshness_dependency_fingerprint,
            generation_context_id=current.generation_context_id,
            draft_id=draft.draft["draft_id"],
            draft_hash=draft.draft_hash,
            draft_execution_mode=mode,
            run_family_id=notebook.run_family_id,
            **pins,
        )
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
            trace.emit(
                "option.lifecycle.changed",
                payload={
                    "option_id": option_id,
                    "option_revision": current.option_revision,
                    "from_status": "selected",
                    "to_status": "materialized",
                    "axis": "lifecycle",
                    "reason": "draft_materialized",
                },
            )
        return MaterializationResult(materialization, draft)

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
        if source.kind == "run" and proposal.operation_id != "model.rerun":
            raise _fail("run projections require a model.rerun proposal")
        if source.kind == "dataset" and proposal.operation_id != "model.genesis":
            raise _fail("dataset projections require a model.genesis proposal")

    def _materialize_run(
        self,
        notebook: Any,
        proposal: Mapping[str, Any],
        provenance: Mapping[str, str],
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

    def _materialize_dataset(
        self,
        notebook: Any,
        proposal: Mapping[str, Any],
        provenance: Mapping[str, str],
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
        allowed_model = {
            "model_type",
            "y",
            "x",
            "focal_x",
            "covariance",
            "model_options",
        }
        if set(model_params) - allowed_model:
            raise _fail("genesis materialization received unknown model params")
        model_type = model_params.get("model_type")
        if not isinstance(model_type, str) or not model_type:
            raise _fail("genesis model_params requires model_type")
        known = {str(entry["key"]) for entry in build_capabilities().get("model_types", [])}
        if model_type not in known or model_type == "auto":
            raise _fail("genesis model_type is not a registered executable capability")
        try:
            model_params = normalize_ols_genesis_model_params(model_params)
        except ValueError as exc:
            raise _fail(str(exc)) from exc
        y = model_params.get("y")
        if not isinstance(y, str) or not y:
            raise _fail("genesis model_params requires evidence-backed y")
        if y not in columns:
            raise _fail("genesis y is not a column in the verified dataset", column=y)
        if model_type != "time_series.arma_garch":
            x = model_params.get("x")
            if (
                not isinstance(x, list)
                or not x
                or any(not isinstance(item, str) or not item for item in x)
            ):
                raise _fail("genesis model_params requires non-empty evidence-backed x")
            missing_x = sorted(set(x) - set(columns))
            if missing_x:
                raise _fail(
                    "genesis x contains columns absent from the verified dataset",
                    columns=missing_x,
                )
        if "covariance" in model_params:
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
        draft = create_genesis_draft(
            self.service.project_root,
            upload_sha256=source.upload_sha256 or "",
            filename=source.filename or "dataset.csv",
            sheet_names=tuple(source.sheet_names),
            columns=columns,
            notebook_provenance=provenance,
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


__all__ = ["MaterializationResult", "NotebookOptionMaterializer"]
