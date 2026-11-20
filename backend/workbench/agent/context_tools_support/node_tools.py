"""Node tools: bounded read-only context projection."""

from __future__ import annotations
from pathlib import Path
from collections.abc import Mapping
from typing import Any
from ...artifacts import read_json
from ...contracts.common.envelope import ContractError
from ..chains import ChainHeadConflict, ChainStore
from ..context_compiler import (
    has_context_artifact_index,
    read_completion_artifact,
    read_context_artifact_index,
    read_context_run_manifest,
)
from ...diagnostic_preview import build_diagnostic_summary_preview
from ...diagnostic_preview.artifact_manifest import build_artifact_manifest
from ...graph_store import GraphStore, graph_to_json
from ...lineage.node_write_validation import _read_indexed_node_hash, build_rerun_operation_context
from ...lineage.op_contract import resolve_operation_contract
from ...lineage.run_inputs import read_run_inputs
from ...services.results_service import read_model_results
from ...estimation_engine import engine_provenance
from ...analysis_loop.time_series_compare import read_time_series_artifacts as _read_time_series_artifacts
from ..operations import OperationRegistry
from ..recipes.registry import build_option_vocabulary, validate_model_options_patch
from ..tools import ToolVisibleError
from .coefficients import (
    _lmm_published_results,
)
from .figures import (
    _bounded_run_figure_evidence,
)
from .requests import (
    InspectArtifactPreviewRequest,
    InspectDiagnosticsRequest,
    InspectNodeContextRequest,
    InspectOperationContractRequest,
    InspectResultSummaryRequest,
    OperationContractUnavailableError,
    _PROJECT_RUN_ID_RE,
)
from .summaries import (
    _analysis_contract_from_run_inputs,
    _bounded_artifact_manifest,
    _bounded_diagnostics,
    _bounded_node,
    _bounded_result_summary,
    _bounded_statistics_evidence,
    _executed_covariance,
    _node_public_result_evidence,
    _read_diagnostic_summary,
    _read_manifest,
)



class NodeToolsMixin:
    def __init__(self, project_root: Path | str) -> None:
        self.project_root = Path(project_root).resolve()

    def _tool_node_id(self, arguments: Mapping[str, Any]) -> str:
        """A run's node id, also when given as the forest key `<node hash>::<node id>`.

        The project context lists nodes by forest key; the tools take the run's node id.
        A key whose hash is not that node's hash in the owner run is passed on unchanged,
        so validation still refuses it and lists the run's node ids.
        """
        raw = str(arguments["op_node_id"])
        node_hash, separator, node_id = raw.partition("::")
        owner = str(arguments.get("owner_run_id") or "")
        if not separator or not _PROJECT_RUN_ID_RE.fullmatch(owner):
            return raw
        try:
            if _read_indexed_node_hash(self.project_root / "runs" / owner, node_id) == node_hash:
                return node_id
        except ValueError:
            pass
        return raw

    def _tool_active_head(self, chain_id: str, requested: str, owner_run_id: Any = None) -> str:
        """Use the durable head when this tool belongs to a managed Chain.

        Legacy read-only sessions have no ChainStore record yet and retain the
        existing selected-run behavior. Mutation canonicalization and HTTP
        confirmation require a managed record before they can proceed.
        """

        if Path(chain_id).name != chain_id:
            # A project-wide conversation ("project:<root>") has no Chain record to hold a head.
            return requested
        try:
            return ChainStore(
                self.project_root / "workbench", create=False
            ).resolve_active_head(
                chain_id,
                requested_active_head_run_id=requested,
            )
        except KeyError:
            return requested
        except ChainHeadConflict as exc:
            # Told to the Agent: surfaced only as its class name, it kept passing a
            # model's own branch run as the head (paid fix4 round, panel, Ask: 8
            # refused reads and three nudges). The head is this conversation's own.
            from ..tools import ToolVisibleError, tool_note
            head = ChainStore(self.project_root / "workbench", create=False).resolve_active_head(chain_id)
            if owner_run_id == requested and self._derives_from(requested, head):
                # A read of that run, with the run also passed as the head: what the
                # refusal below asks for. Read tools change nothing, so do it.
                tool_note(f"active_head_run_id is this conversation's head {head}; read run {requested} "
                          "as owner_run_id under it.")
                return head
            raise ToolVisibleError(
                f"ACTIVE_HEAD_MISMATCH: active_head_run_id must be this conversation's current head {head}, "
                f"not {requested}. To read a result in another run (for example a model's branch run), pass "
                f"that run as owner_run_id and keep active_head_run_id {head}."
            ) from exc

    def _derives_from(self, run_id: str, head: str, *, limit: int = 20) -> bool:
        """Whether ``run_id`` is ``head`` or was derived from it (dataset_source chain)."""
        current = run_id
        for _ in range(limit):
            if current == head:
                return True
            try:
                manifest = read_context_run_manifest(self.project_root / "runs" / current)
            except (OSError, ValueError):
                return False
            current = ((manifest.get("dataset_source") or {}).get("source_run_id")) if isinstance(manifest, dict) else None
            if not isinstance(current, str) or not current:
                return False
        return False

    def inspect_node_context(
        self,
        request: InspectNodeContextRequest,
    ) -> dict[str, Any]:
        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        return {
            **canonical,
            "node": _bounded_node(node),
            **({"covariance_executed": _executed_covariance(
                self.project_root / "runs" / request.owner_run_id,
                request.op_node_id.removeprefix("model:"),
            )} if node.get("stage") == "model" and request.op_node_id.startswith("model:") else {}),
            "run": {
                "run_id": request.owner_run_id,
                "status": manifest.get("status"),
                "started_at": manifest.get("started_at")
                or manifest.get("created_at"),
            },
        }

    def inspect_operation_contract(
        self,
        request: InspectOperationContractRequest,
        *,
        operation_registry: OperationRegistry,
    ) -> dict[str, Any]:
        """Return the registry identity plus the lineage-owned node contract."""

        operation = operation_registry.require(
            request.operation_id,
            request.operation_version,
        )
        # Registry definitions also exist for workflow children so the
        # dispatcher can validate and execute them. They are not independent
        # Agent proposal surfaces: inspecting one against a model node would
        # otherwise (incorrectly) return that node's OLS/Rerun contract.
        # Return a bounded correction that preserves the parent workflow's
        # one-confirmation authorization boundary.
        from ..workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS

        if (
            request.operation_id in WORKFLOW_STEP_SPEC_CONTRACTS
            and not operation.natural_language_enabled
        ):
            raise OperationContractUnavailableError(
                f"{request.operation_id}@{request.operation_version} is a workflow step, "
                "not a top-level proposal contract. Inspect operation.multi_step@v1 "
                "and declare this step in changes.steps."
            )
        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        if operation.contract_owner == "operation_registry" and operation.editable_schema:
            # The operation does not act on one node's editable surface, so no
            # lineage pack can answer for it — this definition is the contract.
            # Without this an Agent asked to compose a workflow could not read
            # the shape of the very operation it was told to propose, and spent
            # its whole step budget guessing.
            contract_payload = {
                "op_type": operation.operation_id,
                "schema_id": f"{operation.operation_id}@{operation.operation_version}",
                "editable_schema": operation.editable_schema,
                "contract_owner": "operation_registry",
            }
            if operation.vocabulary_builder is not None:
                contract_payload["step_vocabulary"] = _step_vocabulary_view(
                    operation.vocabulary_builder(), request.step_operation_ids
                )
        else:
            contract = resolve_operation_contract(stage=node.get("stage"), manifest=manifest)
            if contract is not None:
                contract_payload = {
                    "op_type": contract.op_type,
                    "schema_id": contract.schema_id,
                    "editable_schema": contract.editable_schema,
                }
                if request.operation_id == "model.rerun":
                    contract_payload.update(_rerun_contract_view(contract.editable_schema, operation))
                    contract_payload["option_vocabulary_family"] = contract.op_type
                # A pack whose whole option surface is a single `model_options` JSON
                # control tells the Agent nothing about what may go inside it. Where
                # the pack publishes a vocabulary, attach it so a proposal can be
                # written against real field names, closed value sets, and server
                # caps instead of guesses.
                vocabulary = build_option_vocabulary(contract.op_type)
                if vocabulary is not None:
                    contract_payload["option_vocabulary"] = vocabulary
            elif "data_node" in operation.scope_requirements and operation.editable_schema:
                # Data operations have no per-node lineage contract: `resolve_
                # operation_contract` answers for model nodes only, and a cast's
                # editable shape is identical on every dataset node. The registry is
                # the contract owner here, so say so rather than raising — an Agent
                # allowed to propose an operation must be able to read its contract.
                #
                # Narrow on purpose: model.rerun's registry schema is a permissive
                # `additionalProperties` passthrough, so falling back to it when the
                # lineage contract is missing would claim "anything goes", which is
                # worse than failing closed.
                contract_payload = {
                    "op_type": operation.operation_id,
                    "schema_id": f"{operation.operation_id}@{operation.operation_version}",
                    "editable_schema": operation.editable_schema,
                    "contract_owner": "operation_registry",
                }
            else:
                # Step-5 asked for model.rerun's contract on stage:cleaned and read only
                # "no contract", twice (free-route round, 2026-10-23); say where it applies.
                from ...services.rerun_service import editable_rerun_nodes
                try:
                    editable = editable_rerun_nodes(self.project_root, request.owner_run_id)
                except Exception:
                    editable = []
                where = (f" It edits a model node; in run {request.owner_run_id} pass op_node_id "
                         + " or ".join(editable) + ".") if editable else ""
                raise OperationContractUnavailableError(
                    f"no contract for {request.operation_id}@{request.operation_version} on "
                    f"{request.op_node_id} ({node.get('stage')}).{where}"
                )

        return {
            **canonical,
            "target_type": node.get("stage"),
            "operation": {
                "operation_id": operation.operation_id,
                "operation_version": operation.operation_version,
                "effect_level": operation.effect_level,
                "scope_requirements": list(operation.scope_requirements),
            },
            "contract": contract_payload,
            "node": _bounded_node(node),
        }

    def precheck_model_options_patch(
        self,
        *,
        owner_run_id: str,
        patch: dict[str, Any],
        model_type: str | None = None,
    ) -> None:
        """Raise the owning pack's structured error if the patch cannot execute.

        ``model_type`` is the proposal's own model_type change, applied with
        the patch exactly as the rerun service will apply it.

        Silent when the node's pack declares no validator, or when the node's
        current contract cannot be resolved — refusing a patch on the basis of
        evidence we do not have would be worse than letting execution judge it.
        """

        run_root = self.project_root / "runs" / owner_run_id
        try:
            run_inputs = read_run_inputs(run_root)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            run_inputs = {}
        try:
            manifest = read_context_run_manifest(run_root)
        except (FileNotFoundError, OSError, TypeError, ValueError):
            manifest = {}
        if not isinstance(manifest, dict):
            manifest = {}
        contract = resolve_operation_contract(stage="model", manifest=manifest)
        if contract is not None:
            artifacts, _metadata = _read_time_series_artifacts(run_root)
            current = artifacts.get("ts.analysis_contract")
            if not isinstance(current, dict):
                current = _analysis_contract_from_run_inputs(run_inputs)
            if isinstance(current, dict):
                # A server-persisted analysis contract is more authoritative
                # than a legacy form's model_type.  This matters for reruns
                # whose historical form predates the selected model pack.
                validate_model_options_patch(
                    contract.op_type,
                    current_contract=current,
                    patch=patch,
                )
                return

        source_form = run_inputs.get("form") if isinstance(run_inputs, dict) else None
        if not isinstance(source_form, dict):
            return
        from ...model_options import ModelOptionsError
        from ...services.run_service import merge_form_overrides

        try:
            # This is the same pure merge/bind path the rerun service uses
            # before allocating a child run.  It validates any model pack
            # whose current form is the authoritative contract source.
            merge_form_overrides(
                source_form,
                {"model_options": dict(patch), **({"model_type": model_type} if model_type else {})},
            )
        except ModelOptionsError as exc:
            error = ContractError(str(exc))
            error.code = exc.code  # type: ignore[attr-defined]
            raise error from exc

    def inspect_diagnostics(
        self,
        request: InspectDiagnosticsRequest,
    ) -> dict[str, Any]:
        """Return a bounded, read-only view of the existing diagnostic preview."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        persisted = []
        registered = has_context_artifact_index(run_root)
        if registered:
            # The old reader scans every model_results JSON, including potentially
            # large diagnostic row arrays. Use the existing size/SHA-bound reader
            # for this selected model; failed verification is never a legacy read.
            try:
                index = read_context_artifact_index(run_root)
            except (OSError, ValueError) as exc:
                raise ToolVisibleError("DIAGNOSTIC_INDEX_UNAVAILABLE: registered diagnostic index could not be read; no legacy fallback.") from exc
            if not isinstance(index, dict) or not isinstance(index.get("artifacts"), list):
                raise ToolVisibleError("DIAGNOSTIC_INDEX_UNAVAILABLE: registered diagnostic index is malformed; no legacy fallback.")
            entries = index["artifacts"]
            model_id = request.op_node_id.removeprefix("model:")
            # Versioned native packets retain their existing public owner reader;
            # do not introduce the full completion verifier/source-frame reader.
            if any(isinstance(item, dict) and item.get("artifact_type") == "model_result_packet"
                   and item.get("artifact_id") == f"{model_id}.result" for item in entries):
                from ...services.lmm_result_adapter import read_lmm_public_results
                models = read_lmm_public_results(run_root)
                model_sha = None
            else:
                model = read_completion_artifact(run_root, model_id) if request.op_node_id.startswith("model:") else None
                if (model is None or model.artifact_type != "model_result" or not model.payload
                        or model.payload.get("model_id") != model_id):
                    raise ToolVisibleError("DIAGNOSTIC_MODEL_UNAVAILABLE: selected registered model could not be verified within the bounded read limit; no legacy fallback.")
                models, model_sha = [model.payload], model.sha256
            if model_sha:
                for artifact_id, kind in ((f"diagnostics_{model_id}", "model_diagnostic"),
                                          (f"{model_id}.completion", "analysis_completion_evidence")):
                    artifact = read_completion_artifact(run_root, artifact_id)
                    value = {"model_id": model_id, "source": {"run_id": request.owner_run_id, "artifact_id": artifact_id},
                             "status": "unavailable", "reason": "Registered diagnostic exceeds the bounded read limit or could not be verified for this model; use explicit artifact inspection."}
                    payload = artifact.payload if artifact is not None else None
                    if (artifact is not None and artifact.artifact_type == kind and isinstance(payload, dict)
                            and payload.get("model_id") == model_id
                            and (kind != "analysis_completion_evidence" or payload.get("model_payload_sha256") == model_sha)):
                        value.update(status="available", source={**value["source"], "sha256": artifact.sha256},
                                     summary=payload.get("diagnostics", {}) if kind == "analysis_completion_evidence" else payload)
                        value.pop("reason")
                    persisted.append(value)
        else:
            models = read_model_results(run_root)
        preview = build_diagnostic_summary_preview(
            run_root,
            manifest,
            models,
        )
        diagnostics, omitted_sections = _bounded_diagnostics(preview, persisted=persisted)
        if not registered:
            diagnostics["evidence_verification"] = "Legacy preview; no registered artifact index was available for byte verification."
        elif model_sha is None:
            diagnostics["evidence_verification"] = "Native public preview; the added registered-risk projection is not covered. This does not establish an absence of diagnostic risk."
        return {
            **canonical,
            "node": _bounded_node(node),
            "diagnostics": diagnostics,
            "omitted_sections": omitted_sections,
        }

    def inspect_design_advisories(
        self,
        request: InspectResultSummaryRequest,
    ) -> dict[str, Any]:
        """Return what the run assumed but could not verify (v1.8.7 A2/A2b).

        Both artifacts are produced deterministically by the engine and are
        returned verbatim rather than summarised: an Agent re-deriving an
        effective sample size from a rounded design effect would produce a figure
        that reads as authoritative and disagrees with the result panel.
        """
        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id

        def _read(relative: str, key: str) -> list[dict[str, Any]]:
            path = run_root / relative
            if not path.exists():
                return []
            try:
                payload = read_json(path)
            except (OSError, ValueError):
                return []
            entries = payload.get(key) or []
            # Bounded like every other agent-facing projection: a questionnaire
            # can raise a finding per column, and the whole list would crowd out
            # the rest of the context.
            return [dict(entry) for entry in entries[:12]]

        from ...measurement import split_proposable

        # Split rather than one list: an Agent must be able to tell the columns
        # whose value labels evidence a declaration from the ones that merely
        # share a shape with them. Batching the second kind into a proposal is a
        # guess the user cannot see afterwards.
        proposable, uncertain = split_proposable(
            _read("measurement/advisory.json", "entries")
        )
        return {
            **canonical,
            "node": _bounded_node(node),
            "measurement_advisories": proposable,
            "measurement_uncertain": uncertain,
            "design_findings": _read("measurement/design_precheck.json", "findings"),
            "note": (
                "Computed by the engine. Quote these figures rather than deriving "
                "your own, and raise them as questions, not conclusions."
            ),
        }

    def inspect_statistical_evidence(
        self,
        request: InspectResultSummaryRequest,
    ) -> dict[str, Any]:
        """Return only the run's statistical evidence packet.

        The same facts are reachable through inspect_result_summary, but tool
        choice is name-driven in practice: a question about post-hoc tests or
        effect sizes has to meet a tool whose name says so, or the model
        concludes the tests were never run.
        """

        canonical, node, _manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        return {
            **canonical,
            "node": _bounded_node(node),
            "statistical_evidence": _bounded_statistics_evidence(run_root),
        }

    def inspect_result_summary(
        self,
        request: InspectResultSummaryRequest,
    ) -> dict[str, Any]:
        """Return bounded result facts without exposing raw model result payloads."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        model_results = read_model_results(run_root)
        preview = build_diagnostic_summary_preview(run_root, manifest, model_results)
        summary, summary_status = _read_diagnostic_summary(run_root)
        # Include the exact published LMM estimand, beyond the rounded rows.
        comparison_models = [*model_results, *_lmm_published_results(run_root)]
        node_id = node.get("id", "")
        model_id = node_id.removeprefix("model:") if node_id.startswith("model:") else None
        selected = next(
            (result for result in comparison_models if result.get("model_id") == model_id), None,
        ) if model_id is not None else None
        scoped_models = comparison_models
        if model_id is not None:
            scoped_models = [selected] if selected is not None else []
            coefficients = (summary or {}).get("coefficients_summary")
            table_ref = coefficients.get("full_table_ref") if isinstance(coefficients, dict) else None
            # A run narrative may describe a different model. Only old,
            # single-model runs can bind an unlabelled narrative by exclusion.
            selected_summary = selected is not None and (
                table_ref in (f"model_results/{model_id}.json", f"artifacts/model_results/{model_id}.result.json")
                or (table_ref is None and len(comparison_models) == 1)
            )
            if summary is not None and not selected_summary:
                summary = None
                summary_status = "unavailable_for_selected_model"
        result_summary = _bounded_result_summary(
            summary,
            summary_status=summary_status,
            preview=preview,
            model_results=scoped_models,
            comparison_models=comparison_models,
            run_root=run_root,
        )
        if model_id is not None:
            scope = {
                "model_id": model_id,
                "status": "available" if selected is not None else "unavailable",
                "narrative_scope": "selected_model" if selected_summary and summary else "unavailable",
            }
            provenance = engine_provenance(selected) if selected is not None else None
            if provenance is not None:
                result_summary = {"engine_provenance": {"model_id": model_id, **provenance}, **result_summary}
            result_summary = {"model_scope": scope, **result_summary}
        omitted_sections = ["raw_model_results"]
        if result_summary["coefficient_rows_omitted"]:
            omitted_sections.append("coefficient_rows")
        return {
            **canonical,
            "node": _bounded_node(node),
            "result_summary": result_summary,
            "omitted_sections": omitted_sections,
        }

    def inspect_artifact_preview(
        self,
        request: InspectArtifactPreviewRequest,
    ) -> dict[str, Any]:
        """Return bounded artifact availability for the canonical node target."""

        canonical, node, manifest = self._read_node_snapshot(
            request_id=request.request_id,
            owner_run_id=request.owner_run_id,
            op_node_id=request.op_node_id,
            active_head_run_id=request.active_head_run_id,
        )
        run_root = self.project_root / "runs" / request.owner_run_id
        artifact_manifest = _bounded_artifact_manifest(
            build_artifact_manifest(run_root, read_model_results(run_root))
        )
        lifecycle = str(manifest.get("status") or "completed")
        if lifecycle in {"queued", "running"}:
            available = False
            preview_status = "pending"
        elif lifecycle in {"interrupted", "cancelled"}:
            available = False
            preview_status = "lifecycle_unavailable"
        else:
            available = True
            preview_status = "complete"
        counts = {
            "sections": len(artifact_manifest),
            "expected": sum(
                value.get("expected") is True for value in artifact_manifest.values()
            ),
            "available": sum(
                value.get("available") is True for value in artifact_manifest.values()
            ),
        }
        return {
            **canonical,
            "node": _bounded_node(node),
            "artifact_preview": {
                "available": available,
                "preview_status": preview_status,
                "run_lifecycle_status": lifecycle,
                "artifact_counts": counts,
                "artifact_manifest": artifact_manifest,
                "public_result_evidence": _node_public_result_evidence(
                    self.project_root,
                    owner_run_id=request.owner_run_id,
                    op_node_id=request.op_node_id,
                ),
                "figure_evidence": _bounded_run_figure_evidence(
                    self.project_root,
                    run_id=request.owner_run_id,
                    node=node,
                ),
            },
            "omitted_sections": ["raw_artifact_payloads", "raw_rows", "image_pixels"],
        }

    def _read_node_snapshot(
        self,
        *,
        request_id: str,
        owner_run_id: str,
        op_node_id: str,
        active_head_run_id: str,
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
        runs_root = self.project_root / "runs"
        try:
            canonical = build_rerun_operation_context(
                runs_root,
                request_id=request_id,
                owner_run_id=owner_run_id,
                op_node_id=op_node_id,
                active_head_run_id=active_head_run_id,
            )
        except ValueError as exc:
            message = str(exc)
            prefix = message.partition(":")[0]
            if prefix not in {
                "invalid_operation_target",
                "context_stale",
                "context_mismatch",
            }:
                raise
            try:
                valid_ids = sorted(GraphStore(runs_root=runs_root).read(owner_run_id).nodes)
            except Exception:
                valid_ids = []
            targets = ", ".join(valid_ids[:24]) if valid_ids else "none"
            raise ToolVisibleError(
                f"{prefix.upper()}: {message}. Valid node IDs for run "
                f"{owner_run_id}: {targets}."
            ) from exc
        graph = GraphStore(runs_root=runs_root).read(owner_run_id)
        graph_json = graph_to_json(graph)
        node = graph_json["nodes"].get(op_node_id)
        if not isinstance(node, dict):
            valid_ids = ", ".join(sorted(graph_json["nodes"])[:24]) or "none"
            raise ToolVisibleError(
                "INVALID_OPERATION_TARGET: invalid_operation_target: op_node_id. "
                f"Valid node IDs for run {owner_run_id}: {valid_ids}."
            )
        manifest = _read_manifest(runs_root / owner_run_id)
        return canonical.model_dump(), node, manifest

    def _project_run_root(self, run_id: str) -> Path:
        """Resolve a project run identifier without accepting a filesystem path."""

        if not _PROJECT_RUN_ID_RE.fullmatch(run_id):
            raise ToolVisibleError(
                "PROJECT_RUN_ID_INVALID: run_ids must be project run identifiers, not paths."
            )
        runs_root = (self.project_root / "runs").resolve()
        run_root = (runs_root / run_id).resolve()
        if run_root.parent != runs_root or not run_root.is_dir():
            raise ToolVisibleError(
                f"PROJECT_RUN_NOT_FOUND: no completed project run is available for {run_id!r}."
            )
        return run_root



def _rerun_contract_view(editable_schema: list[dict[str, Any]], operation) -> dict[str, Any]:
    """Project manual controls onto the actual Agent patch, without changing either executor."""
    from ...engine.capabilities import build_capabilities
    from ...model_options import ModelOptionsError, _resolve_model_options_handler

    branches = operation.proposal_schema["properties"]["changes"]["oneOf"]
    writable = set(branches[0]["properties"])
    legacy = set(branches[1]["properties"])
    requirements = {}
    for entry in build_capabilities()["model_types"]:
        if entry["key"] == "auto":
            continue
        required = [field["key"] for field in entry.get("params", ()) if field.get("required")]
        try:
            takes_options = getattr(_resolve_model_options_handler(entry["key"]), "validate_model_options", None) is not None
        except ModelOptionsError:
            takes_options = False
        requirements[entry["key"]] = {
            "required_fields": required,
            "not_writable_fields": [field for field in required if field not in writable],
            "takes_model_options": takes_options,
        }
    return {
        "editable_schema": [field for field in editable_schema if field["key"] in writable],
        "analysis_loop_editable_schema": [field for field in editable_schema if field["key"] in legacy],
        "analysis_loop_guidance": (
            "The legacy covariance/entity_col patch is only for the server-bound Analysis Loop and is "
            "never combined with model_type or any other model.rerun field. For normal OLS reruns use the model_options vocabulary."
        ),
        "family_switch_requirements": requirements,
        "family_switch_guidance": (
            "Source form fields are retained except model_options, which is owned by the target family; "
            "switching a source with nonempty options requires an explicit target-owned replacement. "
            "Required fields must be present in the retained source or be writable in this patch. "
            "To set new bindings outside this patch, inspect_operation_contract with "
            "operation_id=operation.multi_step and step_operation_ids=[model.genesis], "
            "then put the new specification in changes.steps[].spec. "
            "Do not put family binding fields into model_options. option_vocabulary describes the source "
            "family (option_vocabulary_family); a target family whose takes_model_options is false accepts "
            "none, so omit model_options when switching to it."
        ),
    }


#: Implementation identities in a step specification that tell a model nothing
#: about how to write the step.
_INTERNAL_STEP_KEYS = frozenset({
    "semantic_validator_key", "reference_resolver_key", "column_extractor_key", "dispatcher_key",
    "reconciler_key", "diff_builder_key", "verification_builder_key", "output_schema_ref", "scope",
    "effect_level", "scope_requirements", "confirmation_policy", "risk_class", "risk_level",
    "replayable_by_recipe", "capability_kind", "natural_language_enabled",
})


def _step_vocabulary_view(vocabulary: dict[str, Any], requested: tuple[str, ...]) -> dict[str, Any]:
    """The step vocabulary, sized to what the Agent asked for.

    Without ``requested``: every step as one line (summary and required
    fields), so all of them stay discoverable. With it: those steps' full
    specifications, minus implementation identities. Unknown ids are named
    so the Agent can correct them instead of guessing.
    """

    steps = vocabulary.get("step_operations") or {}
    shared = {key: value for key, value in vocabulary.items() if key != "step_operations"}
    if not requested:
        return {
            **shared,
            # "id: first sentence of the summary [required fields]" keeps the
            # whole catalogue discoverable in about a tenth of the full size.
            "step_index": [
                f"{operation_id}: {_first_sentence(spec.get('summary'))} [{', '.join(spec.get('required') or ())}]"
                for operation_id, spec in steps.items()
            ],
            "how_to_get_specs": (
                "Call inspect_operation_contract again with step_operation_ids set to the steps you will "
                "use (up to 12) to get their field names, types and allowed values."
            ),
        }
    unknown = [operation_id for operation_id in requested if operation_id not in steps]
    return {
        **shared,
        "step_operations": {
            operation_id: {key: value for key, value in steps[operation_id].items() if key not in _INTERNAL_STEP_KEYS}
            for operation_id in requested
            if operation_id in steps
        },
        **({"unknown_step_operation_ids": unknown, "known_step_operation_ids": sorted(steps)} if unknown else {}),
    }


def _first_sentence(text: object, limit: int = 90) -> str:
    sentence = str(text or "").split(". ")[0].strip().rstrip(".")
    return sentence if len(sentence) <= limit else sentence[: limit - 1].rstrip() + "…"
