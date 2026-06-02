from __future__ import annotations

from ...artifacts import register_artifact, write_json
from ...router import classify_dataset
from ..context import ModelingContext, RunEnv


class RoutingStage:
    """Classify the dataset (cross-section / time-series / panel) and record
    the analysis_router artifact.

    Extracted verbatim from orchestrator._run_workflow (the routing block) as
    part of the V1.5.4 engine decomposition. Behavior must stay byte-identical.
    """

    name = "routing"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        # Lazy import to avoid a module-load cycle: orchestrator imports this
        # stage at the top of its module, and _normalized_existing lives there.
        from ...orchestrator import _normalized_existing

        cleaned = ctx.data.frame
        schema = ctx.artifacts["_schema"]
        run_root = env.run_root

        env.step("routing", "start", "Classifying dataset...")
        time_candidates = _normalized_existing(schema.time_candidates, cleaned)
        id_candidates = _normalized_existing(schema.id_candidates, cleaned)
        routing = classify_dataset(cleaned, id_candidates, time_candidates)
        env.step("routing", "complete", f"Classified as {routing['kind']}")
        routing_path = run_root / "staged" / "analysis_router.json"
        write_json(routing_path, routing)
        register_artifact(
            run_root,
            "analysis_router",
            routing_path,
            "metadata",
            "analysis_router",
            ["data_profile"],
        )

        ctx.artifacts["_routing"] = routing
        ctx.artifacts["_time_candidates"] = time_candidates
        ctx.artifacts["_id_candidates"] = id_candidates
        return ctx
