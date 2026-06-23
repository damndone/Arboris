"""Stage-output Merkle increment layer (Loop 2A.4 — DRY-RUN).

This loop installs the cache wrapper in DRY-RUN mode: it computes each cacheable
stage's `node_hash` and writes a structured `incremental_trace.json`, but it does
NOT skip any stage — execution is byte-identical to the un-wrapped pipeline. Real
hit/skip + rehydrate lands in Loop 2A.5.

Cacheable boundary (spec §3.2): source / cleaning / profile / validation / routing /
imputation / estimation / diagnostics / report. RecordingStage is NEVER cached — it
builds the graph view from the node_hash mapping (Loop 2A.7), so it is excluded here.
Other stages (ytype / pre_estimation_checks / roles / exposure / statistical_tests /
reliability) simply run without participating in the cache chain.
"""
from __future__ import annotations

from typing import Any

from ..artifacts import write_json
from .hashing import node_hash, override_hash
from .op_spec import op_spec_for_stage

# Map stage CLASS name -> op_spec stage name.
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
    "DiagnosticsStage": "diagnostics",
    "ReliabilityStage": "reliability",
    "ReportStage": "report",
}

# The day-1 cacheable boundary (spec §3.2). RecordingStage deliberately excluded.
CACHEABLE_STAGES: frozenset[str] = frozenset({
    "source", "cleaning", "profile", "validation", "routing",
    "imputation", "estimation", "diagnostics", "report",
})


def run_pipeline_traced(pipeline, ctx, env, *, form: dict, config: dict, upload_hash: str):
    """DRY-RUN cache wrapper: run every stage unchanged, but for each cacheable
    stage compute its Merkle node_hash and append a trace entry. Writes
    `incremental_trace.json` to the run root. Returns the final ctx.

    The cacheable stages form a linear chain in pipeline order: the source stage's
    parent is the upload content hash, and each later cacheable stage's parent is
    the previous cacheable stage's node_hash. (Graph-node-level fan-out is Slice 3.)
    """
    trace: list[dict[str, Any]] = []
    prev_hash = upload_hash

    for stage in pipeline:
        ctx = stage.run(ctx, env)
        name = _STAGE_NAME.get(type(stage).__name__, type(stage).__name__)
        if name in CACHEABLE_STAGES:
            spec = op_spec_for_stage(name, form=form, config=config)
            parents = [prev_hash] if prev_hash else []
            nh = node_hash(parents, spec)
            trace.append({
                "stage": name,
                "node_hash": nh,
                "op_spec_hash": override_hash(spec),
                "status": "miss",  # dry-run: nothing is skipped
                "parents": parents,
            })
            prev_hash = nh
        if ctx.terminal_status in ("blocked", "failed"):
            break

    write_json(env.run_root / "incremental_trace.json", trace)
    return ctx
