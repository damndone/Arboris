"""A proposal as sentences a person can check before confirming.

"Keep rows where age (年龄) is between 25 and 55" says what will happen;
``{"filters": [{"column": "age", "op": "between", "value": [25, 55]}]}`` makes
the reader do the translation. Every line here is derived from the proposal's
persisted content -- data steps through their registry declaration's
``describe`` -- so it can never say something the proposal does not do. The
raw parameters remain available next to it.
"""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any

Labels = Mapping[str, str]


def _name(column: Any, labels: Labels) -> str:
    column = str(column)
    label = labels.get(column)
    return f"{column} ({label})" if label and label != column else column


def _names(columns: Sequence[Any], labels: Labels) -> str:
    return ", ".join(_name(column, labels) for column in columns)


_EXPLORE_WORDS = {
    "summarize": "Summary statistics of",
    "summarize_detail": "Detailed summary (percentiles) of",
    "tabulate": "Frequency table of",
    "misstable": "Missing-value pattern of",
    "correlate": "Correlations among",
    "codebook": "Codebook of",
}


def _explore(spec: Mapping[str, Any], labels: Labels) -> str:
    operation = str(spec.get("operation") or "explore")
    head = _EXPLORE_WORDS.get(operation, f"{operation.replace('_', ' ').capitalize()} of")
    text = f"{head} {_names(spec.get('selected_columns') or (), labels)}"
    group = (spec.get("options") or {}).get("group_by")
    if group:
        text += f", by {_name(group, labels)}"
    return text


def _genesis(spec: Mapping[str, Any], labels: Labels) -> str:
    family = str(spec.get("model_family") or "model")
    family = family.upper() if family == "ols" else family
    branches = []
    for branch in spec.get("branches") or ():
        if not isinstance(branch, Mapping):
            continue
        predictors = list(branch.get("predictors") or ()) + [f"C({item})" for item in branch.get("categorical") or ()]
        branches.append(f"{_name(branch.get('outcome'), labels)} on {_names(predictors, labels) or 'a constant'}")
    covariance = spec.get("covariance")
    text = f"Estimate {family}: " + "; ".join(branches) if branches else f"Estimate {family} model"
    return text + (f" ({covariance} standard errors)" if covariance else "")


def step_sentence(operation_id: str, spec: Mapping[str, Any], labels: Labels | None = None) -> str:
    labels = labels or {}
    if operation_id.startswith("data."):
        from ..data_operation_registry import get_data_operation

        declaration = get_data_operation(operation_id)
        if declaration is not None:
            return declaration.sentence(spec, labels)
    if operation_id == "statistical.explore":
        return _explore(spec, labels)
    if operation_id == "model.genesis":
        return _genesis(spec, labels)
    if operation_id == "model.joint_f_test":
        return f"Joint F-test of the selected terms in model {spec.get('branch_id')}"
    if operation_id == "model.quadratic_stationary_point":
        return f"Turning point of {_name(spec.get('column'), labels)} in model {spec.get('branch_id')}"
    if operation_id == "model.white_test":
        return f"White test for heteroskedasticity in model {spec.get('branch_id')}"
    from .workflow_contracts import WORKFLOW_STEP_SPEC_CONTRACTS, _spec_columns

    contract = WORKFLOW_STEP_SPEC_CONTRACTS.get(operation_id)
    head = (contract.summary if contract is not None else operation_id).split(". ")[0].rstrip(".")
    try:
        columns = sorted(_spec_columns(operation_id, spec))
    except Exception:  # noqa: BLE001 - a description must never break a proposal
        columns = []
    return f"{head}: {_names(columns, labels)}" if columns else head


def _metadata(changes: Mapping[str, Any], labels: Labels) -> list[str]:
    patch = changes.get("labels") if isinstance(changes.get("labels"), Mapping) else changes
    words = {
        "variable_labels": "label",
        "value_labels": "value labels",
        "measurement_level": "measurement level",
        "user_missing_values": "missing-value codes",
    }
    lines = []
    for field, word in words.items():
        entries = patch.get(field) if isinstance(patch, Mapping) else None
        if not isinstance(entries, Mapping):
            continue
        for column, value in entries.items():
            lines.append(
                f"Remove the {word} of {_name(column, labels)}" if value is None
                else f"Set the {word} of {_name(column, labels)} to {value}"
            )
    return lines


def proposal_lines(proposal: Mapping[str, Any], labels: Labels | None = None) -> list[str]:
    """One sentence per thing the proposal will do, in order."""

    labels = labels or {}
    operation_id = str(proposal.get("operation_id") or "")
    changes = proposal.get("changes") if isinstance(proposal.get("changes"), Mapping) else {}
    steps = changes.get("steps")
    if isinstance(steps, list) and steps:
        return [
            step_sentence(str(step.get("operation_id") or ""), step.get("spec") or {}, labels)
            for step in steps
            if isinstance(step, Mapping)
        ]
    if operation_id == "metadata.edit":
        return _metadata(changes, labels) or ["Edit variable metadata"]
    if operation_id in {"data.column.cast", "data.columns.cast"}:
        casts = changes.get("casts") or [changes]
        return [
            f"Change the type of {_name(item.get('column'), labels)} to {item.get('target_dtype')}"
            for item in casts if isinstance(item, Mapping)
        ]
    if operation_id == "model.rerun":
        parts = [f"Re-estimate from {proposal.get('target', {}).get('node_ref', 'the selected node')}"]
        if isinstance(changes.get("labels"), Mapping):
            parts += _metadata(changes, labels)
        for key, value in changes.items():
            if key == "labels":
                continue
            if isinstance(value, Mapping) and "new" in value:
                parts.append(f"Change {key} from {value.get('old')} to {value['new']}")
            else:
                parts.append(f"Set {key} to {value}")
        return parts
    if operation_id == "graph.fork":
        return ["Create a new branch of the analysis from this node (runs nothing yet)"]
    if operation_id == "code.execute":
        return ["Run the proposed code on a copy of the data"]
    return [operation_id or "operation"]
