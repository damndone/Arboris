"""Stage-output Merkle increment layer (Loop 2A.4 dry-run → 2A.5 identity + MICE skip).

Two-layer reuse (PM decision v5, see spec §0/§15):
  1. Identity reuse — every cacheable stage's `node_hash` is recorded; a marker is
     written to the CAS so a later run with the same node_hash is observable as
     `recomputed_same_hash` (the forest dedups shared prefixes by this identity).
  2. Compute skip — day-1 only MICE imputation is truly skipped: if its node_hash is
     already materialized, the imputed frame is restored from the CAS instead of
     re-running MICE.

Full per-stage ctx rehydrate / arbitrary stage skip is Slice 3 — the pre-estimation
ctx is custom-object-heavy (DatasetSchema/DecisionPoint/...) and not cleanly
serializable, so other upstream stages are RE-EXECUTED (cheap, deterministic →
byte-identical) while their identity is reused by hash.

Cacheable boundary (spec §3.2): source / cleaning / profile / validation / routing /
imputation / estimation / diagnostics / report. RecordingStage is NEVER cached.

trace status taxonomy:
  miss_executed        — first execution / hash not seen before
  hit_reused           — execution truly skipped, CAS product reused (day-1: MICE)
  recomputed_same_hash — re-executed but node_hash matches an existing node (identity reuse)
  recomputed_changed   — reserved for parent-trace diff (Loop 2A.6); op_spec/input changed
"""
from __future__ import annotations

from typing import Any

from ..artifacts import write_json
from .hashing import node_hash, override_hash
from .imputation_cache import imputation_cached, materialize_imputation, restore_imputation
from .node_store import node_result_exists, write_node_result
from .op_spec import op_spec_for_stage

_STAGE_NAME: dict[str, str] = {
    "SourceStage": "source",
    "CleaningStage": "cleaning",
    "ProfileStage": "profile",
    "ValidationStage": "validation",
    "RoutingStage": "routing",
    "YTypeStage": "ytype",
    "PreEstimationChecksStage": "pre_estimation_checks",
    "RoleInferenceStage": "roles",
    "ExposureDetectionStage": "exposure",
    "StatisticalTestsStage": "statistical_tests",
    "ImputationStage": "imputation",
    "EstimationStage": "estimation",
    "RecordingStage": "recording",
    "ReliabilityStage": "reliability",
    "ReportStage": "report",
}

CACHEABLE_STAGES: frozenset[str] = frozenset({
    "source", "cleaning", "profile", "validation", "routing",
    "imputation", "estimation", "diagnostics", "report",
})


def _mice_requested(form: dict, config: dict) -> bool:
    request = form.get("imputation")
    method = request.get("method") if isinstance(request, dict) else config.get("imputation_method", "")
    return method == "mice"


def run_pipeline_traced(pipeline, ctx, env, *, form: dict, config: dict, force_full: bool, upload_hash: str):
    """Cache wrapper. Runs the pipeline; for each cacheable stage records its
    Merkle node_hash + status. Only MICE imputation is truly skipped on a hit;
    every other cacheable stage re-executes but reuses identity by hash. Writes
    `incremental_trace.json` to the run root. Returns the final ctx."""
    project_root = env.run_root.parent.parent
    trace: list[dict[str, Any]] = []
    prev_hash = upload_hash

    for stage in pipeline:
        name = _STAGE_NAME.get(type(stage).__name__, type(stage).__name__)

        if name not in CACHEABLE_STAGES:
            ctx = stage.run(ctx, env)
            if ctx.terminal_status in ("blocked", "failed"):
                break
            continue

        spec = op_spec_for_stage(name, form=form, config=config)
        parents = [prev_hash] if prev_hash else []
        nh = node_hash(parents, spec)
        existed = node_result_exists(project_root, nh)

        if name == "imputation" and existed and not force_full and _mice_requested(form, config):
            ctx = restore_imputation(project_root, nh, env.run_root, ctx)
            status = "hit_reused"
        else:
            ctx = stage.run(ctx, env)
            if name == "imputation" and ctx.data.artifact_id == "imputed_dataset":
                materialize_imputation(project_root, nh, env.run_root)
                status = "recomputed_same_hash" if existed else "miss_executed"
            else:
                if not existed:
                    write_node_result(project_root, nh, meta={"stage": name, "identity_only": True}, artifacts={})
                    status = "miss_executed"
                else:
                    status = "recomputed_same_hash"

        trace.append({
            "stage": name,
            "node_hash": nh,
            "op_spec_hash": override_hash(spec),
            "status": status,
            "parents": parents,
        })
        prev_hash = nh
        if ctx.terminal_status in ("blocked", "failed"):
            break

    write_json(env.run_root / "incremental_trace.json", trace)
    return ctx
