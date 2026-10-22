"""Normalize proposal intent against server-owned source and model contracts."""

from __future__ import annotations

from pathlib import Path
from typing import Any

from ...contracts.common.envelope import ContractError
from ..tools import ToolVisibleError


def _overrides_from_proposal_changes(changes: dict[str, Any]) -> dict[str, Any]:
    """Translate proposal old/new evidence into the rerun wire payload."""

    return {
        key: value["new"]
        if (
            key != "model_options"
            and isinstance(value, dict)
            and {"old", "new"}.issubset(value)
        )
        else value
        for key, value in changes.items()
    }


def _require_editable_rerun_target(
    run_root: Path, run_id: str, arguments: dict[str, Any]
) -> None:
    """Refuse a rerun aimed at a node execution will refuse as not editable.

    Labels and missing codes belong to the data, so an Agent naturally
    targets the data node; execution only reruns from an editable (model)
    node. Saying so here, with the node to use, lets it re-plan.
    """

    from ...services.rerun_service import editable_rerun_nodes

    node_ref = (arguments.get("target") or {}).get("node_ref")
    if not isinstance(node_ref, str) or not node_ref:
        return
    try:
        candidates = editable_rerun_nodes(run_root.parent.parent, run_id)
        from ...graph_store import GraphStore

        known = GraphStore(runs_root=run_root.parent).read(run_id).nodes
    except Exception:
        return
    if node_ref not in known or node_ref in candidates:
        return
    from ..tools import ToolVisibleError

    raise ToolVisibleError(
        f"MODEL_RERUN_TARGET_NOT_EDITABLE: {node_ref} cannot be rerun. model.rerun "
        "edits a model node; target "
        + (", ".join(candidates) if candidates else "a model node")
        + ". Labels and missing codes declared there apply to the whole run."
    )


def _canonicalize_data_columns_cast_arguments(
    arguments: dict[str, Any],
    *,
    project_root: Path | None,
) -> dict[str, Any]:
    """Bind the backend facts a model must never supply for a data cast.

    The model contributes the intent — which run, which node, which columns
    become which dtype. Everything else is a fact only the backend can
    state truthfully:

      * `artifact_id` — the durable identity of the data behind the node.
        A model naming it could aim a confirmed operation at data the user
        never selected.
      * `context_fingerprint` — this is the *preview* fingerprint, and the
        preview is computed here, from the real data. The live smoke showed
        a model inventing a fingerprint; execution rejected it, which is
        correct but useless. Binding it means a confirmable proposal is an
        executable one.

    `preview_project_root` must be resolvable; without it (pure contract
    tests) the arguments pass through unchanged and execution still
    revalidates.
    """

    if project_root is None:
        return arguments
    from ...data_operations import (
        DataCastItem,
        DataColumnCastValidationError,
        DataColumnsCastSpecV1,
        preview_data_columns_cast,
        resolve_data_column_cast_context,
    )

    target = dict(arguments.get("target") or {})
    preconditions = dict(arguments.get("preconditions") or {})
    run_id = str(target.get("run_id") or "")
    node_ref = str(target.get("node_ref") or "")
    casts = target.get("casts")
    if not run_id or not node_ref or not isinstance(casts, list) or not casts:
        # Leave a structurally malformed proposal to the operation validator,
        # which owns the error vocabulary the Agent already knows to react to.
        return arguments
    try:
        context = resolve_data_column_cast_context(
            project_root,
            source_run_id=run_id,
            source_node_id=node_ref,
        )
        spec = DataColumnsCastSpecV1(
            source_run_id=run_id,
            source_node_id=node_ref,
            source_artifact_id=str(context["source_artifact_id"]),
            casts=tuple(
                DataCastItem(str(item["column"]), str(item["target_dtype"]))
                for item in casts
                if isinstance(item, dict)
            ),
            output_format=str(target.get("output_format", "csv")),
        )
        preview = preview_data_columns_cast(project_root, spec)
    except (DataColumnCastValidationError, KeyError, TypeError, ValueError):
        # The proposal cannot be resolved against the real data (bad column,
        # unknown node, wrong dtype). Pass it through unbound so the operation
        # validator produces its actionable error. NB: OSError is deliberately
        # NOT caught — a filesystem fault is a real problem the user must see,
        # not something to disguise as "your proposal was malformed".
        return arguments

    target["artifact_id"] = spec.source_artifact_id
    target["casts"] = [item.to_dict() for item in spec.casts]
    target["output_format"] = spec.output_format
    preconditions["context_version"] = "data-columns-cast.v1"
    preconditions["context_fingerprint"] = preview.fingerprint
    preconditions["active_head_run_id"] = run_id
    preconditions["owner_resolution"] = "typed_data_node"
    changes = {
        "casts": target["casts"],
        "output_format": spec.output_format,
    }
    return {
        **arguments,
        "target": target,
        "preconditions": preconditions,
        "changes": changes,
    }


def _canonicalize_workflow_arguments(
    arguments: dict[str, Any],
    *,
    project_root: Path | None,
) -> dict[str, Any]:
    """Bind a workflow proposal to the artifact owned by its source node.

    The Agent may identify the selected node, but it must not choose the
    durable artifact identity behind that node. The workflow executor
    resolves the same ownership witness again at confirmation; binding it
    here keeps a valid proposal executable instead of persisting a node
    hash copied from the graph projection as ``artifact_id``.
    """

    target = dict(arguments.get("target") or {})
    # Node identity the backend binds; a copied value is dropped, never trusted.
    if {"node_hash", "forest_node_key"} & set(target):
        for field in ("node_hash", "forest_node_key"):
            target.pop(field, None)
        arguments = {**arguments, "target": target}
    if project_root is None:
        return arguments
    run_id = str(target.get("run_id") or "")
    node_ref = str(target.get("node_ref") or "")
    if not run_id or not node_ref:
        return arguments
    from ...data_operations import (
        DataColumnCastValidationError,
        resolve_data_column_cast_context,
    )

    if (bound := _workflow_dataset_node(project_root, run_id, node_ref)) != node_ref:
        node_ref = target["node_ref"] = bound
        arguments = {**arguments, "target": target}
    try:
        context = resolve_data_column_cast_context(
            project_root,
            source_run_id=run_id,
            source_node_id=node_ref,
        )
    except (DataColumnCastValidationError, KeyError, TypeError, ValueError):
        # Leave malformed intent to the typed operation validator, which
        # owns the user-visible error vocabulary.
        return arguments
    target["artifact_id"] = str(context["source_artifact_id"])
    return {**arguments, "target": target}


def _workflow_dataset_node(project_root: Path, run_id: str, node_ref: str) -> str:
    """The dataset node a workflow runs on, when the Agent named the model it inspected.

    A workflow reads a dataset stage. Agents target the node they were looking
    at, often ``model:ols_1``; that proposal used to be admitted and then fail
    at confirmation (free-route round, 2026-10-22: six confirmations, none
    ran). The model's one input dataset is a lineage fact, so it is bound with
    a note; any other non-dataset node is refused here, naming the choices.
    """

    from ...graph_model import NodeKind
    from ...graph_store import GraphStore
    from ..tools import tool_note

    try:
        graph = GraphStore(Path(project_root) / "runs").read(run_id)
    except (FileNotFoundError, KeyError, OSError, TypeError, ValueError):
        return node_ref
    node = graph.nodes.get(node_ref)
    if node is None or node.kind == NodeKind.DATASET_STAGE:
        return node_ref
    datasets = sorted(key for key, item in graph.nodes.items() if item.kind == NodeKind.DATASET_STAGE)
    inputs = sorted({edge.source_id for edge in graph.edges.values() if edge.target_id == node_ref
                     and getattr(graph.nodes.get(edge.source_id), "kind", None) == NodeKind.DATASET_STAGE})
    if node.kind == NodeKind.MODEL and len(inputs) == 1:
        tool_note(f"operation.multi_step runs on a dataset node: target.node_ref {node_ref} was bound to "
                  f"{inputs[0]}, the dataset {node_ref} was fitted on.")
        return inputs[0]
    raise ToolVisibleError(
        f"WORKFLOW_SOURCE_NOT_DATASET: operation.multi_step target.node_ref must be a dataset node of run "
        f"{run_id}, not {node_ref}. Dataset nodes in this run: {', '.join(datasets) or 'none'}."
    )


def _clustered_analysis_loop_intent(arguments: dict[str, Any]) -> str | None:
    """Extract an exact cluster field from a legacy generic proposal."""

    def new_value(value: Any) -> Any:
        return value.get("new") if isinstance(value, dict) and "new" in value else value

    changes = arguments.get("changes")
    if not isinstance(changes, dict):
        return None
    covariance = new_value(changes.get("covariance"))
    if covariance != "clustered":
        return None
    cluster = new_value(changes.get("cluster_variable"))
    if cluster is None:
        cluster = new_value(changes.get("entity_col"))
    if type(cluster) is not str or not cluster:
        raise ValueError("analysis_loop_cluster_variable_required")
    return cluster


def _precheck_model_options(
    *, owner_run_id: str, changes: Any, context_provider: Any
) -> None:
    """Let the owning pack reject an unexecutable patch before confirmation.

    The generic rerun validator can only check that model_options is an
    object; the field names, closed value sets, and cross-field rules belong
    to the pack. Deferring that to execution would mean the user confirms a
    proposal that cannot run.
    """

    if not isinstance(changes, dict):
        return
    patch = changes.get("model_options")
    if not isinstance(patch, dict) or not patch:
        return
    precheck = getattr(context_provider, "precheck_model_options_patch", None)
    if precheck is None:
        return
    # The proposal's own model_type is part of the patch: a run fitted
    # with model_type "auto" needs it, and checking the patch against the
    # source form alone refused every correct proposal (user review 6).
    model_type = changes.get("model_type")
    if isinstance(model_type, dict):
        model_type = model_type.get("new")
    try:
        precheck(owner_run_id=owner_run_id, patch=patch,
                 model_type=model_type if isinstance(model_type, str) and model_type else None)
    except ContractError as exc:
        code = getattr(exc, "code", "MODEL_OPTIONS_REJECTED")
        hint = (
            " The source run chose its model automatically: also set changes.model_type to the "
            "executed family (for example \"ols\") as a plain string."
            if code == "MODEL_OPTIONS_EXPLICIT_MODEL_REQUIRED" else ""
        )
        # Visible on purpose: the code and the reason are what let an Agent
        # correct the patch instead of guessing at why it was refused.
        raise ToolVisibleError(
            f"model_options rejected by the model pack ({code}): {exc}.{hint} "
            "Fix the patch against the contract's option_vocabulary and "
            "cross_field_rules, then propose again."
        ) from exc
