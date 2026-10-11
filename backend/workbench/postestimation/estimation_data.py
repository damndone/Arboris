"""The estimation sample of a completed model, recovered from its lineage.

Marginal effects need the regressors the model was estimated on. They are read
from the run's cleaned dataset, the model's own input, and the rows are
checked against the sample fingerprint the kernel recorded at fit time. If the
rows cannot be shown to be the same, the request is refused rather than
answered on different data.
"""

from __future__ import annotations

from collections.abc import Mapping
import io
import json
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from ..artifacts import read_json
from ..contracts.model.inference_kernel import estimation_rows_fingerprint
from .core import PostestimationRefusal

#: How the families name their constant term.
INTERCEPT_NAMES = frozenset({"Intercept", "const", "(Intercept)"})
_DATASET_ARTIFACT_TYPE = "processed_data"


def _dataset_path(run_root: Path) -> Path:
    index = read_json(run_root / "artifacts_index.json")
    paths = [
        item["path"] for item in index.get("artifacts", [])
        if item.get("artifact_type") == _DATASET_ARTIFACT_TYPE and str(item.get("path", "")).endswith(".parquet")
    ]
    if len(paths) != 1:
        raise PostestimationRefusal(
            "ESTIMATION_DATA_UNAVAILABLE", "the model's estimation data could not be located in its run"
        )
    return run_root / paths[0]


def _outcome(run_root: Path) -> str:
    from .comparison_data import _bound_bytes

    summary = json.loads(_bound_bytes(run_root, run_root / "diagnostic_summary.json"))
    identity = summary.get("model_identity") if isinstance(summary, Mapping) else None
    outcome = identity.get("y_variable") if isinstance(identity, Mapping) else None
    if not isinstance(outcome, str) or not outcome:
        raise PostestimationRefusal("ESTIMATION_DATA_UNAVAILABLE", "the run does not record its outcome variable")
    return outcome


def estimation_design(run_root: Path, kernel: Mapping[str, Any]) -> dict[str, np.ndarray]:
    """Each coefficient's column of the estimation sample, in kernel order."""
    if kernel.get("weights") not in (None, "none"):
        raise PostestimationRefusal(
            "WEIGHTED_SAMPLE",
            "the model was estimated with weights; weighted marginal effects are not offered yet",
        )
    fingerprint = kernel.get("estimation_sample_fingerprint")
    if not fingerprint:
        raise PostestimationRefusal(
            "SAMPLE_UNVERIFIED",
            "the model does not record its estimation sample, so the data for marginal effects "
            "cannot be verified",
        )
    from ..contracts.model.result_envelope_registry import declaration_for

    declaration = declaration_for(str(kernel["model_type"]))
    if declaration is not None and declaration.estimation_design_loader is not None:
        return declaration.estimation_design_loader(run_root, kernel)
    from .comparison_data import _bound_bytes

    frame = pd.read_parquet(io.BytesIO(_bound_bytes(run_root, _dataset_path(run_root))))
    names = list(kernel["param_names"])
    regressors = [name for name in names if name not in INTERCEPT_NAMES]
    not_columns = [name for name in regressors if name not in frame.columns]
    if not_columns:
        raise PostestimationRefusal(
            "TRANSFORMED_TERM",
            f"{', '.join(not_columns)} enter the model as transformed, categorical or interaction "
            "terms; marginal effects are offered only for regressors that enter as a single column",
        )
    outcome = _outcome(run_root)
    sample = frame.dropna(subset=[outcome, *regressors])
    if estimation_rows_fingerprint(list(sample.index)) != fingerprint:
        raise PostestimationRefusal(
            "DIFFERENT_SAMPLES",
            "the rows available now are not the rows the model was estimated on, so marginal "
            "effects would describe different data",
        )
    design: dict[str, np.ndarray] = {}
    for name in names:
        if name in INTERCEPT_NAMES:
            design[name] = np.ones(len(sample))
            continue
        values = pd.to_numeric(sample[name], errors="coerce")
        if values.isna().any():
            raise PostestimationRefusal("TRANSFORMED_TERM", f"{name} is not numeric in the estimation data")
        design[name] = values.to_numpy(dtype=float)
    return design
