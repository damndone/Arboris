from __future__ import annotations

import json
from collections.abc import Mapping
from typing import Any, NotRequired

from typing_extensions import TypedDict


class RunRerunFrom(TypedDict):
    """The node a run was rerun from, as its run inputs record it."""

    owner_run_id: str
    op_node_id: str
    node_hash: str
    context_fingerprint: str
    rerun_request_id: str
    patch_id: NotRequired[str]


def run_rerun_from_from_context(
    *,
    request_id: str,
    owner_run_id: str,
    op_node_id: str,
    node_hash: str,
    context_fingerprint: str,
    patch_id: str | None = None,
) -> RunRerunFrom:
    body = RunRerunFrom(
        owner_run_id=owner_run_id,
        op_node_id=op_node_id,
        node_hash=node_hash,
        context_fingerprint=context_fingerprint,
        rerun_request_id=request_id,
    )
    if patch_id:
        body["patch_id"] = patch_id
    return body


def pending_produced_lineage(
    *, produced_owner_run_id: str, rerun_from: dict[str, Any]
) -> dict[str, Any]:
    return {
        "produced_owner_run_id": produced_owner_run_id,
        "produced_op_node_id": None,
        "produced_node_hash": None,
        "rerun_request_id": str(rerun_from["rerun_request_id"]),
        "rerun_from": rerun_from,
        "status": "pending_index",
    }


def indexed_produced_lineage(
    *,
    produced_owner_run_id: str,
    produced_op_node_id: str,
    produced_node_hash: str,
    rerun_from: dict[str, Any],
) -> dict[str, Any]:
    return {
        "produced_owner_run_id": produced_owner_run_id,
        "produced_op_node_id": produced_op_node_id,
        "produced_node_hash": produced_node_hash,
        "rerun_request_id": str(rerun_from["rerun_request_id"]),
        "rerun_from": rerun_from,
        "status": "indexed",
    }


# --------------------------------------------------------------------------
# Node-level provenance (v1.6.3 spec §3.2).
#
# Run-level ``rerun_from`` (run_inputs.json) says where a rerun request came
# from. Node-level ``rerun_from`` belongs to the one node the rerun produced:
# the child run's ``from_node``. It is written into that node's node_index
# entry, so it travels with the node when the forest merges runs that share
# it. "Compare with source" reads the node-level record first.
# --------------------------------------------------------------------------

_RERUN_FROM_KEYS = frozenset(RunRerunFrom.__annotations__)


def well_formed_rerun_from(value: Any) -> RunRerunFrom | None:
    """``value`` as node provenance, or None when it is not one.

    run_inputs written before v1.8.12 also used ``rerun_from`` for a dataset
    bridge and for Agent reruns without a context fingerprint; neither can
    be revalidated, so neither is provenance.
    """

    if not isinstance(value, Mapping) or not set(value) <= _RERUN_FROM_KEYS:
        return None
    required = _RERUN_FROM_KEYS - {"patch_id"}
    if not required <= set(value) or not all(isinstance(item, str) and item for item in value.values()):
        return None
    return RunRerunFrom(**value)  # type: ignore[typeddict-item]


def run_rerun_from(run_inputs: Mapping[str, Any]) -> RunRerunFrom | None:
    """The run-level provenance of a rerun child, when it has one."""

    return well_formed_rerun_from(run_inputs.get("rerun_from"))


def node_level_rerun_from(run_inputs: Mapping[str, Any]) -> tuple[str, RunRerunFrom] | None:
    """(produced node id, its rerun_from) for a context-driven rerun child run."""

    rerun_from = run_rerun_from(run_inputs)
    from_node = run_inputs.get("from_node")
    if rerun_from is None or not isinstance(from_node, str) or rerun_from["op_node_id"] != from_node:
        return None
    return from_node, rerun_from


class DatasetSource(TypedDict):
    """The data-operation node a model run's input data was materialized from."""

    source_run_id: str
    op_node_id: str
    source_artifact_id: str
    source_node_hash: str | None


def dataset_source(run_inputs: Mapping[str, Any]) -> DatasetSource | None:
    """A run's dataset bridge; runs before v1.8.12 stored it under ``rerun_from``."""

    for key in ("dataset_source", "rerun_from"):
        value = run_inputs.get(key)
        if (
            isinstance(value, Mapping)
            and isinstance(value.get("source_run_id"), str)
            and isinstance(value.get("op_node_id"), str)
            and isinstance(value.get("source_artifact_id"), str)
        ):
            return DatasetSource(
                source_run_id=value["source_run_id"],
                op_node_id=value["op_node_id"],
                source_artifact_id=value["source_artifact_id"],
                source_node_hash=value.get("source_node_hash"),
            )
    return None


def node_rerun_from_candidates(node: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    """The node-level provenance records a forest node currently carries."""

    if isinstance(node.get("rerun_from"), Mapping):
        return [node["rerun_from"]]
    return list(node.get("rerun_from_conflicts") or [])


def settle_node_rerun_from(node: dict[str, Any], candidates: list[Mapping[str, Any]]) -> None:
    """Expose one node-level ``rerun_from``, or fail closed on disagreement.

    A forest node shared by several runs collects the record of each run that
    produced it. One distinct record is the node's source; several distinct
    records mean the source is ambiguous, so none is exposed and all are listed
    under ``rerun_from_conflicts`` (spec §3.4: disagreement fails closed).
    """

    distinct: dict[str, Mapping[str, Any]] = {}
    for candidate in candidates:
        distinct.setdefault(json.dumps(candidate, sort_keys=True), candidate)
    node.pop("rerun_from", None)
    node.pop("rerun_from_conflicts", None)
    if len(distinct) == 1:
        node["rerun_from"] = dict(next(iter(distinct.values())))
    elif distinct:
        node["rerun_from_conflicts"] = [dict(distinct[key]) for key in sorted(distinct)]
