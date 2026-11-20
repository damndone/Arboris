"""Covariance-compatible native IV diagnostics; strength is not certified."""
from __future__ import annotations
from dataclasses import dataclass
from typing import Any

import numpy as np
from scipy import stats

from ..checks.iv_checks import first_stage_diagnostic


class WuHausmanUnavailable(ValueError):
    """A classified scientific domain condition, not a point-estimation failure."""

    def __init__(self, reason: str, message: str):
        self.reason = reason
        super().__init__(f"IV_WU_HAUSMAN_UNAVAILABLE: {reason}: {message}")


@dataclass(frozen=True)
class _WuHausmanStatistic:
    stat: float
    df: int
    df_denom: int

    @property
    def dist_name(self) -> str:
        return f"F({self.df},{self.df_denom})"

    @property
    def pval(self) -> float:
        return float(stats.f.sf(self.stat, self.df, self.df_denom))


def _wu_normalized(matrix: np.ndarray) -> np.ndarray:
    scale = np.max(np.abs(matrix), axis=0)
    if np.any(scale == 0):
        raise WuHausmanUnavailable("rank_deficient_augmented_design", "The control-function design must have full column rank.")
    normalized = matrix / scale
    normalized /= np.linalg.norm(normalized, axis=0)
    return normalized


def _wu_basis(matrix: np.ndarray) -> np.ndarray:
    normalized = _wu_normalized(matrix)
    if np.linalg.matrix_rank(normalized) < normalized.shape[1]:
        raise WuHausmanUnavailable("rank_deficient_augmented_design", "The control-function design must have full column rank.")
    return np.linalg.qr(normalized, mode="reduced")[0]


def _wu_control_projection(y: np.ndarray, w: np.ndarray, d: np.ndarray, instruments: np.ndarray):
    """The scientific domain and QR coordinates shared by admission and inference."""
    tested = d.shape[1]
    df = len(y) - w.shape[1] - 2 * tested
    if tested == 0 or df <= 0:
        raise WuHausmanUnavailable("insufficient_residual_df", "The augmented regression requires positive residual degrees of freedom.")
    if not all(np.isfinite(array).all() for array in (y, w, d, instruments)):
        raise WuHausmanUnavailable("nonfinite_design", "The retained model design must be finite.")
    # Normalize D against its original units before assessing the augmented
    # rank: roundoff-only first-stage residuals must not become new regressors.
    scaled_d = _wu_normalized(d)
    qx = _wu_basis(np.column_stack([w, scaled_d]))
    qz = _wu_basis(np.column_stack([w, instruments]))
    outcome_scale = np.max(np.abs(y))
    if outcome_scale == 0:
        raise WuHausmanUnavailable("undefined_residual_variance", "The outcome has zero residual variance.")
    scaled_y = y / outcome_scale
    ordinary = scaled_y - qx @ (qx.T @ scaled_y)
    zero_tolerance = np.finfo(float).eps * max(len(y), qx.shape[1] + tested) * np.linalg.norm(scaled_y)
    if np.linalg.norm(ordinary) <= zero_tolerance:
        raise WuHausmanUnavailable("undefined_residual_variance", "The outcome has zero residual variance.")
    residuals = scaled_d - qz @ (qz.T @ scaled_d)
    controls = residuals - qx @ (qx.T @ residuals)
    if np.linalg.matrix_rank(np.column_stack([qx, controls])) < qx.shape[1] + tested:
        raise WuHausmanUnavailable("rank_deficient_augmented_design", "The first-stage controls add no independently estimable directions.")
    qu = _wu_basis(controls)
    coordinates = qu.T @ ordinary
    augmented_residuals = ordinary - qu @ coordinates
    if np.linalg.norm(augmented_residuals) <= zero_tolerance:
        raise WuHausmanUnavailable("undefined_residual_variance", "The augmented regression has zero residual variance.")
    return coordinates, augmented_residuals, tested, df


def reference_wu_hausman(fitted: Any) -> _WuHausmanStatistic:
    """Owned, unweighted Wu T2 for a joint test of all endogenous regressors.

    With Z=[included exogenous, excluded instruments], residual inclusion is
    algebraically the full-Z Wu test. QR coordinates avoid subtracting two
    nearly equal residual sums of squares. The reference fit is never patched.
    """
    model = fitted.model
    if not np.all(model.weights.ndarray == 1):
        raise WuHausmanUnavailable("weighted_model", "Weighted Wu-Hausman inference has not been validated.")
    coordinates, residuals, tested, df = _wu_control_projection(
        np.asarray(model.dependent.ndarray).reshape(-1), model.exog.ndarray,
        model.endog.ndarray, model.instruments.ndarray)
    statistic = float((coordinates @ coordinates / tested) / (residuals @ residuals / df))
    return _WuHausmanStatistic(statistic, tested, df)


def wu_hausman_statistic(fitted: Any, *, variables: list[str] | None = None):
    """One product definition; a fast fit must expose its actual native slot."""
    if variables is not None:
        raise WuHausmanUnavailable("subset_test", "Only the joint test of all endogenous regressors has been validated.")
    if fitted.cov_type != "unadjusted":
        raise WuHausmanUnavailable("unsupported_covariance", "This Wu-Hausman test assumes homoskedastic errors.")
    from ..estimation_engine.iv import FastIVResults

    if isinstance(fitted, FastIVResults):
        # The unadjusted fast admission already checked the same ndarray/QR
        # domain. A bad value in a defined ABI slot remains a hard error.
        test = fitted.wu_hausman()
        if not np.isfinite(test.stat) or not np.isfinite(test.pval):
            raise RuntimeError("IV_WU_HAUSMAN_INVALID_OUTPUT: the defined native statistic or probability is non-finite")
        return test
    return reference_wu_hausman(fitted)


def iv_point_definition(native):
    from ..canonical import sha256_canonical
    from ..services.completion_products import array_fingerprint
    return {'family': 'iv_2sls', 'intercept': native.has_constant,
        'outcome': native.dependent.cols, 'exogenous': native.exog.cols,
        'endogenous': native.endog.cols, 'instruments': native.instruments.cols,
        'actual_design_sha256': sha256_canonical({
            'y': array_fingerprint(native.dependent.ndarray), 'w': array_fingerprint(native.exog.ndarray),
            'x': array_fingerprint(native.endog.ndarray), 'z': array_fingerprint(native.instruments.ndarray),
            'weights': array_fingerprint(native.weights.ndarray)})}


def build_iv_diagnostics(fitted: Any, n_endog: int, n_instruments: int, strength_check: dict | None = None) -> dict:
    identification = 'under' if n_instruments < n_endog else 'just' if n_instruments == n_endog else 'over'
    evidence = (strength_check or {}).get('evidence') or {}
    weak = dict(evidence) if evidence.get('per_endogenous') else first_stage_diagnostic(fitted)
    weak['anderson_rubin_95'] = evidence.get('anderson_rubin_95')
    weak['message'] = (strength_check or {}).get('summary') or (
        f'First-stage {weak["test"]} = {weak["first_stage_statistic"]:.4g}, reference {weak["reference_distribution"]}. '
        'Instrument strength and validity are not certified.')
    conventional = str(fitted.cov_type) == 'unadjusted'
    name = 'wu_hausman' if conventional else 'wooldridge_regression'
    try:
        test = wu_hausman_statistic(fitted) if conventional else fitted.wooldridge_regression
    except WuHausmanUnavailable as error:
        endogeneity = {'test': name, 'statistic': None, 'pvalue': None,
            'verdict': 'unavailable', 'reason': error.reason, 'message': str(error)}
    else:
        p = float(test.pval)
        endogeneity = {'test': name, 'statistic': float(test.stat), 'pvalue': p,
            'reference_distribution': test.dist_name,
            'verdict': 'rejects_exogeneity' if p < .05 else 'does_not_reject',
            'message': ('The exogeneity test rejects under its maintained model assumptions.' if p < .05 else
                        'The exogeneity test does not reject; this does not establish exogeneity.')}
    if identification == 'over' and str(fitted.cov_type) in {'unadjusted', 'robust', 'heteroskedastic'}:
        test = fitted.sargan if conventional else fitted.wooldridge_overid
        p = float(test.pval)
        overid = {'applicable': True, 'test': 'sargan' if conventional else 'wooldridge_overid',
            'statistic': float(test.stat), 'pvalue': p, 'reference_distribution': test.dist_name,
            'verdict': 'suspect' if p < .05 else 'not_rejected',
            'message': ('The joint instrument/model restrictions are rejected; the test does not identify which assumption fails.'
                        if p < .05 else 'The joint restrictions are not rejected; instrument validity is not established.')}
    else:
        overid = {'applicable': False, 'verdict': 'Not applicable (just-identified).' if identification == 'just'
                  else 'No covariance-compatible over-identification test is validated.'}
    return {'identification': identification, 'weak_instruments': weak, 'endogeneity': endogeneity,
            'overidentification': overid}
