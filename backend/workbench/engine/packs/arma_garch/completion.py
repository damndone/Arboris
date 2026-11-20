"""Evidence from the full-sample production fit, separate from training checks."""
from __future__ import annotations

import numpy as np
from statsmodels.stats.diagnostic import acorr_ljungbox

from workbench.canonical import sha256_canonical
from workbench.engine.packs.time_series.completion import innovation_diagnostics
from .input import ROW_ID_COLUMN, PARSED_TIME_COLUMN
from .transforms import TRANSFORMED_VALUE_COLUMN
from .volatility import validate_variance_parameters
from .statistics import LJUNG_BOX_SIGNIFICANCE_LEVEL


POINT_FIELDS = ('mean_order', 'mean_constant', 'variance_model', 'variance_order',
                'innovation_distribution', 'resolved_strategy', 'hold_back', 'transform')


def input_fingerprint(prepared):
    frame = prepared.transformed_view
    return sha256_canonical({'rows': frame[ROW_ID_COLUMN].tolist(),
        'times': frame[PARSED_TIME_COLUMN].astype(str).tolist(),
        'values': frame[TRANSFORMED_VALUE_COLUMN].tolist(),
        'time_column': prepared.contract.time_column, 'value_column': prepared.contract.value_column,
        'time_index_semantics': prepared.contract.time_index_semantics})


def point_fingerprint(prepared, frozen_spec):
    return sha256_canonical({'input': input_fingerprint(prepared),
        'specification': {key: frozen_spec[key] for key in POINT_FIELDS}})


def fitted_evidence(values, standardized, *, burn, model_df, estimates, standard_errors,
                    variance_spec, variance_parameters, mean_ar=(), mean_ma=()):
    diagnostics = innovation_diagnostics(values, standardized, model_df=model_df, burn=burn)
    diagnostics.update(mean_stationary=bool(np.all(np.abs(np.polynomial.polynomial.polyroots([1., *(-np.asarray(mean_ar))])) > 1)),
        mean_invertible=bool(np.all(np.abs(np.polynomial.polynomial.polyroots([1., *np.asarray(mean_ma)])) > 1)),
        significance_level=LJUNG_BOX_SIGNIFICANCE_LEVEL, method='garch_production_standardized_innovations_v1',
        residual_definition='production_fit_standardized_innovations_after_declared_initialization',
        calibration='asymptotic_diagnostic_approximation_not_forecast_coverage_certification')
    if diagnostics['status'] == 'computed':
        lag = diagnostics['ljung_box']['lags']
        squared = np.asarray(standardized, dtype=float)[burn:]**2
        if np.ptp(squared) == 0:
            diagnostics['squared_ljung_box'] = {'status': 'unavailable', 'reason': 'constant_squared_innovations'}
        else:
            lb = acorr_ljungbox(squared, lags=[lag], model_df=0, return_df=True).iloc[0]
            diagnostics['squared_ljung_box'] = {'status': 'computed', 'lags': lag, 'df': lag,
                'statistic': float(lb.lb_stat), 'p_value': float(lb.lb_pvalue),
                'parameter_adjustment': 'none_approximate_after_estimated_garch'}
    validation = validate_variance_parameters(model=variance_spec.model, p=variance_spec.p,
        q=variance_spec.q, distribution=variance_spec.distribution, parameters=variance_parameters)
    diagnostics['variance_parameters_valid'] = validation.valid
    diagnostics['variance_constraint_reasons'] = list(validation.failure_reasons)
    return {'coefficients': {name: {'estimate': float(value),
            'std_error': float(standard_errors[name]) if np.isfinite(standard_errors[name]) else None}
            for name, value in estimates.items()}, 'diagnostics': diagnostics}


def production_evidence(prepared, forecast):
    summary, spec = forecast['refit_summary'], forecast['frozen_spec']
    native = summary['analysis_evidence']
    frame = prepared.transformed_view
    return {'contract': 'garch.completion.v1', 'model_type': 'time_series.arma_garch',
        'model_id': 'arma_garch_1:production-final', 'fit_scope': 'all_available_observations',
        'nobs': len(frame), 'converged': summary['converged'],
        'coefficients': native['coefficients'],
        'diagnostics': {**native['diagnostics'], 'time_index_semantics': prepared.contract.time_index_semantics,
            'stable_frequency': prepared.audited.time_index.stable_frequency,
            'internal_gap_count': prepared.audited.time_index.internal_gap_count},
        'analysis_contract': prepared.contract.to_dict(), 'frozen_spec': spec,
        'input_fingerprint': input_fingerprint(prepared),
        'point_estimation_fingerprint': point_fingerprint(prepared, spec),
        'analysis_sample_fingerprint': sha256_canonical(frame[ROW_ID_COLUMN].tolist()),
        'scientific_validity': 'not_certified'}
