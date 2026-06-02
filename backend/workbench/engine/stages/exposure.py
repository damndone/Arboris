from __future__ import annotations

from ..context import ModelingContext, RunEnv


class ExposureDetectionStage:
    """Detect an exposure/offset variable for count (Poisson rate) models.

    Extracted verbatim from orchestrator._run_workflow (the exposure detection
    block) as part of the V1.5.4 engine decomposition. Behavior must stay
    byte-identical.
    """

    name = "exposure"

    def run(self, ctx: ModelingContext, env: RunEnv) -> ModelingContext:
        # Lazy import to avoid a module-load cycle: orchestrator imports this
        # stage at the top of its module, while these helpers live there.
        from ...orchestrator import (
            _detect_exposure_candidates,
            _select_valid_exposure_col,
        )

        cleaned = ctx.data.frame
        normalized_x = ctx.artifacts["_normalized_x"]
        y_type = ctx.y_type

        # Detect exposure variable early for count models (needed before statistical tests and VIF)
        exposure_col = None
        if y_type == "count":
            exposure_candidates = _detect_exposure_candidates(normalized_x)
            if exposure_candidates:
                exposure_col = _select_valid_exposure_col(cleaned, exposure_candidates)

        ctx.exposure_col = exposure_col
        return ctx
