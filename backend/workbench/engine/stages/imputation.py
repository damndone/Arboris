from __future__ import annotations

import pandas as pd

from ...artifacts import register_artifact, write_json
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
    is the cleaned frame. Explicit single imputation swaps to one
    ``imputed_dataset`` handle. Multiple imputation exposes every typed handle
    without selecting the first; estimation fits each and pools them
    (``combinators.multiple_imputation``).
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

        m = request.get("m", config.imputation_m) if isinstance(request, dict) else config.imputation_m

        imputation_summary: dict | None = None
        # A malformed m is left to run_mice_imputation, which names what is wrong.
        multiple = type(m) is int and m > 1
        if method == "mice" and multiple and str(ctx.artifacts.get("_sampling_weight") or "").strip():
            # Refused before any dataset is drawn: the imputation model would have
            # to reflect the design (strata, clusters, weights), and pooling
            # design-based variances needs the design's degrees of freedom.
            return _block(
                ctx, env, "MI_WITH_SURVEY_DESIGN",
                "Multiple imputation with a complex sampling design is not supported yet: the "
                "imputation model would have to reflect the design, and pooling design-based "
                "variances needs the design's degrees of freedom. Nothing was imputed or fitted.",
                {"m": m, "sampling_weight": ctx.artifacts.get("_sampling_weight")},
            )
        by_group = ctx.artifacts.get("_by_group_request")
        if method == "mice" and multiple and by_group:
            # Found by the v1.8.10 evaluation (A03): the run pooled the imputations
            # and silently dropped the grouping. The Agent's planner already
            # refuses this pair; a direct request must not do less.
            return _block(
                ctx, env, "MI_WITH_BY_GROUP",
                "Multiple imputation combined with by-group execution is not supported yet: "
                "pooling would have to be done within each group. Run them separately. "
                "Nothing was imputed or fitted.",
                {"m": m, "by_group": by_group},
            )
        if method == "mice":
            imputation_summary = run_mice_imputation(
                cleaned,
                run_root,
                [normalized_y, *normalized_x],
                m=m,
                max_iter=config.imputation_max_iter,
                random_seed=config.random_seed,
                max_missing_rate=config.max_missing_rate,
            )
            if imputation_summary.get("status") == "completed":
                records = imputation_summary.get("dataset_artifacts") or []
                handles: list[DataHandle] = []
                for record in records:
                    if not isinstance(record, dict):
                        raise ValueError("MICE_DATASET_RECORD_INVALID")
                    artifact_id = record.get("artifact_id")
                    relative_path = record.get("path")
                    if (
                        not isinstance(artifact_id, str)
                        or not artifact_id
                        or not isinstance(relative_path, str)
                        or not relative_path
                    ):
                        raise ValueError("MICE_DATASET_RECORD_INVALID")
                    dataset_path = run_root / relative_path
                    if run_root.resolve() not in dataset_path.resolve().parents:
                        raise ValueError("MICE_DATASET_PATH_OUTSIDE_RUN")
                    imputed = pd.read_parquet(dataset_path)
                    handles.append(
                        DataHandle.of(
                            imputed,
                            artifact_id=artifact_id,
                            provenance=("cleaned_dataset",),
                        )
                    )
                if not handles:
                    raise ValueError("MICE_DATASET_HANDLES_MISSING")
                ctx.artifacts["_imputation_handles"] = handles
                ctx.artifacts["_imputation_dataset_ids"] = [
                    handle.artifact_id for handle in handles
                ]
                if len(handles) == 1:
                    ctx = ctx.with_data(handles[0])
            imputation_summary = {
                **imputation_summary,
                "input_artifact": "cleaned_dataset",
                "output_artifact": (
                    "imputed_dataset"
                    if imputation_summary.get("status") == "completed"
                    and imputation_summary.get("mode") == "single_imputation"
                    else (
                        "mice_manifest"
                        if imputation_summary.get("status") == "completed"
                        and imputation_summary.get("mode") == "multiple_imputation"
                        else None
                    )
                ),
                "output_artifacts": (
                    [
                        handle.artifact_id
                        for handle in ctx.artifacts.get("_imputation_handles", [])
                    ]
                    if imputation_summary.get("status") == "completed"
                    else None
                ),
            }
            summary_path = run_root / "imputation_summary.json"
            write_json(summary_path, imputation_summary)
            register_artifact(
                run_root,
                "imputation_summary",
                summary_path,
                "metadata",
                "imputation",
                ["cleaned_dataset"],
            )

        ctx.artifacts["_imputation_summary"] = imputation_summary
        # Stash the modeling-handle id list for downstream stages
        # (Diagnostics needs it for lineage ``inputs=`` references).
        # After this stage ctx.data.artifact_id is either "cleaned_dataset"
        # (baseline path) or "imputed_dataset" (MICE completed); the list
        # must reflect whichever handle the model is fit on.
        if ctx.artifacts.get("_imputation_handles"):
            ctx.artifacts["_model_input_ids"] = [
                handle.artifact_id
                for handle in ctx.artifacts["_imputation_handles"]
            ]
        else:
            ctx.artifacts["_model_input_ids"] = [ctx.data.artifact_id]

        if (
            imputation_summary
            and imputation_summary.get("method") == "mice"
            and (
                imputation_summary.get("status") == "failed"
                or imputation_summary.get("remaining_missing_columns")
            )
        ):
            reasons = [text for text in imputation_summary.get("warnings", [])
                       if text.startswith(("Multiple imputation was not run", "MICE"))]
            return _block(
                ctx, env, "MI_IMPUTATION_FAILED",
                " ".join(reasons) or (
                    "MICE did not produce a complete validated dataset set; "
                    "estimation was blocked before any fallback fit."
                ),
                {
                    "m": imputation_summary.get("m"),
                    "remaining_missing_columns": imputation_summary.get("remaining_missing_columns", []),
                    "failure_reason": imputation_summary.get("failure_reason"),
                },
            )

        return ctx


def _block(ctx: ModelingContext, env: RunEnv, code: str, message: str, evidence: dict) -> ModelingContext:
    """Stop the run before estimation, with the reason recorded where the UI reads it."""
    from ...orchestrator import _lineage, _safe_flush_recorder, _write_manifest

    issue = {"severity": "blocker", "code": code, "message": message, "evidence": evidence}
    write_json(env.run_root / "errors.json", {"issues": [issue]})
    _write_manifest(
        env.run_root,
        env.run_id,
        ctx.artifacts["_mode"],
        "blocked",
        _lineage(ctx.artifacts["_input_files"]),
        started_at=ctx.artifacts["_started_at"],
        y=ctx.artifacts["_y"],
        x=ctx.artifacts["_x"],
        requested_model_type=ctx.artifacts["_model_type"],
    )
    env.step("imputation", "blocked", message)
    _safe_flush_recorder(env.recorder, context="blocked@imputation")
    ctx.terminal_status = "blocked"
    return ctx
