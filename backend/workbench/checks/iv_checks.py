"""Instrument checks: first-stage strength with the Anderson-Rubin set, and the
exclusion restriction.

First-stage relevance is not a general certificate of instrument strength or
validity. AR inversion is separately certified on its supported domain; its
sampling validity still requires the stated design and error assumptions.
"""

from __future__ import annotations

from typing import Any

import numpy as np

from .context import CheckContext
from .contracts import CheckOutcome, CheckSpec, Threshold


def _arrays(fitted: Any) -> dict[str, Any] | None:
    model = getattr(fitted, "model", None)
    try:
        y = np.asarray(model.dependent.ndarray, dtype=float).reshape(-1)
        x = np.asarray(model.endog.ndarray, dtype=float)
        z = np.asarray(model.instruments.ndarray, dtype=float)
        w = np.asarray(model.exog.ndarray, dtype=float)
    except AttributeError:
        return None
    return {"y": y, "x": x, "z": z, "w": w, "cov_type": str(getattr(fitted, "cov_type", "") or "")}


def anderson_rubin_homoskedastic(y, x, z, w, alpha: float = 0.05) -> dict[str, Any]:
    """Globally invert the F(q,n-rank[W,Z]) AR test without a grid."""
    from .ar_confidence import homoskedastic_set

    return homoskedastic_set(y, x, z, w, alpha)


def anderson_rubin_robust(y, x, z, w, centre: float, scale: float, alpha: float = 0.05) -> dict[str, Any]:
    """Globally invert the HC0 AR test; legacy centre/scale do not limit it."""
    from .ar_confidence import robust_set

    return robust_set(y, x, z, w, alpha)


def _describe(region: dict[str, Any]) -> str:
    kind = region["kind"]
    if kind == 'unavailable':
        return 'unavailable: ' + region['reason']
    if kind == 'singleton':
        return f"{{{region['lower']:.4g}}}"
    if kind == "interval":
        return f"[{region['lower']:.4g}, {region['upper']:.4g}]"
    if kind == "union_of_rays":
        return f"(-inf, {region['lower']:.4g}] and [{region['upper']:.4g}, +inf)"
    if kind == "ray_below":
        return f"(-inf, {region['upper']:.4g}]"
    if kind == "ray_above":
        return f"[{region['lower']:.4g}, +inf)"
    if kind == "whole_line":
        return "the whole real line (the data are uninformative about the effect)"
    if kind == "empty":
        return "empty (the instrument restrictions are rejected at every value)"
    return "a union of disjoint pieces"


def first_stage_diagnostic(fitted: Any) -> dict[str, Any]:
    diagnostics = fitted.first_stage.diagnostics
    row = diagnostics.loc[diagnostics['f.stat'].idxmin()]
    statistic, distribution = float(row['f.stat']), str(row['f.dist'])
    conventional = (str(fitted.cov_type) == 'unadjusted' and len(diagnostics) == 1
                    and fitted.model.instruments.shape[1] == 1 and distribution.startswith('F('))
    verdict = ('weak' if statistic < 10 else 'caution' if statistic < 104.7 else 'strong') if conventional else 'unassessed'
    return {'first_stage_statistic': statistic, 'reference_distribution': distribution,
            'first_stage_f': statistic if distribution.startswith('F(') else None,
            'test': 'partial_f' if distribution.startswith('F(') else 'wald_chi2',
            'threshold': 10. if conventional else None, 'caution_threshold': 104.7 if conventional else None,
            'verdict': verdict, 'covariance': str(fitted.cov_type),
            'strength_certified': False,
            'per_endogenous': {str(name): {'statistic': float(r['f.stat']), 'p_value': float(r['f.pval']),
                              'reference_distribution': str(r['f.dist'])} for name, r in diagnostics.iterrows()}}


def first_stage_strength(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    fitted = context.fitted
    try:
        evidence = first_stage_diagnostic(fitted)
    except (AttributeError, KeyError, TypeError, ValueError):
        return CheckOutcome('not_checked', 'The fit does not expose its first-stage statistics.')
    arrays = _arrays(fitted)
    region = {'kind': 'unavailable', 'reason': 'multiple_endogenous_regressors'}
    if arrays is not None and arrays['x'].shape[1] == 1:
        weights = np.asarray(fitted.model.weights.ndarray)
        if not np.all(weights == 1):
            region = {'kind': 'unavailable', 'reason': 'weighted_ar_not_validated'}
        elif arrays['cov_type'] == 'unadjusted':
            region = anderson_rubin_homoskedastic(arrays['y'], arrays['x'], arrays['z'], arrays['w'])
        elif arrays['cov_type'] in {'robust', 'heteroskedastic'}:
            region = anderson_rubin_robust(arrays['y'], arrays['x'], arrays['z'], arrays['w'], 0., 1.)
        else:
            region = {'kind': 'unavailable', 'reason': 'unsupported_covariance_for_ar'}
    evidence['anderson_rubin_95'] = region
    evidence['endogenous_regressor'] = ', '.join(fitted.model.endog.cols)
    statistic, distribution = evidence['first_stage_statistic'], evidence['reference_distribution']
    summary = f'First-stage {evidence["test"]} = {statistic:.4g}, reference {distribution}. '
    if evidence['verdict'] == 'unassessed':
        summary += ('The F=10 and 104.7 benchmarks are not calibrated for this design/reference distribution; '
                    'instrument strength is not certified. ')
    else:
        summary += ('The 10/104.7 benchmarks concern a single instrument and endogenous regressor under '
                    'homoskedastic independent observations; they do not certify exclusion or general inference validity. ')
    if region['kind'] == 'unavailable':
        summary += f'AR confidence set unavailable: {region["reason"]}.'
    else:
        summary += f'Anderson-Rubin 95% confidence set: {_describe(region)}. '
        summary += 'Coverage requires valid instruments and the stated error assumptions; inversion does not certify those assumptions.'
    status = 'fails' if evidence['verdict'] == 'weak' else 'holds' if evidence['verdict'] == 'strong' else 'caution'
    return CheckOutcome(status, summary, evidence,
                        'Justify instrument validity and use applicable weak-instrument-robust inference.')


def exclusion_restriction(context: CheckContext, spec: CheckSpec) -> CheckOutcome:
    fitted = context.fitted
    arrays = _arrays(fitted)
    if arrays is None:
        return CheckOutcome("not_checked", "The fit does not expose its instruments.")
    overidentifying = arrays["z"].shape[1] - arrays["x"].shape[1]
    if overidentifying <= 0:
        return CheckOutcome(
            "needs_reason",
            "The model is exactly identified, so the exclusion restriction (the instrument affects the "
            "outcome only through the endogenous regressor) cannot be tested from the data. It rests on "
            "your argument.",
            {"overidentifying_restrictions": 0},
            "State why the instrument has no other path to the outcome.",
        )
    try:
        robust = str(fitted.cov_type) in {'robust', 'heteroskedastic'}
        if str(fitted.cov_type) not in {'unadjusted', 'robust', 'heteroskedastic'}:
            return CheckOutcome('not_checked', 'No covariance-compatible over-identification test is validated for this fit.')
        test = fitted.wooldridge_overid if robust else fitted.sargan
        test_name = 'Wooldridge robust score' if robust else 'Sargan (homoskedastic)'
        statistic, p_value = float(test.stat), float(test.pval)
    except (AttributeError, TypeError, ValueError):
        return CheckOutcome("not_checked", "The fit does not expose an over-identification test.")
    evidence = {"overidentifying_restrictions": overidentifying, "test": test_name, "statistic": statistic, "p_value": p_value}
    if p_value < spec.threshold("alpha"):
        return CheckOutcome(
            "caution",
            f"The over-identification test rejects ({test_name} p = {p_value:.3g}): at least one instrument "
            "is inconsistent with the joint model restrictions; this test does not identify the violated assumption.",
            evidence,
            "Reconsider which instruments are valid.",
        )
    return CheckOutcome(
        "holds",
        f"The over-identification test does not reject ({test_name} p = {p_value:.3g}). Not rejecting does not "
        "show the instruments are valid; it tests only their mutual consistency.",
        evidence,
    )


FIRST_STAGE_STRENGTH = CheckSpec(
    check_id="iv.first_stage_strength",
    title="Instrument strength",
    requires=frozenset({"design.instruments"}),
    # The attached AR set uses the outcome, even though relevance alone does not.
    blinding="post_fit",
    thresholds=(
        Threshold("fails_below", 10.0, "first-stage F below 10", "Staiger & Stock (1997), Econometrica 65(3)"),
        Threshold("caution_below", 104.7, "first-stage F below 104.7; single-instrument homoskedastic t-inference benchmark",
                  "Lee, McCrary, Moreira & Porter (2022), AER 112(10); Anderson & Rubin (1949)"),
    ),
    run=first_stage_strength,
)

EXCLUSION_RESTRICTION = CheckSpec(
    check_id="iv.exclusion_restriction",
    title="Exclusion restriction",
    requires=frozenset({"design.instruments"}),
    blinding="post_fit",
    thresholds=(Threshold("alpha", 0.05, "over-identification test p below 0.05", "Sargan (1958), Econometrica 26(3)"),),
    run=exclusion_restriction,
)
