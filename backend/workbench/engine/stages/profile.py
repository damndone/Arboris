from __future__ import annotations

from ...artifacts import register_artifact, write_json
from ...profiling import profile_frame
from ..context import ModelingContext, RunEnv


class ProfileStage:
    """Profile the cleaned frame and record the data_profile artifact.

    Extracted verbatim from orchestrator._run_workflow (the profiling block)
    as part of the V1.5.4 engine decomposition. Behavior must stay
    byte-identical. The data_profile lineage now reads ctx.data.artifact_id
    (which is "cleaned_dataset" after CleaningStage) — a lineage-correctness
    improvement that produces the same literal value.
    """

    name = "profiling"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        cleaned = ctx.data.frame
        run_root = env.run_root

        env.step("profiling", "start", "Profiling data...")
        profile = profile_frame(cleaned)
        env.step("profiling", "complete", f"Profiled {profile['row_count']} rows")
        profile_path = run_root / "staged" / "data_profile.json"
        write_json(profile_path, profile)
        register_artifact(
            run_root,
            "data_profile",
            profile_path,
            "profile",
            "profiling",
            [ctx.data.artifact_id],
        )

        ctx.artifacts["_profile"] = profile
        return ctx
