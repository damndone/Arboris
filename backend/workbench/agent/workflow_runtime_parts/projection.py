"""Projection service for workflow execution."""

from __future__ import annotations
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping
from ...api_errors import WorkbenchAPIError
from ...artifacts import read_json, sha256_file
from ...repository.run_repository import _read_artifacts_index
from ..workflow import WorkflowExecutionError, WorkflowStepResult
from .constants import MAX_PROJECTED_POST_ESTIMATION_RESULTS, POST_ESTIMATION_ARTIFACT_TYPES


def _p7_result_status(
    result: Mapping[str, Any],
) -> tuple[object, Mapping[str, Any]]:
    """Read the status from either supported P7 result-envelope shape."""

    status = result.get("status")
    details: Mapping[str, Any] = result
    nested = result.get("result")
    if status is None and isinstance(nested, Mapping) and "status" in nested:
        status = nested.get("status")
        details = nested
    return status, details



def _read_post_estimation_artifact_records(run_dir: Path) -> list[Any]:
    """Read the registry shape needed by the post-estimation projection."""

    try:
        index = _read_artifacts_index(run_dir)
    except (
        AttributeError,
        FileNotFoundError,
        OSError,
        TypeError,
        ValueError,
        WorkbenchAPIError,
    ) as exc:
        raise WorkflowExecutionError(
            "registered post-estimation artifact index cannot be read"
        ) from exc
    if not isinstance(index, Mapping):
        raise WorkflowExecutionError(
            "registered post-estimation artifact index must be an object"
        )
    records = index.get("artifacts", [])
    if not isinstance(records, list):
        raise WorkflowExecutionError(
            "registered post-estimation artifact index must contain an artifacts list"
        )
    return records



def count_post_estimation_results(root: Path, run_id: str) -> int:
    """How many post-estimation entries belong to ``run_id``, without a limit."""

    return len(collect_post_estimation_results(root, run_id, limit=10**9))



def collect_post_estimation_results(
    root: Path,
    run_id: str,
    *,
    limit: int = MAX_PROJECTED_POST_ESTIMATION_RESULTS,
    workflow_id: str | None = None,
    keep_latest: bool = False,
) -> list[dict[str, Any]]:
    """Project durable workflow-analysis evidence that belongs to one run.

    ``workflow_id`` narrows to one workflow before the limit applies: the run
    accumulates evidence from every workflow ever run on it, and one
    workflow's receipt must not fail because earlier ones exist.
    ``keep_latest`` returns the most recently registered ``limit`` entries
    instead of refusing when there are more (the run detail view shows the
    newest and says how many it left out).

    A completed workflow is not an answered question: the step writes a
    provenance-carrying artifact, but nothing renders it, so the user who
    asked never sees the number. This is the read side that product and Agent
    surfaces consume. P7 pack results use the same projection so a composed
    statistical call is not executable-but-invisible.

    Relevance has two identities on purpose. The artifact is persisted on the
    workflow's *source* run, while the model it describes is a *child* run --
    and the child is what the user opens to read the result. Matching only the
    storing run would keep the answer invisible exactly where it is looked for.

    Only artifacts registered in a run's index are read. The index is the
    admission record; trusting loose files on disk would let anything able to
    write into the run directory publish a finding through the product surface.
    """

    if limit <= 0:
        return []
    runs_root = root / "runs"
    if not runs_root.is_dir():
        return []

    collected: list[dict[str, Any]] = []
    for run_dir in sorted(runs_root.iterdir()):
        if not run_dir.is_dir():
            continue
        for record in _read_post_estimation_artifact_records(run_dir):
            if not isinstance(record, Mapping):
                raise WorkflowExecutionError(
                    "registered post-estimation artifact record must be an object"
                )
            artifact_type = record.get("artifact_type")
            if artifact_type not in POST_ESTIMATION_ARTIFACT_TYPES:
                continue
            # The ordinary statistical-tests stage uses the historical
            # artifact type but has no workflow source/result envelope. It is
            # consumed by the run's statistical-evidence projection, not by
            # this post-estimation result list. Model post-estimation tests
            # use the same type with their operation step and remain included.
            if artifact_type == "statistical_test" and record.get("step") == "statistical_tests":
                continue
            entry = _read_post_estimation_entry(run_dir, record)
            if entry["run_id"] != run_id and entry["model_run_id"] != run_id:
                continue
            if workflow_id is not None and entry.get("workflow_id") != workflow_id:
                continue
            collected.append(entry)

    if keep_latest and len(collected) > limit:
        # Index order is registration order: keep the newest.
        collected = collected[-limit:]
    collected.sort(key=lambda item: (item["run_id"], item["artifact_id"]))
    if len(collected) > limit:
        raise WorkflowExecutionError(
            f"post-estimation evidence count {len(collected)} exceeds projection limit {limit}; "
            "request a narrower evidence scope"
        )
    return collected[:limit]



def _read_post_estimation_entry(
    run_dir: Path, record: Mapping[str, Any]
) -> dict[str, Any]:
    """Read one registered post-estimation artifact and fail closed on damage.

    The artifacts index is the admission record.  Once an evidence artifact is
    registered, omitting it from a public projection would turn corruption into
    a false-looking successful analysis.  Loose, unregistered files remain
    ignored by the caller.
    """

    relative = str(record.get("path", ""))
    if not relative:
        raise WorkflowExecutionError(
            "registered post-estimation artifact has no path"
        )
    path = (run_dir / relative).resolve()
    # The index stores repository-relative paths; a traversal escape means the
    # record is not describing this run's own evidence.
    if not path.is_file() or run_dir.resolve() not in path.parents:
        raise WorkflowExecutionError(
            "registered post-estimation artifact is missing or escapes its run"
        )
    expected_sha256 = record.get("sha256")
    if not isinstance(expected_sha256, str) or not expected_sha256:
        raise WorkflowExecutionError(
            "registered post-estimation artifact has no file fingerprint"
        )
    try:
        actual_sha256 = sha256_file(path)
    except OSError as exc:
        raise WorkflowExecutionError(
            "registered post-estimation artifact fingerprint cannot be read"
        ) from exc
    if actual_sha256 != expected_sha256:
        raise WorkflowExecutionError(
            "registered post-estimation artifact fingerprint changed"
        )
    try:
        payload = read_json(path)
    except (OSError, ValueError) as exc:
        raise WorkflowExecutionError(
            "registered post-estimation artifact cannot be read"
        ) from exc
    if not isinstance(payload, Mapping):
        raise WorkflowExecutionError(
            "registered post-estimation artifact payload must be an object"
        )
    source = payload.get("source")
    result = payload.get("result")
    if not isinstance(source, Mapping) or not isinstance(result, Mapping):
        raise WorkflowExecutionError(
            "registered post-estimation artifact must contain source and result objects"
        )
    artifact_type = str(record.get("artifact_type", ""))
    if artifact_type == "p7_analysis":
        required_source = {
            "run_id",
            "node_ref",
            "artifact_id",
            "sha256",
            "workflow_id",
            "workflow_step_id",
            "workflow_step_fingerprint",
            "operation_id",
            "pack_family",
        }
        if payload.get("schema_version") != "workbench.workflow.p7-pack/v1":
            raise WorkflowExecutionError("registered P7 analysis artifact has an invalid schema")
        if set(required_source) - set(source):
            raise WorkflowExecutionError("registered P7 analysis artifact has incomplete provenance")
        if any(not isinstance(source.get(field_name), str) or not source[field_name] for field_name in required_source):
            raise WorkflowExecutionError("registered P7 analysis artifact has invalid provenance")
        if result.get("operation_id") != source.get("operation_id"):
            raise WorkflowExecutionError("registered P7 analysis artifact operation identity is inconsistent")
    if artifact_type == "workflow_capability_result":
        required_source = {
            "run_id",
            "node_ref",
            "artifact_id",
            "sha256",
            "workflow_id",
            "workflow_step_id",
            "workflow_step_fingerprint",
            "operation_id",
        }
        if payload.get("schema_version") != "workbench.workflow.capability/v1":
            raise WorkflowExecutionError("registered workflow capability artifact has an invalid schema")
        if set(required_source) - set(source):
            raise WorkflowExecutionError("registered workflow capability artifact has incomplete provenance")
        if not isinstance(payload.get("request"), Mapping) or not payload.get("request_fingerprint"):
            raise WorkflowExecutionError("registered workflow capability artifact has no replayable request")
        if result.get("operation_id") != source.get("operation_id"):
            raise WorkflowExecutionError("registered workflow capability artifact operation identity is inconsistent")
        expected_result_digest = hashlib.sha256(
            json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode("utf-8")
        ).hexdigest()
        if payload.get("result_sha256") != expected_result_digest:
            raise WorkflowExecutionError("registered workflow capability artifact result digest is inconsistent")
    return {
        "artifact_id": str(record.get("artifact_id", "")),
        "artifact_type": artifact_type,
        "operation_id": str(source.get("operation_id") or record.get("step", "")),
        "run_id": str(source.get("run_id", "")),
        "model_run_id": str(source.get("model_run_id", "")),
        "workflow_id": str(source.get("workflow_id", "")),
        "workflow_step_id": str(source.get("workflow_step_id", "")),
        **(
            {"pack_family": str(source["pack_family"]), "source_sha256": str(source["sha256"])}
            if artifact_type == "p7_analysis"
            else (
                {
                    "source_sha256": str(source["sha256"]),
                    "request_fingerprint": str(payload["request_fingerprint"]),
                    "result_sha256": str(payload["result_sha256"]),
                    "result_schema": str(payload["result_schema"]),
                }
                if artifact_type == "workflow_capability_result"
                else {}
            )
        ),
        "result": dict(result),
    }



def _record_artifact_ids(record: Mapping[str, Any]) -> list[str]:
    ids: list[str] = []
    for key in ("artifact_id", "transcript_artifact_id"):
        value = record.get(key)
        if isinstance(value, str) and value:
            ids.append(value)
    for value in record.get("exports", []) or []:
        if isinstance(value, Mapping) and isinstance(value.get("artifact_id"), str):
            ids.append(value["artifact_id"])
    for key in ("derived", "plot"):
        value = record.get(key)
        if isinstance(value, Mapping):
            for nested_key in ("artifact_id", "recipe_artifact_id"):
                nested = value.get(nested_key)
                if isinstance(nested, str) and nested:
                    ids.append(nested)
    return list(dict.fromkeys(ids))



def _result_from_artifact_ids(
    run_root: Path, artifact_ids: list[str] | tuple[str, ...]
) -> dict[str, Any] | None:
    """Read a step's result block back off disk, or None if it holds none.

    Returning None rather than raising, because the caller is searching a
    dependency chain rather than fetching one known artifact. A dataset
    producer upstream carries a CSV and a recipe and no result block at all --
    a legitimate shape now that a step can declare another step's output as its
    source, which puts that producer in its `depends_on`. Aborting here would
    end the search at the first such dependency instead of continuing to the
    step that does hold the evidence; the caller still refuses when the whole
    chain yields nothing.
    """

    index = _read_artifacts_index(run_root)
    wanted = set(artifact_ids)
    for item in index.get("artifacts", []):
        if item.get("artifact_id") not in wanted:
            continue
        path = run_root / str(item.get("path", ""))
        # Only JSON documents can carry a result block; a derived data.csv read
        # as JSON is a decode error, not an answer.
        if path.is_file() and path.suffix == ".json":
            payload = read_json(path)
            if isinstance(payload, Mapping) and isinstance(payload.get("result"), Mapping):
                return dict(payload["result"])
    return None



def _detail_result(
    previous: Mapping[str, WorkflowStepResult],
    run_root: Path,
    depends_on: tuple[str, ...] | list[str],
    dependency_graph: Mapping[str, tuple[str, ...]] | None = None,
) -> tuple[dict[str, Any], str, str]:
    """Find the percentile evidence this step transitively depends on.

    Resolved through the dependency graph rather than a fixed step id. The
    search is transitive because a plan may legitimately route the evidence
    through an intermediate step — a live agent composed exactly that shape:
    the group comparison depended on the derivation, which depended on the
    detail statistics. Requiring a direct edge would reject a correct plan.
    """

    visited: set[str] = set()
    frontier = list(depends_on)
    while frontier:
        step_id = frontier.pop(0)
        if step_id in visited:
            continue
        visited.add(step_id)
        if dependency_graph is not None:
            frontier.extend(dependency_graph.get(step_id, ()))
        cached = previous.get(step_id)
        if cached is None:
            continue
        result = (
            dict(cached.payload["result"])
            if isinstance(cached.payload.get("result"), Mapping)
            else _result_from_artifact_ids(run_root, cached.artifact_ids)
        )
        if result is None:
            continue
        variables = result.get("variables")
        if isinstance(variables, Mapping) and any(
            isinstance(entry, Mapping) and "percentiles" in entry
            for entry in variables.values()
        ):
            return result, step_id, cached.result_fingerprint or ""
    raise WorkflowExecutionError(
        "no dependency of this step provides percentile evidence: "
        + ", ".join(visited)
    )



def _result_row_counts(result: Mapping[str, Any]) -> dict[str, int]:
    counts = {
        "source": int(result.get("source_row_count", 0) or 0),
        "filtered": int(result.get("filtered_row_count", 0) or 0),
    }
    if isinstance(result.get("groups"), list):
        counts["groups"] = len(result["groups"])
    if result.get("correlation_n") is not None:
        counts["correlation_n"] = int(result["correlation_n"])
    return counts
