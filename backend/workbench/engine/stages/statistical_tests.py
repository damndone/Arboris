from __future__ import annotations

from ..context import ModelingContext, RunEnv


class StatisticalTestsStage:
    """Run statistical tests on the cleaned dataset (correlations, normality,
    Welch's t, etc.) and write their artifacts.

    Extracted verbatim from orchestrator._run_workflow (the block previously
    inlined between ExposureDetectionStage and ImputationStage) as part of the
    V1.5.4 engine decomposition. Behavior must stay byte-identical.

    CRITICAL ORDERING NOTE: this stage runs BEFORE ImputationStage so the
    tests see the cleaned-but-not-yet-imputed frame. The corresponding lineage
    artifacts have ``inputs=["cleaned_dataset"]``, which the goldens
    (specifically ``imputation.json``'s ``statistical_tests_*`` nodes) lock.
    Do NOT move this stage after ImputationStage — that would change the
    input lineage to ``imputed_dataset``.
    """

    name = "statistical_tests"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        from ...statistical_tests import (
            run_statistical_tests,
            summarize_statistical_tests,
            write_statistical_test_artifacts,
        )

        cleaned = ctx.data.frame
        normalized_y = ctx.artifacts["_normalized_y"]
        normalized_x = ctx.artifacts["_normalized_x"]
        exposure_col = ctx.exposure_col
        run_root = env.run_root

        env.step("statistical_tests", "start", "Running statistical tests...")
        stat_analysis_columns = [normalized_y] + [
            v for v in normalized_x if v != (exposure_col or "")
        ]
        statistical_tests = run_statistical_tests(
            cleaned,
            analysis_columns=stat_analysis_columns,
        )
        write_statistical_test_artifacts(run_root, statistical_tests)
        statistical_test_summaries = summarize_statistical_tests(
            statistical_tests, y=normalized_y
        )
        env.step("statistical_tests", "complete", "Statistical tests completed")

        ctx.artifacts["_statistical_tests"] = statistical_tests
        ctx.artifacts["_statistical_test_summaries"] = statistical_test_summaries
        return ctx
