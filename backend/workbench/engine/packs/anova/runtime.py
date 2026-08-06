"""Registry wiring for the ANOVA family."""

from __future__ import annotations

from typing import Any

from ...registry import ModelHandler
from .estimation import fit_anova, validate_anova_model_options

#: Accepted keys, documented here rather than enforced by the version
#: contract, which carries producer/input versions only.
_ACCEPTED_OPTION_KEYS = ("sums_of_squares", "categorical", "interactions", "posthoc")


def _fit(ctx, env):
    options = dict(ctx.artifacts.get("_model_options") or {})
    result = fit_anova(
        ctx.data.frame,
        y=ctx.artifacts["_normalized_y"],
        x=ctx.artifacts["_normalized_x"],
        options=options,
        model_id="anova_1",
    )
    return "anova_1", result, None


def model_handlers() -> dict[str, ModelHandler]:
    from ....model_options import ModelOptionsContract

    return {
        "anova": ModelHandler(
            model_type="anova",
            model_id="anova_1",
            serves_y_types=("continuous",),
            fit=_fit,
            validate_model_options=lambda options: validate_anova_model_options(options),
            model_options_contract=ModelOptionsContract(
                producer_version="anova@1.0",
                input_contract_version="1.0",
            ),
        )
    }
