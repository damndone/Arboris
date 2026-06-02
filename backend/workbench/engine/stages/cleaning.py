from __future__ import annotations

from ...artifacts import register_artifact, write_json
from ...cleaning import clean_frame
from ..context import DataHandle, ModelingContext, RunEnv


class CleaningStage:
    """Clean the raw frame and promote the result to a DataHandle.

    Extracted verbatim from orchestrator._run_workflow (the cleaning block) as
    part of the V1.5.4 engine decomposition. Behavior must stay byte-identical.
    """

    name = "cleaning"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        frame = ctx.data.frame
        schema = ctx.artifacts["_schema"]
        input_files = ctx.artifacts["_input_files"]
        run_root = env.run_root

        env.step("cleaning", "start", "Cleaning data...")
        cleaned, actions = clean_frame(frame, list(schema.time_candidates))
        env.step("cleaning", "complete", f"Applied {len(actions)} cleaning actions")
        raw_inputs = [f"raw_{path.name}" for path in input_files]
        cleaning_path = run_root / "processed" / "cleaning_actions.json"
        write_json(cleaning_path, {"actions": actions})
        register_artifact(
            run_root,
            "cleaning_actions",
            cleaning_path,
            "metadata",
            "cleaning",
            raw_inputs,
        )
        cleaned_path = run_root / "processed" / "cleaned_dataset.parquet"
        cleaned.to_parquet(cleaned_path, index=False)
        register_artifact(
            run_root,
            "cleaned_dataset",
            cleaned_path,
            "processed_data",
            "cleaning",
            raw_inputs,
        )

        ctx = ctx.with_data(
            DataHandle.of(
                cleaned,
                artifact_id="cleaned_dataset",
                provenance=tuple(raw_inputs),
            )
        )
        ctx.artifacts["_actions"] = actions
        ctx.artifacts["_raw_inputs"] = raw_inputs
        # Stash the cleaned frame separately so post-imputation stages
        # (diagnostics, reliability, report) can read it even after
        # ImputationStage swaps ``ctx.data`` to the imputed handle.
        ctx.artifacts["_cleaned"] = cleaned
        return ctx
