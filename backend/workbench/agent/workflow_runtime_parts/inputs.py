"""Inputs service for workflow execution."""

from __future__ import annotations
from pathlib import Path
from typing import Any, Mapping
import numpy as np
import pandas as pd
from ...statistical_exploration import resolve_statistical_source
from ..workflow import WorkflowDraft, WorkflowExecutionError, WorkflowStepResult
from ..workflow_contracts import STEP_REPLAYABLE_BY_RECIPE, WORKFLOW_STEP_SPEC_CONTRACTS
from .constants import _PRODUCED_DATASET_FIELDS, _PRODUCED_DATASET_SCHEMA


def _apply_numeric_recipes(
    frame: pd.DataFrame,
    recipes: list[Mapping[str, Any]] | tuple[Mapping[str, Any], ...],
) -> tuple[pd.DataFrame, list[dict[str, Any]]]:
    """Apply the closed transform vocabulary to a copy of a source frame.

    Contract validation owns recipe shape; runtime validation owns actual data
    domain checks.  In particular, a log is never silently evaluated on zero,
    negative, or non-numeric values, and arithmetic cannot produce infinities.
    """

    derived = frame.copy()
    summaries: list[dict[str, Any]] = []
    for recipe in recipes:
        operator = str(recipe["operator"])
        inputs = [str(column) for column in recipe["input_columns"]]
        output_name = str(recipe["output_name"])
        if output_name in derived.columns:
            raise WorkflowExecutionError(
                f"numeric derivation output already exists: {output_name}"
            )
        missing = [column for column in inputs if column not in derived.columns]
        if missing:
            raise WorkflowExecutionError(
                "numeric derivation source column is unavailable: " + ", ".join(missing)
            )
        numeric_inputs: list[pd.Series] = []
        for column in inputs:
            original = derived[column]
            converted = pd.to_numeric(original, errors="coerce")
            if bool((original.notna() & converted.isna()).any()):
                raise WorkflowExecutionError(
                    f"numeric derivation input is not numeric: {column}"
                )
            numeric_inputs.append(converted.astype(float))
        if operator == "natural_log":
            value = numeric_inputs[0]
            if bool((value.dropna() <= 0).any()):
                raise WorkflowExecutionError(
                    f"natural_log requires strictly positive values: {inputs[0]}"
                )
            result = np.log(value)
        elif operator == "multiply":
            result = numeric_inputs[0] * numeric_inputs[1]
        else:  # contract validation should make this unreachable
            raise WorkflowExecutionError(f"numeric derivation operator is unsupported: {operator}")
        finite = result.notna()
        if bool((~np.isfinite(result[finite])).any()):
            raise WorkflowExecutionError(
                f"numeric derivation produced non-finite values: {output_name}"
            )
        derived[output_name] = result
        summaries.append(
            {
                "operator": operator,
                "input_columns": inputs,
                "output_name": output_name,
                "nonmissing_count": int(finite.sum()),
                "missing_count": int(result.isna().sum()),
            }
        )
    return derived, summaries



def _upstream_numeric_steps(
    draft: WorkflowDraft,
    step_id: str,
    dependency_graph: Mapping[str, tuple[str, ...]],
) -> tuple[Any, ...]:
    """Return declared numeric ancestors in compiled topological order."""

    seen: set[str] = set()

    def visit(current: str) -> None:
        for dependency in dependency_graph.get(current, ()):
            if dependency in seen:
                continue
            seen.add(dependency)
            visit(dependency)

    visit(step_id)
    return tuple(
        item
        for item in draft.steps
        # Read from the contract rather than naming the operation here. The
        # compile-time rule that refuses an unreplayable producer upstream of a
        # sourceless step is derived from the same declaration, so the two
        # cannot drift apart into a plan that compiles and then skips a
        # transform.
        if item.step_id in seen and item.operation_id in STEP_REPLAYABLE_BY_RECIPE
    )



def _workflow_input_frame(
    source_frame: pd.DataFrame,
    draft: WorkflowDraft,
    step: Any,
    dependency_graph: Mapping[str, tuple[str, ...]],
    previous: Mapping[str, WorkflowStepResult],
    root: Path,
) -> pd.DataFrame:
    """Rebuild the exact input for a step from its declared DAG.

    A step that committed to another step's output resolves that persisted
    dataset -- and stops there. Replaying the declared recipes afterwards would
    apply the same derivations a second time onto a frame that already carries
    them, which is why this returns early rather than layering the two.
    Everything else keeps the original behaviour: start from the workflow's own
    target and replay the declared numeric derivations.
    """

    if "source" in step.spec:
        return _resolve_committed_source_frame(
            step, previous, root, workflow_run_id=str(draft.target["run_id"])
        )
    frame = source_frame
    for transform_step in _upstream_numeric_steps(draft, str(step.step_id), dependency_graph):
        frame, _ = _apply_numeric_recipes(frame, transform_step.spec["recipes"])
    return frame



def _require_binding_shape(
    step: Any, from_step: str, produced: Mapping[str, Any], workflow_run_id: str
) -> None:
    """Refuse a binding this runtime cannot read, naming what is wrong.

    The binding is read back from persisted state on resume, so it can outlive
    the code that wrote it. Without this the first sign of a version skew is a
    bare KeyError swallowed by the executor into `error="'node_ref'"`, which
    tells whoever reads it nothing at all -- and the schema version would be a
    field nobody ever compared.

    The run is checked here too, because this step's own output is persisted on
    the workflow's target run and its lineage names the binding's node as the
    parent. A binding from another run would therefore write an edge pointing at
    a node that does not exist in the mutated graph -- a dangling lineage claim
    with no error attached. No plan can currently produce one, since the only
    dataset producer publishes the target run's id; that is a property of
    today's operations, not a guarantee of this contract.
    """

    version = produced.get("schema_version")
    if version != _PRODUCED_DATASET_SCHEMA:
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} published a "
            f"{version!r} binding, but this runtime reads {_PRODUCED_DATASET_SCHEMA!r}"
        )
    missing = [field for field in _PRODUCED_DATASET_FIELDS if not produced.get(field)]
    if missing:
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} published an incomplete "
            "binding, missing: " + ", ".join(missing)
        )
    if str(produced["run_id"]) != workflow_run_id:
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} published a binding on "
            f"run {produced['run_id']}, but this workflow runs on run "
            f"{workflow_run_id}; consuming it would give this step a parent node "
            "that the mutated graph does not contain"
        )
    contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(step.operation_id)
    accepted_roles = contract.accepted_dataset_kinds if contract is not None else ()
    if accepted_roles:
        dataset_kind = produced.get("dataset_kind")
        if not isinstance(dataset_kind, str) or not dataset_kind:
            raise WorkflowExecutionError(
                f"workflow step {step.step_id} source {from_step} published an incomplete binding, missing: dataset_kind"
            )
        if dataset_kind not in accepted_roles:
            raise WorkflowExecutionError(
                f"workflow step {step.step_id} source {from_step} published dataset role "
                f"{dataset_kind!r}; accepted roles: " + ", ".join(accepted_roles)
            )



def _committed_source_binding(
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
    workflow_run_id: str,
) -> Mapping[str, Any]:
    """Return the validated binding a step committed to consuming.

    One resolution shared by the two halves that must agree: the frame a step
    computes from, and the lineage it then claims. Resolving them separately is
    how a step ends up correctly consuming an upstream dataset while reporting
    the original table as its parent.
    """

    commitment = step.spec["source"]
    from_step = str(commitment["from_step"])
    upstream = previous.get(from_step)
    if upstream is None:
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} has not completed"
        )
    produced = upstream.payload.get(str(commitment["output"]))
    if not isinstance(produced, Mapping):
        # Two different faults, two different places to look. A live upstream
        # result without the binding means the producing step really published
        # nothing. A result the executor rebuilt from persisted state without it
        # means the state record never carried the binding -- the producing step
        # is fine, and sending the reader to audit its output wastes the whole
        # investigation on a step that is working.
        if upstream.restored_from_state:
            # What is known: the result was rebuilt from the state record, and
            # the record carried no binding. Why it carried none is not known
            # here, and naming one cause would send readers of the other causes
            # to the wrong place -- including toward a re-run that fails
            # identically. So the branch reports the fact and lists what can
            # produce it, rather than asserting which one happened.
            raise WorkflowExecutionError(
                f"workflow step {step.step_id} source {from_step} completed in an "
                f"earlier pass, but its {commitment['output']!r} binding did not "
                "survive into the persisted workflow state. Two things can cause "
                "this and they need different fixes: the state record was written "
                "before bindings were persisted, in which case re-running the plan "
                "from the start resolves it; or the producing step completes "
                "without publishing the binding, in which case a re-run fails the "
                "same way and the producer is what to fix"
            )
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} published no "
            f"{commitment['output']!r} binding"
        )
    _require_binding_shape(step, from_step, produced, workflow_run_id)
    return produced



def _lineage_source(
    draft: WorkflowDraft,
    step: Any,
    source_context: Mapping[str, Any],
    previous: Mapping[str, WorkflowStepResult],
) -> dict[str, str]:
    """Where this step's output is actually derived from, for the record.

    A step that declared a `source` computed from the upstream dataset, so the
    graph edge, the recipe's source block and the artifact inputs must all name
    that dataset. Naming `draft.target` instead produces no error and no red
    test -- it just makes the lineage say the original table produced a node it
    did not, which misdirects rerun, comparison, explanation and reporting
    alike. A step without a `source` really is derived from the target, and
    keeps naming it.

    This is resolved once per step in the executor and handed to whatever
    persists the step's output, rather than left for each persist function to
    remember. The persist functions no longer receive `source_context` at all,
    so a new one cannot reach for the target's digest by habit: the only source
    identity in scope is the one this returns.
    """

    if "source" not in step.spec:
        return {
            "run_id": str(draft.target["run_id"]),
            "artifact_id": str(draft.target["artifact_id"]),
            "node_ref": str(draft.target["node_ref"]),
            "sha256": str(source_context["source_sha256"]),
        }
    produced = _committed_source_binding(
        step, previous, str(draft.target["run_id"])
    )
    return {
        "run_id": str(produced["run_id"]),
        "artifact_id": str(produced["artifact_id"]),
        "node_ref": str(produced["node_ref"]),
        "sha256": str(produced["content_sha256"]),
    }



def _resolve_committed_source_frame(
    step: Any,
    previous: Mapping[str, WorkflowStepResult],
    root: Path,
    *,
    workflow_run_id: str,
) -> pd.DataFrame:
    """Load the dataset the upstream step actually persisted."""

    commitment = step.spec["source"]
    from_step = str(commitment["from_step"])
    produced = _committed_source_binding(step, previous, workflow_run_id)
    context, frame = resolve_statistical_source(
        root,
        source_run_id=str(produced["run_id"]),
        source_node_id=str(produced["node_ref"]),
        source_artifact_id=str(produced["artifact_id"]),
    )
    # Execution-time half of the guarantee: compare the bytes that actually
    # arrived against the bytes the upstream step published. Comparing step
    # fingerprints here would look like a check and never fire -- the binding
    # carries the producing step's own fingerprint, so both sides are the same
    # value no matter which artifact the binding points at.
    if str(produced["content_sha256"]) != str(context["source_sha256"]):
        raise WorkflowExecutionError(
            f"workflow step {step.step_id} source {from_step} resolved to different "
            "content than the completed step published"
        )
    return frame

