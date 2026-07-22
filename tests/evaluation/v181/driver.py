"""Public-seam driver for the ETS Model Pack under evaluation.

The evaluation lane does not read the Model Pack Lane's implementation. It
drives the *public* seams that already exist in the v1.7.2 baseline and that the
locked contract implies the pack must plug into:

* ``MODEL_REGISTRY['time_series.ets'].fit(ctx, env) -> (model_id, result, fitted)``
* ``MODEL_REGISTRY['time_series.ets'].validate_model_options(options)``

The option *payload* shape is not locked by the Contract Sprint — only the
result is (``ETSResultContract``). The driver therefore offers the specification
under both the nested and the flat spelling and records which one the pack
accepted; if neither is accepted that is reported as a contract gap, not
patched.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

TIME_COLUMN = "when"
VALUE_COLUMN = "value"


class ETSPackUnavailable(RuntimeError):
    """The pack under evaluation is not registered."""


class ETSOptionsRejected(RuntimeError):
    """The pack refused the options payload (validation-time refusal)."""


@dataclass
class _Recorder:
    nodes: list[dict[str, Any]] | None = None
    edges: list[dict[str, Any]] | None = None

    def __post_init__(self) -> None:
        self.nodes = []
        self.edges = []

    def record_stage(self, node_id, display_label, **kwargs) -> None:
        self.nodes.append({"node_id": node_id, "display_label": display_label})

    def record_edge(self, edge_id, source_id, target_id, op, **kwargs) -> None:
        self.edges.append({"edge_id": edge_id, "op": op})


def frame_for(values: np.ndarray) -> pd.DataFrame:
    """A regular business-day frame carrying the synthetic series."""

    return pd.DataFrame(
        {
            TIME_COLUMN: pd.bdate_range("2000-01-03", periods=len(values)),
            VALUE_COLUMN: np.asarray(values, dtype=float),
        }
    )


def ets_options(spec: dict[str, Any], *, flat: bool = False) -> dict[str, Any]:
    """Options built from the contract's own field names."""

    base: dict[str, Any] = {
        "dataset_ref": "dataset:evaluation:v181",
        "time_column": TIME_COLUMN,
        "value_column": VALUE_COLUMN,
        "fit_method": "mle",
    }
    if flat:
        base.update(spec)
    else:
        base["specification"] = dict(spec)
    return base


def fit_ets(
    values: np.ndarray,
    spec: dict[str, Any],
    *,
    tmp_path: Path,
    run_id: str = "eval-ets",
) -> tuple[dict[str, Any], dict[str, Any]]:
    """Run the registered pack once. Returns ``(result, metadata)``.

    Raises ``ETSPackUnavailable`` when the Model Pack Lane has not landed, and
    ``ETSOptionsRejected`` when the pack refuses the options (which is the
    correct behaviour for an illegal specification).
    """

    from workbench.contracts.model.ets import ETS_MODEL_TYPE
    from workbench.engine.context import DataHandle, ModelingContext, RunEnv
    from workbench.engine.packs import bootstrap_builtin_packs
    from workbench.engine.registry import (
        MODEL_REGISTRY,
        ModelOptionsValidationError,
    )

    try:
        bootstrap_builtin_packs()
    except Exception:
        pass
    handler = MODEL_REGISTRY.get(ETS_MODEL_TYPE)
    if handler is None:
        raise ETSPackUnavailable(
            f"{ETS_MODEL_TYPE} is not in MODEL_REGISTRY; registered: "
            f"{sorted(MODEL_REGISTRY)}"
        )

    source = frame_for(values)
    run_root = Path(tmp_path) / run_id
    run_root.mkdir(parents=True, exist_ok=True)
    (run_root / "artifacts_index.json").write_text(
        json.dumps({"artifacts": []}), encoding="utf-8"
    )

    last_error: Exception | None = None
    for flat in (False, True):
        options = ets_options(spec, flat=flat)
        if handler.validate_model_options is not None:
            try:
                handler.validate_model_options(options)
            except ModelOptionsValidationError as error:
                last_error = error
                continue
            except (ValueError, TypeError, KeyError) as error:
                last_error = error
                continue
        ctx = ModelingContext(
            data=DataHandle.of(
                source.copy(deep=True),
                artifact_id="cleaned_dataset",
                provenance=("raw_input.csv",),
            ),
            y_col=VALUE_COLUMN,
            x_cols=[],
            y_type="continuous",
            requested_model_type=ETS_MODEL_TYPE,
        )
        ctx.artifacts.update(
            {
                "_model_options": options,
                "_frames": {"input.csv": source},
                "_upload_hash": "c" * 64,
                "_raw_inputs": ["raw_input.csv"],
            }
        )
        env = RunEnv(run_root=run_root, run_id=run_id, recorder=_Recorder())
        _model_id, result, _fitted = handler.fit(ctx, env)
        return result, {"options_shape": "flat" if flat else "nested"}

    raise ETSOptionsRejected(
        "the pack rejected both the nested and the flat contract-named options: "
        f"{last_error!r}"
    )


def reference_fit(values: np.ndarray, spec: dict[str, Any]) -> dict[str, float]:
    """An independent statsmodels ETS fit used as a secondary oracle.

    This is not the primary oracle — the DGP parameters are. It exists to catch
    wiring errors (wrong sample, wrong specification, rescaled likelihood) that
    parameter recovery alone would tolerate.
    """

    from statsmodels.tsa.exponential_smoothing.ets import ETSModel

    finite = np.asarray(values, dtype=float)
    finite = finite[np.isfinite(finite)]
    model = ETSModel(
        finite,
        error=spec["error"],
        trend=spec["trend"],
        seasonal=spec["seasonal"],
        seasonal_periods=spec["seasonal_periods"],
        damped_trend=spec["damped_trend"],
    )
    fitted = model.fit(disp=False)
    params = dict(zip(fitted.param_names, [float(v) for v in fitted.params]))
    return {
        "aic": float(fitted.aic),
        "bic": float(fitted.bic),
        "log_likelihood": float(fitted.llf),
        "sigma2": float(fitted.scale),
        "n_obs": int(fitted.nobs),
        "params": params,
    }


__all__ = [
    "ETSOptionsRejected",
    "ETSPackUnavailable",
    "TIME_COLUMN",
    "VALUE_COLUMN",
    "ets_options",
    "fit_ets",
    "frame_for",
    "reference_fit",
]
