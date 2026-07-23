"""Deterministic entry points for the v1.8.1 `time_series.ets` pack."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

import pandas as pd

from .estimation import ETSFitOutcome, estimate_ets
from .errors import ETSInputError
from .input import ETSModelOptions, prepare_ets_input


MODEL_ID = "ets_1"


def fit_ets(frame: pd.DataFrame, options: Mapping[str, Any]) -> ETSFitOutcome:
    """Validate options and data, then fit one ETS specification."""

    validated = ETSModelOptions.from_dict(options)
    prepared = prepare_ets_input(frame, validated)
    return estimate_ets(prepared)


def fit_from_context(ctx: Any, env: Any) -> tuple[str, dict[str, Any], None]:
    """Engine-handler adapter: normalized context in, public packet out."""

    options = ctx.artifacts.get("_model_options")
    if not isinstance(options, Mapping):
        raise ValueError("ETS model_options must be a mapping")
    env.progress("ets", "Preparing the ETS modelled series.")
    try:
        outcome = fit_ets(ctx.data.frame, options)
    except ETSInputError as error:
        ctx.artifacts["_ets_diagnostic"] = error.to_dict()
        raise
    packet = outcome.to_dict()
    ctx.artifacts["_ets_result"] = packet
    env.progress("ets", "ETS fit completed.")
    env.checkpoint()
    return MODEL_ID, packet, None


__all__ = ["MODEL_ID", "fit_ets", "fit_from_context"]
