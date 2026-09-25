"""Replicate weight construction — the general variance channel.

This is what makes the engine work for estimators Taylor linearization cannot
touch: it never needs an influence function, because it simply re-runs the whole
estimator under each set of weights.  Quantile regression, panel fixed effects,
DID and anything an agent writes in the sandbox all reach a design-based variance
through here.

It is also not optional in practice.  NHANES, CPS and similar surveys publish
replicate weights and name them as the recommended variance method, so a system
without this channel cannot follow the publisher's own instructions.
"""

from __future__ import annotations

import numpy as np
import pandas as pd
from scipy.linalg import hadamard

from .design import SurveyDesign, _validated_weight_array
from .errors import SurveyEngineError


def build_replicates(
    design: SurveyDesign, replicate_type: str | None
) -> tuple[np.ndarray, list[float]]:
    """Return (n_obs x n_replicates) weights and the per-replicate scale factors."""
    if (
        replicate_type is not None
        and design.replicate_type is not None
        and replicate_type != design.replicate_type
    ):
        raise SurveyEngineError(
            "SURVEY_REPLICATE_DECLARATION_MISMATCH",
            "the requested replicate method does not match the declared survey design",
            declared_replicate_type=design.replicate_type,
            requested_replicate_type=replicate_type,
        )
    kind = replicate_type or design.replicate_type
    if kind is None:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_TYPE_REQUIRED",
            "the replicate channel needs a replicate_type",
        )
    if kind == "provided":
        weights, scales = _provided(design)
        return _validate_replicates(design, weights, scales)
    if design.replicate_weight_columns:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_COLUMNS_UNSUPPORTED",
            f"replicate_type={kind!r} generates weights and cannot carry replicate columns; "
            "use replicate_type='provided' to consume named columns",
            replicate_type=kind,
            replicate_weight_columns=list(design.replicate_weight_columns)[:16],
        )
    if kind == "jackknife":
        weights, scales = _jackknife(design)
    elif kind == "brr":
        weights, scales = _brr(design)
    elif kind == "bootstrap":
        weights, scales = _bootstrap(design)
    else:
        raise SurveyEngineError("SURVEY_REPLICATE_TYPE_INVALID", kind)
    return _validate_replicates(design, weights, scales)


def _validate_replicates(
    design: SurveyDesign,
    weights: np.ndarray,
    scales: list[float],
) -> tuple[np.ndarray, list[float]]:
    """Validate generated and publisher-supplied weights at one boundary."""

    try:
        matrix = np.asarray(weights, dtype=float)
    except (TypeError, ValueError, OverflowError) as exc:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_INVALID",
            "replicate weights cannot be represented as finite numeric values",
            reason="non_numeric",
        ) from exc
    if matrix.ndim != 2 or matrix.shape[0] != len(design.frame) or matrix.shape[1] < 1:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_INVALID",
            "replicate weights must be a non-empty observation-by-replicate matrix",
            reason="shape",
            expected_rows=len(design.frame),
            actual_shape=list(matrix.shape),
        )
    if not np.isfinite(matrix).all():
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_INVALID",
            "replicate weights must be finite",
            reason="nonfinite",
        )
    if (matrix < 0).any():
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_INVALID",
            "replicate weights must be nonnegative",
            reason="negative",
        )
    try:
        normalized_scales = [float(scale) for scale in scales]
    except (TypeError, ValueError, OverflowError) as exc:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_INVALID",
            "replicate scales must be finite positive numbers",
            reason="scale_invalid",
        ) from exc
    if len(normalized_scales) != matrix.shape[1] or any(
        not np.isfinite(scale) or scale <= 0 for scale in normalized_scales
    ):
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_INVALID",
            "replicate scales must align with the weight matrix and be positive",
            reason="scale_invalid",
            expected_replicates=matrix.shape[1],
            actual_scales=len(normalized_scales),
        )
    return matrix, normalized_scales


def _psu_index(design: SurveyDesign) -> tuple[np.ndarray, np.ndarray, dict[str, list[int]]]:
    strata = design._stratum_key.to_numpy()
    psu = design._psu_key.to_numpy()
    groups: dict[str, list[int]] = {}
    for stratum in pd.unique(strata):
        groups[str(stratum)] = list(pd.unique(psu[strata == stratum]))
    return strata, psu, groups


def _provided(design: SurveyDesign) -> tuple[np.ndarray, list[float]]:
    columns = design.replicate_weight_columns
    if not columns:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_MISSING",
            "replicate_type='provided' requires replicate_weight_columns",
        )
    missing = [c for c in columns if c not in design.frame.columns]
    if missing:
        raise SurveyEngineError(
            "SURVEY_REPLICATE_WEIGHTS_MISSING", f"missing columns: {', '.join(missing)}"
        )
    weights = np.column_stack(
        [
            _validated_weight_array(
                design.frame,
                column,
                allow_zero=True,
                error_code="SURVEY_REPLICATE_WEIGHT_INVALID",
            )
            for column in columns
        ]
    )
    # Published replicate weights are combined weights (the sampling weight is
    # already folded in), which is the NHANES/CPS convention.
    scales = [1.0 / weights.shape[1]] * weights.shape[1]
    return weights, scales


def _jackknife(design: SurveyDesign) -> tuple[np.ndarray, list[float]]:
    """Stratified delete-one-PSU jackknife (R's JKn).

    Dropping PSU i in stratum h reweights the remaining PSUs of that stratum by
    n_h/(n_h-1); the replicate carries scale (n_h-1)/n_h.
    """
    strata, psu, groups = _psu_index(design)
    base = design.weights
    columns: list[np.ndarray] = []
    scales: list[float] = []

    for stratum, psu_ids in groups.items():
        n_h = len(psu_ids)
        if n_h < 2:
            raise SurveyEngineError(
                "SURVEY_LONELY_PSU",
                f"stratum {stratum!r} has a single PSU; the jackknife needs at least two",
                strata=[stratum],
            )
        in_stratum = strata == stratum
        for dropped in psu_ids:
            w = base.copy()
            w[in_stratum] *= n_h / (n_h - 1)
            w[psu == dropped] = 0.0
            columns.append(w)
            scales.append((n_h - 1) / n_h)

    return np.column_stack(columns), scales


def _brr(design: SurveyDesign) -> tuple[np.ndarray, list[float]]:
    """Balanced repeated replication over a Hadamard design.

    Requires exactly two PSUs per stratum -- that is the definition, not a
    limitation we chose, and a design that does not satisfy it must be told so
    rather than quietly handed a different method.
    """
    strata, psu, groups = _psu_index(design)
    bad = {h: len(ids) for h, ids in groups.items() if len(ids) != 2}
    if bad:
        raise SurveyEngineError(
            "SURVEY_BRR_REQUIRES_TWO_PSU_PER_STRATUM",
            f"strata with other than two PSUs: {sorted(bad)}",
            strata=sorted(bad),
        )

    stratum_names = sorted(groups)
    n_strata = len(stratum_names)

    # BRR is NOT uniquely defined: the estimate depends on which balanced set of
    # half-samples is used.  Measured on the committed fixture, R returns
    # 1.62518598 from its 12-replicate matrix and 1.70845732 from a 20-replicate
    # one, and a 16-replicate Sylvester matrix gives a third value -- all valid.
    # So the balanced set is part of the specification, not an implementation
    # detail, and a BRR standard error reported without naming its set is
    # under-specified.  Callers may supply one; otherwise a Sylvester matrix is
    # built and recorded on the result.
    if design.hadamard_matrix is not None:
        try:
            matrix = np.asarray(design.hadamard_matrix)
        except (TypeError, ValueError) as exc:
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_INVALID",
                "custom BRR matrix must be a finite numeric matrix",
            ) from exc
        if matrix.ndim != 2 or matrix.size == 0 or not np.issubdtype(matrix.dtype, np.number):
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_INVALID",
                "custom BRR matrix must be a two-dimensional numeric matrix",
            )
        if not np.isfinite(matrix).all():
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_INVALID",
                "custom BRR matrix must contain only finite values",
            )
        if matrix.shape[0] < n_strata + 1 or matrix.shape[1] < n_strata + 1:
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_TOO_SMALL",
                f"a {matrix.shape} matrix cannot balance {n_strata} strata",
            )
        unique_values = set(np.unique(matrix).tolist())
        if unique_values <= {0, 1}:
            normalized = np.where(matrix == 1, 1, -1)
        elif unique_values <= {-1, 1}:
            normalized = matrix.astype(int)
        else:
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_INVALID",
                "custom BRR matrix values must use either 0/1 or -1/1 coding",
            )
        if not np.all(normalized[:, 0] == 1):
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_INVALID",
                "custom BRR matrix must start with an all-positive reference column",
            )
        order = matrix.shape[0]
        # R emits 0/1; convert to the +/-1 half-sample selector, dropping the
        # leading all-ones column.
        selector = normalized[:, 1 : n_strata + 1]
        if (selector.sum(axis=0) != 0).any():
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_UNBALANCED",
                "custom BRR selector columns must contain equal positive and negative assignments",
            )
        gram = selector.T @ selector
        off_diagonal = gram - np.diag(np.diag(gram))
        if (off_diagonal != 0).any():
            raise SurveyEngineError(
                "SURVEY_BRR_HADAMARD_NOT_ORTHOGONAL",
                "custom BRR selector columns must be pairwise orthogonal",
            )
    else:
        order = 1
        while order < n_strata + 1:
            order *= 2
        selector = hadamard(order)[:, 1 : n_strata + 1]

    base = design.weights
    columns: list[np.ndarray] = []
    for row in selector:
        w = base.copy()
        for sign, stratum in zip(row, stratum_names, strict=True):
            first, second = groups[stratum]
            keep, drop = (first, second) if sign > 0 else (second, first)
            w[psu == keep] *= 2.0
            w[psu == drop] = 0.0
        columns.append(w)

    scales = [1.0 / order] * order
    return np.column_stack(columns), scales


def _bootstrap(design: SurveyDesign, replicates: int = 500, seed: int = 20260805) -> tuple[np.ndarray, list[float]]:
    """Rao-Wu rescaling bootstrap: resample PSUs within strata with replacement."""
    strata, psu, groups = _psu_index(design)
    rng = np.random.default_rng(seed)
    base = design.weights
    columns: list[np.ndarray] = []

    for _ in range(replicates):
        w = np.zeros_like(base)
        for stratum, psu_ids in groups.items():
            n_h = len(psu_ids)
            if n_h < 2:
                raise SurveyEngineError(
                    "SURVEY_BOOTSTRAP_REQUIRES_TWO_PSU_PER_STRATUM",
                    f"stratum {stratum!r} has fewer than two PSUs",
                    strata=[stratum],
                )
            drawn = rng.choice(n_h, size=n_h - 1, replace=True)
            counts = np.bincount(drawn, minlength=n_h)
            # Rao-Wu rescaling uses the nonnegative multiplicity of each PSU
            # in an n_h-1 draw, then restores the stratum total by n_h/(n_h-1).
            factor = counts * n_h / (n_h - 1)
            for pid, f in zip(psu_ids, factor, strict=True):
                rows = psu == pid
                w[rows] = base[rows] * f
        columns.append(w)

    scales = [1.0 / replicates] * replicates
    return np.column_stack(columns), scales
