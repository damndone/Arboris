"""Turn two selected graph nodes into a durable comparison.

The route layer supplies only what a user can honestly point at -- a run and a
node on it. Everything that makes the comparison trustworthy is re-derived
here: the node identities from each run's node index, the lineage relation from
the family scan, and the comparison itself from persisted artifacts. Nothing is
refitted, so the stored packet is a reading of evidence that already existed.
"""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from ..analysis_loop.time_series_compare import (
    build_arma_garch_compare_packet,
    build_arma_garch_compare_presentation,
    read_time_series_artifacts,
)
from ..artifacts import read_json
from ..lineage.compare_nodes import (
    CompareEndpoint,
    CompareNodeError,
    CompareNodeRecord,
    CompareNodeStore,
    build_compare_node,
    canonical_endpoint_order,
)
from ..lineage.family import scan_family
from ..lineage.headset import forest_node_key
from ..lineage.node_index import NODE_INDEX_FILENAME
from ..lineage.run_inputs import read_run_inputs
from ..predictive_research.consumer_projection import (
    read_prediction_evidence_from_run_root,
)
from ..predictive_research.schema import PayloadContractError


ARMA_GARCH_PACK_ID = "time_series.arma_garch"
_PREDICTION_ARTIFACT_TYPES = {
    "prediction_sample_spec",
    "prediction_split_plan",
    "prediction_packet",
    "evaluation_packet",
    "negative_control_packet",
    "prediction_result",
}


def _resolve_endpoint(runs_dir: Path, run_id: str, node_id: str) -> CompareEndpoint:
    run_root = runs_dir / run_id
    if not run_root.is_dir():
        raise CompareNodeError(
            "COMPARE_RUN_NOT_FOUND",
            f"run {run_id} does not exist in this project",
            evidence={"run_id": run_id},
        )
    try:
        node_index = read_json(run_root / NODE_INDEX_FILENAME)
    except (FileNotFoundError, OSError, ValueError):
        node_index = {}
    entry = node_index.get(node_id) or {}
    node_hash = entry.get("node_hash")
    if not node_hash:
        # A node with no Merkle identity cannot be addressed stably, so a
        # comparison anchored on it could silently drift to another node.
        raise CompareNodeError(
            "COMPARE_ENDPOINT_NOT_IDENTIFIED",
            f"node {node_id} in run {run_id} has no node hash",
            evidence={"run_id": run_id, "node_id": node_id},
        )
    return CompareEndpoint(
        run_id=run_id,
        node_id=node_id,
        node_hash=str(node_hash),
        forest_node_key=forest_node_key(node_id, node_index),
    )


def _ancestor_key(
    runs_dir: Path, left: CompareEndpoint, right: CompareEndpoint
) -> str | None:
    """Return the endpoint key that produced the other, if either did."""

    if left.run_id == right.run_id:
        return None
    family = scan_family(runs_dir, right.run_id)
    if left.run_id in family.ancestors:
        return left.forest_node_key
    family = scan_family(runs_dir, left.run_id)
    if right.run_id in family.ancestors:
        return right.forest_node_key
    return None


def _pack_id(runs_dir: Path, run_id: str) -> str | None:
    try:
        manifest = read_json(runs_dir / run_id / "run_manifest.json")
    except (FileNotFoundError, OSError, ValueError):
        return None
    routing = manifest.get("model_routing") or {}
    for key in ("requested_model_type", "effective_model_type"):
        if routing.get(key) == ARMA_GARCH_PACK_ID:
            return ARMA_GARCH_PACK_ID
    return None


def _source_run_id(runs_dir: Path, run_id: str) -> str | None:
    try:
        return read_run_inputs(runs_dir / run_id).get("rerun_of")
    except (FileNotFoundError, OSError, TypeError, ValueError):
        return None


def _prediction_projection_for_compare(
    runs_dir: Path,
    run_id: str,
) -> dict[str, Any] | None:
    run_root = runs_dir / run_id
    try:
        index = read_json(run_root / "artifacts_index.json")
    except (FileNotFoundError, OSError, ValueError):
        return None
    records = index.get("artifacts") if isinstance(index, dict) else None
    if not isinstance(records, list) or not any(
        isinstance(record, dict) and record.get("artifact_type") in _PREDICTION_ARTIFACT_TYPES
        for record in records
    ):
        return None
    try:
        return read_prediction_evidence_from_run_root(run_root, consumer="compare")
    except (PayloadContractError, OSError, ValueError) as error:
        raise CompareNodeError(
            "PREDICTION_EVIDENCE_INVALID",
            "predictive evidence could not be validated for comparison",
            evidence={"run_id": run_id, "reason": str(error)},
        ) from error


def _build_prediction_compare_packet(
    left: dict[str, Any],
    right: dict[str, Any],
) -> dict[str, Any]:
    if left.get("status") == "legacy" or right.get("status") == "legacy":
        if left.get("status") != "legacy" or right.get("status") != "legacy":
            raise CompareNodeError(
                "PREDICTION_LEGACY_RESULT_INCOMPARABLE",
                "legacy prediction results cannot be numerically compared with v1.8.6 evidence",
                evidence={"left_status": left.get("status"), "right_status": right.get("status")},
            )
        return {
            "schema_id": "workbench.prediction.compare.v1",
            "compare_status": "legacy_only",
            "comparability": "legacy_only",
            "message": left.get("message"),
            "left": left,
            "right": right,
        }
    if left.get("sample_spec_hash") != right.get("sample_spec_hash"):
        raise CompareNodeError(
            "PREDICTION_SAMPLE_INCOMPATIBLE",
            "prediction results use different sample specifications",
            evidence={
                "left_sample_spec_hash": left.get("sample_spec_hash"),
                "right_sample_spec_hash": right.get("sample_spec_hash"),
            },
        )
    if left.get("split_plan_hash") != right.get("split_plan_hash"):
        raise CompareNodeError(
            "PREDICTION_SPLIT_INCOMPATIBLE",
            "prediction results must use the same persisted SplitPlan",
            evidence={
                "left_split_plan_hash": left.get("split_plan_hash"),
                "right_split_plan_hash": right.get("split_plan_hash"),
            },
        )
    left_metrics = left.get("oos", {}).get("metrics", {})
    right_metrics = right.get("oos", {}).get("metrics", {})
    metric_diff = {
        metric: {
            "left": left_metrics.get(metric),
            "right": right_metrics.get(metric),
            "difference": right_metrics.get(metric) - left_metrics.get(metric),
        }
        for metric in sorted(set(left_metrics) & set(right_metrics))
        if isinstance(left_metrics.get(metric), (int, float))
        and isinstance(right_metrics.get(metric), (int, float))
    }
    return {
        "schema_id": "workbench.prediction.compare.v1",
        "compare_status": "complete",
        "comparability": "typed_same_split_plan",
        "split_plan_hash": left.get("split_plan_hash"),
        "sample_spec_hash": left.get("sample_spec_hash"),
        "metric_diff": metric_diff,
        "left": left,
        "right": right,
    }


def _build_packet(
    runs_dir: Path,
    left: CompareEndpoint,
    right: CompareEndpoint,
    *,
    relation: str,
) -> dict[str, Any]:
    left_prediction = _prediction_projection_for_compare(runs_dir, left.run_id)
    right_prediction = _prediction_projection_for_compare(runs_dir, right.run_id)
    if left_prediction is not None or right_prediction is not None:
        if left_prediction is None or right_prediction is None:
            raise CompareNodeError(
                "PREDICTION_EVIDENCE_REQUIRED",
                "predictive-research comparison requires predictive evidence on both endpoints",
                evidence={"left_run_id": left.run_id, "right_run_id": right.run_id},
            )
        return _build_prediction_compare_packet(left_prediction, right_prediction)
    if _pack_id(runs_dir, left.run_id) != ARMA_GARCH_PACK_ID or _pack_id(
        runs_dir, right.run_id
    ) != ARMA_GARCH_PACK_ID:
        # Storing an empty packet would put a node on the graph that claims a
        # comparison nobody computed. Refuse until a pack declares a builder.
        raise CompareNodeError(
            "COMPARE_UNSUPPORTED_PACK",
            "a durable comparison is only available between two ARMA-GARCH runs",
            evidence={"left_run_id": left.run_id, "right_run_id": right.run_id},
        )
    left_artifacts, _ = read_time_series_artifacts(runs_dir / left.run_id)
    right_artifacts, _ = read_time_series_artifacts(runs_dir / right.run_id)
    packet = build_arma_garch_compare_packet(
        source_run_id=left.run_id,
        child_run_id=right.run_id,
        source_artifacts=left_artifacts,
        child_artifacts=right_artifacts,
        child_source_run_id=_source_run_id(runs_dir, right.run_id),
        relation=relation,
    )
    payload = packet.to_dict()
    payload["presentation"] = build_arma_garch_compare_presentation(packet)
    return payload


def create_compare_node(
    runs_dir: Path,
    *,
    left_run_id: str,
    left_node_id: str,
    right_run_id: str,
    right_node_id: str,
    now: str | None = None,
) -> CompareNodeRecord:
    """Create (or reuse) the comparison node for two graph nodes."""

    left = _resolve_endpoint(runs_dir, left_run_id, left_node_id)
    right = _resolve_endpoint(runs_dir, right_run_id, right_node_id)
    ancestor = _ancestor_key(runs_dir, left, right)
    # The packet reads the left side as the baseline, so it is built from the
    # same ordering the record will store -- one function decides both.
    ordered, relation = canonical_endpoint_order(
        left, right, ancestor_forest_node_key=ancestor
    )
    record = build_compare_node(
        left=ordered[0],
        right=ordered[1],
        packet=_build_packet(
            runs_dir, ordered[0], ordered[1], relation=relation
        ),
        created_at=now or datetime.now(UTC).isoformat(),
        ancestor_forest_node_key=ancestor,
    )
    return CompareNodeStore(runs_dir.parent).create(record)


def delete_compare_node(runs_dir: Path, compare_id: str) -> bool:
    return CompareNodeStore(runs_dir.parent, create=False).delete(compare_id)


def list_compare_nodes(runs_dir: Path) -> list[CompareNodeRecord]:
    return CompareNodeStore(runs_dir.parent, create=False).list()


__all__ = ["create_compare_node", "delete_compare_node", "list_compare_nodes"]
