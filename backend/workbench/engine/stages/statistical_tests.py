from __future__ import annotations

from ..context import ModelingContext, RunEnv
from ...orchestrator._errors import WorkflowValidationError


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
        dataset_sha256 = str(ctx.artifacts.get("_upload_hash") or "")
        if len(dataset_sha256) != 64 or any(
            character not in "0123456789abcdef" for character in dataset_sha256
        ):
            dataset_sha256 = None
        paired_columns, reference_means = _declared_test_targets(
            ctx.artifacts.get("_statistical_tests_request"), cleaned
        )
        # An explicitly declared paired or one-sample target is a request for
        # that test, so its columns join the analysis set even when they are
        # not model predictors.
        for extra in [name for pair in (paired_columns or ()) for name in pair] + list(
            reference_means or ()
        ):
            if extra not in stat_analysis_columns:
                stat_analysis_columns.append(extra)
        statistical_tests = run_statistical_tests(
            cleaned,
            analysis_columns=stat_analysis_columns,
            dataset_sha256=dataset_sha256,
            lineage_parent=str(ctx.data.artifact_id or "cleaned_dataset"),
            paired_columns=paired_columns,
            reference_means=reference_means,
        )
        write_statistical_test_artifacts(run_root, statistical_tests)
        statistical_test_summaries = summarize_statistical_tests(
            statistical_tests, y=normalized_y
        )
        env.step("statistical_tests", "complete", "Statistical tests completed")

        ctx.artifacts["_statistical_tests"] = statistical_tests
        ctx.artifacts["_statistical_test_summaries"] = statistical_test_summaries
        return ctx


def _declared_test_targets(
    request: object,
    frame: "object",
) -> tuple[list[tuple[str, str]] | None, dict[str, float] | None]:
    """Read the explicitly declared paired and one-sample test targets.

    Pairing carries meaning that column order cannot supply, so a malformed
    pair is rejected rather than guessed.  Absent declarations simply leave the
    corresponding tests out of the packet.
    """

    if not isinstance(request, dict):
        return None, None
    columns = set(getattr(frame, "columns", []))

    raw_pairs = request.get("paired_columns")
    paired: list[tuple[str, str]] | None = None
    if raw_pairs is not None:
        if not isinstance(raw_pairs, (list, tuple)):
            raise WorkflowValidationError(
                "STATISTICAL_TESTS_PAIR_INVALID",
                "paired_columns must be a list of "
                "two-column pairs, for example [[\"before\", \"after\"]]"
            )
        paired = []
        for pair in raw_pairs:
            if not isinstance(pair, (list, tuple)) or len(pair) != 2:
                raise WorkflowValidationError(
                    "STATISTICAL_TESTS_PAIR_INVALID",
                    "each paired_columns entry must "
                    "name exactly two columns; pairing is never inferred from column "
                    "order"
                )
            left, right = str(pair[0]), str(pair[1])
            missing = [name for name in (left, right) if name not in columns]
            if missing:
                raise WorkflowValidationError(
                    "STATISTICAL_TESTS_PAIR_INVALID",
                    "paired_columns names absent "
                    f"columns {missing}"
                )
            if left == right:
                raise WorkflowValidationError(
                    "STATISTICAL_TESTS_PAIR_INVALID",
                    "a paired test needs two distinct "
                    f"columns, got {left!r} twice"
                )
            paired.append((left, right))

    raw_means = request.get("reference_means")
    means: dict[str, float] | None = None
    if raw_means is not None:
        if not isinstance(raw_means, dict):
            raise WorkflowValidationError(
                "STATISTICAL_TESTS_REFERENCE_MEAN_INVALID",
                "reference_means must map "
                "a column to its hypothesised population mean"
            )
        means = {}
        for column, value in raw_means.items():
            name = str(column)
            if name not in columns:
                raise WorkflowValidationError(
                    "STATISTICAL_TESTS_REFERENCE_MEAN_INVALID",
                    "reference_means names "
                    f"an absent column {name!r}"
                )
            try:
                means[name] = float(value)
            except (TypeError, ValueError) as error:
                raise WorkflowValidationError(
                    "STATISTICAL_TESTS_REFERENCE_MEAN_INVALID",
                    "reference_means value "
                    f"for {name!r} must be a finite number"
                ) from error
    return paired or None, means or None
