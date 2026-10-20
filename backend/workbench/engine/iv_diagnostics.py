"""Covariance-compatible native IV diagnostics; strength is not certified."""
from __future__ import annotations
from typing import Any
from ..checks.iv_checks import first_stage_diagnostic


def build_iv_diagnostics(fitted: Any, n_endog: int, n_instruments: int, strength_check: dict | None = None) -> dict:
    identification = 'under' if n_instruments < n_endog else 'just' if n_instruments == n_endog else 'over'
    weak = first_stage_diagnostic(fitted)
    evidence = (strength_check or {}).get('evidence') or {}
    weak['anderson_rubin_95'] = evidence.get('anderson_rubin_95')
    weak['message'] = (strength_check or {}).get('summary') or (
        f'First-stage {weak["test"]} = {weak["first_stage_statistic"]:.4g}, reference {weak["reference_distribution"]}. '
        'Instrument strength and validity are not certified.')
    conventional = str(fitted.cov_type) == 'unadjusted'
    test = fitted.wu_hausman() if conventional else fitted.wooldridge_regression
    name = 'wu_hausman' if conventional else 'wooldridge_regression'
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
