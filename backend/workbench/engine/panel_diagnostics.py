"""Native panel residual evidence: descriptive checks, not iid OLS tests."""
from __future__ import annotations

import numpy as np
import pandas as pd

from ..canonical import sha256_canonical
from ..services.completion_products import array_fingerprint
from ..checks.fit_checks import CLUSTER_COUNT


def panel_evidence(fitted, primary, frame, *, y, x, entity, time, cluster=None):
    native = fitted.model
    covariance = primary.get('covariance_evidence') or {}
    positions = np.arange(len(frame))
    if covariance.get('covariance') == 'clustered':
        fields = list(dict.fromkeys([y, *x, cluster or entity]))
        positions = positions[frame[fields].notna().all(axis=1)]
    if len(positions) != len(native.not_null):
        return {'status': 'unavailable', 'reason': 'retained_row_mapping_unverified'}, [], {}
    positions = positions[native.not_null]
    actual_y = pd.to_numeric(frame[y].iloc[positions], errors='coerce').to_numpy()
    if not np.array_equal(actual_y, native.dependent.values2d[:, 0]):
        return {'status': 'unavailable', 'reason': 'retained_row_mapping_unverified'}, [], {}
    residual = fitted.resids.to_numpy(dtype=float)
    entity_ids = native.dependent.entity_ids[:, 0]
    time_values = native.dependent.index.get_level_values(1)
    # Vectorized stable pairing replaces one Python group/row loop per entity.
    order = np.lexsort((time_values.to_numpy(), entity_ids))
    ordered_ids, values = entity_ids[order], residual[order]
    adjacent = ordered_ids[1:] == ordered_ids[:-1]
    left, right = values[:-1][adjacent], values[1:][adjacent]
    if time is None or entity is None:
        left, right = left[:0], right[:0]
    correlation = None
    if len(left) > 1 and np.std(left) > 0 and np.std(right) > 0:
        correlation = float(np.corrcoef(left, right)[0, 1])
    n_entities = int(np.unique(entity_ids).size)
    clusters = covariance.get('cluster_count')
    cluster_assessment = ('not_applicable' if clusters is None else
        'severe' if clusters < CLUSTER_COUNT.threshold('severe_below') else
        'caution' if clusters < CLUSTER_COUNT.threshold('caution_below') else 'many_cluster_reference')
    result = {'status': 'computed', 'method': 'panel_within_residual_descriptive_v1',
        'residual_definition': 'y minus fitted slopes and all fitted fixed effects',
        'nobs': len(residual), 'n_entities': n_entities, 'n_times': int(time_values.nunique()),
        'total_parameter_rank': int(fitted.df_model), 'slope_parameter_count': len(fitted.params),
        'absorbed_parameter_rank': int(fitted.df_model)-len(fitted.params),
        'residual_df': int(fitted.df_resid), 'covariance': covariance.get('covariance'),
        'cluster_count': covariance.get('cluster_count'), 'inference': covariance,
        'cluster_count_assessment': cluster_assessment,
        'pairing': 'adjacent_observed_times_within_entity' if time is not None and entity is not None else 'unavailable_without_declared_entity_and_time',
        'adjacent_pairs': len(left),
        'adjacent_residual_correlation': correlation, 'serial_dependence_test': 'not_performed',
        'description': 'Observed-time neighbors can have gaps. Pairing requires declared entity and time fields. Correlation is descriptive, not an independence test.',
        'residuals': residual, 'residual_summary': {'count': int(residual.size),
            'mean': float(residual.mean()), 'rms': float(np.sqrt(np.mean(residual**2))),
            'min': float(residual.min()), 'max': float(residual.max()),
            'sha256': array_fingerprint(residual), 'fingerprint_version': 'numpy-bytes.v1'},
        'scientific_validity': 'not_certified'}
    definition = {'family': primary['model_type'], 'entity_effects': native.entity_effects,
        'time_effects': native.time_effects, 'outcome': native.dependent.vars,
        'design': native.exog.vars, 'actual_design_sha256': sha256_canonical({
            'y': array_fingerprint(native.dependent.values2d), 'x': array_fingerprint(native.exog.values2d),
            'entity_partition': array_fingerprint(native.dependent.entity_ids),
            'time_partition': array_fingerprint(native.dependent.time_ids)})}
    return result, positions, definition
