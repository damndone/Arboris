"""Residual descriptions and actual-row provenance, separate from the locked result.

These are descriptive checks, not iid/studentized residuals or a certificate of
normality, covariance adequacy, identification or inferential validity.
"""
from __future__ import annotations


import numpy as np
import pandas as pd

from workbench.canonical import sha256_canonical
from workbench.contracts.common.envelope import PacketEnvelope
from workbench.services.completion_products import source_binding, read_analysis_frame

DEFINITIONS = {
    'marginal': 'y - X beta',
    'conditional': 'y - X beta - Z b_hat',
    'random_effect_prediction': 'b_hat = Psi Z^T (Z Psi Z^T + sigma2 I)^-1 (y - X beta), within subject',
    'scaled_conditional': 'conditional_residual / sqrt(residual_variance); not studentized or independent',
}


def point_estimation_fingerprint(prepared):
    """Hash actual modeled values/partitions, excluding unused data and labels."""
    controls = list(prepared.fixed_effects[4:])
    frame = prepared.frame
    return sha256_canonical({
        'fixed': prepared.formula, 'random': prepared.random_effects, 'method': prepared.input.fit_method,
        'numeric_values': np.asarray(frame[[prepared.outcome, prepared.input.time, *controls]], dtype=float).tolist(),
        'subject_partition': pd.factorize(frame[prepared.input.subject_id], sort=False)[0].tolist(),
        'comparison_group': (frame[prepared.input.group] == prepared.comparison_group_value).tolist()})


def build_analysis_evidence(*, source, prepared, result, fitted):
    payload = result['payload']
    evidence = {'schema_version': 1, 'model_id': payload['model_id'],
        'model_type': payload['model_type'], 'execution_binding': payload['execution_binding'],
        'result_identity': payload['result_identity'], 'source': source,
        'status': 'unavailable', 'reason': 'fit_incomplete', 'nobs': payload['nobs'],
        'residual_definitions': DEFINITIONS, 'rows': [], 'summary': None,
        'analysis_sample_sha256': None,
        'point_estimation_fingerprint': point_estimation_fingerprint(prepared) if payload['status'] == 'complete' else None,
        'outcome': prepared.outcome, 'controls': list(prepared.fixed_effects[4:]),
        'limitations': ['Descriptive conditional residuals are correlated and shrunken; no normality or independence test is certified.']}
    if payload['status'] == 'complete' and fitted is not None:
        model = fitted.model
        marginal = np.asarray(model.endog - model.exog @ fitted.fe_params, dtype=float)
        conditional = marginal.copy()
        psi, sigma2 = np.asarray(fitted.cov_re), float(fitted.scale)
        try:
            for group in model.group_labels:
                positions = model.row_indices[group]
                z = model.exog_re[positions]
                v = z @ psi @ z.T + sigma2 * np.eye(len(positions))
                b = psi @ z.T @ np.linalg.solve(v, marginal[positions])
                conditional[positions] -= z @ b
            scaled = conditional / np.sqrt(sigma2)
            if not np.isfinite(np.concatenate([marginal, conditional, scaled])).all():
                raise ValueError('nonfinite residuals')
        except (np.linalg.LinAlgError, ValueError):
            evidence['reason'] = 'residual_computation_failed'
        else:
            # Prepared input owns this positional mapping, including duplicate
            # pandas labels, missing outcomes/controls and unbalanced panels.
            retained = list(prepared.source_row_positions)
            evidence.update(status='complete' if source else 'unavailable',
                reason=None if source else 'source_unverified',
                analysis_sample_sha256=sha256_canonical(retained),
                rows=[{'source_row_position': pos, 'marginal_residual': float(m),
                       'conditional_residual': float(c), 'scaled_conditional_residual': float(s),
                       'conditional_fitted': float(y - c)}
                      for pos, m, c, s, y in zip(retained, marginal, conditional, scaled, model.endog)],
                summary={key: {'mean': float(np.mean(value)), 'rms': float(np.sqrt(np.mean(value ** 2))),
                               'min': float(np.min(value)), 'max': float(np.max(value)),
                               'quantile_probabilities': [.01, .25, .5, .75, .99],
                               'quantiles': np.quantile(value, [.01, .25, .5, .75, .99]).tolist()}
                         for key, value in [('marginal', marginal), ('conditional', conditional), ('scaled_conditional', scaled)]})
    return PacketEnvelope(contract='linear_mixed_effects.analysis_evidence', contract_version='1.0',
                          producer_version='linear_mixed_effects@1.0', payload=evidence).to_dict()
