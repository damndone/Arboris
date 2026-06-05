from __future__ import annotations

import pandas as pd

from ...imputation import run_mice_imputation
from ..context import DataHandle, ModelingContext, RunEnv
from ..imputation_registry import ImputationMethod, register_imputation_method


register_imputation_method(ImputationMethod(
    key="mice",
    label="MICE (Multiple Imputation)",
    description=(
        "Multiple Imputation by Chained Equations. Recommended when more than "
        "5-10% of rows would otherwise be dropped due to missing values."
    ),
))


class ImputationStage:
    """Optionally swap the modeling frame to the MICE-imputed dataset.

    Extracted verbatim from orchestrator._run_workflow (the imputation block)
    as part of the V1.5.4 engine decomposition. Behavior must stay
    byte-identical.

    This is the epicenter of the "fit on data A, record data B" bug class:
    after the (config-gated) MICE branch succeeds, the modeling frame and its
    lineage id are bound into ONE DataHandle via ``with_data``, so the frame the
    model is fit on and the artifact_id recorded for lineage cannot diverge.

    On entry ``ctx.data`` is the cleaned handle (artifact_id == "cleaned_dataset"),
    so the baseline (no-imputation) path is a no-op: the working handle already
    is the cleaned frame. Only when ``config.imputation_method == "mice"`` and the
    imputation completes does the handle atomically swap to "imputed_dataset".
    """

    name = "imputation"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        config = ctx.artifacts["_config"]
        cleaned = ctx.data.frame
        normalized_y = ctx.artifacts["_normalized_y"]
        normalized_x = ctx.artifacts["_normalized_x"]
        run_root = env.run_root
        request = ctx.artifacts.get("_imputation_request")
        method = request.get("method") if isinstance(request, dict) else config.imputation_method

        imputation_summary: dict | None = None
        if method == "mice":
            imputation_summary = run_mice_imputation(
                cleaned,
                run_root,
                [normalized_y, *normalized_x],
                m=config.imputation_m,
                max_iter=config.imputation_max_iter,
                random_seed=config.random_seed,
                max_missing_rate=config.max_missing_rate,
            )
            if imputation_summary.get("status") == "completed":
                imputed = pd.read_parquet(run_root / "processed" / "imputed_dataset.parquet")
                ctx = ctx.with_data(
                    DataHandle.of(
                        imputed,
                        artifact_id="imputed_dataset",
                        provenance=("cleaned_dataset",),
                    )
                )

        ctx.artifacts["_imputation_summary"] = imputation_summary
        # Stash the modeling-handle id list for downstream stages
        # (Diagnostics needs it for lineage ``inputs=`` references).
        # After this stage ctx.data.artifact_id is either "cleaned_dataset"
        # (baseline path) or "imputed_dataset" (MICE completed); the list
        # must reflect whichever handle the model is fit on.
        ctx.artifacts["_model_input_ids"] = [ctx.data.artifact_id]
        return ctx
